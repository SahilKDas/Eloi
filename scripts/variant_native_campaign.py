#!/usr/bin/env python3
"""Bounded, resumable training campaign for Eloi's native variant evaluators."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
for dependency in (ROOT / ".deps/python", ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"):
    if dependency.is_dir():
        sys.path.insert(0, str(dependency))

import chess
import chess.engine
import chess.variant
import numpy as np
import psutil

import train_nnue as nnue

VARIANTS = ("chess960", "atomic", "antichess")
SEEDS = {"chess960": 0x960E401, "atomic": 0xA70E401, "antichess": 0xA17E401}
TOTAL = 100_000
QUOTAS = {"train": 80_000, "validation": 10_000, "test": 10_000}
TEACHER_NODES = 2_000
MAX_PIECES = 32
WORK = ROOT / "tmp/variant-native"
TEACHER = ROOT / ".deps/fairy-stockfish/fairy-stockfish_x86-64-bmi2.exe"
TEACHER_SHA256 = "9ADEFF67FF3AD8A80D9706AD4416FD2D8A34AE681A14BF424B6E176C7DE916F1"
PARENT = ROOT / "include/eloi/nnue_weights.hpp"
MAX_WORKING_SET = 2 * 1024**3
MIN_FREE_RAM = 3 * 1024**3
MAX_SWAP_GROWTH = 128 * 1024**2
MAX_TRAINING_BYTES = 7 * 1024**3
MAX_TEMP_BYTES = 10_000_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def board_for(variant: str, rng: random.Random, game: int):
    if variant == "chess960":
        index = (game * 37 + rng.randrange(960)) % 960
        return chess.Board.from_chess960_pos(index), index
    if variant == "atomic":
        return chess.variant.AtomicBoard(), None
    if variant == "antichess":
        return chess.variant.AntichessBoard(), None
    raise ValueError(variant)


def partition_for(variant: str, game: int) -> str:
    value = hashlib.sha256(f"Eloi-variant-v1|{variant}|game|{game}".encode()).digest()[0]
    return "train" if value < 205 else "validation" if value < 230 else "test"


def canonical(board: chess.Board) -> str:
    plain = board.fen()
    mirrored = board.mirror().fen()
    return min(plain, mirrored)


def feature_indices(board: chess.Board, side: chess.Color) -> np.ndarray:
    king = board.king(side)
    oriented_king = 0 if king is None else (king if side else king ^ 56)
    bucket = (chess.square_file(oriented_king) >= 4) + 2 * (chess.square_rank(oriented_king) // 2)
    planes = {chess.PAWN: 0, chess.BISHOP: 1, chess.KNIGHT: 2,
              chess.ROOK: 3, chess.QUEEN: 4, chess.KING: 5}
    values = []
    for square, piece in board.piece_map().items():
        plane = (0 if piece.color == side else 6) + planes[piece.piece_type]
        oriented = square if side else square ^ 56
        values.append((bucket * 12 + plane) * 64 + oriented)
    return np.asarray(sorted(values), dtype=np.int16)


def open_arrays(directory: Path, mode: str):
    directory.mkdir(parents=True, exist_ok=True)
    create = mode == "w+"
    features = np.lib.format.open_memmap(directory / "features.npy", mode=mode,
        dtype=np.int16, shape=(TOTAL, 2, MAX_PIECES) if create else None)
    lengths = np.lib.format.open_memmap(directory / "lengths.npy", mode=mode,
        dtype=np.uint8, shape=(TOTAL, 2) if create else None)
    targets = np.lib.format.open_memmap(directory / "targets.npy", mode=mode,
        dtype=np.float32, shape=(TOTAL,) if create else None)
    return features, lengths, targets


def configure_teacher(engine: chess.engine.SimpleEngine, variant: str) -> None:
    settings = {"Threads": 3, "Hash": 64}
    # python-chess owns UCI_Variant and UCI_Chess960 and switches both from the
    # concrete Board type passed to analyse(). Setting them here is rejected.
    engine.configure({key: value for key, value in settings.items() if key in engine.options})


def teacher_score(engine: chess.engine.SimpleEngine, board: chess.Board) -> tuple[float, str]:
    info = engine.analyse(board, chess.engine.Limit(nodes=TEACHER_NODES))
    score = info["score"].pov(chess.WHITE).score(mate_score=1500)
    if score is None:
        score = 0
    pv = " ".join(move.uci() for move in info.get("pv", [])[:8])
    return float(np.clip(score, -1500, 1500)), pv


def collect(variant: str) -> None:
    if sha256(TEACHER) != TEACHER_SHA256:
        raise RuntimeError("Fairy-Stockfish teacher identity mismatch")
    directory = WORK / variant
    state_path = directory / "collector-state.json"
    metadata_path = directory / "positions.jsonl"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["protocol_sha256"] != protocol_hash(variant):
            raise RuntimeError("collector protocol mismatch")
        arrays = open_arrays(directory, "r+")
        seen = {json.loads(line)["canonical"] for line in metadata_path.read_text(encoding="utf-8").splitlines()}
    else:
        directory.mkdir(parents=True, exist_ok=False)
        arrays = open_arrays(directory, "w+")
        state = {"variant": variant, "protocol_sha256": protocol_hash(variant),
                 "count": 0, "game": 0, "partitions": {name: 0 for name in QUOTAS},
                 "status": "collecting"}
        seen = set()
        atomic_json(state_path, state)
    features, lengths, targets = arrays
    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    engine = chess.engine.SimpleEngine.popen_uci(str(TEACHER), timeout=30, creationflags=flags)
    configure_teacher(engine, variant)
    try:
        while state["count"] < TOTAL:
            game = state["game"]
            state["game"] += 1
            partition = partition_for(variant, game)
            if state["partitions"][partition] >= QUOTAS[partition]:
                continue
            rng = random.Random(SEEDS[variant] ^ game)
            board, chess960_index = board_for(variant, rng, game)
            source_ply = 0
            for ply in range(160):
                if board.is_game_over(claim_draw=True):
                    break
                legal = sorted(board.legal_moves, key=lambda move: move.uci())
                if not legal:
                    break
                # Deterministic broad trajectories; the teacher labels positions,
                # rather than controlling their distribution.
                board.push(legal[rng.randrange(len(legal))])
                source_ply += 1
                if source_ply < 6 or source_ply % 2:
                    continue
                if state["partitions"][partition] >= QUOTAS[partition]:
                    break
                identity = canonical(board)
                if identity in seen:
                    continue
                score, pv = teacher_score(engine, board)
                white, black = feature_indices(board, chess.WHITE), feature_indices(board, chess.BLACK)
                index = state["count"]
                features[index].fill(-1); lengths[index] = (len(white), len(black))
                features[index, 0, :len(white)] = white
                features[index, 1, :len(black)] = black
                targets[index] = score
                row = {"schema": 1, "id": index, "variant": variant,
                       "partition": partition, "source_game": game,
                       "source_ply": source_ply, "fen": board.fen(),
                       "canonical": identity, "teacher_cp_white": score,
                       "teacher_pv": pv, "chess960_index": chess960_index}
                with metadata_path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                seen.add(identity); state["count"] += 1
                state["partitions"][partition] += 1
                if state["count"] % 100 == 0:
                    features.flush(); lengths.flush(); targets.flush()
                    atomic_json(state_path, state)
                    print(json.dumps({"variant": variant, "count": state["count"],
                                      "partitions": state["partitions"]}), flush=True)
                if state["count"] >= TOTAL:
                    break
        state["status"] = "complete"
        state["teacher_sha256"] = sha256(TEACHER)
        state["dataset_sha256"] = {name: sha256(directory / name) for name in
                                    ("features.npy", "lengths.npy", "targets.npy", "positions.jsonl")}
        atomic_json(state_path, state)
    finally:
        engine.quit()


def protocol_hash(variant: str) -> str:
    payload = {"schema": 1, "variant": variant, "total": TOTAL, "quotas": QUOTAS,
               "teacher_nodes": TEACHER_NODES, "teacher_sha256": TEACHER_SHA256,
               "seed": SEEDS[variant], "max_pieces": MAX_PIECES}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest().upper()


def rows_for_partition(directory: Path, partition: str):
    features, lengths, targets = open_arrays(directory, "r")
    indices = []
    with (directory / "positions.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["partition"] == partition:
                indices.append(row["id"])
    for index in indices:
        yield (features[index, 0, :lengths[index, 0]].astype(np.int32),
               features[index, 1, :lengths[index, 1]].astype(np.int32),
               float(targets[index]))


def metrics(model, samples) -> dict:
    errors = [abs(nnue.forward(*model, white, black)[0] - target)
              for white, black, target in samples]
    return {"count": len(errors), "mae_cp": float(np.mean(errors)),
            "p95_cp": float(np.percentile(errors, 95))}


def train(variant: str) -> None:
    directory = WORK / variant
    state = json.loads((directory / "collector-state.json").read_text(encoding="utf-8"))
    if state["status"] != "complete" or state["partitions"] != QUOTAS:
        raise RuntimeError("dataset is incomplete")
    baseline = tuple(value.astype(np.float32).copy() for value in nnue.load_quantized_header(PARENT))
    validation = list(rows_for_partition(directory, "validation"))
    selected = None; best = float("inf"); stale = 0; reports = []
    model = tuple(value.copy() for value in baseline)
    train_rows = list(rows_for_partition(directory, "train"))
    for epoch in range(1, 9):
        model = nnue.train_evaluations(*model, train_rows, epochs=1,
                                       trainable_channels=list(range(64)))
        anchored = tuple(base + .25 * (value - base) for value, base in zip(model, baseline))
        report = metrics(anchored, validation)
        report["epoch"] = epoch; reports.append(report)
        if report["mae_cp"] < best - .25:
            best = report["mae_cp"]; selected = tuple(value.copy() for value in anchored); stale = 0
        else:
            stale += 1
        if stale >= 2:
            break
    if selected is None:
        raise RuntimeError("no checkpoint selected")
    output = directory / "candidate"
    output.mkdir(parents=True, exist_ok=False)
    checkpoint = output / "float.npz"
    np.savez(checkpoint, weights=selected[0], bias=selected[1], output=selected[2])
    header = output / f"nnue_{variant}_weights.hpp"
    nnue.write_header(header, *selected,
        {"train_evaluations": QUOTAS["train"], "train_pairs": 0}, {variant},
        source_description=f"E4 {variant} Fairy-Stockfish 14 distillation")
    result = {"schema": 1, "variant": variant, "selected_validation_mae_cp": best,
              "epochs": reports, "checkpoint_sha256": sha256(checkpoint),
              "header_sha256": sha256(header), "sealed_test_opened": False,
              "production_changed": False}
    atomic_json(output / "training.json", result)


def evaluate_test(variant: str) -> None:
    """Open the sealed split once, after checkpoint selection is immutable."""
    directory = WORK / variant
    output = directory / "candidate"
    destination = output / "sealed-test.json"
    if destination.exists():
        raise FileExistsError(destination)
    training = json.loads((output / "training.json").read_text(encoding="utf-8"))
    checkpoint = output / "float.npz"
    if sha256(checkpoint) != training["checkpoint_sha256"]:
        raise RuntimeError("selected checkpoint identity changed")
    archive = np.load(checkpoint, allow_pickle=False)
    model = (archive["weights"].astype(np.float32),
             archive["bias"].astype(np.float32),
             archive["output"].astype(np.float32))
    samples = list(rows_for_partition(directory, "test"))
    if len(samples) != QUOTAS["test"]:
        raise RuntimeError("sealed test partition count mismatch")
    result = {
        "schema": 1,
        "variant": variant,
        "selection_frozen": True,
        "checkpoint_sha256": training["checkpoint_sha256"],
        "header_sha256": training["header_sha256"],
        "partition": "test",
        "partition_count": QUOTAS["test"],
        "metrics": metrics(model, samples),
    }
    atomic_json(destination, result)


def project_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def coordinator(stage: str) -> None:
    memory = psutil.virtual_memory()
    if memory.available < MIN_FREE_RAM:
        raise RuntimeError(f"need at least 3 GiB available RAM; found {memory.available / 1024**3:.2f}")
    swap_start = psutil.swap_memory().used
    commands = [[sys.executable, __file__, stage, "--variant", variant] for variant in VARIANTS]
    logs = WORK / "logs"; logs.mkdir(parents=True, exist_ok=True)
    processes = []
    for variant, command in zip(VARIANTS, commands):
        output = (logs / f"{stage}-{variant}.log").open("a", encoding="utf-8")
        process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0)
        processes.append((variant, process, output))
    try:
        while any(process.poll() is None for _, process, _ in processes):
            children = []
            for _, process, _ in processes:
                if process.poll() is None:
                    parent = psutil.Process(process.pid)
                    children.extend([parent, *parent.children(recursive=True)])
            working = sum(item.memory_info().rss for item in children if item.is_running())
            if working > MAX_WORKING_SET:
                raise RuntimeError(f"campaign working set exceeded 2 GiB: {working}")
            if psutil.swap_memory().used - swap_start > MAX_SWAP_GROWTH:
                raise RuntimeError("pagefile use grew by more than 128 MiB")
            if project_bytes(WORK) > MAX_TRAINING_BYTES:
                raise RuntimeError("training quota exceeded")
            time.sleep(5)
        failures = {variant: process.returncode for variant, process, _ in processes
                    if process.returncode != 0}
        if failures:
            raise RuntimeError(f"variant workers failed: {failures}")
    except Exception:
        for _, process, _ in processes:
            if process.poll() is None:
                process.terminate()
        raise
    finally:
        for _, _, output in processes:
            output.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("collect", "train", "evaluate-test",
                                          "collect-all", "train-all",
                                          "evaluate-test-all"))
    parser.add_argument("--variant", choices=VARIANTS)
    args = parser.parse_args()
    if args.stage.endswith("-all"):
        coordinator(args.stage[:-4])
    elif not args.variant:
        parser.error("--variant is required")
    elif args.stage == "collect":
        collect(args.variant)
    elif args.stage == "train":
        train(args.variant)
    else:
        evaluate_test(args.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
