#!/usr/bin/env python3
"""Independently verify ABC100 PGNs; optionally retain exactly 100 results.

Never starts an engine, changes the running match, or deletes a file.
"""
import argparse
import collections
import io
import json
import math
from pathlib import Path
import statistics

import abc100_match as match

PROTOCOL_SHA = "75B94D5B438D7084A5B05C5136A59C8CAB949F3C7D8213CF7BEE8A85DDA93889"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_row(row, protocol):
    require(row["protocol_sha256"] == PROTOCOL_SHA, "Game protocol mismatch")
    require(not row.get("protocol_failure"), "Protocol-failed game")
    board = match.restore_board(row)
    pgn = match.chess.pgn.read_game(io.StringIO(row["pgn"]))
    require(pgn is not None and not pgn.errors, "Invalid PGN")
    require(pgn.end().board().fen() == board.fen(), "PGN/record final board mismatch")
    require(pgn.headers["Result"] == row["result"], "PGN/record result mismatch")
    require(row["pgn"] == match.game_pgn(row), "Stored PGN differs from reconstructed game")
    require(row["result"] in ("1-0", "0-1", "1/2-1/2"), "Unfinished game")
    if row["game"] == 100:
        require(row["candidate"] == "Human", "Game 100 must be the human exhibition")
        if row["termination"] == "Human resignation":
            expected = "0-1" if row["candidate_white"] else "1-0"
            require(row["result"] == expected and row["label"] == "loss", "Resignation result mismatch")
            return
    else:
        require(1 <= row["game"] <= 99, "Unexpected game number")
        plan = protocol["schedule"][row["game"] - 1]
        require(all(row[key] == value for key, value in plan.items()), "Frozen pairing mismatch")
    outcome = board.outcome(claim_draw=True)
    require(outcome is not None or board.ply() >= 200, "Nonterminal game before adjudication limit")
    require(row["result"] == (outcome.result() if outcome else "1/2-1/2"), "Incorrect adjudication")
    label = "draw" if outcome is None or outcome.winner is None else (
        "win" if outcome.winner == row["candidate_white"] else "loss")
    require(row["label"] == label, "Candidate-relative result mismatch")


def paired_summary(rows, name):
    subset = sorted((row for row in rows if row["candidate"] == name), key=lambda r: r["candidate_game"])
    values = {"win": 1.0, "draw": 0.5, "loss": 0.0}
    pairs = []
    for i in range(0, len(subset) - 1, 2):
        first, second = subset[i:i + 2]
        require(first["opening"] == second["opening"] and first["candidate_white"] != second["candidate_white"],
                "Invalid opening pair")
        pairs.append({"opening": first["opening"], "white_result": first["label"],
                      "black_result": second["label"],
                      "points_of_two": values[first["label"]] + values[second["label"]]})
    fractions = [p["points_of_two"] / 2 for p in pairs]
    interval = None
    if len(fractions) > 1:
        mean = statistics.mean(fractions)
        margin = 1.96 * statistics.stdev(fractions) / math.sqrt(len(fractions))
        interval = [max(0, mean - margin), min(1, mean + margin)]
    return {"mirrored_pairs": pairs, "paired_score_95pct_descriptive_interval": interval,
            "interval_method": "Normal approximation over mirrored opening pairs only; excludes odd extra game. Small nonrandom sample, descriptive, not a general Elo guarantee.",
            "unpaired_extra_game": {"result": subset[-1]["label"], "color": "white", "opening": 16}
            if len(subset) == 33 else None}


