#!/usr/bin/env python3
"""Build and validate E1-64 and E32 without changing production Eloi."""
from __future__ import annotations

import argparse
import collections
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

import run_fresh_nnue_campaign as fresh
import train_nnue as trainer
import validation_support
import chess


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "tmp/nnue-e1-e32"
PRODUCTION_HEADER = ROOT / "include/eloi/nnue_weights.hpp"
PRODUCTION_PROVENANCE = ROOT / "data/nnue_provenance.json"
C_CHECKPOINT = ROOT / "tmp/nnue-fresh-data/candidates/C/float.npz"
CMAKE = Path("C:/msys64/ucrt64/bin/cmake.exe")
MSYS = Path("C:/msys64/ucrt64/bin")
PROJECTED_BYTES = 250_000_000
REVIVAL_DENSITY = 32
E1_SEED = 0xE101
E32_SEED = 0xE032


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"evidence collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def load_c():
    provenance = read_json(PRODUCTION_PROVENANCE)
    if sha256(PRODUCTION_HEADER) != provenance["selected_weights_sha256"]:
        raise RuntimeError("production C header identity changed")
    if not C_CHECKPOINT.is_file():
        raise RuntimeError("C float checkpoint is unavailable")
    if sha256(C_CHECKPOINT) != provenance["checkpoint_sha256"]:
        raise RuntimeError("C float checkpoint identity changed")
    with np.load(C_CHECKPOINT) as saved:
        model = tuple(saved[name].copy() for name in ("weights", "bias", "output"))
    quantized = trainer.quantize_model(*model)
    header = trainer.load_quantized_header(PRODUCTION_HEADER)
    if any(not np.array_equal(left, right)
           for left, right in zip(quantized, header)):
        raise RuntimeError("C checkpoint does not quantize to production")
    return model, provenance


def learning_key(fen):
    placement = fen.split()[0]
    mirrored = "/".join(reversed(placement.split("/"))).swapcase()
    return min(placement, mirrored)


def load_evaluations_readonly(provenance):
    positions = ROOT / "tmp/nnue-fresh-data/positions.jsonl"
    labels = ROOT / "tmp/nnue-fresh-data/labels.jsonl"
    exclusion_path = (
        ROOT / "tmp/nnue-fresh-data/learning-equivalence-exclusions.json"
    )
    exclusions = read_json(exclusion_path)
    if sha256(positions) != provenance["inputs"]["positions_sha256"]:
        raise RuntimeError("frozen position identity changed")
    if sha256(labels) != provenance["inputs"]["labels_sha256"]:
        raise RuntimeError("frozen label identity changed")
    if exclusions["positions_sha256"] != sha256(positions):
        raise RuntimeError("learning-equivalence exclusions do not match positions")
    conflicts = set(exclusions["conflicting_learning_keys"])
    result = {"train": [], "validation": [], "test": []}
    with labels.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if not row["accepted"] or row["partition"] == "test":
                continue
            if learning_key(row["fen"]) in conflicts:
                continue
            board = chess.Board(row["fen"])
            result[row["partition"]].append((
                trainer.features(board, chess.WHITE),
                trainer.features(board, chess.BLACK),
                float(row["high"]["cp"]),
                1.0,
                {"record_id": row["id"], "phase_bucket": row["phase"]},
            ))
    return result


def load_puzzles_readonly(provenance):
    source = (
        ROOT / ".deps/nnue-inputs-v2-broader1/canonical-puzzles.jsonl"
    )
    selection_path = ROOT / "tmp/nnue-fresh-data/puzzle-selection.json"
    selection = read_json(selection_path)
    if sha256(source) != provenance["inputs"]["canonical_puzzles_sha256"]:
        raise RuntimeError("canonical puzzle identity changed")
    selected_ids = selection["selected_ids"]
    if len(selected_ids) != selection["count"] or len(set(selected_ids)) != len(selected_ids):
        raise RuntimeError("frozen puzzle selection is malformed")
    wanted = set(selected_ids)
    rows = {}
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["record_id"] in wanted:
                rows[row["record_id"]] = row
    if set(rows) != wanted:
        raise RuntimeError("frozen puzzle selection cannot be reconstructed")
    pairs = []
    for record_id in selected_ids:
        row = rows[record_id]
        board = chess.Board(row["decision_fen"])
        best = chess.Move.from_uci(row["best_move"])
        if best not in board.legal_moves:
            raise RuntimeError(f"selected puzzle has illegal best move: {record_id}")
        alternatives = sorted(
            (move for move in board.legal_moves if move != best),
            key=lambda move: move.uci(),
        )
        if not alternatives:
            raise RuntimeError(f"selected puzzle has no negative move: {record_id}")
        alternative = trainer.deterministic_choice(
            alternatives,
            trainer.SEED,
            "canonical-random-negative",
            record_id,
        )
        best_board, alternative_board = board.copy(), board.copy()
        best_board.push(best)
        alternative_board.push(alternative)
        pairs.append((
            trainer.features(best_board, chess.WHITE),
            trainer.features(best_board, chess.BLACK),
            trainer.features(alternative_board, chess.WHITE),
            trainer.features(alternative_board, chess.BLACK),
            1 if board.turn == chess.WHITE else -1,
        ))
    return pairs


