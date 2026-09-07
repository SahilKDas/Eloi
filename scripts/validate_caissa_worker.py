#!/usr/bin/env python3
"""Validate normal and deliberately crashed Caissa worker behavior.

The validator keeps UCI stdin open until each search completes. The crash
case terminates only Eloi's private child worker and requires the parent
engine to remain alive, report the contained failure, and return a move.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def probe(executable: Path, crash: bool, timeout: float) -> dict:
    environment = os.environ.copy()
    if crash:
        environment["ELOI_CAISSA_WORKER_CRASH_TEST"] = "1"
    else:
        environment.pop("ELOI_CAISSA_WORKER_CRASH_TEST", None)
    process = subprocess.Popen(
        [str(executable), "--uci"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
    )
    assert process.stdin is not None and process.stdout is not None
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        for line in process.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    for command in (
        "uci", "isready", "setoption name Hash value 32",
        "position startpos", "go movetime 1000" if crash
        else "go movetime 500",
    ):
        process.stdin.write(command + "\n")
    process.stdin.flush()

    transcript: list[str] = []
    bestmove = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=min(0.1, deadline - time.monotonic()))
        except queue.Empty:
            continue
        if line is None:
            break
        transcript.append(line)
        if line.startswith("bestmove "):
            bestmove = line.split(maxsplit=1)[1]
            break
    try:
        process.stdin.write("quit\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        exit_code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        exit_code = process.wait(timeout=2)
    joined = "\n".join(transcript)
    legal_move = len(bestmove) in (4, 5) and bestmove != "0000"
    expected_details = (
        ("Caissa worker pipe closed after crash or exit",)
        if crash else
        ("E2 and Caissa agreed", "hybrid disagreement resolved")
    )
    expected_detail_seen = any(detail in joined for detail in expected_details)
    unexpected_failure_seen = not crash and "Caissa failed;" in joined
    return {
        "mode": "crashed-child" if crash else "normal",
        "bestmove": bestmove,
        "legal_move_shape": legal_move,
        "parent_exit_code": exit_code,
        "expected_detail_seen": expected_detail_seen,
        "unexpected_failure_seen": unexpected_failure_seen,
        "transcript": transcript,
        "passed": (
            legal_move and exit_code == 0 and expected_detail_seen
            and not unexpected_failure_seen
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    engine = args.engine.resolve()
    output = args.output.resolve()
    if not engine.is_file() or output.exists():
        print("BLOCKED: engine absent or output collision")
        return 2
    normal = probe(engine, False, args.timeout_seconds)
    crashed = probe(engine, True, args.timeout_seconds)
    evidence = {
        "schema": "eloi-caissa-worker-containment-v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine": str(engine),
        "engine_sha256": sha256(engine),
        "settings": {
            "threads_per_engine": 3,
            "normal_movetime_ms": 500,
            "crash_movetime_ms": 1000,
        },
        "normal": normal,
        "crashed_child": crashed,
        "passed": normal["passed"] and crashed["passed"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({
        "passed": evidence["passed"],
        "normal_bestmove": normal["bestmove"],
        "crash_fallback_bestmove": crashed["bestmove"],
        "output": str(output),
    }, indent=2))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
