#!/usr/bin/env python3
"""Compare official, pre-recovery, restored and full-width regression traces.

The official executable is never instrumented or replaced. Its trace is limited
to UCI observations; internal root/TT diagnostics come from the current binary.
Only regression and diagnostic positions are used, never sealed match FENs.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import shlex
import subprocess
import os

import engine_lab as lab
import search_recovery as recovery


def regressions():
    rows = []
    for line in (recovery.ROOT / "tests/epd/v2_5_regressions.epd").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=4)
        ops = {}
        for part in fields[4].split(";"):
            values = shlex.split(part)
            if values:
                ops[values[0]] = " ".join(values[1:])
        rows.append({"id": ops["id"], "fen": " ".join(fields[:4]) + " " +
                     ops.get("hmvc", "0") + " " + ops.get("fmvn", "1"),
                     "depth": int(ops.get("acd", "4")), "expected": ops.get("bm"),
                     "forbidden": ops.get("am"), "category": ops["c0"]})
    return rows


def uci_trace(engine, fen, depth):
    board = lab.chess.Board(fen)
    rows = {}
    with engine.analysis(board, lab.chess.engine.Limit(depth=depth, time=15), game=object()) as analysis:
        for info in analysis:
            if not info.get("depth") or "score" not in info or info.get("lowerbound") or info.get("upperbound"):
                continue
            score = info["score"].pov(board.turn).score(mate_score=30000)
            pv = [m.uci() for m in info.get("pv", [])]
            rows[info["depth"]] = {"depth": info["depth"], "score_cp": score,
                                    "selected_move": pv[0] if pv else "0000", "pv": pv,
                                    "nodes": info.get("nodes", 0)}
        result = analysis.wait()
    return {"iterations": list(rows.values()),
            "bestmove": result.move.uci() if result.move else "0000"}


def run(candidate: pathlib.Path, output: pathlib.Path, max_ms: int):
    recovery.resource_check(projected=100_000_000)
    official = recovery.SCRATCH / "baseline/Eloi.exe"
    previous = recovery.SCRATCH / "pre-recovery/Eloi.exe"
    if recovery.sha256(official) != recovery.BASELINE:
        raise ValueError("official baseline identity mismatch")
    if output.exists():
        raise ValueError("use a new diagnostic evidence directory")
    output.mkdir(parents=True)
    report = {"schema": 1, "source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=recovery.ROOT, text=True).strip(),
        "weights_sha256": recovery.WEIGHTS,
        "engines": {"official": recovery.sha256(official), "pre_recovery": recovery.sha256(previous),
                    "restored": recovery.sha256(candidate)},
        "settings": {"hash_mb": 4, "threads": 3, "max_ms_per_profile": max_ms,
                     "node_cap_per_profile": 2_000_000}, "regressions": []}
    baseline_engine = lab.start_engine(official, idle_priority=os.name == "nt")
    previous_engine = lab.start_engine(previous, idle_priority=os.name == "nt")
    baseline_engine.configure({"Hash": 4})
    previous_engine.configure({"Hash": 4})
    try:
        for case in regressions():
            row = {**case, "official": uci_trace(baseline_engine, case["fen"], case["depth"]),
                   "pre_recovery": uci_trace(previous_engine, case["fen"], case["depth"])}
            for profile in ("production", "full-width"):
                path = output / f"{case['id']}-{profile}.json"
                command = [str(candidate), "--diagnose-search", "--fen", case["fen"],
                           "--depth", str(case["depth"]), "--profile", profile, "--json", str(path),
                           "--max-ms", str(max_ms), "--nodes", "2000000", "--hash-mb", "4"]
                done = subprocess.run(command, capture_output=True, text=True, timeout=max_ms / 1000 + 15,
                                      creationflags=subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0)
                if done.returncode not in (0, 3):
                    raise RuntimeError(done.stderr or done.stdout)
                trace = json.loads(path.read_text())
                row[profile] = {"path": str(path.relative_to(recovery.ROOT)), "sha256": recovery.sha256(path),
                                "completed": trace["completed"], "total_nodes_consumed": trace["total_nodes_consumed"],
                                "static_eval_cp": trace["static_eval_cp"],
                                "iterations": [{k: item[k] for k in ("depth", "score_cp", "selected_move", "pv", "nodes", "pruning")}
                                               for item in trace["iterations"]]}
            report["regressions"].append(row)
            lab.atomic_json(output / "comparison.json", report)
            names = []
            for mode in ("official", "pre_recovery", "production", "full-width"):
                iterations = row[mode]["iterations"]
                names.append(f"{mode}=" + (f"d{iterations[-1]['depth']}:{iterations[-1]['selected_move']}" if iterations else "terminal"))
            print(case["id"] + " " + " ".join(names), flush=True)
    finally:
        baseline_engine.quit()
        previous_engine.quit()
    # Quantify how much previous completed root ordering is discarded.
    ordering = []
    for row in report["regressions"]:
        trace = json.loads((recovery.ROOT / row["production"]["path"]).read_text())
        for earlier, later in zip(trace["iterations"], trace["iterations"][1:]):
            ranked = sorted((m for m in earlier["root_moves"] if m["score_cp"] is not None),
                            key=lambda m: -m["score_cp"])
            order = [m["move"] for m in later["root_moves"]]
            for rank, move in enumerate(ranked[:5]):
                if move["move"] in order and order.index(move["move"]) >= 10:
                    ordering.append({"id": row["id"], "previous_depth": earlier["depth"], "move": move["move"],
                                     "previous_rank": rank + 1, "previous_bound": move["bound"],
                                     "next_search_index": order.index(move["move"]) + 1})
    report["discarded_previous_order_examples"] = ordering
    lab.atomic_json(output / "comparison.json", report)
    print(json.dumps({"report": str(output / "comparison.json"), "ordering_examples": len(ordering)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--max-ms", type=int, default=15000)
    args = parser.parse_args()
    run(args.candidate.resolve(), args.output.resolve(), args.max_ms)
