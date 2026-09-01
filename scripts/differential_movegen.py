#!/usr/bin/env python3
"""Differential legal-move validation against python-chess."""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for dependency_root in (
    ROOT / ".deps" / "python",
    ROOT / ".deps" / "lichess-bot" / ".venv" / "Lib" / "site-packages",
):
    if dependency_root.is_dir():
        sys.path.insert(0, str(dependency_root))

import chess
import chess.variant

SEED = 0xE101D1FF


def random_position(variant: str, rng: random.Random) -> chess.Board:
    if variant == "chess960":
        board = chess.Board.from_chess960_pos(rng.randrange(960))
        maximum_plies = 48
    elif variant == "horde":
        board = chess.variant.HordeBoard()
        maximum_plies = 36
    else:
        board = chess.Board()
        maximum_plies = 56
    for _ in range(rng.randrange(maximum_plies + 1)):
        moves = list(board.legal_moves)
        if not moves:
            break
        board.push(rng.choice(moves))
        if board.is_game_over(claim_draw=True):
            break
    return board


def reference_moves(board: chess.Board) -> set[str]:
    return {
        board.uci(move, chess960=board.chess960)
        for move in board.legal_moves
    }


def eloi_moves(executable: pathlib.Path, board: chess.Board,
               variant: str) -> set[str]:
    fen = board.shredder_fen() if variant == "chess960" else board.fen()
    command = [
        str(executable),
        "--perft",
        "--depth",
        "1",
        "--divide",
        "--fen",
        fen,
        "--variant",
        "horde" if variant == "horde" else "standard",
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        line.split(":", 1)[0].strip()
        for line in completed.stdout.splitlines()
        if ": " in line and not line.startswith("perft,")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=pathlib.Path)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=ROOT / "tmp" / "engine-lab" / "movegen-differential.json",
    )
    args = parser.parse_args()
    if args.samples <= 0:
        parser.error("--samples must be positive")
    executable = args.engine.resolve()
    rng = random.Random(SEED)
    failures = []
    checked = 0
    for variant in ("standard", "chess960", "horde"):
        for sample in range(args.samples):
            board = random_position(variant, rng)
            expected = reference_moves(board)
            actual = eloi_moves(executable, board, variant)
            checked += 1
            if expected != actual:
                failures.append({
                    "variant": variant,
                    "sample": sample + 1,
                    "fen": (
                        board.shredder_fen()
                        if variant == "chess960" else board.fen()
                    ),
                    "missing": sorted(expected - actual),
                    "unexpected": sorted(actual - expected),
                })
                print(
                    f"{variant} sample {sample + 1}: mismatch",
                    file=sys.stderr,
                )
            else:
                print(
                    f"{variant} sample {sample + 1}/{args.samples}: ok",
                    flush=True,
                )
    report = {
        "schema": 1,
        "seed": SEED,
        "engine": str(executable),
        "samples_per_variant": args.samples,
        "positions_checked": checked,
        "failures": failures,
        "passed": not failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        f"checked {checked} positions; failures={len(failures)}; "
        f"report={args.output}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
