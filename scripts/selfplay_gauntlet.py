#!/usr/bin/env python3
"""Run a deterministic, mirrored UCI self-play gauntlet for Eloi.

python-chess is a development-only dependency. Each seed is played twice with
the engines' colours exchanged. Opening books are disabled for both engines.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / ".deps" / "python"))
import chess
import chess.engine


SEEDS = (
    (),
    ("e2e4", "c7c5", "g1f3", "d7d6"),
    ("d2d4", "d7d5", "c2c4", "e7e6"),
    ("g1f3", "d7d5", "g2g3", "g8f6"),
    ("c2c4", "e7e5", "b1c3", "g8f6"),
    ("d2d4", "g8f6", "c2c4", "g7g6"),
    ("e2e4", "c7c6", "d2d4", "d7d5"),
    ("e2e4", "e7e6", "d2d4", "d7d5"),
)


def seeded_board(index: int) -> chess.Board:
    board = chess.Board()
    for text in SEEDS[index % len(SEEDS)]:
        board.push_uci(text)
    return board


def configure(engine: chess.engine.SimpleEngine) -> None:
    options = engine.options
    settings = {}
    if "OwnBook" in options:
        settings["OwnBook"] = False
    if "Hash" in options:
        settings["Hash"] = 32
    if settings:
        engine.configure(settings)


def play_game(candidate: chess.engine.SimpleEngine,
              baseline: chess.engine.SimpleEngine, game: int, nodes: int,
              max_plies: int) -> float:
    board = seeded_board(game // 2)
    candidate_is_white = game % 2 == 0
    while not board.is_game_over(claim_draw=True) and board.ply() < max_plies:
        candidate_turn = board.turn == candidate_is_white
        engine = candidate if candidate_turn else baseline
        result = engine.play(board, chess.engine.Limit(nodes=nodes))
        if result.move is None or result.move not in board.legal_moves:
            return 0.0 if candidate_turn else 1.0
        board.push(result.move)
    outcome = board.outcome(claim_draw=True)
    if outcome is None or outcome.winner is None:
        return 0.5
    return 1.0 if outcome.winner == candidate_is_white else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=pathlib.Path)
    parser.add_argument("--baseline", required=True, type=pathlib.Path)
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--nodes", type=int, default=2000)
    parser.add_argument("--max-plies", type=int, default=160)
    parser.add_argument("--required-score", type=float, default=55.0)
    args = parser.parse_args()
    if args.games < 2 or args.games % 2:
        parser.error("--games must be a positive even number")

    scores = []
    candidate = chess.engine.SimpleEngine.popen_uci([str(args.candidate), "--uci"])
    baseline = chess.engine.SimpleEngine.popen_uci([str(args.baseline), "--uci"])
    try:
        configure(candidate)
        configure(baseline)
        for game in range(args.games):
            score = play_game(candidate, baseline, game, args.nodes, args.max_plies)
            scores.append(score)
            print(f"game {game + 1}/{args.games} score {score:.1f} "
                  f"total {sum(scores):.1f}", flush=True)
    finally:
        candidate.quit()
        baseline.quit()

    percentage = 100.0 * sum(scores) / len(scores)
    wins = scores.count(1.0)
    draws = scores.count(0.5)
    losses = scores.count(0.0)
    print(f"gauntlet games {len(scores)} nodes {args.nodes} wins {wins} "
          f"draws {draws} losses {losses} score {percentage:.2f}%")
    return 0 if percentage > args.required_score else 1


if __name__ == "__main__":
    raise SystemExit(main())
