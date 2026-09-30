#!/usr/bin/env python3
"""Frozen mirrored Crazyhouse evaluator qualification against generic Eloi."""
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

GAMES = 100
PAIRS = 50
MOVETIME_MS = 250
MAX_PLIES = 240
SEED = 0xC2A2_2026


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def openings() -> list[str]:
    rng = random.Random(SEED)
    result: list[str] = []
    seen: set[str] = set()
    while len(result) < PAIRS:
        board = chess.variant.CrazyhouseBoard()
        for _ in range(rng.randrange(8, 25)):
            if board.is_game_over():
                break
            board.push(rng.choice(sorted(board.legal_moves, key=lambda move: move.uci())))
        identity = " ".join(board.fen().split()[:4])
        if not board.is_game_over() and identity not in seen:
            seen.add(identity)
            result.append(board.fen())
    return result


def configure(engine: chess.engine.SimpleEngine) -> None:
    values = {name: value for name, value in (
        ("Threads", 3), ("Hash", 32), ("OwnBook", False),
        ("Noise", 0), ("Move Overhead", 0),
    ) if name in engine.options}
    if values:
        engine.configure(values)


def play(candidate_path: Path, baseline_path: Path, row: dict):
    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    candidate = chess.engine.SimpleEngine.popen_uci(
        [str(candidate_path), "--uci"], timeout=30, creationflags=flags)
    baseline = chess.engine.SimpleEngine.popen_uci(
        [str(baseline_path), "--uci"], timeout=30, creationflags=flags)
    board = chess.variant.CrazyhouseBoard(row["fen"])
    started = time.monotonic()
    played = 0
    try:
        configure(candidate)
        configure(baseline)
        limit = chess.engine.Limit(time=MOVETIME_MS / 1000)
        while not board.is_game_over() and played < MAX_PLIES:
            engine = candidate if board.turn == row["candidate_white"] else baseline
            answer = engine.play(board, limit)
            if answer.move is None or answer.move not in board.legal_moves:
                raise RuntimeError(f"illegal or missing move at ply {board.ply()}: {answer.move}")
            board.push(answer.move)
            played += 1
    finally:
        candidate.quit()
        baseline.quit()
    outcome = board.outcome()
    if outcome is None or outcome.winner is None:
        score, result = 0.5, "1/2-1/2"
    else:
        score = 1.0 if outcome.winner == row["candidate_white"] else 0.0
        result = "1-0" if outcome.winner else "0-1"
    game = chess.pgn.Game.from_board(board)
    game.headers.update({
        "Event": "Eloi Rust Crazyhouse qualification",
        "Round": str(row["game"]),
        "White": "Eloi-Crazyhouse" if row["candidate_white"] else "Eloi-generic",
        "Black": "Eloi-generic" if row["candidate_white"] else "Eloi-Crazyhouse",
        "Result": result,
    })
    return ({**row, "score": score, "result": result, "played_plies": played,
             "elapsed_seconds": round(time.monotonic() - started, 3),
             "final_fen": board.fen()}, game)


def summary(rows: list[dict]) -> dict:
    wins = sum(row["score"] == 1 for row in rows)
    draws = sum(row["score"] == 0.5 for row in rows)
    losses = sum(row["score"] == 0 for row in rows)
    points = wins + draws / 2
    return {"completed": len(rows), "wins": wins, "draws": draws, "losses": losses,
            "score_points": points, "score_percent": 100 * points / GAMES}


def verify(path: Path) -> dict:
    count = 0
    with path.open(encoding="utf-8") as stream:
        while game := chess.pgn.read_game(stream):
            board = game.board()
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    raise RuntimeError(f"illegal replay move in game {count + 1}: {move}")
                board.push(move)
            count += 1
    return {"verified_games": count, "expected_games": GAMES, "passed": count == GAMES}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    frozen = openings()
    schedule = [{"game": pair * 2 + color + 1, "pair": pair + 1,
                 "candidate_white": color == 0, "fen": fen}
                for pair, fen in enumerate(frozen) for color in range(2)]
    protocol = {
        "schema": "eloi-rust-crazyhouse-gate-v1", "games": GAMES,
        "pairs": PAIRS, "mirrored": True, "movetime_ms": MOVETIME_MS,
        "max_plies": MAX_PLIES, "threads_per_engine": 3, "hash_mb": 32,
        "priority": "idle", "seed": SEED,
        "candidate_sha256": sha256(args.candidate),
        "baseline_sha256": sha256(args.baseline),
        "runner_sha256": sha256(Path(__file__)), "schedule": schedule,
        "qualification": "candidate score_points > 50/100; zero failures; 100/100 replay",
    }
    atomic_json(args.output / "protocol.json", protocol)
    rows, failures = [], []
    pgn = args.output / "games.pgn"
    for row in schedule:
        try:
            result, game = play(args.candidate.resolve(), args.baseline.resolve(), row)
            rows.append(result)
            with pgn.open("a", encoding="utf-8", newline="\n") as stream:
                print(game, file=stream, end="\n\n")
        except Exception as error:
            failures.append({**row, "error": f"{type(error).__name__}: {error}"})
        evidence = {"schema": "eloi-rust-crazyhouse-results-v1", "complete": False,
                    "summary": summary(rows), "results": rows,
                    "protocol_failures": failures}
        atomic_json(args.output / "results.json", evidence)
        print(json.dumps({"game": row["game"], **evidence["summary"],
                          "failures": len(failures)}), flush=True)
        if failures:
            return 2
    evidence["complete"] = True
    evidence["replay_verification"] = verify(pgn)
    evidence["qualification"] = {
        "above_50_percent": evidence["summary"]["score_points"] > 50,
        "passed": evidence["summary"]["score_points"] > 50
                  and evidence["replay_verification"]["passed"],
    }
    evidence["hashes"] = {name: sha256(args.output / name)
                           for name in ("protocol.json", "games.pgn")}
    atomic_json(args.output / "results.json", evidence)
    evidence["hashes"]["results.json"] = sha256(args.output / "results.json")
    return 0 if evidence["qualification"]["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
