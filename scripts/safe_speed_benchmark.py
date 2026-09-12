#!/usr/bin/env python3
"""Alternating, bounded 250/500/1000 ms Eloi speed and decision benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess
import chess.engine

TIMES_MS = (250, 500, 1000)
FENS = (
    chess.STARTING_FEN,
    "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PB1N2/PP1N1PPP/R1BQ1RK1 w - - 2 9",
    "2r2rk1/1p1bqppp/p2bp3/3n4/3P4/1PN1PN2/PB3PPP/2RQ1RK1 w - - 3 14",
    "4rrk1/1p1nqppp/p2p4/2pP4/2P1P3/2N1B3/PPQ2PPP/3R1RK1 w - - 1 18",
    "8/5pk1/3p2p1/3Pp2p/4P2P/5PP1/6K1/8 w - - 0 36",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def run_engine(label: str, executable: Path, repetition: int) -> list[dict]:
    creationflags = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0) if os.name == "nt" else 0
    engine = chess.engine.SimpleEngine.popen_uci(
        [str(executable), "--uci"], timeout=30, creationflags=creationflags
    )
    rows = []
    try:
        engine.configure({"Threads": 3, "Hash": 32})
        for time_ms in TIMES_MS:
            for position, fen in enumerate(FENS):
                board = chess.Board(fen)
                started = time.perf_counter()
                result = engine.play(
                    board, chess.engine.Limit(time=time_ms / 1000),
                    game=(label, repetition, time_ms, position),
                    info=chess.engine.INFO_ALL,
                )
                wall_ms = (time.perf_counter() - started) * 1000
                nodes = int(result.info.get("nodes", 0))
                depth = int(result.info.get("depth", 0))
                score = result.info.get("score")
                rows.append({
                    "engine": label, "repetition": repetition,
                    "time_ms": time_ms, "position": position, "fen": fen,
                    "move": result.move.uci() if result.move else None,
                    "score_white_cp": score.white().score(mate_score=30000) if score else None,
                    "nodes": nodes, "depth": depth, "wall_ms": wall_ms,
                    "nps": nodes * 1000 / wall_ms if wall_ms else 0,
                    "deadline_overrun": wall_ms > time_ms + 500,
                })
    finally:
        engine.quit()
    return rows


def summarize(rows: list[dict]) -> dict:
    result = {"tiers": {}}
    for time_ms in TIMES_MS:
        tier = [row for row in rows if row["time_ms"] == time_ms]
        by_engine = {}
        for label in ("baseline", "candidate"):
            selected = [row for row in tier if row["engine"] == label]
            by_engine[label] = {
                "median_nps": statistics.median(row["nps"] for row in selected),
                "median_nodes": statistics.median(row["nodes"] for row in selected),
                "median_depth": statistics.median(row["depth"] for row in selected),
                "overruns": sum(row["deadline_overrun"] for row in selected),
            }
        ratio = by_engine["candidate"]["median_nps"] / by_engine["baseline"]["median_nps"]
        result["tiers"][str(time_ms)] = {**by_engine, "nps_ratio": ratio}
    ratios = [row["nps_ratio"] for row in result["tiers"].values()]
    result["overall_median_nps_ratio"] = statistics.median(ratios)
    result["gate"] = {
        "overall_at_least_five_percent": result["overall_median_nps_ratio"] >= 1.05,
        "no_tier_slower_than_two_percent": all(ratio >= 0.98 for ratio in ratios),
        "no_median_depth_reduction": all(
            row["candidate"]["median_depth"] >= row["baseline"]["median_depth"]
            for row in result["tiers"].values()),
        "no_deadline_overrun": not any(row["deadline_overrun"] for row in rows),
    }
    result["gate"]["passed"] = all(result["gate"].values())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10:
        raise ValueError("repetitions must be 1..10")
    if args.output.exists():
        raise FileExistsError(args.output)
    rows = []
    for repetition in range(args.repetitions):
        order = (("baseline", args.baseline), ("candidate", args.candidate))
        if repetition % 2:
            order = tuple(reversed(order))
        for label, executable in order:
            rows.extend(run_engine(label, executable.resolve(), repetition))
    evidence = {
        "schema": "eloi-safe-speed-benchmark-v1",
        "settings": {"threads": 3, "hash_mb": 32,
                     "times_ms": TIMES_MS, "repetitions": args.repetitions,
                     "priority": "idle" if os.name == "nt" else "default"},
        "identities": {"baseline_sha256": sha256(args.baseline),
                       "candidate_sha256": sha256(args.candidate)},
        "samples": rows,
    }
    evidence.update(summarize(rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"tiers": evidence["tiers"], "gate": evidence["gate"]}, indent=2))
    return 0 if evidence["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
