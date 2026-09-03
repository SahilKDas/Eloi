#!/usr/bin/env python3
"""Frozen, one-hour A/B/C research assessment. No training or engine changes.

All game records are create-only. A protocol incident stops the campaign without
assigning a chess result. Never resumes or rewrites ABC100. No deletion methods.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request

import engine_lab as lab

chess = lab.chess
ROOT = lab.ROOT
WORK = ROOT / "tmp/abc60"
START = ROOT / "data/abc60_start.json"
PROTOCOL = ROOT / "data/abc60_protocol.json"
FLAGS = (subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
EXPECTED = {
    "v2.0.0": ("tmp/search-recovery/baseline/Eloi.exe", lab.OFFICIAL_V2_SHA256),
    "A": ("tmp/nnue-fresh-data/candidates/A/build/Eloi.exe", "4D3589577D495D2CBA68473385D04AF0DF3125E29F1CBB076B5197F1AA6DE9A9"),
    "B": ("tmp/nnue-fresh-data/candidates/B/build/Eloi.exe", "2F12FCA565C900F3B53A40F17DF4F59E95AFCDBFFE283FFCDF4F63CD04BE9274"),
    "C": ("tmp/nnue-fresh-data/candidates/C/build/Eloi.exe", "E2F7CE21B59D56BEBF1DF00334CC60C6032869648D86D2D3DF834021D046C6EA"),
}
WEIGHTS = {
    "production": ("include/eloi/nnue_weights.hpp", "CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E"),
    "A": ("tmp/nnue-fresh-data/candidates/A/include/eloi/nnue_weights.hpp", "EC39F85274CB7AA964580EC3BC4B0A4AB9A055E121BB9D1AAC63B71C63015958"),
    "B": ("tmp/nnue-fresh-data/candidates/B/include/eloi/nnue_weights.hpp", "85F3C538D2A914AA5333B2A00EADC3A44CC675D3F78113FDD5AD0AF1893673D7"),
    "C": ("tmp/nnue-fresh-data/candidates/C/include/eloi/nnue_weights.hpp", "6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD"),
}
KNOWN = {
    "A": {"FAIL: RootSplit: lichess-002mG: expected f8e8, got e5h2"},
    "B": {"FAIL: RootSplit: online-bIw09dp9-knight-hang: forbidden online blunder repeated: c6e5"},
    "C": {"FAIL: RootSplit: lichess-001XA: best move remains stable across quiescence depths",
          "FAIL: RootSplit: poisoned-pawn-capture: best move remains stable across quiescence depths"},
    "production": set(),
}
TARGETS = {"lichess-002mG", "lichess-001XA", "poisoned-pawn-capture",
           "online-Lc65wiSv-bishop-hang", "online-bIw09dp9-knight-hang"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def tree_bytes(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def resource_check(projected=0):
    roots = [ROOT / "tmp", ROOT / "dist", ROOT / "pkg", ROOT / ".deps", ROOT / "build"]
    roots += list(ROOT.glob("build-*"))
    roots += [Path(p) for p in read(START)["external_temporary_directories_found"]]
    usage = {str(p): tree_bytes(p) for p in roots}
    # Conservatively count all .deps, including deliberately retained dependencies.
    total = sum(usage.values())
    training = tree_bytes(ROOT / "tmp/nnue-fresh-data") + tree_bytes(ROOT / ".deps/nnue-inputs") + tree_bytes(ROOT / ".deps/nnue-inputs-v2-broader1")
    owned = tree_bytes(WORK)
    # Reserve ten MB for tracked runner/report/manifest artifacts and finalization.
    quota_check(total, training, owned, projected, shutil.disk_usage(ROOT).free)
    return {"utc": lab.utc_now(), "total_bytes": total, "training_bytes": training,
            "own_bytes": owned, "free_bytes": shutil.disk_usage(ROOT).free, "roots": usage,
            "new_bytes_reserved": 100_000_000, "conservative_dependencies_counted": True}


def quota_check(total, training, owned, projected, free):
    require(total + projected <= 10_000_000_000, "Total temporary cap would be exceeded")
    require(training <= min(8_000_000_000, 7 * 1024**3), "Training cap exceeded")
    require(owned + projected <= 90_000_000, "ABC60 artifact quota would be exceeded")
    require(free >= projected + 1_000_000_000, "Insufficient free-space safety margin")


def create(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    resource_check(len(payload))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def event(value):
    payload = (json.dumps({"utc": lab.utc_now(), **value}, sort_keys=True) + "\n").encode()
    # Per-move writes are tiny; leave a reserved 10 MB margin for final reporting.
    require(tree_bytes(WORK) + len(payload) <= 80_000_000, "Move-log quota reached")
    with (WORK / "events.jsonl").open("ab") as stream:
        stream.write(payload)
        stream.flush()


class Budget:
    def __init__(self, started):
        elapsed = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(started)).total_seconds()
        self.origin = time.monotonic() - elapsed

    def remaining(self, minute):
        return minute * 60 - (time.monotonic() - self.origin)

    def check(self, minute):
        if self.remaining(minute) <= 0:
            raise TimeoutError(f"Campaign minute-{minute} deadline reached")


def verify_identities(expected):
    result = {}
    for name, (relative, digest) in expected.items():
        require(lab.sha256(ROOT / relative) == digest, f"Identity mismatch: {name}")
        result[name] = {"path": relative, "sha256": digest}
    return result


def fen_key(fen):
    return " ".join(chess.Board(fen).fen(en_passant="fen").split()[:4])


def pick_openings(reserve, used):
    selected, seen = [], set(used)
    seen.update(fen_key(p["fen"]) for p in reserve[:17])
    for index, row in enumerate(reserve[17:], 17):
        key = fen_key(row["fen"])
        if key in seen:
            continue
        board = chess.Board(row["fen"])
        require(board.is_valid() and not board.is_game_over(claim_draw=True), "Invalid opening")
        selected.append({"reserve_index": index, "fen": row["fen"]})
        seen.add(key)
        if len(selected) == 14:
            return selected[:4], selected[4:]
    raise ValueError("Not enough unused reserve openings")


def prior_openings():
    used, manifest = set(), {}
    # Inspect actual match records/PGNs, not master opening or training datasets.
    def walk(value):
        if isinstance(value, dict):
            if "fen" in value and any(k in value for k in ("candidate", "game", "result", "candidate_color")):
                used.add(fen_key(value["fen"]))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for root in (ROOT / "data", ROOT / "tmp"):
        for path in root.rglob("*"):
            if not path.is_file() or WORK in path.parents:
                continue
            if path.suffix == ".json" and path.stat().st_size < 20_000_000 and any(
                    word in path.name.lower() for word in ("game-", "results", "checkpoint", "playoff", "protocol", "match")):
                before = len(used)
                walk(read(path))
                if len(used) > before:
                    manifest[str(path.relative_to(ROOT))] = lab.sha256(path)
            elif path.suffix == ".pgn":
                with path.open(encoding="utf-8-sig") as stream:
                    while game := chess.pgn.read_game(stream):
                        require(not game.errors, f"Malformed historical PGN: {path}")
                        used.add(fen_key(game.board().fen()))
                manifest[str(path.relative_to(ROOT))] = lab.sha256(path)
    return used, manifest


def make_schedule(openings, stage, candidate=None):
    rows = []
    for index, opening in enumerate(openings):
        names = [candidate] if candidate else list("ABC"[index % 3:] + "ABC"[:index % 3])
        for white in (True, False):
            for name in names:
                rows.append({"game": len(rows) + 1, "stage": stage, "candidate": name,
                             "opening": index, "candidate_white": white, **opening})
    return rows


def stats(rows):
    counts = collections.Counter(r["label"] for r in rows)
    w, d, loss = (counts[k] for k in ("win", "draw", "loss"))
    pairs = []
    for opening in sorted({r["opening"] for r in rows}):
        group = [r for r in rows if r["opening"] == opening]
        if len(group) == 2 and {r["candidate_white"] for r in group} == {True, False}:
            pairs.append({"opening": opening, "points": sum({"win": 1, "draw": .5, "loss": 0}[r["label"]] for r in group)})
    scores = [p["points"] / 2 for p in pairs]
    interval = None
    if len(scores) > 1:
        error = 1.96 * statistics.stdev(scores) / math.sqrt(len(scores))
        interval = [max(0, statistics.mean(scores) - error), min(1, statistics.mean(scores) + error)]
    return {"games": len(rows), "wins": w, "draws": d, "losses": loss,
            "points": w + d / 2, "score": (w + d / 2) / len(rows) if rows else None,
            "non_losses_secondary": w + d, "mirrored_pairs": pairs,
            "paired_95pct_descriptive_interval": interval,
            "uncertainty_method": "Normal approximation over mirrored pairs; small nonrandom sample, descriptive only; not an Elo guarantee.",
            "color_split": {color: dict(collections.Counter(r["label"] for r in rows if r["candidate_white"] == white))
                            for color, white in (("white", True), ("black", False))}}


def select(rows):
    require(len(rows) == 24 and not any(r.get("protocol_failure") for r in rows), "Incomplete or invalid screening")
    summaries = {name: stats([r for r in rows if r["candidate"] == name]) for name in "ABC"}
    require(all(s["games"] == 8 for s in summaries.values()), "Unequal screening")
    return min("ABC", key=lambda n: (-summaries[n]["points"], summaries[n]["losses"], "CAB".index(n)))


def confirmation_positive(rows):
    return len(rows) == 20 and not any(r.get("protocol_failure") for r in rows) and stats(rows)["points"] >= 11


def check_response(board, move, elapsed):
    if move is None or move not in board.legal_moves:
        return "illegal-or-missing-move"
    if elapsed > 2.5:
        return "watchdog-exceeded"
    return None


def process_snapshot():
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'Eloi|python|stockfish|ninja|cmake|cc1|lichess' } | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    raw = subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True, creationflags=FLAGS, timeout=10)
    rows = json.loads(raw) if raw.strip() else []
    return rows if isinstance(rows, list) else [rows]


def verify_no_competing_job():
    rows = process_snapshot()
    allowed = set(read(START)["protected_existing_processes"]) | {os.getpid()}
    for row in rows:
        require(row["ProcessId"] in allowed, f"Unexpected potentially competing workload PID {row['ProcessId']}: {row['Name']}")
    # GET only: do not call any game/start/resume endpoint.
    with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=3) as response:
        state = json.load(response)
    require(state.get("human", {}).get("result") in ("0-1", "1-0", "1/2-1/2"), "Human game may still be active")
    require(read(ROOT / "tmp/abc100/summary.json").get("automated_status") == "paused_error", "Old match is not paused")
    return rows


def prepare():
    start = read(START)
    Budget(start["started_utc"]).check(12)
    usage = resource_check(80_000_000)
    processes = verify_no_competing_job()
    ready = bounded_process([sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_abc60.py", "-v"],
                            30, Budget(start["started_utc"]), 12)
    require(ready["returncode"] == 0 and not ready["censored"], "Runner tests did not pass before deadline")
    create(WORK / "runner-tests.json", ready)
    used, history = prior_openings()
    reserve_path = ROOT / "data/search_recovery/reserve.json"
    screening, confirmation = pick_openings(read(reserve_path)["positions"], used)
    protected = [p for p in (ROOT / "tmp/abc100").rglob("*") if p.is_file()]
    protected += [ROOT / "data/nnue_abc100_protocol.json", ROOT / "scripts/abc100_match.py", ROOT / "scripts/abc100_gui_fix.py"]
    files = [Path(__file__), ROOT / "scripts/test_abc60.py", ROOT / "scripts/engine_lab.py", START,
             ROOT / "tests/epd/v2_5_regressions.epd", ROOT / "data/nnue_fresh_data_results.json"]
    document = {"schema": 1, "experiment": "abc60-strength-assessment-v1", "created_utc": lab.utc_now(),
                "start": start, "preflight": usage, "processes": processes,
                "binaries": verify_identities(EXPECTED), "weights": verify_identities(WEIGHTS),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "files": {str(p.relative_to(ROOT)): lab.sha256(p) for p in files},
                "protected": {str(p.relative_to(ROOT)): lab.sha256(p) for p in protected},
                "reserve_sha256": lab.sha256(reserve_path), "prior_opening_evidence": history,
                "screening_openings": screening, "confirmation_openings": confirmation,
                "screening_schedule": make_schedule(screening, "screening"),
                "confirmation_schedules": {n: make_schedule(confirmation, "confirmation", n) for n in "ABC"},
                "selection": "screening points descending, losses ascending, then C A B",
                "confirmation": {"games": 20, "required_points": 11, "release_authorized": False},
                "settings": {"movetime_ms": 250, "threads": 3, "hash_mb": 32, "own_book": False,
                             "noise": 0, "move_overhead_ms": 0, "max_absolute_ply": 200, "claim_draw": True,
                             "watchdog_seconds": 2.5, "hard_response_seconds": 5, "priority": "Windows Idle",
                             "fresh_processes_per_game": True, "maximum_games": 44},
                "known_failures": {n: sorted(v) for n, v in KNOWN.items()}}
    require(document["source_commit"] == start["source_commit"], "Source revision changed")
    Budget(start["started_utc"]).check(12)
    create(PROTOCOL, document)
    print(json.dumps({"protocol": str(PROTOCOL), "sha256": lab.sha256(PROTOCOL), "openings": [p["reserve_index"] for p in screening + confirmation]}), flush=True)


def verify_protocol(protocol):
    verify_identities(EXPECTED)
    verify_identities(WEIGHTS)
    for relative, digest in protocol["files"].items():
        require(lab.sha256(ROOT / relative) == digest, f"Frozen file changed: {relative}")
    for relative, digest in protocol["protected"].items():
        require(lab.sha256(ROOT / relative) == digest, f"Protected ABC100 file changed: {relative}")


def epd_cases():
    rows = []
    for line in (ROOT / "tests/epd/v2_5_regressions.epd").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=4)
        ops = {}
        for clause in fields[4].split(";"):
            values = shlex.split(clause)
            if values:
                ops[values[0]] = " ".join(values[1:])
        depth = max(int(ops.get("acd", "1")), *[int(n) for n in ops.get("stable", "1").split()])
        rows.append({"id": ops["id"], "fen": " ".join(fields[:4]) + " " + ops.get("hmvc", "0") + " " + ops.get("fmvn", "1"),
                     "depth": depth, "operations": ops})
    require(len(rows) == 15, "Regression suite count changed")
    return rows


def bounded_process(command, seconds, budget, minute):
    budget.check(minute)
    began = time.monotonic()
    proc = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=FLAGS)
    censored = False
    try:
        out, _ = proc.communicate(timeout=min(seconds, budget.remaining(minute)))
    except subprocess.TimeoutExpired:
        censored = True
        proc.kill()  # Exact child owned by this invocation, never a bridge/frontend.
        out, _ = proc.communicate(timeout=2)
    return {"command": command, "returncode": proc.returncode, "censored": censored,
            "elapsed_seconds": time.monotonic() - began, "output": out.decode(errors="replace")}


def diagnostics(protocol, budget):
    for name in ("A", "B", "C", "production"):
        path = ROOT / (f"tmp/nnue-fresh-data/candidates/{name}/build/eloi_tests.exe" if name != "production" else "tmp/nnue-fresh-data/production-control/eloi_tests.exe")
        row = {"candidate": name, "binary_sha256": lab.sha256(path), **bounded_process([str(path)], 45, budget, 18)}
        row["failures"] = [line.strip() for line in row["output"].splitlines() if line.startswith("FAIL:")]
        row["unexpected_failures"] = sorted(set(row["failures"]) - KNOWN[name])
        create(WORK / f"tests-{name}.json", row)
        print(f"tests {name}: exit={row['returncode']} censored={row['censored']} failures={len(row['failures'])}", flush=True)
        require(not row["unexpected_failures"], f"Unexpected correctness failure in {name}")
        require(row["censored"] or row["returncode"] == 0 or bool(row["failures"]), f"Test crash in {name}")
    for name in "ABC":
        for case in epd_cases():
            for profile in (["production", "full-width"] if case["id"] in TARGETS else ["production"]):
                resource_check(1_000_000)
                output = WORK / "diagnostics" / f"{name}-{case['id']}-{profile}.json"
                require(not output.exists(), "Diagnostic path already exists")
                output.parent.mkdir(parents=True, exist_ok=True)
                command = [str(ROOT / EXPECTED[name][0]), "--diagnose-search", "--fen", case["fen"],
                           "--depth", str(case["depth"]), "--profile", profile, "--json", str(output),
                           "--max-ms", "2000", "--nodes", "2000000", "--hash-mb", "32"]
                row = {"candidate": name, "case": case, "profile": profile,
                       **bounded_process(command, 2.5, budget, 18)}
                row["trace_path"] = str(output.relative_to(ROOT)) if output.exists() else None
                create(WORK / "diagnostics" / f"{name}-{case['id']}-{profile}-process.json", row)
                require(row["censored"] or row["returncode"] in (0, 3), "Diagnostic engine failed")
        print(f"diagnostics {name}: 15 production + 5 full-width traces recorded", flush=True)


def engine_start(path, budget, minute):
    budget.check(minute)
    engine = chess.engine.SimpleEngine.popen_uci([str(path), "--uci", "--move-overhead", "0"],
                timeout=min(5, budget.remaining(minute)), cwd=WORK, creationflags=FLAGS)
    try:
        lab.configure(engine)
        require("Threads" in engine.options and engine.options["Threads"].min <= 3 <= engine.options["Threads"].max, "Three-thread UCI contract unavailable")
        return engine
    except BaseException:
        engine.close()
        raise


def pgn_text(plan, moves, result, termination):
    board = chess.Board(plan["fen"])
    game = chess.pgn.Game.from_board(board)
    game.headers.update({"Event": "ABC60 " + plan["stage"], "Round": str(plan["game"]), "Result": result,
                         "White": plan["candidate"] if plan["candidate_white"] else "v2.0.0",
                         "Black": "v2.0.0" if plan["candidate_white"] else plan["candidate"],
                         "Termination": termination, "MoveTimeMs": "250"})
    node = game
    for uci in moves:
        move = chess.Move.from_uci(uci)
        require(move in board.legal_moves, "Illegal retained move")
        board.push(move)
        node = node.add_variation(move)
    return str(game) + "\n\n"


def play(plan, protocol, budget, minute):
    board = chess.Board(plan["fen"])
    moves, timings, engines = [], [], {}
    incident = None
    event({"type": "game_started", "plan": plan})
    try:
        for name in (plan["candidate"], "v2.0.0"):
            engines[name] = engine_start(ROOT / EXPECTED[name][0], budget, minute)
        while not board.is_game_over(claim_draw=True) and board.ply() < 200:
            budget.check(minute)
            name = plan["candidate"] if board.turn == plan["candidate_white"] else "v2.0.0"
            remaining = min(5, budget.remaining(minute))
            engines[name].timeout = max(.001, remaining - .25)
            before = board.fen()
            began = time.monotonic()
            move = None
            try:
                played = engines[name].play(board, chess.engine.Limit(time=.25), info=chess.engine.INFO_BASIC)
                move = played.move
                failure = check_response(board, move, time.monotonic() - began)
            except Exception as error:
                failure = f"engine-response-error:{type(error).__name__}"
            elapsed = time.monotonic() - began
            if budget.remaining(minute) <= 0:
                failure = "campaign-deadline"
            observation = {"type": "move", "stage": plan["stage"], "game": plan["game"], "engine": name,
                           "fen": before, "move": move.uci() if move else None, "elapsed_seconds": elapsed,
                           "protocol_failure": failure}
            event(observation)
            if failure:
                incident = observation
                break
            timings.append(elapsed)
            moves.append(move.uci())
            board.push(move)
    except Exception as error:
        incident = {"type": type(error).__name__, "message": str(error), "fen": board.fen(),
                    "stage": plan["stage"], "game": plan["game"]}
        event({"type": "game_interruption", "incident": incident})
    finally:
        for engine in engines.values():
            engine.close()  # Closes only this game's fresh owned subprocess.
            try:
                engine.returncode.result(timeout=2)
            except Exception:
                incident = incident or {"type": "owned-engine-shutdown-timeout", "fen": board.fen()}
    row = {**plan, "protocol_sha256": lab.sha256(PROTOCOL), "moves": moves, "move_seconds": timings,
           "final_fen": board.fen(), "ended_utc": lab.utc_now()}
    if incident:
        row.update({"result": "*", "protocol_failure": incident, "termination": "interrupted"})
    else:
        outcome = board.outcome(claim_draw=True)
        row.update({"result": outcome.result() if outcome else "1/2-1/2",
                    "label": "draw" if not outcome or outcome.winner is None else "win" if outcome.winner == plan["candidate_white"] else "loss",
                    "termination": str(outcome.termination.name) if outcome else "absolute-ply-200 adjudication"})
    row["pgn"] = pgn_text(plan, moves, row["result"], row["termination"])
    create(WORK / f"{plan['stage']}-{plan['game']:03d}.json", row)
    require(not incident, f"Stopped on game incident: {incident}")
    validate_game(row, plan, lab.sha256(PROTOCOL))
    return row


def validate_game(row, plan, protocol_hash):
    require(all(row[k] == v for k, v in plan.items()), "Pairing mismatch")
    require(row["protocol_sha256"] == protocol_hash, "Protocol hash mismatch")
    require(not row.get("protocol_failure"), "Protocol-failed game")
    game = chess.pgn.read_game(io.StringIO(row["pgn"]))
    require(game is not None and not game.errors, "Malformed PGN")
    require(game.board().fen() == chess.Board(plan["fen"]).fen(), "PGN start mismatch")
    require([m.uci() for m in game.mainline_moves()] == row["moves"], "PGN move mismatch")
    board = chess.Board(plan["fen"])
    for uci in row["moves"]:
        require(not board.is_game_over(claim_draw=True) and board.ply() < 200, "Moves after termination")
        move = chess.Move.from_uci(uci)
        require(move in board.legal_moves, "Illegal replay move")
        board.push(move)
    outcome = board.outcome(claim_draw=True)
    require(outcome is not None or board.ply() >= 200, "Premature adjudication")
    result = outcome.result() if outcome else "1/2-1/2"
    label = "draw" if not outcome or outcome.winner is None else "win" if outcome.winner == plan["candidate_white"] else "loss"
    require(row["result"] == game.headers["Result"] == result and row["label"] == label, "Wrong result")
    require(row["final_fen"] == board.fen() == game.end().board().fen(), "Wrong final position")
    require(len(row["move_seconds"]) == len(row["moves"]) and all(0 <= t <= 2.5 for t in row["move_seconds"]), "Invalid move timing")


def report():
    protocol = read(PROTOCOL)
    verify_protocol(protocol)
    screening, confirmation, incidents = [], [], []
    for path in sorted(WORK.glob("screening-*.json")):
        row = read(path)
        if row.get("protocol_failure"):
            incidents.append(row)
        else:
            validate_game(row, protocol["screening_schedule"][row["game"] - 1], lab.sha256(PROTOCOL))
            screening.append(row)
    require([r["game"] for r in screening] == list(range(1, len(screening) + 1)), "Screening gap")
    selected = select(screening) if len(screening) == 24 and not incidents else None
    for path in sorted(WORK.glob("confirmation-*.json")):
        require(selected is not None, "Confirmation before valid selection")
        row = read(path)
        if row.get("protocol_failure"):
            incidents.append(row)
        else:
            validate_game(row, protocol["confirmation_schedules"][selected][row["game"] - 1], lab.sha256(PROTOCOL))
            confirmation.append(row)
    require([r["game"] for r in confirmation] == list(range(1, len(confirmation) + 1)), "Confirmation gap")
    positive = selected is not None and confirmation_positive(confirmation) and not incidents
    evidence = {"experiment": protocol["experiment"], "generated_utc": lab.utc_now(),
                "protocol_sha256": lab.sha256(PROTOCOL), "screening": {n: stats([r for r in screening if r["candidate"] == n]) for n in "ABC"},
                "selected": selected, "confirmation": stats(confirmation), "provisional_positive": positive,
                "release_qualified": False, "production_unchanged": True, "old_match_unchanged": True,
                "tests": [read(p) for p in sorted(WORK.glob("tests-*.json"))],
                "incidents": incidents, "outcome": read(WORK / "outcome.json") if (WORK / "outcome.json").exists() else None,
                "resources": resource_check(), "files": {str(p.relative_to(ROOT)): lab.sha256(p) for p in WORK.rglob("*") if p.is_file()}}
    create(ROOT / "data/abc60_results.json", evidence)
    lines = ["# A/B/C — One-Hour Strength Assessment", "", f"Generated: {evidence['generated_utc']}", "",
             "## Outcome", "", (f"**{selected} is the provisional preferred brain** after passing the separate 20-game score checkpoint." if positive else
             "**Inconclusive comparison; no candidate qualified for release.**"), "",
             "This is a small exploratory experiment, not a reliable Elo estimate. All original release-blocking regression failures remain in force. Production and ABC100 are unchanged.", "",
             "## Screening", "", "| Brain | Games / 8 | W / D / L | Points | Score |", "|---|---:|---:|---:|---:|"]
    for n, s in evidence["screening"].items():
        score = f"{s['score']:.1%}" if s["score"] is not None else "n/a"
        lines.append(f"| {n} | {s['games']} | {s['wins']} / {s['draws']} / {s['losses']} | {s['points']} | {score} |")
    s = evidence["confirmation"]
    lines += ["", "## Independent confirmation", "", f"Selected: {selected or 'none'}. Completed **{s['games']}/20**; W/D/L **{s['wins']}/{s['draws']}/{s['losses']}**, **{s['points']}/20 points**. Required: 11 points, all 20 games completed, zero protocol failures.", "",
              f"Paired 95% descriptive score interval: {s['paired_95pct_descriptive_interval']}. {s['uncertainty_method']}", "",
              "## Correctness and interruptions", "", "Exact test outputs and bounded search traces are retained in the evidence manifest. Depth-stability failures are not automatically blunders; full-width search is not an oracle.", ""]
    for row in evidence["tests"]:
        lines.append(f"- {row['candidate']}: exit {row['returncode']}; censored={row['censored']}; failures: " + ("; ".join(row["failures"]) or "none observed"))
    lines += ["", f"Game incidents: {len(incidents)}. Campaign outcome: `{json.dumps(evidence['outcome'])}`.", "",
              "## Protocol and evidence", "", "250 ms/move; three search threads; 32 MB hash; books/noise disabled; Windows Idle; fresh processes per game; mirrored openings; absolute-ply-200 adjudication. No result-based early stopping, replacement opponent, extra games, or pooled pass score.", "",
              f"Protocol SHA-256: `{evidence['protocol_sha256']}`.", "",
              "[Protocol](data/abc60_protocol.json) · [Machine-readable results](data/abc60_results.json)", "",
              f"Final conservatively counted temporary bytes: {evidence['resources']['total_bytes']:,}; training: {evidence['resources']['training_bytes']:,}; ABC60 scratch: {evidence['resources']['own_bytes']:,}.", "",
              "## Follow-up", "", "An ensemble requires evaluator-isolated accumulators and TT semantics; it was not implemented. The 41 dormant training channels remain a separate training investigation. Neither experiment is justified as a proven strength improvement by this run.", ""]
    path = ROOT / "ABC60_ASSESSMENT.md"
    require(not path.exists(), "Assessment already exists")
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    print(json.dumps({"report": str(path), "selected": selected, "positive": positive, "screening": len(screening), "confirmation": len(confirmation)}), flush=True)


def run():
    protocol = read(PROTOCOL)
    budget = Budget(protocol["start"]["started_utc"])
    verify_protocol(protocol)
    verify_no_competing_job()
    outcome = {"status": "started", "started_utc": lab.utc_now()}
    try:
        diagnostics(protocol, budget)
        rows = []
        for plan in protocol["screening_schedule"]:
            budget.check(38)
            resource_check(1_000_000)
            rows.append(play(plan, protocol, budget, 38))
            print(f"screening {len(rows)}/24 " + json.dumps({n: stats([r for r in rows if r['candidate'] == n])['points'] for n in 'ABC'}), flush=True)
        selected = select(rows)
        create(WORK / "selection.json", {"selected": selected, "screening_hashes": {p.name: lab.sha256(p) for p in WORK.glob('screening-*.json')}})
        print(f"Selected {selected}; starting fixed 20-game confirmation", flush=True)
        confirmed = []
        for plan in protocol["confirmation_schedules"][selected]:
            budget.check(55)
            resource_check(1_000_000)
            confirmed.append(play(plan, protocol, budget, 55))
            print(f"confirmation {len(confirmed)}/20 " + json.dumps(stats(confirmed)), flush=True)
        outcome.update({"status": "completed", "selected": selected, "positive": confirmation_positive(confirmed)})
    except Exception as error:
        outcome.update({"status": "stopped", "type": type(error).__name__, "message": str(error)})
        print(json.dumps(outcome), flush=True)
    finally:
        outcome["ended_utc"] = lab.utc_now()
        create(WORK / "outcome.json", outcome)
        report()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "report"))
    args = parser.parse_args()
    {"prepare": prepare, "run": run, "report": report}[args.action]()
