#!/usr/bin/env python3
"""Explicitly authorized concurrent B/C screen; A's prior solo score is context.

Two worker processes isolate transports and records. No engine code changes.
The coordinator stops both on a protocol incident or resource/deadline failure.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import time

import run_abc60 as base

GROUP = base.ROOT / "tmp/abc60-parallel"
base.WORK = GROUP
base.PROTOCOL = base.ROOT / "data/abc60_parallel_protocol.json"
base.START = base.ROOT / "data/abc60_parallel_start.json"
original_resource_check = base.resource_check


def resource_check(projected=0):
    base.require(base.tree_bytes(GROUP) + projected <= 19_000_000, "Shared parallel scratch quota")
    return original_resource_check(projected)


base.resource_check = resource_check


class StopBudget(base.Budget):
    def check(self, minute):
        super().check(minute)
        if (GROUP / "STOP.json").exists():
            raise RuntimeError("Parallel coordinator requested stop")


def prepare():
    start = base.read(base.START)
    budget = base.Budget(start["started_utc"])
    budget.check(5)
    processes = base.verify_no_competing_job()
    usage = resource_check(10_000_000)
    tests = base.bounded_process([sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_abc60*.py", "-v"], 30, budget, 5)
    base.require(tests["returncode"] == 0 and not tests["censored"], "Reusable transport/scoring tests failed")
    base.create(GROUP / "runner-tests.json", tests)
    prior_path = base.ROOT / "data/abc60_followup_protocol.json"
    prior = base.read(prior_path)
    protected = dict(prior["protected"])
    for path in [p for p in (base.ROOT / "tmp/abc60-followup").rglob("*") if p.is_file()] + [
            prior_path, base.ROOT / "data/abc60_followup_results.json", base.ROOT / "data/abc60_followup_games.pgn",
            base.ROOT / "ABC60_FOLLOWUP.md", base.ROOT / "data/abc60_combined_summary.json"]:
        protected[str(path.relative_to(base.ROOT))] = base.lab.sha256(path)
    files = [Path(__file__), base.ROOT / "scripts/run_abc60.py", base.ROOT / "scripts/engine_lab.py", base.START,
             base.ROOT / "scripts/test_abc60.py", base.ROOT / "scripts/test_abc60_analysis.py"]
    protocol = {"schema": 1, "experiment": "abc60-parallel-bc-v1", "start": start,
                "binaries": base.verify_identities(base.EXPECTED), "weights": base.verify_identities(base.WEIGHTS),
                "files": {str(p.relative_to(base.ROOT)): base.lab.sha256(p) for p in files},
                "protected": protected, "preflight": usage, "processes": processes,
                "settings": {**prior["settings"], "maximum_games": 40, "simultaneous_searches": 2,
                             "total_active_search_threads": 6},
                "schedules": {n: base.make_schedule(prior["openings"], "parallel-" + n, n) for n in "BC"},
                "games_each": 20, "required_points_each": 11, "release_authorized": False,
                "a_solo_context": {"games": 20, "wins": 8, "draws": 5, "losses": 7, "points": 10.5,
                                   "protocol_sha256": base.lab.sha256(prior_path)},
                "comparability_warning": "Same openings and per-engine settings as A, but B/C share CPU. Concurrent fixed-movetime results are not a clean strength comparison with A's solo run; actual overlap can vary as games finish.",
                "failure_policy": "Any worker incident stops both; do not score incomplete games, rerun or extend.",
                "worker_isolation": "separate Python processes, private engine pairs, private logs and records"}
    budget.check(5)
    base.create(base.PROTOCOL, protocol)
    print(base.json.dumps({"protocol_sha256": base.lab.sha256(base.PROTOCOL), "games_each": 20, "active_threads": 6}), flush=True)


def worker(name):
    base.WORK = GROUP / name
    protocol = base.read(base.PROTOCOL)
    base.verify_protocol(protocol)
    budget = StopBudget(protocol["start"]["started_utc"])
    outcome = {"candidate": name, "started_utc": base.lab.utc_now(), "status": "running"}
    base.WORK.mkdir(parents=True, exist_ok=True)
    try:
        rows = []
        for plan in protocol["schedules"][name]:
            budget.check(18)
            resource_check(1_000_000)
            rows.append(base.play(plan, protocol, budget, 18))
            s = base.stats(rows)
            print(f"{name} {len(rows)}/20 W/D/L {s['wins']}/{s['draws']}/{s['losses']} points {s['points']}", flush=True)
        outcome["status"] = "completed"
    except Exception as error:
        outcome.update({"status": "stopped", "error": f"{type(error).__name__}: {error}"})
    finally:
        outcome["ended_utc"] = base.lab.utc_now()
        base.create(base.WORK / "outcome.json", outcome)


def collect(protocol):
    base.verify_protocol(protocol)
    candidates = {}
    for name in "BC":
        rows, incidents = [], []
        for path in sorted((GROUP / name).glob(f"parallel-{name}-*.json")):
            row = base.read(path)
            if row.get("protocol_failure"):
                incidents.append(row)
            else:
                base.validate_game(row, protocol["schedules"][name][row["game"]-1], base.lab.sha256(base.PROTOCOL))
                rows.append(row)
        base.require([r["game"] for r in rows] == list(range(1, len(rows)+1)), "Game sequence gap")
        outcome_path = GROUP / name / "outcome.json"
        candidates[name] = {"summary": base.stats(rows), "games": rows, "incidents": incidents,
                            "passed_provisional_checkpoint": base.confirmation_positive(rows) and not incidents,
                            "outcome": base.read(outcome_path) if outcome_path.exists() else {"status": "terminated-or-incomplete"}}
    return candidates


def finish(protocol):
    candidates = collect(protocol)
    document = {"experiment": protocol["experiment"], "protocol_sha256": base.lab.sha256(base.PROTOCOL),
                "candidates": candidates, "a_solo_context": protocol["a_solo_context"],
                "comparability_warning": protocol["comparability_warning"], "release_qualified": False,
                "resources": resource_check(), "prior_evidence_unchanged": True,
                "files": {str(p.relative_to(base.ROOT)): base.lab.sha256(p) for p in GROUP.rglob("*") if p.is_file()}}
    base.create(base.ROOT / "data/abc60_parallel_results.json", document)
    lines = ["# B/C Parallel Screen", "", protocol["comparability_warning"], "",
             "| Brain | Conditions | Games | W/D/L | Points | Provisional checkpoint |", "|---|---|---:|---:|---:|---|",
             "| A | Prior solo run, context only | 20 | 8/5/7 | 10.5/20 | Missed |"]
    pgn = []
    for name, result in candidates.items():
        s = result["summary"]
        lines.append(f"| {name} | Concurrent B/C | {s['games']}/20 | {s['wins']}/{s['draws']}/{s['losses']} | {s['points']} | {'Passed' if result['passed_provisional_checkpoint'] else 'Not passed'} |")
        pgn += [r["pgn"] for r in result["games"] + result["incidents"]]
    lines += ["", "## Protocol and limitations", "", "User explicitly authorized B/C concurrency: two simultaneous searches, exactly three search threads per engine, six active search threads total; fresh private engine pair per game; 250 ms/move, 32 MB hash, books/noise off, Idle priority, absolute-ply-200 adjudication. Same ten mirrored openings as A's solo follow-up. New twenty-minute budget, minute-18 search cutoff, no result-based early stop or extra games.", "",
              "Eleven points and all 20 cleanly completed games are required for each provisional checkpoint. This is not release qualification. All original tactical/depth-stability failures remain in force. Results must not be used to declare B or C stronger than solo A without equal-load confirmation.", "",
              "## Evidence", "", "[Protocol](data/abc60_parallel_protocol.json) · [Results, game records, color splits and paired uncertainty](data/abc60_parallel_results.json) · [PGNs](data/abc60_parallel_games.pgn) · [A follow-up and combined context](ABC60_FOLLOWUP.md)", "",
              f"Protocol SHA-256: `{base.lab.sha256(base.PROTOCOL)}`. Final temporary bytes: {document['resources']['total_bytes']:,}; parallel scratch: {base.tree_bytes(GROUP):,}.", "",
              "Production, earlier evidence and the existing frontend were preserved. No training, Stockfish execution, engine changes, deletion, release package or publication.", ""]
    with (base.ROOT / "data/abc60_parallel_games.pgn").open("x", encoding="utf-8") as stream:
        stream.write("".join(pgn))
    with (base.ROOT / "ABC60_PARALLEL.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    print(base.json.dumps({n: r["summary"] for n, r in candidates.items()}), flush=True)


def run():
    protocol = base.read(base.PROTOCOL)
    base.verify_protocol(protocol)
    base.verify_no_competing_job()
    budget = base.Budget(protocol["start"]["started_utc"])
    budget.check(18)
    workers, logs = {}, []
    try:
        for name in "BC":
            log = (GROUP / f"{name}-worker.log").open("x", encoding="utf-8")
            logs.append(log)
            workers[name] = subprocess.Popen([sys.executable, "-B", "-u", str(Path(__file__)), "worker", "--brain", name],
                          cwd=base.ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=base.FLAGS)
        base.create(GROUP / "workers.json", {n: p.pid for n, p in workers.items()})
        previous = None
        while any(p.poll() is None for p in workers.values()):
            reason = None
            if budget.remaining(18) <= 0:
                reason = "search deadline"
            if base.tree_bytes(GROUP) > 18_000_000:
                reason = "shared scratch quota"
            for name, proc in workers.items():
                path = GROUP / name / "outcome.json"
                if proc.poll() is not None and (proc.returncode != 0 or not path.exists() or base.read(path)["status"] != "completed"):
                    reason = f"worker {name} stopped or failed"
            if reason and not (GROUP / "STOP.json").exists():
                base.create(GROUP / "STOP.json", {"reason": reason, "utc": base.lab.utc_now()})
            status = {n: len(list((GROUP / n).glob(f"parallel-{n}-*.json"))) for n in "BC"}
            if status != previous:
                print(base.json.dumps({"recorded_games": status}), flush=True)
                previous = status
            if budget.remaining(19.5) <= 0:
                for name, proc in workers.items():
                    if proc.poll() is None:
                        # Only the exact still-live worker process created above and its own engines.
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=5, creationflags=base.FLAGS)
                break
            time.sleep(.25)
    finally:
        for proc in workers.values():
            if proc.poll() is None:
                proc.wait(timeout=6)
        for log in logs:
            log.close()
        finish(protocol)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "worker"))
    parser.add_argument("--brain", choices=("B", "C"))
    args = parser.parse_args()
    if args.action == "worker":
        base.require(args.brain is not None, "Worker brain required")
        worker(args.brain)
    else:
        {"prepare": prepare, "run": run}[args.action]()