def channel_indices(model):
    weights, _, output = trainer.quantize_model(*model)
    occupied = (np.count_nonzero(weights, axis=0) != 0) | (output != 0)
    return np.flatnonzero(occupied).tolist(), np.flatnonzero(~occupied).tolist()


def channel_stats(model, evaluation_samples=()):
    weights, bias, output = trainer.quantize_model(*model)
    occupied = (np.count_nonzero(weights, axis=0) != 0) | (output != 0)
    informative = np.zeros(output.size, dtype=np.int64)
    sample_count = 0
    for sample in evaluation_samples:
        _, white, black = trainer.forward_quantized(
            weights, bias, output, sample[0], sample[1]
        )
        informative += white != black
        sample_count += 1
    return {
        "hidden": int(output.size),
        "occupied_channels": int(np.count_nonzero(occupied)),
        "dormant_channels": int(np.count_nonzero(~occupied)),
        "nonzero_output_coefficients": int(np.count_nonzero(output)),
        "nonzero_input_weights": int(np.count_nonzero(weights)),
        "informative_channels": (
            int(np.count_nonzero(informative)) if sample_count else None
        ),
        "minimum_informative_fraction": (
            float(informative.min() / sample_count) if sample_count else None
        ),
        "median_informative_fraction": (
            float(np.median(informative) / sample_count) if sample_count else None
        ),
    }


def revive_channels(model, indices, seed):
    weights, bias, output = (array.copy() for array in model)
    channels = sorted(set(int(index) for index in indices))
    if any(index < 0 or index >= output.size for index in channels):
        raise ValueError("revival channel index is outside the network")
    rng = np.random.default_rng(seed)
    sparse_count = trainer.FEATURES // REVIVAL_DENSITY
    for sequence, channel in enumerate(channels):
        weights[:, channel] = 0
        selected = rng.choice(trainer.FEATURES, sparse_count, replace=False)
        signs = rng.choice(np.array([-1.0, 1.0], dtype=np.float32), sparse_count)
        weights[selected, channel] = signs
        bias[channel] = 8
        output[channel] = 1 if sequence % 2 == 0 else -1
    return weights, bias, output


def compact_c_to_32(model):
    occupied, _ = channel_indices(model)
    if len(occupied) > 32:
        raise RuntimeError(
            f"C has {len(occupied)} occupied channels and cannot compact exactly to 32"
        )
    selected = occupied
    weights, bias, output = model
    compact = (
        np.zeros((trainer.FEATURES, 32), dtype=np.float32),
        np.full(32, 8, dtype=np.float32),
        np.zeros(32, dtype=np.float32),
    )
    for destination, source in enumerate(selected):
        compact[0][:, destination] = weights[:, source]
        compact[1][destination] = bias[source]
        compact[2][destination] = output[source]
    return compact, selected, list(range(len(selected), 32))


def quantized_predictions(model, samples):
    quantized = trainer.quantize_model(*model)
    return [
        trainer.forward_quantized(
            *quantized, sample[0], sample[1]
        )[0]
        for sample in samples
    ]


def epoch_recorder(candidate, phase, validation, rows):
    def record(epoch, weights, bias, output, optimizer):
        model = (weights, bias, output)
        metrics = fresh.regression_metrics(model, validation)
        row = {
            "candidate": candidate,
            "phase": phase,
            "epoch": epoch,
            "optimizer": optimizer,
            "quantized_validation_mae_cp": metrics["mae_cp"],
            "channels": channel_stats(model, validation),
        }
        rows.append(row)
        print(json.dumps(row), flush=True)
    return record


