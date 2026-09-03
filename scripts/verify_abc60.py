#!/usr/bin/env python3
"""Cross-check completed ABC60 PGNs against per-response events; retain evidence.

No engines, network, rewrites, deletions, or match resumption. The event/PGN
cross-check is separate from the runner's board-record validator.
"""
import argparse
import collections
import io
from pathlib import Path

import run_abc60 as run


def audit():
    protocol = run.read(run.PROTOCOL)
    run.verify_protocol(protocol)
    outcome = run.read(run.WORK / "outcome.json")
    run.require(outcome["status"] == "completed", "Only a completed campaign can be fully retained")
    selection = run.read(run.WORK / "selection.json")["selected"]
    rows = []
    events = collections.defaultdict(list)
    for line in (run.WORK / "events.jsonl").read_text().splitlines():
        row = run.json.loads(line)
        if row["type"] == "move":
            events[row["stage"], row["game"]].append(row)
    for stage, plans in (("screening", protocol["screening_schedule"]),
                         ("confirmation", protocol["confirmation_schedules"][selection])):
        for plan in plans:
            path = run.WORK / f"{stage}-{plan['game']:03d}.json"
            row = run.read(path)
            run.require(not row.get("protocol_failure"), "Incident in completed game")
            run.require(all(row[k] == v for k, v in plan.items()), "Saved pairing differs from frozen schedule")
            run.require(row["protocol_sha256"] == run.lab.sha256(run.PROTOCOL), "Wrong game protocol")
            pgn = run.chess.pgn.read_game(io.StringIO(row["pgn"]))
            run.require(pgn is not None and not pgn.errors, "Invalid PGN")
            board = pgn.board()
            run.require(board.fen() == run.chess.Board(plan["fen"]).fen(), "Incorrect starting board")
            observed = events.pop((stage, plan["game"]), [])
            moves = list(pgn.mainline_moves())
            run.require(len(observed) == len(moves) == len(row["move_seconds"]), "Missing/extra responses")
            for i, (move, event) in enumerate(zip(moves, observed)):
                run.require(not board.is_game_over(claim_draw=True) and board.ply() < 200, "Play after game termination")
                run.require(event["fen"] == board.fen(), "Response recorded for wrong position")
                run.require(event["move"] == move.uci() == row["moves"][i], "Response/PGN/record disagree")
                expected_engine = plan["candidate"] if board.turn == plan["candidate_white"] else "v2.0.0"
                run.require(event["engine"] == expected_engine, "Wrong engine moved")
                run.require(event["protocol_failure"] is None, "Protocol incident in event log")
                run.require(0 <= event["elapsed_seconds"] <= 2.5 and event["elapsed_seconds"] == row["move_seconds"][i], "Timing mismatch")
                run.require(move in board.legal_moves, "Illegal PGN move")
                board.push(move)
            result = board.outcome(claim_draw=True)
            run.require(result is not None or board.ply() >= 200, "Unsupported adjudication")
            expected_result = result.result() if result else "1/2-1/2"
            expected_label = "draw" if not result or result.winner is None else "win" if result.winner == plan["candidate_white"] else "loss"
            run.require(row["result"] == pgn.headers["Result"] == expected_result, "Incorrect outcome")
            run.require(row["label"] == expected_label, "Incorrect candidate-relative outcome")
            run.require(row["final_fen"] == board.fen(), "Final board mismatch")
            rows.append(row)
    run.require(not events, "Unmatched response events")
    screening = [r for r in rows if r["stage"] == "screening"]
    confirmation = [r for r in rows if r["stage"] == "confirmation"]
    run.require(run.select(screening) == selection, "Wrong selection")
    results = run.read(run.ROOT / "data/abc60_results.json")
    run.require(results["confirmation"] == run.stats(confirmation), "Published confirmation summary differs")
    for name in "ABC":
        run.require(results["screening"][name] == run.stats([r for r in screening if r["candidate"] == name]), "Published screening summary differs")
    run.require(results["provisional_positive"] == run.confirmation_positive(confirmation), "Wrong checkpoint outcome")
    times = [t for row in rows for t in row["move_seconds"]]
    return {"schema": 1, "experiment": protocol["experiment"], "selected": selection,
            "game_count": len(rows), "move_count": len(times), "maximum_response_seconds": max(times),
            "illegal_moves": 0, "protocol_incidents": 0, "protected_abc100_files_verified": len(protocol["protected"]),
            "production_unchanged": True, "release_qualified": False, "games": rows,
            "hashes": {str(p.relative_to(run.ROOT)): run.lab.sha256(p) for p in
                       (Path(__file__), run.PROTOCOL, run.ROOT / "data/abc60_results.json",
                        run.ROOT / "data/abc60_diagnostics.json", run.WORK / "events.jsonl")}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retain", action="store_true")
    args = parser.parse_args()
    document = audit()
    if args.retain:
        payload = "".join(row["pgn"] for row in document["games"]).encode()
        run.resource_check(len(payload))
        destination = run.ROOT / "data/abc60_games.pgn"
        with destination.open("xb") as stream:
            stream.write(payload)
        document["hashes"][str(destination.relative_to(run.ROOT))] = run.lab.sha256(destination)
        run.create(run.ROOT / "data/abc60_verified_games.json", document)
    print(run.json.dumps({k: document[k] for k in ("selected", "game_count", "move_count", "maximum_response_seconds", "illegal_moves", "protocol_incidents", "protected_abc100_files_verified")}, indent=2))
