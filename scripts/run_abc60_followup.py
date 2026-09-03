#!/usr/bin/env python3
"""New user-authorized A confirmation after host sleep; original run immutable.

Reuses the frozen ABC60 transport, legality checks, resource guards and scoring.
Only output/start/protocol locations are rebound; all rebinding is recorded.
"""
import argparse
from pathlib import Path
import subprocess
import sys

import run_abc60 as base

ORIGINAL_WORK = base.WORK
ORIGINAL_PROTOCOL = base.PROTOCOL
base.WORK = base.ROOT / "tmp/abc60-followup"
base.PROTOCOL = base.ROOT / "data/abc60_followup_protocol.json"
base.START = base.ROOT / "data/abc60_followup_start.json"


def prepare():
    start = base.read(base.START)
    budget = base.Budget(start["started_utc"])
    budget.check(5)
    processes = base.verify_no_competing_job()
    usage = base.resource_check(20_000_000)
    ready = base.bounded_process([sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_abc60*.py", "-v"], 30, budget, 5)
    base.require(ready["returncode"] == 0 and not ready["censored"], "Reusable runner tests failed")
    base.create(base.WORK / "runner-tests.json", ready)
    old = base.read(ORIGINAL_PROTOCOL)
    used, historical = base.prior_openings()
    first, rest = base.pick_openings(base.read(base.ROOT / "data/search_recovery/reserve.json")["positions"], used)
    openings = (first + rest)[:10]
    protected = dict(old["protected"])
    for path in [p for p in ORIGINAL_WORK.rglob("*") if p.is_file()] + [
            ORIGINAL_PROTOCOL, base.ROOT / "data/abc60_results.json", base.ROOT / "ABC60_ASSESSMENT.md",
            base.ROOT / "data/abc60_diagnostics.json", base.ROOT / "data/abc60_power_interruption.json"]:
        protected[str(path.relative_to(base.ROOT))] = base.lab.sha256(path)
    files = [Path(__file__), base.ROOT / "scripts/run_abc60.py", base.ROOT / "scripts/engine_lab.py", base.START,
             base.ROOT / "scripts/test_abc60.py", base.ROOT / "scripts/test_abc60_analysis.py"]
    protocol = {"schema": 1, "experiment": "abc60-independent-followup-v1", "start": start,
                "created_utc": base.lab.utc_now(), "candidate": "A", "games": 20, "required_points": 11,
                "selection_basis": "A won the completed frozen ABC60 screening, before this follow-up was requested.",
                "no_pooling_with_interrupted_confirmation": True, "release_authorized": False,
                "original_protocol_sha256": base.lab.sha256(ORIGINAL_PROTOCOL),
                "binaries": base.verify_identities(base.EXPECTED), "weights": base.verify_identities(base.WEIGHTS),
                "files": {str(p.relative_to(base.ROOT)): base.lab.sha256(p) for p in files},
                "protected": protected, "prior_opening_evidence": historical, "openings": openings,
                "schedule": base.make_schedule(openings, "confirmation", "A"), "settings": old["settings"],
                "module_rebindings": {"WORK": str(base.WORK), "PROTOCOL": str(base.PROTOCOL), "START": str(base.START)},
                "preflight": usage, "processes": processes,
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=base.ROOT, text=True).strip()}
    protocol["settings"] = {**protocol["settings"], "maximum_games": 20}
    budget.check(5)
    base.create(base.PROTOCOL, protocol)
    print(base.json.dumps({"protocol_sha256": base.lab.sha256(base.PROTOCOL), "reserve_indices": [p["reserve_index"] for p in openings]}), flush=True)


def finish(protocol, outcome):
    base.verify_protocol(protocol)
    completed, incidents = [], []
    for path in sorted(base.WORK.glob("confirmation-*.json")):
        row = base.read(path)
        if row.get("protocol_failure"):
            incidents.append(row)
        else:
            base.validate_game(row, protocol["schedule"][row["game"] - 1], base.lab.sha256(base.PROTOCOL))
            completed.append(row)
    base.require([r["game"] for r in completed] == list(range(1, len(completed) + 1)), "Completed-game gap")
    summary = base.stats(completed)
    passed = base.confirmation_positive(completed) and not incidents
    result = {"experiment": protocol["experiment"], "outcome": outcome, "summary": summary,
              "passed_provisional_checkpoint": passed, "release_qualified": False,
              "production_and_prior_evidence_unchanged": True, "games": completed, "incidents": incidents,
              "resources": base.resource_check(), "protocol_sha256": base.lab.sha256(base.PROTOCOL),
              "files": {str(p.relative_to(base.ROOT)): base.lab.sha256(p) for p in base.WORK.rglob("*") if p.is_file()}}
    base.create(base.ROOT / "data/abc60_followup_results.json", result)
    pgn = "".join(row["pgn"] for row in completed + incidents)
    with (base.ROOT / "data/abc60_followup_games.pgn").open("x", encoding="utf-8") as stream:
        stream.write(pgn)
    score = f"{summary['score']:.1%}" if summary["score"] is not None else "n/a"
    lines = ["# A — Independent Confirmation After Host Sleep", "",
             f"**{'Provisional checkpoint passed' if passed else 'No provisional checkpoint pass'}; no release qualification.**", "",
             f"Completed {summary['games']}/20 games against the exact published v2.0.0: **{summary['wins']} wins, {summary['draws']} draws, {summary['losses']} losses; {summary['points']} points ({score}).**", "",
             "This is a new user-authorized experiment following a documented laptop-sleep interruption. It neither resumes nor repairs the previous experiment. Previous 11.5/16 confirmation points are excluded from this score.", "",
             "## Frozen protocol", "", "Ten new mirrored reserve openings; 250 ms/move; three search threads; 32 MB hash; books/noise off; Idle priority; fresh engine processes per game; absolute-ply-200 draw adjudication. Twenty-minute total budget, minute-18 search cutoff. The threshold is 11/20 points, all games completed, no protocol incidents. No extra games or result-based stopping.", "",
             f"Protocol SHA-256: `{base.lab.sha256(base.PROTOCOL)}`.", "",
             "## Interpretation", "", f"Paired 95% descriptive score interval: {summary['paired_95pct_descriptive_interval']}. {summary['uncertainty_method']}", "",
             f"Color split: `{base.json.dumps(summary['color_split'])}`. Mirrored pair points: `{[p['points'] for p in summary['mirrored_pairs']]}`.", "",
             "A remains blocked from release by its original required-defense regression. Better match results do not waive that failure or prove superiority over C. No training, engine changes, Stockfish use, installation, deletion or publication occurred.", "",
             f"Protocol incidents: {len(incidents)}. Outcome: `{base.json.dumps(outcome)}`.", "",
             "## Evidence", "", "[Protocol](data/abc60_followup_protocol.json) · [Results and all game records](data/abc60_followup_results.json) · [PGNs](data/abc60_followup_games.pgn) · [Original assessment](ABC60_ASSESSMENT.md)", "",
             f"Final temporary bytes: {result['resources']['total_bytes']:,}; training: {result['resources']['training_bytes']:,}; follow-up scratch: {result['resources']['own_bytes']:,}.", ""]
    with (base.ROOT / "ABC60_FOLLOWUP.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    print(base.json.dumps({"passed": passed, "summary": summary, "report": "ABC60_FOLLOWUP.md"}), flush=True)


def run():
    protocol = base.read(base.PROTOCOL)
    base.verify_protocol(protocol)
    base.verify_no_competing_job()
    budget = base.Budget(protocol["start"]["started_utc"])
    outcome = {"started_utc": base.lab.utc_now(), "status": "running"}
    rows = []
    try:
        for plan in protocol["schedule"]:
            budget.check(18)
            base.resource_check(1_000_000)
            rows.append(base.play(plan, protocol, budget, 18))
            s = base.stats(rows)
            print(f"follow-up {len(rows)}/20: W/D/L {s['wins']}/{s['draws']}/{s['losses']}; points {s['points']}", flush=True)
        outcome["status"] = "completed"
    except Exception as error:
        outcome.update({"status": "stopped", "error": f"{type(error).__name__}: {error}"})
    finally:
        outcome["ended_utc"] = base.lab.utc_now()
        base.create(base.WORK / "outcome.json", outcome)
        finish(protocol, outcome)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    args = parser.parse_args()
    {"prepare": prepare, "run": run}[args.action]()
