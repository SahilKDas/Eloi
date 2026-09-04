#!/usr/bin/env python3
"""Standard-only E2 NNUE campaign starting from production C."""
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
import numpy as np
import engine_lab
import nnue_e1_e32 as e1
import run_fresh_nnue_campaign as fresh
import train_nnue as trainer
import validation_support
import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "tmp/nnue-e2-standard-v2"
PRODUCTION_HEADER = ROOT / "include/eloi/nnue_weights.hpp"
C_BINARY = ROOT / "tmp/release-v2.5.0-attempt2/standalone-A/package/Eloi.exe"
E1_BINARY = ROOT / "tmp/nnue-e1-e32/candidates/E1-selected/build-1/Eloi.exe"
E1_RESULTS = ROOT / "tmp/nnue-e1-e32/gauntlet125/e1_vs_v250_results.json"
E1_PGN = ROOT / "tmp/nnue-e1-e32/gauntlet125/e1_vs_v250_games.pgn"
TEACHER = ROOT / "tmp/nnue-fresh-data/teacher/stockfish.exe"
RESERVE = ROOT / "data/search_recovery/reserve.json"
STRENGTH_OPENINGS = ROOT / "data/strength_openings.json"
CMAKE = Path("C:/msys64/ucrt64/bin/cmake.exe")
MSYS = Path("C:/msys64/ucrt64/bin")
PROJECTED_BYTES = 500_000_000
MAX_HARD_POSITIONS = 192
DIAGNOSTIC_NODES = 5_000
TEACHER_NODES = 100_000
TEACHER_ROOT_NODES = 25_000
MATE_SCORE = 30_000

EXPECTED = {
    "production_weights": "6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD",
    "c_binary": "4263AD9FE953252FAE0E0295FE03B16817A2275E560D4AA4067FDD54AC6309C5",
    "e1_binary": "FD817BAACA3D0E29DB74E24738BD68BBD1915CA12C09DEFC8F7C1A527C6908FC",
    "teacher": "5F95EAEA0D4EB697381989187CE6EB4D6AD59283C34421765ECC73CDB09BA766",
    "e1_results": "B0FDCF0B6DA928A97EAC3CD8F96BA91D7D9DD59FA1A968E1995491021C0C5241",
    "e1_pgn": "CBFAD67653309142C9AD3A3B4736E8597ADFC3E57828076BFDA8944C520603B9",
}
RECIPES = (
    {"id": "E2-conservative", "teacher_fraction": 0.25,
     "delta_fraction": 0.30, "hard_weight": 0.75, "hard_epochs": 2},
    {"id": "E2-balanced", "teacher_fraction": 0.50,
     "delta_fraction": 0.50, "hard_weight": 1.00, "hard_epochs": 2},
    {"id": "E2-ranking", "teacher_fraction": 0.50,
     "delta_fraction": 0.70, "hard_weight": 1.50, "hard_epochs": 3},
)


def sha256(path: Path) -> str:
    return engine_lab.sha256(Path(path))


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def immutable_json(path: Path, value) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"evidence collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def standard_board(fen: str) -> chess.Board:
    board = chess.Board(fen, chess960=False)
    if board.chess960 or type(board) is not chess.Board:
        raise ValueError("E2 accepts FIDE standard positions only")
    if not board.is_valid():
        raise ValueError(f"invalid standard position: {fen}")
    return board


def chess_points(label: str) -> float:
    try:
        return {"win": 1.0, "draw": 0.5, "loss": 0.0}[label]
    except KeyError as error:
        raise ValueError(f"unknown result: {label}") from error


