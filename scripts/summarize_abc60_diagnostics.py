#!/usr/bin/env python3
"""Interpret retained ABC60 traces only. Never starts engines or changes gates."""
import argparse
from pathlib import Path

import run_abc60 as run


def interpret(trace, operations):
    depths = {row["depth"]: row for row in trace["iterations"]}
    final = trace["final_result"]
    complete = trace["completed"]
    required = operations.get("bm")
    forbidden = operations.get("am")
    stable = [int(n) for n in operations.get("stable", "").split()]
    stability = None
    swing = None
    if len(stable) == 2 and all(d in depths for d in stable):
        shallow, deep = (depths[d] for d in stable)
        stability = shallow["selected_move"] == deep["selected_move"]
        swing = abs(shallow["score_cp"] - deep["score_cp"])
    return {"completed": complete, "requested_depth": trace["requested_depth"],
            "completed_depth": final["depth"], "static_eval_cp": trace["static_eval_cp"],
            "move": final["selected_move"], "score_cp": final["score_cp"], "pv": final["pv"],
            "required_move": required, "forbidden_move": forbidden,
            "required_move_satisfied": final["selected_move"] == required if required and complete else None,
            "forbidden_move_repeated": final["selected_move"] == forbidden if forbidden and complete else None,
            "same_move_at_stability_depths": stability, "score_swing_cp": swing,
            "maximum_swing_cp": int(operations["swing"]) if "swing" in operations else None,
            "pruning": final["pruning"], "nodes": trace["total_nodes_consumed"],
            "ladder": [{k: row[k] for k in ("depth", "selected_move", "score_cp", "pv", "nodes")}
                       for row in trace["iterations"]]}


def collect():
    rows, manifest = [], {}
    for path in sorted((run.WORK / "diagnostics").glob("*-process.json")):
        process = run.read(path)
        record = {"candidate": process["candidate"], "case": process["case"]["id"],
                  "profile": process["profile"], "process_censored": process["censored"],
                  "returncode": process["returncode"], "elapsed_seconds": process["elapsed_seconds"]}
        manifest[str(path.relative_to(run.ROOT))] = run.lab.sha256(path)
        if process["trace_path"]:
            trace_path = run.ROOT / process["trace_path"]
            trace = run.read(trace_path)
            record.update(interpret(trace, process["case"]["operations"]))
            manifest[str(trace_path.relative_to(run.ROOT))] = run.lab.sha256(trace_path)
            if record["case"] in run.TARGETS:
                # Root scores carry their original bounds; never treat a bound as exact.
                record["final_root_moves"] = trace["final_result"]["root_moves"]
        rows.append(record)
    return {"schema": 1, "experiment": "abc60-strength-assessment-v1", "trace_count": len(rows),
            "complete_searches": sum(r.get("completed", False) for r in rows),
            "censored_searches": sum(not r.get("completed", False) for r in rows),
            "source_hash": run.lab.sha256(Path(__file__)), "protocol_sha256": run.lab.sha256(run.PROTOCOL),
            "notes": ["Censored searches do not establish a result at the requested depth.",
                      "Full-width retains alpha-beta, TT, extensions and normal quiescence; it is not an oracle.",
                      "A different best move at two depths is not by itself a tactical mistake.",
                      "Diagnostic ladders share iterative-deepening state; fixed-depth unit tests start fresh searches.",
                      "Raw root alternatives retain lower/upper/exact bounds and missing scores.",
                      "No original assertion, eligibility decision, or production setting was changed."],
            "traces": rows, "files": manifest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retain", action="store_true")
    args = parser.parse_args()
    document = collect()
    if args.retain:
        run.require(document["trace_count"] == 60, "Do not retain a partial diagnostic assessment")
        run.create(run.ROOT / "data/abc60_diagnostics.json", document)
    print(run.json.dumps({k: document[k] for k in ("trace_count", "complete_searches", "censored_searches")}, indent=2))
