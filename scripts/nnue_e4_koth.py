#!/usr/bin/env python3
"""Build a deterministic, bounded E4-KOTH fine-tuning candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parents[1]
for dependency_root in (ROOT / ".deps/python", ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"):
    if dependency_root.is_dir():
        sys.path.insert(0, str(dependency_root))

import chess
import chess.variant
import numpy as np

import train_nnue as trainer

SEED = 0xFA101
WORK = ROOT / "tmp/e4-koth"
PARENT = ROOT / "tmp/nnue-e4-preservation/candidates-r2/E4-anchor-10/float.npz"
PARENT_HEADER = ROOT / "include/eloi/nnue_weights.hpp"
PARENT_CHECKPOINT_SHA = "D613B853FE534B6AD3604080E559DB26D9CCC55E124005FE60B9ABBCD508EE99"
PARENT_HEADER_SHA = "4C705496950E27204C976F0D027CAA9C73B209961584F7998742AA481B524E88"
POSITION_COUNT = 20_000
ANCHOR_FRACTION = 0.25
HILL_CP_PER_STEP = 120


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def hill_distance(board: chess.Board, side: chess.Color) -> int:
    king = board.king(side)
    if king is None:
        return 8
    return min(chess.square_distance(king, square) for square in (chess.D4, chess.E4, chess.D5, chess.E5))


def koth_target(board: chess.Board, base_model) -> float:
    if board.is_variant_win():
        return 1500.0 if board.turn == chess.WHITE else -1500.0
    if board.is_variant_loss():
        return -1500.0 if board.turn == chess.WHITE else 1500.0
    white = trainer.features(board, chess.WHITE)
    black = trainer.features(board, chess.BLACK)
    base = float(trainer.forward_quantized(*base_model, white, black)[0])
    shaped = base + HILL_CP_PER_STEP * (hill_distance(board, chess.BLACK) - hill_distance(board, chess.WHITE))
    return float(np.clip(shaped, -1500.0, 1500.0))


def deterministic_positions(count: int) -> list[chess.variant.KingOfTheHillBoard]:
    rng = random.Random(SEED)
    seen: dict[str, chess.variant.KingOfTheHillBoard] = {}
    game = 0
    while len(seen) < count:
        board = chess.variant.KingOfTheHillBoard()
        for ply in range(100):
            if board.is_game_over(claim_draw=True):
                break
            legal = list(board.legal_moves)
            if not legal:
                break
            # Half broad exploration, half king-to-hill pressure. This is data
            # generation only; the engine still proves moves with alpha-beta.
            if rng.random() < 0.5:
                side = board.turn
                ranked = []
                for move in legal:
                    child = board.copy(stack=False)
                    child.push(move)
                    ranked.append((hill_distance(child, side), move.uci(), move))
                best_distance = min(item[0] for item in ranked)
                pool = [item[2] for item in ranked if item[0] <= best_distance + 1]
                move = rng.choice(pool)
            else:
                move = rng.choice(legal)
            board.push(move)
            if 4 <= ply <= 80 and not board.is_game_over(claim_draw=True):
                key = board.fen()
                seen.setdefault(key, board.copy(stack=False))
                if len(seen) >= count:
                    break
        game += 1
        if game > count * 2:
            raise RuntimeError("could not generate enough unique KOTH positions")
    return list(seen.values())


def split(position: chess.Board) -> str:
    return "validation" if hashlib.sha256(("E4-KOTH|" + position.fen()).encode()).digest()[0] < 26 else "train"


def metrics(model, rows) -> dict:
    errors = []
    for white, black, target, *_ in rows:
        predicted = trainer.forward(*model, white, black)[0]
        errors.append(abs(float(target) - float(predicted)))
    return {"count": len(errors), "mae_cp": float(np.mean(errors)), "p95_cp": float(np.percentile(errors, 95))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", type=int, default=POSITION_COUNT)
    args = parser.parse_args()
    if args.positions != POSITION_COUNT:
        raise RuntimeError("the frozen campaign requires exactly 20,000 positions")
    if sha256(PARENT) != PARENT_CHECKPOINT_SHA:
        raise RuntimeError("E4-10 parent checkpoint identity mismatch")
    if sha256(PARENT_HEADER) != PARENT_HEADER_SHA:
        raise RuntimeError("E4-10 parent header identity mismatch")
    if WORK.exists():
        raise RuntimeError(f"campaign output already exists: {WORK}")
    WORK.mkdir(parents=True)
    parent_float = np.load(PARENT)
    parent = tuple(parent_float[name].astype(np.float32).copy() for name in ("weights", "bias", "output"))
    base_quantized = trainer.load_quantized_header(PARENT_HEADER)
    positions = deterministic_positions(args.positions)
    rows = {"train": [], "validation": []}
    manifest = []
    for index, board in enumerate(positions):
        target = koth_target(board, base_quantized)
        partition = split(board)
        rows[partition].append((trainer.features(board, chess.WHITE), trainer.features(board, chess.BLACK), target, 1.0, {"fen": board.fen()}))
        manifest.append({"id": index, "fen": board.fen(), "partition": partition, "target_cp": target})
    before = metrics(parent, rows["validation"])
    learned = tuple(array.copy() for array in parent)
    learned = trainer.train_evaluations(*learned, rows["train"], epochs=1, trainable_channels=list(range(64)))
    candidate = tuple(base + ANCHOR_FRACTION * (new - base) for base, new in zip(parent, learned))
    after = metrics(candidate, rows["validation"])
    include = WORK / "candidate/include/eloi"
    include.mkdir(parents=True)
    checkpoint = WORK / "candidate/e4-koth-float.npz"
    np.savez(checkpoint, weights=candidate[0], bias=candidate[1], output=candidate[2])
    header = include / "nnue_weights.hpp"
    trainer.write_header(header, *candidate, {"train_evaluations": len(rows["train"]), "train_pairs": 0}, {"king-of-the-hill"}, source_description="E4-10 anchored KOTH hill-distance fine-tuning")
    (WORK / "positions.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in manifest), encoding="utf-8", newline="\n")
    report = {"schema": 1, "campaign": "E4-KOTH", "seed": SEED, "positions": args.positions, "train": len(rows["train"]), "validation": len(rows["validation"]), "parent_checkpoint_sha256": sha256(PARENT), "parent_header_sha256": sha256(PARENT_HEADER), "anchor_fraction": ANCHOR_FRACTION, "hill_cp_per_step": HILL_CP_PER_STEP, "validation_before": before, "validation_after": after, "candidate_checkpoint_sha256": sha256(checkpoint), "candidate_header_sha256": sha256(header), "production_changed": False}
    (WORK / "training.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())