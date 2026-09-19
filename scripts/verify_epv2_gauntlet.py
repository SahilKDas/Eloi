#!/usr/bin/env python3
"""Replay and independently verify an EPV2 qualification PGN."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess.pgn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--pgn", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = json.loads(args.results.read_text(encoding="utf-8"))
    expected = evidence["results"]
    failures = []
    games = []
    with args.pgn.open(encoding="utf-8") as stream:
        while game := chess.pgn.read_game(stream):
            games.append(game)
    if len(games) != len(expected):
        failures.append(f"PGN count {len(games)} != result count {len(expected)}")
    for index, (game, row) in enumerate(zip(games, expected), 1):
        board = game.board()
        try:
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    raise ValueError(f"illegal move {move.uci()}")
                board.push(move)
        except Exception as error:
            failures.append(f"game {index}: {error}")
            continue
        if game.headers.get("Result") != row["result"]:
            failures.append(f"game {index}: result mismatch")
        if game.headers.get("ReserveIndex") != str(row["reserve_index"]):
            failures.append(f"game {index}: reserve index mismatch")
        if board.fen() != row["final_fen"]:
            failures.append(f"game {index}: final FEN mismatch")
    report = {"schema": "eloi-epv2-gauntlet-replay-v1",
              "passed": not failures, "games": len(games),
              "failures": failures}
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