def train_residual(candidate, model, trainable, evaluations, puzzles, validation):
    history = []
    weights, bias, output = model
    weights, bias, output = trainer.train_evaluations(
        weights, bias, output, list(evaluations), epochs=2,
        trainable_channels=trainable,
        epoch_callback=epoch_recorder(candidate, "evaluation-warmup", validation, history),
    )
    weights, bias, output = trainer.train_pairs(
        weights, bias, output, list(puzzles), epochs=3,
        trainable_channels=trainable,
        epoch_callback=epoch_recorder(candidate, "tactical-ranking", validation, history),
    )
    weights, bias, output = trainer.train_evaluations(
        weights, bias, output, list(evaluations), epochs=1,
        trainable_channels=trainable,
        epoch_callback=epoch_recorder(candidate, "evaluation-recalibration", validation, history),
    )
    return (weights, bias, output), history


def emit_candidate(name, model, trainable, metadata, validation, counts):
    directory = WORK / "candidates" / name
    if directory.exists():
        raise RuntimeError(f"candidate output collision: {directory}")
    include = directory / "include/eloi"
    include.mkdir(parents=True)
    checkpoint = directory / "float.npz"
    np.savez(checkpoint, weights=model[0], bias=model[1], output=model[2])
    header = include / "nnue_weights.hpp"
    architecture = include / "nnue_architecture.hpp"
    trainer.write_header(
        header, *model, counts, set(),
        source_description=(
            "Eloi C residual experiment; existing offline labels only; "
            "no runtime teacher"
        ),
    )
    trainer.write_architecture(architecture, len(model[2]))
    if any(not np.array_equal(left, right) for left, right in zip(
        trainer.load_quantized_header(header), trainer.quantize_model(*model)
    )):
        raise RuntimeError(f"{name} header/checkpoint mismatch")
    report = {
        "id": name,
        "architecture_hidden": len(model[2]),
        "trainable_channels": list(trainable),
        "weights_sha256": sha256(header),
        "architecture_sha256": sha256(architecture),
        "checkpoint_sha256": sha256(checkpoint),
        "quantized_validation": fresh.regression_metrics(model, validation),
        "channels": channel_stats(model, validation),
        **metadata,
    }
    write_json(directory / "training.json", report)
    return report


def train():
    if WORK.exists():
        raise RuntimeError(
            "candidate work already exists; preserve it or choose a fresh experiment root"
        )
    snapshot = validation_support.resource_snapshot(WORK, PROJECTED_BYTES)
    c, provenance = load_c()
    samples = load_evaluations_readonly(provenance)
    puzzles = load_puzzles_readonly(provenance)
    evaluations, validation = samples["train"], samples["validation"]
    occupied, dormant = channel_indices(c)
    if len(dormant) != 41:
        raise RuntimeError(f"expected 41 dormant C channels, found {len(dormant)}")

    WORK.mkdir(parents=True)
    initial_c_predictions = quantized_predictions(c, validation)

    e1_initial = revive_channels(c, dormant, E1_SEED)
    e1, e1_history = train_residual(
        "E1", e1_initial, dormant, evaluations, puzzles, validation
    )

    compact, selected, e32_trainable = compact_c_to_32(c)
    compact_predictions = quantized_predictions(compact, validation)
    if compact_predictions != initial_c_predictions:
        raise RuntimeError("32-unit C compaction changed quantized predictions")
    e32_initial = revive_channels(compact, e32_trainable, E32_SEED)
    e32, e32_history = train_residual(
        "E32", e32_initial, e32_trainable, evaluations, puzzles, validation
    )

    counts = {
        "train_evaluations": len(evaluations),
        "train_pairs": len(puzzles),
        "validation_evaluations": len(validation),
    }
    baseline = {
        "weights_sha256": sha256(PRODUCTION_HEADER),
        "checkpoint_sha256": sha256(C_CHECKPOINT),
        "quantized_validation": fresh.regression_metrics(c, validation),
        "channels": channel_stats(c, validation),
    }
    reports = [
        emit_candidate("E1", e1, dormant, {
            "recipe": "C plus deterministic revival and residual-only A-B-C training of 41 dormant channels",
            "history": e1_history,
            "preserved_c_channels": occupied,
        }, validation, counts),
        emit_candidate("E32", e32, e32_trainable, {
            "recipe": "Exact 23-channel C compaction plus deterministic revival and residual-only A-B-C training of nine channels",
            "history": e32_history,
            "c_source_channels": selected,
            "pre_revival_predictions_identical_to_c": True,
        }, validation, counts),
    ]
    protocol = {
        "schema": 1,
        "purpose": "isolated E1-64 and E32 experiment; production remains C",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_hashes": {
            path.relative_to(ROOT).as_posix(): sha256(path)
            for path in (
                Path(__file__),
                ROOT / "scripts/train_nnue.py",
                ROOT / "scripts/run_fresh_nnue_campaign.py",
                ROOT / "scripts/validation_support.py",
            )
        },
        "inputs": {
            "production_provenance_sha256": sha256(PRODUCTION_PROVENANCE),
            "labels_sha256": provenance["inputs"]["labels_sha256"],
            "canonical_puzzles_sha256": provenance["inputs"]["canonical_puzzles_sha256"],
            "stockfish_executed": False,
        },
        "bounds": {
            "projected_new_bytes": PROJECTED_BYTES,
            "concurrent_heavy_jobs": 1,
            "search_threads_per_engine": 3,
        },
        "revival": {
            "density_denominator": REVIVAL_DENSITY,
            "e1_seed": E1_SEED,
            "e32_seed": E32_SEED,
            "active_c_parameters_frozen_during_training": True,
        },
        "resource_preflight": snapshot,
        "baseline": baseline,
        "candidates": reports,
        "production_changed": sha256(PRODUCTION_HEADER)
        != provenance["selected_weights_sha256"],
        "held_out_test_opened": False,
        "gauntlet_run": False,
    }
    write_json(WORK / "training-results.json", protocol)
    print(json.dumps({
        "baseline_mae": baseline["quantized_validation"]["mae_cp"],
        "candidates": {
            report["id"]: {
                "mae": report["quantized_validation"]["mae_cp"],
                "channels": report["channels"],
            }
            for report in reports
        },
    }, indent=2))


