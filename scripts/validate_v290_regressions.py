#!/usr/bin/env python3
"""Bounded regression validation through the real v2.9.0 production route.

Unlike ``--diagnose-search``, this runner enters Eloi through UCI, so an
opt-in hybrid build exercises ProductionBrain and the embedded Caissa network.
Every depth uses a fresh, Windows-Idle, three-thread engine process.  This is a
correctness gate, not a strength match.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import time

import caissa_adapter_parity as probe
import differential_movegen as movegen
import validation_support


ROOT = Path(__file__).resolve().parents[1]


class RegressionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegressionError(message)


def requested_depths(case: dict) -> list[int]:
    operations = case["operations"]
    for key in ("stable", "compare"):
        if key in operations:
            depths = [int(value) for value in operations[key].split()]
            require(len(depths) == 2, f"{case['id']}: {key} needs two depths")
            return depths
    return [int(operations.get("acd", case["depth"]))]


def pv_from_info(result: dict) -> list[str]:
    line = result.get("last_info", "")
    tokens = line.split()
    if "pv" not in tokens:
        return []
    return tokens[tokens.index("pv") + 1:]


def legal_pv(fen: str, moves: list[str]) -> bool:
    board = movegen.chess.Board(fen)
    try:
        for text in moves:
            move = board.parse_uci(text)
            if move not in board.legal_moves:
                return False
            board.push(move)
    except ValueError:
        return False
    return True


def score_cp(result: dict, board) -> int | None:
    info = result.get("parsed_info")
    if info is not None:
        if info["score_kind"] == "cp":
            return info["score_value"]
        distance = max(1, abs(info["score_value"]))
        return (30_001 - distance) * (1 if info["score_value"] > 0 else -1)
    if board.is_checkmate():
        return -30_000
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    return None


def evaluate_case(case: dict, results: dict[int, dict]) -> dict:
    operations = case["operations"]
    board = movegen.chess.Board(case["fen"])
    legal_roots = {move.uci() for move in board.legal_moves}
    depths = requested_depths(case)
    failures: list[str] = []
    rows = []
    for depth in depths:
        result = results[depth]
        move = result["bestmove"]
        pv = pv_from_info(result)
        terminal = not legal_roots
        if terminal:
            if move != "0000":
                failures.append(f"depth {depth}: terminal root returned {move}")
        elif move not in legal_roots:
            failures.append(f"depth {depth}: Eloi-illegal root move {move}")
        if not terminal and (not pv or pv[0] != move or not legal_pv(case["fen"], pv)):
            failures.append(f"depth {depth}: missing or illegal PV")
        if "am" in operations and move in operations["am"].split():
            failures.append(f"depth {depth}: forbidden move {move}")
        route = any(
            "caissa" in line.lower() or "hybrid" in line.lower()
            for line in result.get("info_strings", [])
        )
        if not terminal and not route:
            failures.append(f"depth {depth}: hybrid route was not reported")
        value = score_cp(result, board)
        rows.append({
            "depth": depth,
            "bestmove": move,
            "score_cp": value,
            "pv": pv,
            "elapsed_ms": result["elapsed_ms"],
            "hybrid_route_reported": route,
            "info_strings": result.get("info_strings", []),
        })

    deepest = rows[-1]
    if "bm" in operations and deepest["bestmove"] not in operations["bm"].split():
        failures.append(
            f"depth {deepest['depth']}: required {operations['bm']}, "
            f"got {deepest['bestmove']}"
        )
    if "ce" in operations and deepest["score_cp"] != int(operations["ce"]):
        failures.append(
            f"depth {deepest['depth']}: expected score {operations['ce']}, "
            f"got {deepest['score_cp']}"
        )
    if len(rows) == 2:
        if "stable" in operations and rows[0]["bestmove"] != rows[1]["bestmove"]:
            failures.append("stable depths changed preferred move")
        if rows[0]["score_cp"] is None or rows[1]["score_cp"] is None:
            failures.append("comparison depth omitted its score")
        elif "swing" in operations:
            swing = abs(rows[0]["score_cp"] - rows[1]["score_cp"])
            if swing > int(operations["swing"]):
                failures.append(
                    f"score swing {swing} exceeds {operations['swing']} cp"
                )

    return {
        "id": case["id"],
        "fen": case["fen"],
        "operations": operations,
        "probes": rows,
        "failures": failures,
        "passed": not failures,
    }


def run(engine: Path, output: Path, timeout_seconds: float) -> dict:
    engine = engine.resolve()
    output = output.resolve()
    require(engine.is_file(), f"engine is absent: {engine}")
    require(not output.exists(), f"refusing evidence collision: {output}")
    require(
        output.is_relative_to((ROOT / "tmp").resolve()),
        "evidence must stay below repository tmp",
    )
    validation_support.resource_snapshot(output.parent, projected=2_000_000)
    cases = validation_support.epd_cases()
    require(len(cases) == 15, "regression corpus count changed")

    started = time.monotonic()
    rows = []
    protocol_failures = []
    for case in cases:
        results = {}
        for depth in requested_depths(case):
            board = movegen.chess.Board(case["fen"])
            try:
                results[depth] = probe.run_probe(
                    engine,
                    engine.parent,
                    ["--uci", "--move-overhead", "0"],
                    case["fen"],
                    f"go depth {depth}",
                    timeout_seconds,
                    allow_null_bestmove=not any(board.legal_moves),
                )
            except Exception as error:  # retain the exact bounded failure
                protocol_failures.append({
                    "id": case["id"],
                    "depth": depth,
                    "error": f"{type(error).__name__}: {error}",
                })
                break
        if len(results) == len(requested_depths(case)):
            rows.append(evaluate_case(case, results))
        else:
            rows.append({
                "id": case["id"], "fen": case["fen"],
                "operations": case["operations"],
                "probes": [], "failures": ["protocol probe incomplete"],
                "passed": False,
            })

    evidence = {
        "schema": "eloi-v2.9.0-hybrid-regressions-v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "runner_sha256": probe.sha256_file(Path(__file__)),
        "engine": str(engine),
        "engine_sha256": probe.sha256_file(engine),
        "settings": {
            "cases": len(cases), "threads": 3, "hash_mb": 16,
            "fresh_process_per_depth": True,
            "priority": "idle", "timeout_seconds": timeout_seconds,
        },
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "protocol_failures": protocol_failures,
        "cases": rows,
    }
    evidence["passed"] = (
        not protocol_failures and all(row["passed"] for row in rows)
    )
    probe.write_evidence(output, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if not 0.5 <= args.timeout_seconds <= 30:
        parser.error("timeout must be between 0.5 and 30 seconds")
    try:
        evidence = run(args.engine, args.output, args.timeout_seconds)
    except (RegressionError, ValueError) as error:
        print(f"BLOCKED: {error}")
        return 2
    for row in evidence["cases"]:
        probes = ", ".join(
            f"d{item['depth']} {item['bestmove']} ({item['score_cp']})"
            for item in row["probes"]
        )
        status = "PASS" if row["passed"] else "FAIL"
        print(f"{row['id']}: {status} {probes}")
        for failure in row["failures"]:
            print(f"  {failure}")
    print(
        f"hybrid regressions: {sum(row['passed'] for row in evidence['cases'])}"
        f"/{len(evidence['cases'])} passed; "
        f"protocol_failures={len(evidence['protocol_failures'])}; "
        f"evidence={args.output}"
    )
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
