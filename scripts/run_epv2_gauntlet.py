#!/usr/bin/env python3
"""Run a frozen mirrored EPV2-versus-E2 qualification stage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess
import chess.engine
import chess.pgn

SELECTIVITY = "reverse-futility,razoring,internal-reduction,probcut,futility,lmp,lmr"
SCREEN_INDICES = list(range(240, 270))
CONFIRMATION_INDICES = list(range(53, 120)) + list(range(195, 228))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def schedule(indices: list[int], positions: list[dict]) -> list[dict]:
    games = []
    for pair, index in enumerate(indices):
        for candidate_white in (True, False):
            games.append({"game": len(games) + 1, "pair": pair + 1,
                          "reserve_index": index,
                          "candidate_white": candidate_white,
                          "fen": positions[index]["fen"]})
    return games


def configure(engine: chess.engine.SimpleEngine) -> None:
    values = {}
    for name, value in (("Threads", 3), ("Hash", 32), ("OwnBook", False),
                        ("Noise", 0)):
        if name in engine.options:
            values[name] = value
    if values:
        engine.configure(values)


def play(command_candidate: list[str], command_baseline: list[str], row: dict,
         nodes: int | None, movetime_ms: int | None, max_plies: int) -> tuple[dict, chess.pgn.Game]:
    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
    candidate = chess.engine.SimpleEngine.popen_uci(command_candidate, timeout=30,
                                                     creationflags=flags)
    baseline = chess.engine.SimpleEngine.popen_uci(command_baseline, timeout=30,
                                                    creationflags=flags)
    started = time.monotonic()
    board = chess.Board(row["fen"])
    moves = []
    try:
        configure(candidate)
        configure(baseline)
        limit = chess.engine.Limit(nodes=nodes,
                                   time=None if movetime_ms is None else movetime_ms / 1000)
        while not board.is_game_over(claim_draw=True) and len(moves) < max_plies:
            candidate_turn = board.turn == row["candidate_white"]
            engine = candidate if candidate_turn else baseline
            result = engine.play(board, limit)
            if result.move is None or result.move not in board.legal_moves:
                raise RuntimeError(f"illegal or missing move at ply {len(moves)}: {result.move}")
            moves.append(result.move.uci())
            board.push(result.move)
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
    game.headers.update({"Event": "Eloi EPV2 qualification",
                         "Round": str(row["game"]),
                         "White": "EPV2" if row["candidate_white"] else "E2",
                         "Black": "E2" if row["candidate_white"] else "EPV2",
                         "Result": result_text,
                         "ReserveIndex": str(row["reserve_index"])})
    return ({**row, "score": score, "result": result_text, "plies": len(moves),
             "elapsed_seconds": round(time.monotonic() - started, 3),
             "final_fen": board.fen()}, game)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--reserve", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stage", choices=("screen", "confirmation"), required=True)
    limits = parser.add_mutually_exclusive_group(required=True)
    limits.add_argument("--nodes", type=int)
    limits.add_argument("--movetime-ms", type=int)
    parser.add_argument("--max-plies", type=int, default=200)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)

    reserve = json.loads(args.reserve.read_text(encoding="utf-8"))
    indices = SCREEN_INDICES if args.stage == "screen" else CONFIRMATION_INDICES
    frozen = schedule(indices, reserve["positions"])
    expected_games = 60 if args.stage == "screen" else 200
    if len(frozen) != expected_games:
        raise RuntimeError("frozen schedule has the wrong game count")
    candidate = [str(args.engine.resolve()), "--uci", "--brain", "eloi-policy",
                 "--policy-value", str(args.model.resolve()), "--selectivity", SELECTIVITY]
    baseline = [str(args.engine.resolve()), "--uci", "--brain", "eloi-single",
                "--selectivity", SELECTIVITY]
    protocol = {"schema": "eloi-epv2-gauntlet-v1", "stage": args.stage,
                "games": expected_games, "mirrored": True,
                "qualification_threshold": "screen >= 50% chess score; confirmation > 50%",
                "nodes": args.nodes, "movetime_ms": args.movetime_ms,
                "max_plies": args.max_plies, "threads_per_engine": 3, "hash_mb": 32,
                "engine_sha256": sha256(args.engine), "model_sha256": sha256(args.model),
                "reserve_sha256": sha256(args.reserve), "runner_sha256": sha256(Path(__file__)),
                "indices": indices, "schedule": frozen,
                "sealed_confirmation_indices": CONFIRMATION_INDICES}
    write_json(args.output / "protocol.json", protocol)
    results = []
    failures = []
    pgn_path = args.output / "games.pgn"
    for row in frozen:
        try:
            result, game = play(candidate, baseline, row, args.nodes,
                                args.movetime_ms, args.max_plies)
            results.append(result)
            with pgn_path.open("a", encoding="utf-8", newline="\n") as stream:
                print(game, file=stream, end="\n\n")
        except Exception as error:
            failures.append({**row, "error": f"{type(error).__name__}: {error}"})
        wins = sum(r["score"] == 1 for r in results)
        draws = sum(r["score"] == .5 for r in results)
        losses = sum(r["score"] == 0 for r in results)
        evidence = {"schema": "eloi-epv2-gauntlet-results-v1", "stage": args.stage,
                    "complete": len(results) + len(failures) == expected_games,
                    "results": results, "protocol_failures": failures,
                    "summary": {"completed": len(results), "wins": wins,
                                "draws": draws, "losses": losses,
                                "score_points": wins + draws / 2,
                                "score_percent": 100 * (wins + draws / 2) / expected_games}}
        write_json(args.output / "results.json", evidence)
        print(json.dumps({"game": row["game"], **evidence["summary"],
                          "failures": len(failures)}), flush=True)
        if failures:
            return 2
    threshold = evidence["summary"]["score_percent"]
    passed = threshold >= 50.0 if args.stage == "screen" else threshold > 50.0
    evidence["passed"] = passed
    write_json(args.output / "results.json", evidence)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
