#!/usr/bin/env python3
"""Evaluate F1/F2/F3 lab profiles on Eloi's frozen regression corpus."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
sys.path.insert(0, str(ROOT / "scripts"))
import chess
import chess.engine
import validation_support

MECHANISMS = ("reverse-futility", "razoring", "internal-reduction",
              "null-move", "probcut", "futility", "lmp", "lmr")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def expected(case: dict, move: str) -> list[str]:
    operations = case["operations"]
    failures = []
    if operations.get("bm") and move != operations["bm"]:
        failures.append(f"expected {operations['bm']}, got {move}")
    if operations.get("am") and move == operations["am"]:
        failures.append(f"played forbidden {move}")
    return failures


def run_profile(engine: Path, model: Path | None, profile: str,
                cases: list[dict], timeout: float, brain: str) -> dict:
    command = [str(engine), "--brain", brain,
               "--selectivity", profile]
    if model:
        command += ["--policy-value", str(model)]
    started = time.monotonic()
    rows = []
    with chess.engine.SimpleEngine.popen_uci(command, timeout=timeout,
                                              cwd=str(ROOT)) as process:
        for case in cases:
            board = chess.Board(case["fen"])
            info = process.analyse(board, chess.engine.Limit(depth=case["depth"]))
            move = info.get("pv", [])[0].uci() if info.get("pv") else "0000"
            score = info["score"].pov(board.turn).score(mate_score=30_000)
            rows.append({"id": case["id"], "depth": case["depth"],
                         "move": move, "score_cp": score,
                         "nodes": info.get("nodes"),
                         "failures": expected(case, move)})
    return {"profile": profile, "brain": brain, "policy": bool(model), "positions": rows,
            "failures": sum(len(row["failures"]) for row in rows),
            "nodes": sum(row["nodes"] or 0 for row in rows),
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--profile", action="append", dest="profiles")
    parser.add_argument("--epd", action="append", type=Path)
    parser.add_argument("--brain", choices=("eloi-single", "eloi-policy"),
                        default="eloi-single")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    cases = [case for path in (args.epd or [None])
             for case in validation_support.epd_cases(path)]
    if args.profiles:
        profiles = [run_profile(args.engine.resolve(), args.model.resolve(), name,
                                cases, args.timeout_seconds, args.brain)
                    for name in args.profiles]
    else:
        profiles = [
            run_profile(args.engine.resolve(), None, "none", cases,
                        args.timeout_seconds, args.brain),
            run_profile(args.engine.resolve(), args.model.resolve(), "none", cases,
                        args.timeout_seconds, args.brain),
        ]
        profiles += [run_profile(args.engine.resolve(), args.model.resolve(), name,
                                 cases, args.timeout_seconds, args.brain)
                     for name in MECHANISMS]
        profiles.append(run_profile(args.engine.resolve(), args.model.resolve(),
                                    "all", cases, args.timeout_seconds, args.brain))
    evidence = {
        "schema": "eloi-native-f1-f3-regression-screen-v1",
        "engine_sha256": sha256(args.engine), "model_sha256": sha256(args.model),
        "cases": len(cases), "profiles": profiles,
        "passing_profiles": [row["profile"] for row in profiles
                             if row["policy"] and row["failures"] == 0],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({"passing_profiles": evidence["passing_profiles"],
                      "summary": [{"profile": row["profile"],
                                   "policy": row["policy"],
                                   "failures": row["failures"],
                                   "nodes": row["nodes"]}
                                  for row in profiles]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
