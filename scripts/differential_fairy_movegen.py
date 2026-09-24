#!/usr/bin/env python3
"""Compare Eloi Atomic/Antichess legal moves with python-chess."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess.variant


def eloi_moves(executable: Path, board, variant: str) -> set[str]:
    process = subprocess.run(
        [str(executable), "--perft", "--depth", "1", "--divide",
         "--variant", variant, "--fen", board.fen()],
        cwd=ROOT, text=True, capture_output=True, timeout=15, check=True)
    return {line.split(":", 1)[0] for line in process.stdout.splitlines()
            if ":" in line and not line.startswith("perft,")}


def positions(board_type, count: int, seed: int):
    rng = random.Random(seed)
    result = []
    while len(result) < count:
        board = board_type()
        for ply in range(rng.randrange(0, 70)):
            if board.is_game_over(claim_draw=True):
                break
            board.push(rng.choice(sorted(board.legal_moves,
                                         key=lambda move: move.uci())))
        if not board.is_game_over(claim_draw=True):
            result.append(board)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=64)
    args = parser.parse_args()
    report = {"samples_per_variant": args.samples, "mismatches": []}
    variants = (("atomic", chess.variant.AtomicBoard, 0xA701C),
                ("antichess", chess.variant.AntichessBoard, 0xA471))
    for name, board_type, seed in variants:
        for index, board in enumerate(positions(board_type, args.samples, seed)):
            expected = {move.uci() for move in board.legal_moves}
            actual = eloi_moves(args.engine.resolve(), board, name)
            if expected != actual:
                report["mismatches"].append({
                    "variant": name, "sample": index, "fen": board.fen(),
                    "missing": sorted(expected - actual),
                    "extra": sorted(actual - expected)})
    report["passed"] = not report["mismatches"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
