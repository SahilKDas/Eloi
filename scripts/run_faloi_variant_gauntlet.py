#!/usr/bin/env python3
"""Run a frozen mirrored Atomic or Antichess Eloi gauntlet."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess.engine
import chess.pgn
import chess.variant


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def board_type(variant: str):
    return (chess.variant.AtomicBoard if variant == "atomic"
            else chess.variant.AntichessBoard)


def schedule(variant: str, games: int) -> list[dict]:
    rng = random.Random(0xFA101 + (1 if variant == "atomic" else 2))
    positions, seen = [], set()
    while len(positions) < games // 2:
        board = board_type(variant)()
        for _ in range(4):
            board.push(rng.choice(sorted(board.legal_moves,
                                         key=lambda move: move.uci())))
        key = board.fen()
        if key not in seen and not board.is_game_over(claim_draw=True):
            seen.add(key)
            positions.append(key)
    return [{"game": pair * 2 + offset + 1, "pair": pair + 1, "fen": fen,
             "candidate_white": offset == 0}
            for pair, fen in enumerate(positions) for offset in range(2)]


def configure(engine: chess.engine.SimpleEngine) -> None:
    options = {name: value for name, value in
               (("Threads", 3), ("Hash", 32), ("OwnBook", False), ("Noise", 0))
               if name in engine.options}
    engine.configure(options)


def play(candidate: Path, baseline: Path, row: dict, variant: str,
         movetime_ms: int, max_plies: int):
    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    command = lambda path: [str(path), "--uci", "--brain", "eloi"]
    engines = [chess.engine.SimpleEngine.popen_uci(command(path), timeout=30,
               creationflags=flags) for path in (candidate, baseline)]
    board = board_type(variant)(row["fen"])
    started, played = time.monotonic(), 0
    try:
        for engine in engines:
            configure(engine)
        while not board.is_game_over(claim_draw=True) and played < max_plies:
            use_candidate = board.turn == row["candidate_white"]
            engine = engines[0] if use_candidate else engines[1]
            response = engine.play(board, chess.engine.Limit(
                time=movetime_ms / 1000))
            if response.move is None or response.move not in board.legal_moves:
                raise RuntimeError(f"illegal/missing move at ply {played}: "
                                   f"{response.move}")
            board.push(response.move)
            played += 1
    finally:
        for engine in engines:
            engine.quit()
    outcome = board.outcome(claim_draw=True)
    if outcome is None or outcome.winner is None:
        score, result = .5, "1/2-1/2"
    else:
        score = 1.0 if outcome.winner == row["candidate_white"] else 0.0
        result = "1-0" if outcome.winner else "0-1"
    game = chess.pgn.Game.from_board(board)
    game.headers.update({
        "Event": f"Faloi {variant} {movetime_ms}ms gauntlet",
        "Round": str(row["game"]),
        "White": "Faloi-tuned" if row["candidate_white"] else "E4-traditional",
        "Black": "E4-traditional" if row["candidate_white"] else "Faloi-tuned",
        "Result": result, "Pair": str(row["pair"])})
    return ({**row, "score": score, "result": result, "plies": played,
             "elapsed_seconds": round(time.monotonic() - started, 3),
             "final_fen": board.fen()}, game)


def replay(path: Path, variant: str, expected: int) -> dict:
    verified = 0
    with path.open(encoding="utf-8") as stream:
        while game := chess.pgn.read_game(stream):
            board = board_type(variant)(game.headers["FEN"])
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    raise RuntimeError(f"illegal replay move in game {verified + 1}")
                board.push(move)
            actual = board.result(claim_draw=True)
            if actual != game.headers["Result"] and not (
                    actual == "*" and game.headers["Result"] == "1/2-1/2"):
                raise RuntimeError(f"result mismatch in game {verified + 1}")
            verified += 1
    return {"verified_games": verified, "passed": verified == expected}



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True,
                        choices=("atomic", "antichess"))
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--movetime-ms", type=int, default=250)
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--max-plies", type=int, default=200)
    args = parser.parse_args()
    if args.games <= 0 or args.games % 2:
        parser.error("--games must be a positive even number")
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    frozen = schedule(args.variant, args.games)
    protocol = {
        "schema": "faloi-variant-gauntlet-v1", "variant": args.variant,
        "games": args.games, "mirrored": True, "movetime_ms": args.movetime_ms,
        "max_plies": args.max_plies, "threads_per_engine": 3, "hash_mb": 32,
        "candidate_sha256": sha(args.candidate),
        "baseline_sha256": sha(args.baseline),
        "runner_sha256": sha(Path(__file__)), "schedule": frozen}
    atomic_json(args.output / "protocol.json", protocol)
    results, failures = [], []
    pgn = args.output / "games.pgn"
    for row in frozen:
        try:
            result, game = play(args.candidate.resolve(), args.baseline.resolve(),
                                row, args.variant, args.movetime_ms,
                                args.max_plies)
            results.append(result)
            with pgn.open("a", encoding="utf-8", newline="\n") as stream:
                print(game, file=stream, end="\n\n")
        except Exception as error:
            failures.append({**row, "error": f"{type(error).__name__}: {error}"})
        wins = sum(item["score"] == 1 for item in results)
        draws = sum(item["score"] == .5 for item in results)
        losses = sum(item["score"] == 0 for item in results)
        evidence = {
            "schema": "faloi-variant-results-v1",
            "complete": len(results) + len(failures) == args.games,
            "results": results, "protocol_failures": failures,
            "summary": {"completed": len(results), "wins": wins, "draws": draws,
                        "losses": losses, "score_points": wins + draws / 2,
                        "score_percent": 100 * (wins + draws / 2) / args.games}}
        atomic_json(args.output / "results.json", evidence)
        print(json.dumps({"game": row["game"], **evidence["summary"],
                          "failures": len(failures)}), flush=True)
        if failures:
            return 2
    evidence["replay_verification"] = replay(pgn, args.variant, args.games)
    evidence["passed"] = (evidence["summary"]["score_points"] > args.games / 2 and
                          not evidence["protocol_failures"] and
                          evidence["replay_verification"]["passed"])
    atomic_json(args.output / "results.json", evidence)
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