def collect():
    require(match.lab.sha256(match.PROTOCOL) == PROTOCOL_SHA, "Original protocol changed")
    protocol = match.read(match.PROTOCOL)
    match.verify_protocol(protocol)
    amendment_path = match.ROOT / "data/nnue_abc100_gui_amendment.json"
    amendment = match.read(amendment_path)
    require(match.lab.sha256(match.ROOT / amendment["adapter_path"]) == amendment["adapter_sha256"], "GUI adapter changed")
    require(match.lab.sha256(match.ROOT / "include/eloi/nnue_weights.hpp") ==
            "CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E", "Production network changed")
    paths = sorted(match.WORK.glob("game-*.json"))
    rows = []
    human = None
    for path in paths:
        row = match.read(path)
        require(path.name == f"game-{row['game']:03d}.json", "Game filename mismatch")
        validate_row(row, protocol)
        if row["game"] == 100:
            require(human is None, "Duplicate human game")
            human = row
        else:
            rows.append(row)
    require([r["game"] for r in rows] == list(range(1, len(rows) + 1)), "Completed game gap/duplicate")
    standings = match.summarize(rows)
    for name in "ABC":
        standings[name].update(paired_summary(rows, name))
    manifest_paths = [match.PROTOCOL, amendment_path, Path(__file__),
                      match.ROOT / "scripts/test_abc100_match.py",
                      match.ROOT / "scripts/test_report_abc100.py", *paths]
    if len(rows) == 99:
        manifest_paths.extend(p for p in (
            match.WORK / "events.jsonl", match.WORK / "terminal.log",
            match.WORK / "terminal.err", match.WORK / "terminal-2.log",
            match.WORK / "terminal-2.err", match.WORK / "automated-results.json",
            match.WORK / "automated-evidence.json") if p.exists())
    result = {
        "schema": 1, "experiment": protocol["experiment"], "protocol_sha256": PROTOCOL_SHA,
        "counts": {"automated": len(rows), "human": int(human is not None),
                   "total": len(rows) + int(human is not None)},
        "complete": len(rows) == 99 and human is not None,
        "standings": standings, "human": human, "results": rows,
        "pass_rule": protocol["pass_rule"], "binaries": protocol["binaries"],
        "settings": protocol["settings"], "interruption": amendment,
        "validation": {"legal_pgn_replay": True, "result_recalculation": True,
                       "frozen_schedule_and_identities": True, "human_excluded_from_candidates": True,
                       "production_weights_unchanged": True},
        "limitations": ["33 games per candidate; same small reserve-opening set",
                        "17 White / 16 Black games per candidate",
                        "Non-loss pass is not a higher-score or higher-Elo requirement",
                        "Prior deterministic correctness failures remain unresolved",
                        "One documented restart in game 9; search caches reset",
                        "No independent clean-build reproducibility or final performance gate completed"],
        "release_qualified": False, "production_replaced": False,
        "files": {str(p.relative_to(match.ROOT)): {"sha256": match.lab.sha256(p), "bytes": p.stat().st_size}
                  for p in manifest_paths},
    }
    timing_path = match.ROOT / "data/nnue_abc100_timing_interruption.json"
    if timing_path.exists():
        result["timing_interruption"] = match.read(timing_path)
        result["has_recorded_timing_failure"] = True
        result["files"][str(timing_path.relative_to(match.ROOT))] = {
            "sha256": match.lab.sha256(timing_path), "bytes": timing_path.stat().st_size}
        result["limitations"].append("A v2.0.0 move exceeded the 2.5-second watchdog in game 90; see retained timing interruption and any later explicit continuation decision")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retain", action="store_true")
    parser.add_argument("--retain-paused", action="store_true")
    args = parser.parse_args()
    result = collect()
    require(not (args.retain and args.retain_paused), "Choose final or paused retention, not both")
    if args.retain_paused:
        require(not result["complete"], "Completed run must use final retention")
        require(match.read(match.WORK / "summary.json")["automated_status"] == "paused_error", "Run is not paused on an error")
        result["status"] = "paused_error_not_final"
        path = match.ROOT / "data/nnue_abc100_paused_results.json"
        if path.exists():
            require(match.read(path) == result, "Existing paused evidence differs; no overwrite")
        else:
            match.immutable(path, result)
        print(json.dumps({"paused_report": str(path), "sha256": match.lab.sha256(path)}))
    if args.retain:
        require(result["complete"], "Refuse final retention until all 99 automated + one human game finish")
        require((match.WORK / "automated-evidence.json").exists(), "Wait for runner evidence export to finish")
        pgn_path = match.ROOT / "data/games/nnue_abc100.pgn"
        pgn = "".join(row["pgn"] for row in [*result["results"], result["human"]])
        if pgn_path.exists():
            require(pgn_path.read_text(encoding="utf-8") == pgn, "Existing retained PGN differs; no overwrite")
        else:
            pgn_path.parent.mkdir(parents=True, exist_ok=True)
            with pgn_path.open("x", encoding="utf-8") as stream:
                stream.write(pgn)
        result["retained_pgn"] = {"path": str(pgn_path.relative_to(match.ROOT)), "sha256": match.lab.sha256(pgn_path)}
        report_path = match.ROOT / "data/nnue_abc100_results.json"
        if report_path.exists():
            require(match.read(report_path) == result, "Existing retained evidence differs; no overwrite")
        else:
            match.immutable(report_path, result)
        print(json.dumps({"report": str(report_path), "sha256": match.lab.sha256(report_path)}))
    print(json.dumps({"counts": result["counts"], "complete": result["complete"],
                      "validation": result["validation"], "release_qualified": False}))


if __name__ == "__main__":
    main()
