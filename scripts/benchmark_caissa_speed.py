#!/usr/bin/env python3
"""Benchmark an Eloi/Caissa executable at fixed nodes and retain decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess
import chess.engine


FENS = (
    chess.STARTING_FEN,
    "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PB1N2/PP1N1PPP/R1BQ1RK1 w - - 2 9",
    "2r2rk1/1p1bqppp/p2bp3/3n4/3P4/1PN1PN2/PB3PPP/2RQ1RK1 w - - 3 14",
    "4rrk1/1p1nqppp/p2p4/2pP4/2P1P3/2N1B3/PPQ2PPP/3R1RK1 w - - 1 18",
    "8/5pk1/3p2p1/3Pp2p/4P2P/5PP1/6K1/8 w - - 0 36",
)


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=pathlib.Path)
    parser.add_argument("--nodes", type=int, default=100_000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    rows = []
    engine = chess.engine.SimpleEngine.popen_uci([str(args.engine), "--uci"], timeout=30)
    try:
        engine.configure({"Threads": 3, "Hash": 32})
        for repetition in range(args.repetitions):
            for index, fen in enumerate(FENS):
                board = chess.Board(fen)
                started = time.perf_counter()
                result = engine.play(board, chess.engine.Limit(nodes=args.nodes), game=(repetition, index), info=chess.engine.INFO_ALL)
                elapsed = time.perf_counter() - started
                nodes = int(result.info.get("nodes", 0))
                score = result.info.get("score")
                rows.append({
                    "repetition": repetition,
                    "position": index,
                    "fen": fen,
                    "move": result.move.uci() if result.move else None,
                    "score_white_cp": score.white().score(mate_score=30_000) if score else None,
                    "nodes": nodes,
                    "elapsed_seconds": elapsed,
                    "nps": nodes / elapsed if elapsed else 0.0,
                })
                print(json.dumps(rows[-1]), flush=True)
    finally:
        engine.quit()
    result = {
        "engine": str(args.engine.resolve()),
        "engine_sha256": sha256(args.engine),
        "nodes_requested": args.nodes,
        "repetitions": args.repetitions,
        "samples": rows,
        "median_elapsed_seconds": statistics.median(row["elapsed_seconds"] for row in rows),
        "median_nps": statistics.median(row["nps"] for row in rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
