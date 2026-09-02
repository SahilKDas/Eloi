#!/usr/bin/env python3
"""Run a deterministic, mirrored UCI self-play gauntlet for Eloi.

python-chess is a development-only dependency. Each seed is played twice with
the engines' colours exchanged. Opening books are disabled for both engines.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
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


def configure(engine: chess.engine.SimpleEngine, *, timed: bool,
              parallel_mode: str) -> None:
    options = engine.options
    settings = {}
    if "OwnBook" in options:
        settings["OwnBook"] = False
    if "Hash" in options:
        settings["Hash"] = 32
    if timed and "Depth" in options:
        settings["Depth"] = 0
    if "ParallelMode" in options:
        settings["ParallelMode"] = parallel_mode
    elif parallel_mode != "RootSplit":
        raise RuntimeError("this engine supports RootSplit only")
    if "Threads" in options:
        settings["Threads"] = 3
    if "Noise" in options:
        settings["Noise"] = 0
    if settings:
        engine.configure(settings)


def play_game(candidate: chess.engine.SimpleEngine,
              baseline: chess.engine.SimpleEngine, game: int,
              limit: chess.engine.Limit,
              max_plies: int) -> float:
    board = seeded_board(game // 2)
    candidate_is_white = game % 2 == 0
    while not board.is_game_over(claim_draw=True) and board.ply() < max_plies:
        candidate_turn = board.turn == candidate_is_white
        engine = candidate if candidate_turn else baseline
        try:
            result = engine.play(board, limit)
        except Exception as error:
            label = "candidate" if candidate_turn else "baseline"
            raise RuntimeError(
                f"{label} failed in game {game + 1} at ply {board.ply()} "
                f"from {board.fen()}: {type(error).__name__}: {error}"
            ) from error
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
    parser.add_argument(
        "--candidate-parallel-mode",
        choices=("RootSplit", "LazySMP"), default="RootSplit",
    )
    parser.add_argument(
        "--baseline-parallel-mode",
        choices=("RootSplit", "LazySMP"), default="RootSplit",
    )
    parser.add_argument(
        "--correctness-test", type=pathlib.Path,
        help="run the same deterministic test executable for both modes before play",
    )
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument(
        "--start-game", type=int, default=0,
        help="zero-based global mirrored-game index used to resume a gate",
    )
    strength = parser.add_mutually_exclusive_group()
    strength.add_argument("--nodes", type=int)
    strength.add_argument("--depth", type=int)
    strength.add_argument("--movetime-ms", type=int)
    parser.add_argument(
        "--idle-priority",
        action="store_true",
        help="run test engines at Windows Idle priority so foreground play wins CPU",
    )
    parser.add_argument("--max-plies", type=int, default=160)
    parser.add_argument("--required-score", type=float, default=55.0)
    args = parser.parse_args()
    if args.games < 2 or args.games % 2:
        parser.error("--games must be a positive even number")
    if args.start_game < 0:
        parser.error("--start-game must be non-negative")
    if args.nodes is not None and args.nodes < 1:
        parser.error("--nodes must be positive")
    if args.depth is not None and args.depth < 1:
        parser.error("--depth must be positive")
    if args.movetime_ms is not None and args.movetime_ms < 1:
        parser.error("--movetime-ms must be positive")
    if args.nodes is None and args.depth is None and args.movetime_ms is None:
        args.nodes = 2000
    limit = chess.engine.Limit(
        nodes=args.nodes,
        depth=args.depth,
        time=(args.movetime_ms / 1000.0
              if args.movetime_ms is not None else None),
    )

    popen_args = {}
    if args.idle_priority:
        if os.name != "nt":
            parser.error("--idle-priority is currently supported only on Windows")
        popen_args["creationflags"] = subprocess.IDLE_PRIORITY_CLASS

    preflight_ok = True
    if args.correctness_test:
        checked = []
        for label, mode in (("candidate", args.candidate_parallel_mode),
                            ("baseline", args.baseline_parallel_mode)):
            if mode in checked:
                continue
            checked.append(mode)
            if mode != "RootSplit":
                raise RuntimeError("current correctness executable validates RootSplit only")
            command = [str(args.correctness_test)]
            print(f"{label} correctness preflight: {' '.join(command)}",
                  flush=True)
            completed = subprocess.run(command, check=False, timeout=120)
            passed = completed.returncode == 0
            preflight_ok = preflight_ok and passed
            print(f"{mode} correctness: {'PASS' if passed else 'FAIL'}",
                  flush=True)

    scores = []
    engine_timeout = 60.0 if args.idle_priority else 10.0
    candidate = chess.engine.SimpleEngine.popen_uci(
        [str(args.candidate), "--uci"], timeout=engine_timeout, **popen_args)
    baseline = chess.engine.SimpleEngine.popen_uci(
        [str(args.baseline), "--uci"], timeout=engine_timeout, **popen_args)
    try:
        configure(candidate, timed=args.movetime_ms is not None,
                  parallel_mode=args.candidate_parallel_mode)
        configure(baseline, timed=args.movetime_ms is not None,
                  parallel_mode=args.baseline_parallel_mode)
        for game in range(args.start_game, args.start_game + args.games):
            score = play_game(candidate, baseline, game, limit, args.max_plies)
            scores.append(score)
            completed = game - args.start_game + 1
            print(f"game {game + 1} ({completed}/{args.games}) score {score:.1f} "
                  f"total {sum(scores):.1f}", flush=True)
    finally:
        candidate.quit()
        baseline.quit()

    percentage = 100.0 * sum(scores) / len(scores)
    wins = scores.count(1.0)
    draws = scores.count(0.5)
    losses = scores.count(0.0)
    if args.nodes is not None:
        search_label = f"nodes {args.nodes}"
    elif args.depth is not None:
        search_label = f"depth {args.depth}"
    else:
        search_label = f"movetime {args.movetime_ms}ms"
    print(f"gauntlet candidate {args.candidate_parallel_mode} baseline "
          f"{args.baseline_parallel_mode} games {len(scores)} {search_label} wins {wins} "
          f"draws {draws} losses {losses} score {percentage:.2f}%")
    if not preflight_ok:
        print("selection: REJECTED because at least one mode failed correctness")
        return 2
    return 0 if percentage > args.required_score else 1


if __name__ == "__main__":
    raise SystemExit(main())