def hard_partition(identity: str) -> str:
    digest = hashlib.sha256(
        f"E2-hard-partition-v1|{identity}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return "validation" if fraction < 0.20 else "train"


def poor_pair_indexes(rows: list[dict], maximum_points: float = 0.5) -> list[int]:
    if len(rows) < 124:
        raise ValueError("E1 gauntlet is incomplete")
    selected = []
    for index in range(62):
        pair = rows[2 * index:2 * index + 2]
        if pair[0]["opening"] != pair[1]["opening"]:
            raise ValueError("E1 gauntlet pairing is malformed")
        if sum(chess_points(row["result"]) for row in pair) <= maximum_points:
            selected.append(index)
    return selected


def validate_identities() -> dict:
    paths = {"production_weights": PRODUCTION_HEADER, "c_binary": C_BINARY,
             "e1_binary": E1_BINARY, "teacher": TEACHER,
             "e1_results": E1_RESULTS, "e1_pgn": E1_PGN}
    actual = {name: sha256(path) for name, path in paths.items()}
    for name, expected in EXPECTED.items():
        if actual[name] != expected:
            raise RuntimeError(f"{name} identity changed: {actual[name]}")
    return actual


def analysis_row(engine, board: chess.Board, nodes: int) -> dict:
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes), game=object())
    pv = info.get("pv", ())
    score = info["score"].pov(board.turn).score(mate_score=MATE_SCORE)
    return {"move": pv[0].uci() if pv else None,
            "score_cp_for_side_to_move": int(score or 0),
            "depth": int(info.get("depth", 0)), "nodes": int(info.get("nodes", 0)),
            "pv": [move.uci() for move in pv[:8]]}


def raw_hard_positions() -> list[dict]:
    result = read_json(E1_RESULTS)
    poor = set(poor_pair_indexes(result["results"]))
    games = []
    with E1_PGN.open(encoding="utf-8") as stream:
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            if game.errors:
                raise RuntimeError(f"invalid E1 PGN: {game.errors}")
            games.append(game)
    if len(games) != 125:
        raise RuntimeError("E1 PGN must contain exactly 125 games")
    candidates = {}
    for pair_index in sorted(poor):
        pair_points = sum(chess_points(item["result"])
                          for item in result["results"][2 * pair_index:2 * pair_index + 2])
        for row_index in (2 * pair_index, 2 * pair_index + 1):
            row, game = result["results"][row_index], games[row_index]
            candidate_white = row["candidate_color"] == "white"
            board = game.board()
            if type(board) is not chess.Board or board.chess960:
                raise RuntimeError("non-standard game found in E1 evidence")
            for move_number, move in enumerate(game.mainline_moves()):
                if board.turn == candidate_white and board.ply() >= 8:
                    fen = board.fen()
                    identity = hashlib.sha256(
                        f"E2-standard|{row_index}|{move_number}|{fen}".encode()).hexdigest()
                    candidates.setdefault(fen, {
                        "id": identity, "fen": fen, "actual_e1_move": move.uci(),
                        "source_game": row_index + 1, "source_pair": pair_index,
                        "source_pair_points": pair_points})
                board.push(move)
    return sorted(candidates.values(), key=lambda row: row["id"])


def prepare() -> dict:
    identities = validate_identities()
    protocol_path = WORK / "protocol.json"
    if not protocol_path.exists():
        snapshot = validation_support.resource_snapshot(WORK, PROJECTED_BYTES)
        protocol = {
            "schema": 1, "campaign": "E2-standard-only",
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "source_hashes": {
                Path(__file__).relative_to(ROOT).as_posix(): sha256(Path(__file__)),
                "scripts/train_nnue.py": sha256(ROOT / "scripts/train_nnue.py"),
                "scripts/engine_lab.py": sha256(ROOT / "scripts/engine_lab.py")},
            "identities": identities,
            "rules": {"training": "FIDE standard chess only",
                      "offline_validation": "FIDE standard chess only",
                      "strength_matches": "FIDE standard chess only",
                      "chess960_training_rows": 0, "horde_training_rows": 0,
                      "stockfish_role": "offline labels only; never code or runtime backend"},
            "bounds": {"projected_new_bytes": PROJECTED_BYTES,
                       "maximum_hard_positions": MAX_HARD_POSITIONS,
                       "diagnostic_nodes_per_engine_position": DIAGNOSTIC_NODES,
                       "teacher_nodes_per_position": TEACHER_NODES,
                       "teacher_root_nodes_per_extra_move": TEACHER_ROOT_NODES,
                       "search_threads_per_eloi_engine": 3, "concurrent_heavy_jobs": 1},
            "recipes": RECIPES, "resource_preflight": snapshot,
            "strength_ladder": {"screen": "20 games per candidate at 10,000 nodes/move",
                                "confirmation": "60 games; require at least 52%",
                                "final": "125 games; require at least 63 points"},
            "production_changed": False}
        immutable_json(protocol_path, protocol)
    else:
        protocol = read_json(protocol_path)
        if protocol["identities"] != identities:
            raise RuntimeError("frozen E2 input identities changed")
    path = WORK / "hard-positions.json"
    if path.exists():
        return read_json(path)
    raw = raw_hard_positions()[:384]
    c_engine = e1_engine = None
    selected = []
    try:
        c_engine = engine_lab.start_engine(C_BINARY, idle_priority=True)
        e1_engine = engine_lab.start_engine(E1_BINARY, idle_priority=True)
        for index, row in enumerate(raw, 1):
            board = standard_board(row["fen"])
            c_search = analysis_row(c_engine, board, DIAGNOSTIC_NODES)
            e1_search = analysis_row(e1_engine, board, DIAGNOSTIC_NODES)
            if row["actual_e1_move"] != c_search["move"] or e1_search["move"] != c_search["move"]:
                selected.append({**row, "c_search": c_search, "e1_search": e1_search})
            if len(selected) >= MAX_HARD_POSITIONS:
                break
            if index % 32 == 0:
                print(json.dumps({"stage": "diagnose", "examined": index,
                                  "selected": len(selected)}), flush=True)
    finally:
        for engine in (c_engine, e1_engine):
            if engine is not None:
                engine.quit()
    document = {"schema": 1, "rules": "FIDE standard chess only",
                "selection": "deterministic E1 weak-pair sample; retain C/E1 root disagreements",
                "raw_candidates_examined": len(raw), "count": len(selected),
                "positions": selected}
    if len(selected) < 48:
        raise RuntimeError(f"insufficient hard disagreements: {len(selected)}")
    immutable_json(path, document)
    return document


