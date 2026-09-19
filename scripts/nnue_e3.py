#!/usr/bin/env python3
"""Build and train controlled 64/128-unit Eloi E3 NNUE candidates.

Raw player PGNs and generated labels stay ignored.  The two architectures see
the same positions in the same order; the 128-unit model starts with E2 in its
first 64 channels and neutral appended channels.  Nothing in this module writes
the production NNUE header.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[1]
for dependency_root in (
    _BOOTSTRAP_ROOT / ".deps" / "python",
    _BOOTSTRAP_ROOT / ".deps" / "lichess-bot" / ".venv" / "Lib" / "site-packages",
):
    if dependency_root.is_dir():
        sys.path.insert(0, str(dependency_root))

import chess
import chess.engine
import chess.pgn
import numpy as np

import engine_lab
import train_nnue as trainer


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "tmp/nnue-e3-player-games"
SOURCES = (
    {
        "id": "viswanathan-anand",
        "player": "Viswanathan Anand",
        "pgn": ROOT / ".deps/e3-player-games/Anand/Anand.pgn",
        "archive": ROOT / ".deps/e3-player-games/Anand.zip",
        "archive_sha256": "9F7227690C26ED05688CF1C118C46585C8D6A69A054764F5EF2649C47AEB292F",
        "url": "https://www.pgnmentor.com/players/Anand.zip",
    },
    {
        "id": "anish-giri",
        "player": "Anish Giri",
        "pgn": ROOT / ".deps/e3-player-games/Giri/Giri.pgn",
        "archive": ROOT / ".deps/e3-player-games/Giri.zip",
        "archive_sha256": "A0649419C055A45849D000BAEC27F4008DDA69194D99C3524426466DD100AA63",
        "url": "https://www.pgnmentor.com/players/Giri.zip",
    },
)
TEACHER = (
    ROOT
    / "tmp/v3.1.2-final-packages/exoskeleton-A/"
      "Eloi-v3.1.2-windows-x64-exoskeleton/Eloi.exe"
)
TEACHER_NETWORK = TEACHER.parent / "eval-71-v1.25.pnn"
PRODUCTION_WEIGHTS = ROOT / "include/eloi/nnue_weights.hpp"
EPV2_DATASET = ROOT / "tmp/eloi-native-v2-teacher-150000-r3/teacher.jsonl"
EPV2_MANIFEST = ROOT / "tmp/eloi-native-v2-teacher-150000-r3/manifest.json"
EPV2_SHA256 = "FD851DE4D66AC9E4987A4D6B6364202CCD1F6CC8D7159C8B4C9434E9DAC40DC8"
POSITIONS_PER_PLAYER = 20_000
LABEL_NODES = 10_000
SEED = "eloi-e3-player-games-v1"
TRAINING_REVISION = 3
PROJECTED_BYTES = 850_000_000
MAX_TOTAL_TEMP = 10 * 1024**3
MAX_TRAINING_TEMP = 7 * 1024**3


def sha256(path: Path) -> str:
    return engine_lab.sha256(path)


def stable_digest(*parts: object) -> bytes:
    return hashlib.sha256("|".join(map(str, parts)).encode()).digest()


def immutable_json(path: Path, value) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"evidence collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def enforce_resources() -> dict:
    total = directory_bytes(ROOT / "tmp") + directory_bytes(ROOT / ".deps")
    training = directory_bytes(WORK)
    free = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize if os.name != "nt" else None
    if total + PROJECTED_BYTES > MAX_TOTAL_TEMP:
        raise RuntimeError("E3 projected artifacts exceed the 10 GB temporary cap")
    if training + PROJECTED_BYTES > MAX_TRAINING_TEMP:
        raise RuntimeError("E3 projected artifacts exceed the 7 GiB trainer cap")
    return {"temporary_bytes": total, "campaign_bytes": training,
            "projected_new_bytes": PROJECTED_BYTES, "free_bytes": free}


def partition(game_id: str) -> str:
    value = int.from_bytes(stable_digest(SEED, "partition", game_id)[:8], "big")
    fraction = value / float(1 << 64)
    if fraction < 0.10:
        return "validation"
    if fraction < 0.20:
        return "test"
    return "train"


def canonical_key(board: chess.Board) -> str:
    return " ".join(board.fen().split()[:4])


def game_identity(source_id: str, ordinal: int, game: chess.pgn.Game) -> str:
    tags = game.headers
    return hashlib.sha256(
        f"{source_id}|{ordinal}|{tags.get('White','')}|{tags.get('Black','')}|"
        f"{tags.get('Date','')}|{tags.get('Event','')}|{tags.get('Round','')}".encode()
    ).hexdigest()


def source_positions(source: dict) -> tuple[list[dict], dict]:
    path = source["pgn"]
    if not path.is_file() or sha256(source["archive"]) != source["archive_sha256"]:
        raise RuntimeError(f"missing or changed source archive for {source['player']}")
    candidates: dict[str, dict] = {}
    games = invalid = nonstandard = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            games += 1
            if game.errors:
                invalid += 1
                continue
            board = game.board()
            if type(board) is not chess.Board or board.chess960:
                nonstandard += 1
                continue
            gid = game_identity(source["id"], games, game)
            part = partition(gid)
            for ply, move in enumerate(game.mainline_moves()):
                # PGN termination is authoritative here.  Asking whether a draw
                # can be claimed at every historical ply repeatedly scans move
                # history and makes the corpus pass quadratic.
                if ply >= 10 and not board.is_game_over(claim_draw=False):
                    key = canonical_key(board)
                    priority = stable_digest(SEED, source["id"], gid, ply, key).hex()
                    row = {
                        "id": hashlib.sha256(f"{source['id']}|{gid}|{ply}|{key}".encode()).hexdigest(),
                        "source": source["id"], "player": source["player"],
                        "game_id": gid, "game_ordinal": games, "ply": ply,
                        "partition": part, "fen": board.fen(), "priority": priority,
                    }
                    previous = candidates.get(key)
                    if previous is None or row["priority"] < previous["priority"]:
                        candidates[key] = row
                board.push(move)
    selected = sorted(candidates.values(), key=lambda row: row["priority"])[
        :POSITIONS_PER_PLAYER
    ]
    return selected, {"games": games, "invalid_games": invalid,
                      "nonstandard_games": nonstandard,
                      "unique_positions": len(candidates), "selected": len(selected)}


def prepare() -> dict:
    path = WORK / "positions.jsonl"
    protocol_path = WORK / "protocol.json"
    if path.exists() and protocol_path.exists():
        return json.loads(protocol_path.read_text(encoding="utf-8"))
    if path.exists() or protocol_path.exists():
        raise RuntimeError("partial E3 prepare evidence exists")
    resource = enforce_resources()
    rows, reports, seen = [], {}, set()
    for source in SOURCES:
        selected, report = source_positions(source)
        reports[source["id"]] = report
        for row in selected:
            key = canonical_key(chess.Board(row["fen"]))
            if key not in seen:
                seen.add(key)
                rows.append(row)
    rows.sort(key=lambda row: (row["partition"], row["priority"], row["id"]))
    WORK.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    counts = {name: sum(row["partition"] == name for row in rows)
              for name in ("train", "validation", "test")}
    protocol = {
        "schema": 1, "campaign": "E3-controlled-64-vs-128",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "rules": "FIDE Standard only; game-group partition; test sealed during selection",
        "architectures": [64, 128], "positions_per_player": POSITIONS_PER_PLAYER,
        "label_nodes": LABEL_NODES, "teacher_threads": 3,
        "sources": [{**{k: v for k, v in source.items() if k not in ("pgn", "archive")},
                     "pgn_sha256": sha256(source["pgn"])} for source in SOURCES],
        "source_reports": reports, "counts": counts,
        "positions_sha256": sha256(path), "resource_preflight": resource,
        "production_changed": False,
    }
    immutable_json(protocol_path, protocol)
    return protocol


def label() -> dict:
    protocol = prepare()
    positions = [json.loads(line) for line in
                 (WORK / "positions.jsonl").read_text(encoding="utf-8").splitlines()]
    output = WORK / "labels.jsonl"
    existing = []
    if output.exists():
        existing = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        if [row["id"] for row in existing] != [row["id"] for row in positions[:len(existing)]]:
            raise RuntimeError("E3 label resume prefix differs from frozen positions")
    if len(existing) == len(positions):
        return {"count": len(existing), "sha256": sha256(output)}
    if not TEACHER.is_file() or not TEACHER_NETWORK.is_file():
        raise RuntimeError("frozen v3.1.2 Caissa teacher package is unavailable")
    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    engine = chess.engine.SimpleEngine.popen_uci(
        [str(TEACHER)], timeout=30.0, creationflags=flags, cwd=str(TEACHER.parent))
    try:
        settings = {}
        if "Threads" in engine.options:
            settings["Threads"] = 3
        if "Hash" in engine.options:
            settings["Hash"] = 32
        if settings:
            engine.configure(settings)
        with output.open("a", encoding="utf-8", newline="\n") as stream:
            for index, row in enumerate(positions[len(existing):], len(existing) + 1):
                board = chess.Board(row["fen"], chess960=False)
                info = engine.analyse(board, chess.engine.Limit(nodes=LABEL_NODES), game=object())
                value = info["score"].white().score(mate_score=1500)
                labelled = {**row, "target_cp_white": int(max(-1500, min(1500, value or 0))),
                            "teacher_depth": int(info.get("depth", 0)),
                            "teacher_nodes": int(info.get("nodes", 0))}
                stream.write(json.dumps(labelled, sort_keys=True) + "\n")
                stream.flush()
                if index % 250 == 0:
                    print(json.dumps({"stage": "label", "complete": index,
                                      "total": len(positions)}), flush=True)
    finally:
        engine.quit()
    result = {"count": len(positions), "sha256": sha256(output),
              "teacher_executable_sha256": sha256(TEACHER),
              "teacher_network_sha256": sha256(TEACHER_NETWORK)}
    immutable_json(WORK / "label-result.json", result)
    return result


def expand_e2(model, hidden: int):
    weights, bias, output = model
    if hidden == 64:
        return tuple(array.copy() for array in model)
    if hidden != 128 or weights.shape[1] != 64:
        raise ValueError("E3 supports only a 64-unit E2 seed expanded to 128")
    expanded_weights = np.zeros((weights.shape[0], hidden), dtype=np.float32)
    expanded_bias = np.zeros(hidden, dtype=np.float32)
    expanded_output = np.zeros(hidden, dtype=np.float32)
    expanded_weights[:, :64] = weights
    expanded_bias[:64] = bias
    expanded_output[:64] = output
    # Exactly-zero appended channels are dormant: zero output weights prevent
    # input gradients, while identical zero activations prevent output updates.
    # Seed the extra capacity deterministically at negligible output influence.
    rng = np.random.default_rng(0xE3128)
    expanded_weights[:, 64:] = rng.normal(
        0.0, 0.12, (weights.shape[0], 64)
    ).astype(np.float32)
    expanded_bias[64:] = 8.0
    expanded_output[64:] = rng.normal(0.0, 0.004, 64).astype(np.float32)
    return expanded_weights, expanded_bias, expanded_output


def player_samples(rows: list[dict], wanted: str) -> list[tuple]:
    samples = []
    for row in rows:
        if row["partition"] != wanted:
            continue
        board = chess.Board(row["fen"], chess960=False)
        samples.append((trainer.features(board, chess.WHITE),
                        trainer.features(board, chess.BLACK),
                        float(row["target_cp_white"]), 1.0,
                        {"record_id": row["id"], "source": row["source"]}))
    return samples


def load_epv2_broad() -> dict:
    """Reuse frozen EPV2 train/validation labels without opening sealed test."""
    manifest = json.loads(EPV2_MANIFEST.read_text(encoding="utf-8"))
    if manifest["dataset_sha256"] != EPV2_SHA256 or sha256(EPV2_DATASET) != EPV2_SHA256:
        raise RuntimeError("EPV2 teacher dataset identity changed")
    evaluations = {"train": [], "validation": []}
    pair_candidates = {"train": [], "validation": []}
    with EPV2_DATASET.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            part = row["partition"]
            if part == "test":
                continue
            if part not in evaluations:
                raise RuntimeError(f"unexpected EPV2 partition: {part}")
            board = chess.Board(row["fen"], chess960=False)
            oriented = row["teacher_cp"] if board.turn else -row["teacher_cp"]
            # EPV2 uses +/-30000 for mate policy/value training.  Eloi's scalar
            # NNUE convention is a bounded +/-1500 cp target; allowing mate
            # sentinels into this loss dominated the mean and destabilized
            # ordinary evaluation/search interaction in revision 2.
            target = float(max(-1500, min(1500, oriented)))
            evaluations[part].append((
                trainer.features(board, chess.WHITE),
                trainer.features(board, chess.BLACK), target,
                float(row.get("tactical_weight", 1.0)),
                {"record_id": row["record_id"], "source": "EPV2"},
            ))
            policy = row.get("policy", [])
            if len(policy) < 2:
                continue
            best = chess.Move.from_uci(policy[0]["move"])
            alternative = chess.Move.from_uci(policy[1]["move"])
            if best not in board.legal_moves or alternative not in board.legal_moves:
                raise RuntimeError(f"EPV2 policy contains illegal move: {row['record_id']}")
            best_board = board.copy(stack=False)
            best_board.push(best)
            alt_board = board.copy(stack=False)
            alt_board.push(alternative)
            priority = stable_digest(SEED, "pair", row["record_id"]).hex()
            pair_candidates[part].append((priority, (
                trainer.features(best_board, chess.WHITE),
                trainer.features(best_board, chess.BLACK),
                trainer.features(alt_board, chess.WHITE),
                trainer.features(alt_board, chess.BLACK),
                1 if board.turn == chess.WHITE else -1,
                min(2.0, float(row.get("tactical_weight", 1.0))),
            )))
    pairs = {}
    for part, limit in (("train", 12_000), ("validation", 4_000)):
        pairs[part] = [sample for _, sample in
                       sorted(pair_candidates[part], key=lambda item: item[0])[:limit]]
    return {"evaluations": evaluations, "pairs": pairs,
            "manifest_sha256": sha256(EPV2_MANIFEST),
            "dataset_sha256": sha256(EPV2_DATASET)}


def train() -> dict:
    label_result = label()
    result_path = WORK / f"training-result-r{TRAINING_REVISION}.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in
            (WORK / "labels.jsonl").read_text(encoding="utf-8").splitlines()]
    provenance = json.loads(
        (ROOT / "data/nnue_provenance.json").read_text(encoding="utf-8")
    )
    if sha256(PRODUCTION_WEIGHTS) != provenance["selected_weights_sha256"]:
        raise RuntimeError("production E2 header identity changed")
    # The historical float checkpoint was intentionally not retained.  The
    # production header is the authoritative E2 artifact, so use its exact
    # quantized parameters as the common seed for both architectures.
    e2_model = tuple(
        array.astype(np.float32).copy()
        for array in trainer.load_quantized_header(PRODUCTION_WEIGHTS)
    )
    broad = load_epv2_broad()
    tactical_pairs = broad["pairs"]["train"]
    validation_pairs = broad["pairs"]["validation"]
    train_rows = [*broad["evaluations"]["train"], *player_samples(rows, "train")]
    validation = {"broad": broad["evaluations"]["validation"],
                  "players": player_samples(rows, "validation")}
    reports = []
    for hidden in (64, 128):
        model = expand_e2(e2_model, hidden)
        channels = list(range(hidden))
        model = trainer.train_evaluations(
            *model, list(train_rows), epochs=2, trainable_channels=channels)
        preserving = [(*pair, 0.25) for pair in tactical_pairs]
        model = trainer.train_pairs(
            *model, preserving, epochs=1, trainable_channels=channels)
        directory = WORK / f"candidates-r{TRAINING_REVISION}" / f"E3-{hidden}"
        include = directory / "include/eloi"
        include.mkdir(parents=True, exist_ok=False)
        checkpoint = directory / "float.npz"
        np.savez(checkpoint, weights=model[0], bias=model[1], output=model[2])
        header = include / "nnue_weights.hpp"
        architecture = include / "nnue_architecture.hpp"
        counts = {"train_evaluations": len(train_rows),
                  "broad_train_evaluations": len(broad["evaluations"]["train"]),
                  "player_train_evaluations": len(player_samples(rows, "train")),
                  "player_validation_evaluations": len(validation["players"]),
                  "sealed_player_test_evaluations": sum(r["partition"] == "test" for r in rows),
                  "train_pairs": len(tactical_pairs)}
        trainer.write_header(header, *model, counts, set(),
                             source_description="E3 Standard-only broad plus Anand/Giri positions")
        trainer.write_architecture(architecture, hidden)
        report = {
            "candidate": f"E3-{hidden}", "hidden": hidden, "counts": counts,
            "checkpoint_sha256": sha256(checkpoint), "weights_sha256": sha256(header),
            "architecture_sha256": sha256(architecture),
            "broad_validation": trainer.validation_metrics(
                *model, validation["broad"], validation_pairs),
            "player_validation": trainer.validation_metrics(
                *model, validation["players"], validation_pairs),
            "sealed_test_opened": False,
        }
        immutable_json(directory / "training.json", report)
        reports.append(report)
        print(json.dumps({"stage": "trained", "candidate": f"E3-{hidden}",
                          "player_mae": report["player_validation"]["quantized"]["evaluations"]["mae_cp"]}),
              flush=True)
    result = {"schema": 1, "campaign": "E3-controlled-64-vs-128",
              "label_result": label_result, "candidates": reports,
              "selection": "engine-in-loop testing required; offline metrics are diagnostic",
              "sealed_test_opened": False, "training_revision": TRAINING_REVISION,
              "production_weights_sha256": sha256(PRODUCTION_WEIGHTS),
              "production_changed": False}
    immutable_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "label", "train", "all"))
    args = parser.parse_args()
    started = time.monotonic()
    result = prepare() if args.stage == "prepare" else label() if args.stage == "label" else train()
    print(json.dumps({"stage": args.stage, "elapsed_seconds": time.monotonic() - started,
                      "result": result}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