def train_selected():
    validation_support.resource_snapshot(WORK, PROJECTED_BYTES)
    c, provenance = load_c()
    samples = load_evaluations_readonly(provenance)
    evaluations, validation = samples["train"], samples["validation"]
    occupied, dormant = channel_indices(c)
    if len(dormant) != 41:
        raise RuntimeError(f"expected 41 dormant C channels, found {len(dormant)}")
    counts = {
        "train_evaluations": len(evaluations),
        "train_pairs": 0,
        "validation_evaluations": len(validation),
    }

    e1_history = []
    e1_initial = revive_channels(c, dormant, E1_SEED)
    e1 = trainer.train_evaluations(
        *e1_initial,
        list(evaluations),
        epochs=1,
        trainable_channels=dormant,
        epoch_callback=epoch_recorder(
            "E1-selected", "evaluation-warmup", validation, e1_history
        ),
    )

    compact, selected, e32_trainable = compact_c_to_32(c)
    if quantized_predictions(compact, validation) != quantized_predictions(c, validation):
        raise RuntimeError("32-unit C compaction changed quantized predictions")
    e32_history = []
    e32_initial = revive_channels(compact, e32_trainable, E32_SEED)
    e32 = trainer.train_evaluations(
        *e32_initial,
        list(evaluations),
        epochs=1,
        trainable_channels=e32_trainable,
        epoch_callback=epoch_recorder(
            "E32-selected", "evaluation-warmup", validation, e32_history
        ),
    )

    reports = [
        emit_candidate("E1-selected", e1, dormant, {
            "recipe": "C plus deterministic revival and one residual evaluation epoch on 41 channels",
            "selection": "lowest predeclared-stage validation MAE; sealed test unopened",
            "history": e1_history,
            "preserved_c_channels": occupied,
        }, validation, counts),
        emit_candidate("E32-selected", e32, e32_trainable, {
            "recipe": "Exact 23-channel C compaction plus nine revived channels and one residual evaluation epoch",
            "selection": "lowest predeclared-stage validation MAE; sealed test unopened",
            "history": e32_history,
            "c_source_channels": selected,
            "pre_revival_predictions_identical_to_c": True,
        }, validation, counts),
    ]
    write_json(WORK / "selected-training-results.json", {
        "schema": 1,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_hashes": {
            path.relative_to(ROOT).as_posix(): sha256(path)
            for path in (Path(__file__), ROOT / "scripts/train_nnue.py")
        },
        "candidates": reports,
        "held_out_test_opened": False,
        "gauntlet_run": False,
        "production_header_unchanged": (
            sha256(PRODUCTION_HEADER) == provenance["selected_weights_sha256"]
        ),
    })
    print(json.dumps({
        report["id"]: report["quantized_validation"]["mae_cp"]
        for report in reports
    }, indent=2))