def score_cp(info: dict, color: chess.Color) -> int:
    value = info["score"].pov(color).score(mate_score=MATE_SCORE)
    return int(value or 0)


def label() -> dict:
    prepared = prepare()
    output_path = WORK / "hard-labels.jsonl"
    existing = []
    if output_path.exists():
        existing = [json.loads(line) for line in
                    output_path.read_text(encoding="utf-8").splitlines() if line]
    expected_ids = [row["id"] for row in prepared["positions"]]
    if [row["id"] for row in existing] != expected_ids[:len(existing)]:
        raise RuntimeError("hard-label resume prefix differs from frozen positions")
    if len(existing) == len(expected_ids):
        return {"count": len(existing), "path": output_path.as_posix(),
                "sha256": sha256(output_path)}

    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    teacher = chess.engine.SimpleEngine.popen_uci(
        [str(TEACHER)], timeout=120.0, creationflags=flags)
    try:
        settings = {}
        if "Threads" in teacher.options:
            settings["Threads"] = 1
        if "Hash" in teacher.options:
            settings["Hash"] = 64
        if settings:
            teacher.configure(settings)
        with output_path.open("a", encoding="utf-8", newline="\n") as stream:
            remaining = prepared["positions"][len(existing):]
            for index, source in enumerate(remaining, len(existing) + 1):
                board = standard_board(source["fen"])
                multipv = min(4, board.legal_moves.count())
                infos = teacher.analyse(
                    board, chess.engine.Limit(nodes=TEACHER_NODES),
                    multipv=multipv, game=object())
                if isinstance(infos, dict):
                    infos = [infos]
                move_scores = {}
                for info in infos:
                    pv = info.get("pv", ())
                    if pv:
                        move_scores[pv[0].uci()] = score_cp(info, board.turn)
                best_move = infos[0]["pv"][0]
                best_score_side = score_cp(infos[0], board.turn)
                candidates = [source["actual_e1_move"], source["c_search"]["move"],
                              source["e1_search"]["move"], *move_scores.keys()]
                ordered = []
                for uci in candidates:
                    if uci and uci != best_move.uci() and uci not in ordered:
                        move = chess.Move.from_uci(uci)
                        if move in board.legal_moves:
                            ordered.append(uci)
                alternatives = []
                for uci in ordered[:4]:
                    if uci not in move_scores:
                        info = teacher.analyse(
                            board, chess.engine.Limit(nodes=TEACHER_ROOT_NODES),
                            root_moves=[chess.Move.from_uci(uci)], game=object())
                        move_scores[uci] = score_cp(info, board.turn)
                    gap = best_score_side - move_scores[uci]
                    if gap >= 20:
                        alternatives.append({"move": uci,
                                             "score_cp_for_side_to_move": move_scores[uci],
                                             "gap_cp": gap})
                row = {
                    "id": source["id"], "fen": source["fen"],
                    "partition": hard_partition(source["id"]),
                    "best_move": best_move.uci(),
                    "target_cp_white": max(-2000, min(2000, score_cp(infos[0], chess.WHITE))),
                    "alternatives": alternatives, "source": source,
                    "teacher": {"name": "Stockfish 17.1", "nodes": TEACHER_NODES,
                                "role": "offline label generator only"},
                    "variant": "standard"}
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                if index % 16 == 0 or index == len(expected_ids):
                    print(json.dumps({"stage": "label", "completed": index,
                                      "total": len(expected_ids)}), flush=True)
    finally:
        teacher.quit()
    rows = [json.loads(line) for line in
            output_path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != len(expected_ids):
        raise RuntimeError("hard labeling ended incomplete")
    result = {"count": len(rows),
              "train": sum(r["partition"] == "train" for r in rows),
              "validation": sum(r["partition"] == "validation" for r in rows),
              "pairs": sum(len(r["alternatives"]) for r in rows),
              "sha256": sha256(output_path), "stockfish_runtime_dependency": False}
    if not result["train"] or not result["validation"]:
        raise RuntimeError("salted hard-data partition produced an empty split")
    immutable_json(WORK / "hard-labels-summary.json", result)
    return result


def distilled_samples(samples: list, c_model, teacher_fraction: float) -> list:
    quantized = trainer.quantize_model(*c_model)
    result = []
    for white, black, target, *_rest in samples:
        c_score = float(trainer.forward_quantized(*quantized, white, black)[0])
        blended = (1.0 - teacher_fraction) * c_score + teacher_fraction * float(target)
        result.append((white, black, blended, 0.50))
    return result


def hard_samples() -> dict[str, dict[str, list]]:
    rows = [json.loads(line) for line in
            (WORK / "hard-labels.jsonl").read_text(encoding="utf-8").splitlines() if line]
    result = {part: {"evaluations": [], "pairs": []}
              for part in ("train", "validation")}
    for row in rows:
        if row.get("variant") != "standard":
            raise RuntimeError("variant row reached E2 hard-data loader")
        board = standard_board(row["fen"])
        part = row["partition"]
        meta = {"record_id": row["id"], "phase_bucket": "hard-gauntlet"}
        result[part]["evaluations"].append((
            trainer.features(board, chess.WHITE), trainer.features(board, chess.BLACK),
            float(row["target_cp_white"]), 1.5, meta))
        best = chess.Move.from_uci(row["best_move"])
        best_board = board.copy()
        best_board.push(best)
        for alternative in row["alternatives"]:
            alt_board = board.copy()
            alt_board.push(chess.Move.from_uci(alternative["move"]))
            weight = max(0.5, min(2.0, alternative["gap_cp"] / 100.0))
            result[part]["pairs"].append((
                trainer.features(best_board, chess.WHITE), trainer.features(best_board, chess.BLACK),
                trainer.features(alt_board, chess.WHITE), trainer.features(alt_board, chess.BLACK),
                1 if board.turn == chess.WHITE else -1, weight))
    return result


def anchor_to_c(model, c_model, delta_fraction: float):
    return tuple(c + delta_fraction * (candidate - c)
                 for c, candidate in zip(c_model, model))


def pair_accuracy(model, pairs: list) -> float | None:
    if not pairs:
        return None
    quantized = trainer.quantize_model(*model)
    correct = 0
    for best_w, best_b, alt_w, alt_b, side, *_ in pairs:
        best = trainer.forward_quantized(*quantized, best_w, best_b)[0]
        alt = trainer.forward_quantized(*quantized, alt_w, alt_b)[0]
        correct += side * (best - alt) > 0
    return correct / len(pairs)


def model_drift(model, c_model, samples: list) -> dict:
    candidate_q = trainer.quantize_model(*model)
    c_q = trainer.quantize_model(*c_model)
    differences = []
    for sample in samples:
        candidate = trainer.forward_quantized(*candidate_q, sample[0], sample[1])[0]
        baseline = trainer.forward_quantized(*c_q, sample[0], sample[1])[0]
        differences.append(abs(candidate - baseline))
    return {"count": len(differences),
            "mean_absolute_cp": float(np.mean(differences)),
            "median_absolute_cp": float(np.median(differences)),
            "max_absolute_cp": float(np.max(differences))}


def train() -> dict:
    label()
    output_path = WORK / "training-results.json"
    if output_path.exists():
        return read_json(output_path)
    c_model, provenance = e1.load_c()
    base = e1.load_evaluations_readonly(provenance)
    legacy_pairs = e1.load_puzzles_readonly(provenance)
    hard = hard_samples()
    all_channels = list(range(64))
    reports = []
    for recipe in RECIPES:
        model = tuple(array.copy() for array in c_model)
        evaluation_rows = distilled_samples(
            base["train"], c_model, recipe["teacher_fraction"])
        model = trainer.train_evaluations(
            *model, list(evaluation_rows), epochs=1,
            trainable_channels=all_channels)
        preserving_pairs = [(*pair, 0.20) for pair in legacy_pairs]
        model = trainer.train_pairs(
            *model, preserving_pairs, epochs=1,
            trainable_channels=all_channels)
        weighted_hard = [(*pair[:5], pair[5] * recipe["hard_weight"])
                         for pair in hard["train"]["pairs"]]
        model = trainer.train_pairs(
            *model, weighted_hard, epochs=recipe["hard_epochs"],
            trainable_channels=all_channels)
        recalibration = [*evaluation_rows, *hard["train"]["evaluations"]]
        model = trainer.train_evaluations(
            *model, recalibration, epochs=1,
            trainable_channels=all_channels)
        model = anchor_to_c(model, c_model, recipe["delta_fraction"])

        directory = WORK / "candidates" / recipe["id"]
        if directory.exists():
            raise RuntimeError(f"candidate collision: {directory}")
        include = directory / "include/eloi"
        include.mkdir(parents=True)
        checkpoint = directory / "float.npz"
        np.savez(checkpoint, weights=model[0], bias=model[1], output=model[2])
        header = include / "nnue_weights.hpp"
        architecture = include / "nnue_architecture.hpp"
        counts = {"train_evaluations": (len(base["train"]) +
                                         len(hard["train"]["evaluations"])),
                  "train_pairs": len(legacy_pairs) + len(hard["train"]["pairs"]),
                  "base_train_evaluations": len(base["train"]),
                  "base_validation_evaluations": len(base["validation"]),
                  "legacy_standard_pairs": len(legacy_pairs),
                  "hard_train_evaluations": len(hard["train"]["evaluations"]),
                  "hard_train_pairs": len(hard["train"]["pairs"]),
                  "hard_validation_evaluations": len(hard["validation"]["evaluations"]),
                  "hard_validation_pairs": len(hard["validation"]["pairs"]),
                  "chess960_rows": 0, "horde_rows": 0}
        trainer.write_header(
            header, *model, counts, set(),
            source_description=("FIDE standard only; C-distilled offline Stockfish "
                                "labels and engine-derived hard rankings"))
        trainer.write_architecture(architecture, 64)
        report = {**recipe, "architecture_hidden": 64,
                  "checkpoint_sha256": sha256(checkpoint),
                  "weights_sha256": sha256(header),
                  "architecture_sha256": sha256(architecture), "counts": counts,
                  "standard_validation": fresh.regression_metrics(model, base["validation"]),
                  "hard_validation": {
                      "evaluation": fresh.regression_metrics(
                          model, hard["validation"]["evaluations"]),
                      "pair_accuracy": pair_accuracy(model, hard["validation"]["pairs"])},
                  "c_preservation_drift": model_drift(model, c_model, base["validation"]),
                  "channels": e1.channel_stats(model, base["validation"])}
        immutable_json(directory / "training.json", report)
        reports.append(report)
        print(json.dumps({"stage": "trained", "candidate": recipe["id"],
                          "standard_mae": report["standard_validation"]["mae_cp"],
                          "hard_pair_accuracy": report["hard_validation"]["pair_accuracy"],
                          "c_drift": report["c_preservation_drift"]["mean_absolute_cp"]}),
              flush=True)
    result = {"schema": 1, "rules": "FIDE standard chess only",
              "starting_network_sha256": EXPECTED["production_weights"],
              "candidates": reports,
              "selection_metric": "engine-in-loop screen against C; offline metrics diagnostic only",
              "production_changed": sha256(PRODUCTION_HEADER) != EXPECTED["production_weights"]}
    immutable_json(output_path, result)
    return result


def run_command(command: list, log: Path, timeout: int) -> dict:
    flags = subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = dict(os.environ)
    env["PATH"] = str(MSYS) + os.pathsep + env.get("PATH", "")
    started = time.monotonic()
    with log.open("w", encoding="utf-8", newline="\n") as stream:
        result = subprocess.run([str(item) for item in command], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout, creationflags=flags, env=env)
    return {"command": [str(item) for item in command], "exit_code": result.returncode,
            "elapsed_seconds": time.monotonic() - started,
            "log": log.relative_to(ROOT).as_posix(), "log_sha256": sha256(log)}


def validate_candidate(name: str) -> dict:
    directory = WORK / "candidates" / name
    build = directory / "build-1"
    if build.exists():
        raise RuntimeError(f"build collision: {build}")
    build.mkdir()
    checks = []
    commands = (
        ([CMAKE, "-S", ROOT, "-B", build, "-G", "Ninja",
          "-DCMAKE_BUILD_TYPE=Release", "-DELOI_BUILD_TESTS=ON", "-DELOI_BUILD_APP=ON",
          f"-DCMAKE_CXX_COMPILER={(MSYS / 'c++.exe').as_posix()}",
          f"-DCMAKE_MAKE_PROGRAM={(MSYS / 'ninja.exe').as_posix()}",
          f"-DCMAKE_RC_COMPILER={(MSYS / 'windres.exe').as_posix()}",
          f"-DELOI_NNUE_INCLUDE_DIR={(directory / 'include').as_posix()}"],
         directory / "configure.log", 180),
        ([CMAKE, "--build", build, "--target", "Eloi", "eloi_tests", "-j", "2"],
         directory / "build.log", 900))
    for command, log, timeout in commands:
        check = run_command(command, log, timeout)
        checks.append(check)
        if check["exit_code"]:
            return {"candidate": name, "passed": False, "checks": checks}
    runtime = (
        ([build / "eloi_tests.exe"], directory / "tests.log", 180),
        ([build / "Eloi.exe", "--perft", "--depth", "4"], directory / "perft.log", 60),
        ([sys.executable, ROOT / "scripts/differential_movegen.py", "--engine",
          build / "Eloi.exe", "--samples", "32"], directory / "differential.log", 300))
    for command, log, timeout in runtime:
        checks.append(run_command(command, log, timeout))
    perft = (directory / "perft.log").read_text(encoding="utf-8")
    return {"candidate": name,
            "passed": all(check["exit_code"] == 0 for check in checks) and ",4,197281," in perft,
            "checks": checks, "binary_sha256": sha256(build / "Eloi.exe"),
            "production_unchanged": sha256(PRODUCTION_HEADER) == EXPECTED["production_weights"]}


def validate() -> dict:
    train()
    path = WORK / "validation-results.json"
    if path.exists():
        return read_json(path)
    result = {"schema": 1,
              "candidates": [validate_candidate(recipe["id"]) for recipe in RECIPES]}
    result["all_passed"] = all(row["passed"] for row in result["candidates"])
    immutable_json(path, result)
    return result


def freeze_suite(name: str, source: Path, indexes: range) -> Path:
    document = read_json(source)
    selected = []
    for index in indexes:
        row = document["positions"][index]
        board = standard_board(row["fen"])
        selected.append({"source_index": index, "fen": board.fen(),
                         "filter_cp": row.get("filter_cp")})
    path = WORK / "matches" / f"{name}-openings.json"
    immutable_json(path, {"schema": 1, "name": name,
                          "rules": "FIDE standard chess only",
                          "source": source.relative_to(ROOT).as_posix(),
                          "source_sha256": sha256(source), "positions": selected})
    return path


def match(candidate: Path, suite: Path, stem: str, games: int,
          required_score: float, allow_unpaired: bool = False) -> dict:
    protocol_path = WORK / "matches" / f"{stem}-protocol.json"
    immutable_json(protocol_path, {
        "schema": 1, "rules": "FIDE standard chess only",
        "candidate_sha256": sha256(candidate), "baseline_sha256": sha256(C_BINARY),
        "suite_sha256": sha256(suite), "games": games, "nodes_per_move": 10_000,
        "threads_per_engine": 3, "hash_mb": 32, "max_plies": 200,
        "required_score": required_score, "allow_unpaired_final": allow_unpaired})
    return engine_lab.strength_gate(
        candidate, C_BINARY, suite,
        WORK / "matches" / f"{stem}-results.json",
        WORK / "matches" / f"{stem}.pgn", None, games, 200,
        architecture_playoff=False, nodes=10_000, gate_metric="score",
        required_score=required_score, idle_priority=True,
        protocol_path=protocol_path, allow_unpaired_final=allow_unpaired)


def screen() -> dict:
    validation = validate()
    if not validation["all_passed"]:
        raise RuntimeError("E2 correctness failure blocks strength screening")
    output = WORK / "screen-results.json"
    if output.exists():
        return read_json(output)
    suite = freeze_suite("screen", RESERVE, range(183, 193))
    training = read_json(WORK / "training-results.json")
    metrics = {row["id"]: row for row in training["candidates"]}
    results = []
    for recipe in RECIPES:
        name = recipe["id"]
        candidate = WORK / "candidates" / name / "build-1/Eloi.exe"
        report = match(candidate, suite, f"screen-{name}", 20, 0.50)
        results.append({"candidate": name, "wins": report["wins"],
                        "draws": report["draws"], "losses": report["losses"],
                        "score": report["score"], "passed": report["passed"],
                        "hard_pair_accuracy": metrics[name]["hard_validation"]["pair_accuracy"],
                        "c_drift_cp": metrics[name]["c_preservation_drift"]["mean_absolute_cp"]})
    preference = {"E2-balanced": 2, "E2-conservative": 1, "E2-ranking": 0}
    selected = max(results, key=lambda row: (
        row["score"], -row["losses"], row["hard_pair_accuracy"] or -1,
        -row["c_drift_cp"], preference[row["candidate"]]))
    document = {"schema": 1, "games_per_candidate": 20, "results": results,
                "selection_order": "score, fewer losses, hard-pair accuracy, lower C drift, fixed preference",
                "selected": selected["candidate"],
                "offline_metrics_selected_candidate": False}
    immutable_json(output, document)
    return document


def confirm() -> dict:
    selection = screen()
    output = WORK / "confirmation-results.json"
    if output.exists():
        return read_json(output)
    suite = freeze_suite("confirmation", RESERVE, range(193, 223))
    name = selection["selected"]
    candidate = WORK / "candidates" / name / "build-1/Eloi.exe"
    report = match(candidate, suite, f"confirmation-{name}", 60, 0.52)
    document = {"schema": 1, "candidate": name, "wins": report["wins"],
                "draws": report["draws"], "losses": report["losses"],
                "score": report["score"], "required_score": 0.52,
                "passed": report["passed"]}
    immutable_json(output, document)
    return document


def final_gauntlet() -> dict:
    confirmation = confirm()
    if not confirmation["passed"]:
        raise RuntimeError("E2 confirmation failed; final gauntlet is blocked")
    output = WORK / "final-results.json"
    if output.exists():
        return read_json(output)
    suite = freeze_suite("final", STRENGTH_OPENINGS, range(300, 363))
    name = confirmation["candidate"]
    candidate = WORK / "candidates" / name / "build-1/Eloi.exe"
    report = match(candidate, suite, f"final-{name}", 125, 0.504, True)
    document = {"schema": 1, "candidate": name, "wins": report["wins"],
                "draws": report["draws"], "losses": report["losses"],
                "score": report["score"],
                "points": report["wins"] + report["draws"] / 2,
                "required_points": 63, "passed": report["passed"],
                "production_promoted": False}
    immutable_json(output, document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "label", "train", "validate",
                                          "screen", "confirm", "final", "run"))
    args = parser.parse_args()
    validate_identities()
    operations = {"prepare": prepare, "label": label, "train": train,
                  "validate": validate, "screen": screen, "confirm": confirm,
                  "final": final_gauntlet, "run": final_gauntlet}
    result = operations[args.stage]()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
