#!/usr/bin/env python3
"""Run a frozen mirrored E4-KOTH versus E4-traditional gauntlet."""
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
import chess
import chess.engine
import chess.pgn
import chess.variant


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def openings(count: int = 50) -> list[str]:
    rng = random.Random(0xE4_40_7A)
    result: list[str] = []
    seen: set[str] = set()
    while len(result) < count:
        board = chess.variant.KingOfTheHillBoard()
        for _ in range(4):
            moves = sorted(board.legal_moves, key=lambda move: move.uci())
            board.push(moves[rng.randrange(len(moves))])
        key = " ".join(board.fen().split()[:4])
        if key not in seen and not board.is_game_over(claim_draw=True):
            seen.add(key)
            result.append(board.fen())
    return result


def schedule(game_count: int = 100) -> list[dict]:
    if game_count <= 0 or game_count % 2:
        raise ValueError("game count must be a positive even number")
    games: list[dict] = []
    for pair, fen in enumerate(openings(game_count // 2), start=1):
        for candidate_white in (True, False):
            games.append({"game": len(games) + 1, "pair": pair,
                          "candidate_white": candidate_white, "fen": fen})
    return games


def configure(engine: chess.engine.SimpleEngine) -> None:
    values = {}
    # python-chess owns UCI_Variant and sets it from the variant board on play().
    for name, value in (("Threads", 3), ("Hash", 32),
                        ("OwnBook", False), ("Noise", 0)):
        if name in engine.options:
            values[name] = value
    engine.configure(values)


def play(candidate_path: Path, baseline_path: Path, row: dict,
         movetime_ms: int, max_plies: int) -> tuple[dict, chess.pgn.Game]:
    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    command_candidate = [str(candidate_path), "--uci", "--brain", "eloi"]
    command_baseline = [str(baseline_path), "--uci", "--brain", "eloi"]
    candidate = chess.engine.SimpleEngine.popen_uci(command_candidate, timeout=30,
                                                     creationflags=flags)
    baseline = chess.engine.SimpleEngine.popen_uci(command_baseline, timeout=30,
                                                    creationflags=flags)
    board = chess.variant.KingOfTheHillBoard(row["fen"])
    started = time.monotonic()
    try:
        configure(candidate)
        configure(baseline)
        limit = chess.engine.Limit(time=movetime_ms / 1000)
        while not board.is_game_over(claim_draw=True) and board.ply() < max_plies + 4:
            engine = candidate if board.turn == row["candidate_white"] else baseline
            response = engine.play(board, limit)
            if response.move is None or response.move not in board.legal_moves:
                raise RuntimeError(f"illegal or missing move at ply {board.ply()}: {response.move}")
            board.push(response.move)
    finally:
        candidate.quit()
        baseline.quit()
    outcome = board.outcome(claim_draw=True)
    if outcome is None or outcome.winner is None:
        score, result_text = 0.5, "1/2-1/2"
    else:
        score = 1.0 if outcome.winner == row["candidate_white"] else 0.0
        result_text = "1-0" if outcome.winner else "0-1"
    game = chess.pgn.Game.from_board(board)
    game.headers.update({"Event": "E4 KOTH 250ms gauntlet", "Round": str(row["game"]),
                         "White": "E4-KOTH" if row["candidate_white"] else "E4-traditional",
                         "Black": "E4-traditional" if row["candidate_white"] else "E4-KOTH",
                         "Variant": "King of the Hill", "Result": result_text,
                         "Pair": str(row["pair"])})
    return ({**row, "score": score, "result": result_text,
             "plies": board.ply() - 4,
             "elapsed_seconds": round(time.monotonic() - started, 3),
             "final_fen": board.fen(),
             "termination": outcome.termination.name if outcome else "PLY_LIMIT"}, game)


def verify_pgn(path: Path, expected: int) -> dict:
    count = 0
    with path.open(encoding="utf-8") as stream:
        while game := chess.pgn.read_game(stream):
            board = chess.variant.KingOfTheHillBoard(game.headers["FEN"])
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    raise RuntimeError(f"replay found illegal move in game {count + 1}: {move}")
                board.push(move)
            actual = board.result(claim_draw=True)
            adjudicated_draw = actual == "*" and game.headers["Result"] == "1/2-1/2"
            if actual != game.headers["Result"] and not adjudicated_draw:
                raise RuntimeError(f"replay result mismatch in game {count + 1}")
            count += 1
    return {"verified_games": count, "expected_games": expected, "passed": count == expected}


def summarize(results: list[dict], total_games: int) -> dict:
    wins = sum(result["score"] == 1 for result in results)
    draws = sum(result["score"] == .5 for result in results)
    losses = sum(result["score"] == 0 for result in results)
    score_points = wins + draws / 2
    return {"completed": len(results), "wins": wins, "draws": draws,
            "losses": losses, "score_points": score_points,
            "score_percent": 100.0 * score_points / total_games}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--movetime-ms", type=int, default=250)
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--games", type=int, default=100)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    frozen = schedule(args.games)
    protocol = {"schema": "eloi-e4-koth-gauntlet-v1", "games": args.games,
                "variant": "kingofthehill", "mirrored": True,
                "movetime_ms": args.movetime_ms, "max_plies": args.max_plies,
                "threads_per_engine": 3, "hash_mb": 32,
                "candidate_sha256": sha256(args.candidate),
                "baseline_sha256": sha256(args.baseline),
                "runner_sha256": sha256(Path(__file__)), "schedule": frozen}
    write_json(args.output / "protocol.json", protocol)
    results: list[dict] = []
    failures: list[dict] = []
    pgn_path = args.output / "games.pgn"
    for row in frozen:
        try:
            result, game = play(args.candidate.resolve(), args.baseline.resolve(), row,
                                args.movetime_ms, args.max_plies)
            results.append(result)
            with pgn_path.open("a", encoding="utf-8", newline="\n") as stream:
                print(game, file=stream, end="\n\n")
        except Exception as error:
            failures.append({**row, "error": f"{type(error).__name__}: {error}"})
        evidence = {"schema": "eloi-e4-koth-results-v1",
                    "complete": len(results) + len(failures) == args.games,
                    "results": results, "protocol_failures": failures,
                    "summary": summarize(results, args.games)}
        write_json(args.output / "results.json", evidence)
        print(json.dumps({"game": row["game"], **evidence["summary"],
                          "failures": len(failures)}), flush=True)
        if failures:
            return 2
    evidence["replay_verification"] = verify_pgn(pgn_path, args.games)
    evidence["passed"] = evidence["summary"]["score_percent"] > 50.0
    write_json(args.output / "results.json", evidence)
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