def run_command(command, log, timeout):
    flags = (
        subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
        if os.name == "nt" else 0
    )
    env = dict(os.environ)
    env["PATH"] = str(MSYS) + os.pathsep + env.get("PATH", "")
    started = time.monotonic()
    with log.open("w", encoding="utf-8", newline="\n") as output:
        result = subprocess.run(
            [str(item) for item in command],
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=flags,
        )
    return {
        "command": [str(item) for item in command],
        "exit_code": result.returncode,
        "elapsed_seconds": time.monotonic() - started,
        "log": log.relative_to(ROOT).as_posix(),
        "log_sha256": sha256(log),
    }


def validate_candidate(name, attempt):
    directory = WORK / "candidates" / name
    if not (directory / "training.json").is_file():
        raise RuntimeError(f"{name} has not been trained")
    build = directory / f"build-{attempt}"
    if build.exists():
        raise RuntimeError(f"build collision: {build}")
    build.mkdir()
    checks = []
    commands = [
        ([CMAKE, "-S", ROOT, "-B", build, "-G", "Ninja",
          "-DCMAKE_BUILD_TYPE=Release", "-DELOI_BUILD_TESTS=ON",
          "-DELOI_BUILD_APP=ON",
          f"-DCMAKE_CXX_COMPILER={(MSYS / 'c++.exe').as_posix()}",
          f"-DCMAKE_MAKE_PROGRAM={(MSYS / 'ninja.exe').as_posix()}",
          f"-DCMAKE_RC_COMPILER={(MSYS / 'windres.exe').as_posix()}",
          f"-DELOI_NNUE_INCLUDE_DIR={(directory / 'include').as_posix()}"],
         directory / f"configure-{attempt}.log", 180),
        ([CMAKE, "--build", build, "--target", "Eloi", "eloi_tests", "-j", "2"],
         directory / f"build-{attempt}.log", 900),
    ]
    for command, log, timeout in commands:
        result = run_command(command, log, timeout)
        checks.append(result)
        if result["exit_code"]:
            return {"candidate": name, "passed": False, "checks": checks}
    binary, tests = build / "Eloi.exe", build / "eloi_tests.exe"
    runtime = [
        ([tests], directory / f"tests-{attempt}.log", 180),
        ([binary, "--perft", "--depth", "4"],
         directory / f"perft-{attempt}.log", 60),
        ([sys.executable, ROOT / "scripts/differential_movegen.py",
          "--engine", binary, "--samples", "32"],
         directory / f"differential-{attempt}.log", 300),
    ]
    for command, log, timeout in runtime:
        checks.append(run_command(command, log, timeout))
    perft_text = (
        directory / f"perft-{attempt}.log"
    ).read_text(encoding="utf-8")
    passed = (
        all(check["exit_code"] == 0 for check in checks)
        and ",4,197281," in perft_text
    )
    return {
        "candidate": name,
        "passed": passed,
        "checks": checks,
        "binary_sha256": sha256(binary),
        "production_header_unchanged": (
            sha256(PRODUCTION_HEADER)
            == read_json(PRODUCTION_PROVENANCE)["selected_weights_sha256"]
        ),
    }


def validate(candidates=("E1", "E32"), evidence_stem="validation-results"):
    validation_support.resource_snapshot(WORK, PROJECTED_BYTES)
    attempt = 1 + len(list(WORK.glob(f"{evidence_stem}*.json")))
    output = {
        "schema": 1,
        "attempt": attempt,
        "candidates": [
            validate_candidate(name, attempt) for name in candidates
        ],
        "gauntlet_run": False,
    }
    output["all_passed"] = all(row["passed"] for row in output["candidates"])
    suffix = "" if attempt == 1 else f"-{attempt}"
    write_json(WORK / f"{evidence_stem}{suffix}.json", output)
    print(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(
            "train",
            "train-selected",
            "validate",
            "validate-selected",
            "run",
        ),
    )
    args = parser.parse_args()
    if args.stage in ("train", "run"):
        train()
    if args.stage in ("validate", "run"):
        validate()
    if args.stage == "train-selected":
        train_selected()
    if args.stage == "validate-selected":
        validate(
            ("E1-selected", "E32-selected"),
            "selected-validation-results",
        )


if __name__ == "__main__":
    main()
