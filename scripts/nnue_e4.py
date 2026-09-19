#!/usr/bin/env python3
"""Train conservative E4 candidates while preserving E2 behavior."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
for dependency_root in (
    ROOT / ".deps/python",
    ROOT / ".deps/lichess-bot/.venv/Lib/site-packages",
):
    if dependency_root.is_dir():
        sys.path.insert(0, str(dependency_root))

import chess
import numpy as np

import engine_lab
import nnue_e3 as e3
import train_nnue as trainer
import validation_support

WORK = ROOT / "tmp/nnue-e4-preservation"
PRODUCTION = ROOT / "include/eloi/nnue_weights.hpp"
PRODUCTION_SHA256 = "E3DFBE02F4DC765C45E243EFD4437E9EC3390D4F167531D6F54765CECB899C9F"
REGRESSIONS = ROOT / "tests/epd/v2_5_regressions.epd"
RECIPES = (
    {"id": "E4-anchor-10", "delta_fraction": 0.10},
    {"id": "E4-anchor-20", "delta_fraction": 0.20},
    {"id": "E4-anchor-35", "delta_fraction": 0.35},
)
TRAINING_REVISION = 2


def sha256(path: Path) -> str:
    return engine_lab.sha256(path)


def immutable_json(path: Path, value) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"evidence collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def e2_model():
    if sha256(PRODUCTION) != PRODUCTION_SHA256:
        raise RuntimeError("production E2 identity changed")
    return tuple(array.astype(np.float32).copy()
                 for array in trainer.load_quantized_header(PRODUCTION))


def e2_score(model, sample) -> float:
    return float(trainer.forward_quantized(*model, sample[0], sample[1])[0])


def distilled(samples: list, baseline, teacher_fraction: float = 0.20) -> list:
    result = []
    for sample in samples:
        target = ((1.0 - teacher_fraction) * e2_score(baseline, sample)
                  + teacher_fraction * float(sample[2]))
        result.append((sample[0], sample[1], target, min(1.5, float(sample[3])), sample[4]))
    return result


def anchor(model, baseline, fraction: float):
    return tuple(base + fraction * (candidate - base)
                 for candidate, base in zip(model, baseline))


def regression_pairs() -> tuple[list, list]:
    pairs, cases = [], []
    for row in validation_support.epd_cases(REGRESSIONS):
        operations = row["operations"]
        best_tokens = operations.get("bm", "").split()
        if not best_tokens:
            continue
        best_uci = best_tokens[0]
        board = chess.Board(row["fen"])
        best = chess.Move.from_uci(best_uci)
        if best not in board.legal_moves:
            raise RuntimeError(f"regression best move is illegal: {row['id']}")
        case_id = row["id"]
        alternatives = sorted(
            (move for move in board.legal_moves if move != best),
            key=lambda move: hashlib.sha256(
                f"E4|{case_id}|{move.uci()}".encode()).digest(),
        )[:8]
        best_board = board.copy(stack=False)
        best_board.push(best)
        for alternative in alternatives:
            alt_board = board.copy(stack=False)
            alt_board.push(alternative)
            pairs.append((
                trainer.features(best_board, chess.WHITE),
                trainer.features(best_board, chess.BLACK),
                trainer.features(alt_board, chess.WHITE),
                trainer.features(alt_board, chess.BLACK),
                1 if board.turn == chess.WHITE else -1,
                4.0,
            ))
        cases.append({"id": case_id, "best": best.uci(),
                      "alternatives": len(alternatives)})
    return pairs, cases


def load_training():
    labels = e3.WORK / "labels.jsonl"
    if sha256(labels) != "B60FB0FA72CB5F37E3E7411BB1F456A1850B90E130857976CF2C5E06F93CB7FE":
        raise RuntimeError("E3 player labels changed")
    rows = [json.loads(line) for line in labels.read_text(encoding="utf-8").splitlines()]
    broad = e3.load_epv2_broad()
    train = [*broad["evaluations"]["train"], *e3.player_samples(rows, "train")]
    validation = [*broad["evaluations"]["validation"],
                  *e3.player_samples(rows, "validation")]
    return train, validation, broad["pairs"]


def train() -> dict:
    result_path = WORK / f"training-result-r{TRAINING_REVISION}.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    baseline = e2_model()
    train_rows, validation, pairs = load_training()
    hard_pairs, hard_cases = regression_pairs()
    model = tuple(array.copy() for array in baseline)
    model = trainer.train_evaluations(
        *model, distilled(train_rows, baseline), epochs=1,
        trainable_channels=list(range(64)))
    model = trainer.train_pairs(
        *model, [(*pair[:5], 0.50) for pair in pairs["train"]], epochs=1,
        trainable_channels=list(range(64)))
    model = trainer.train_pairs(
        *model, list(hard_pairs), epochs=3,
        trainable_channels=list(range(64)))

    reports = []
    for recipe in RECIPES:
        candidate = anchor(model, baseline, recipe["delta_fraction"])
        directory = WORK / f"candidates-r{TRAINING_REVISION}" / recipe["id"]
        include = directory / "include/eloi"
        include.mkdir(parents=True, exist_ok=False)
        checkpoint = directory / "float.npz"
        np.savez(checkpoint, weights=candidate[0], bias=candidate[1], output=candidate[2])
        header = include / "nnue_weights.hpp"
        architecture = include / "nnue_architecture.hpp"
        counts = {"train_evaluations": len(train_rows),
                  "train_pairs": len(pairs["train"]) + len(hard_pairs),
                  "preservation_pairs": len(pairs["train"]),
                  "regression_pairs": len(hard_pairs),
                  "regression_cases": len(hard_cases)}
        trainer.write_header(
            header, *candidate, counts, set(),
            source_description="E4 E2-preserving corrected targets and tactical replay")
        trainer.write_architecture(architecture, 64)
        metrics = trainer.validation_metrics(
            *candidate, validation, pairs["validation"])
        report = {**recipe, "weights_sha256": sha256(header),
                  "checkpoint_sha256": sha256(checkpoint),
                  "validation": metrics, "counts": counts}
        immutable_json(directory / "training.json", report)
        reports.append(report)
    result = {
        "schema": 1, "campaign": "E4-E2-preservation",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "production_weights_sha256": sha256(PRODUCTION),
        "teacher_fraction": 0.20, "e2_fraction": 0.80,
        "target_clamp_cp": 1500, "regression_cases": hard_cases,
        "training_revision": TRAINING_REVISION,
        "candidates": reports, "sealed_tests_opened": False,
        "production_changed": False,
    }
    immutable_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train",))
    parser.parse_args()
    print(json.dumps(train(), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
