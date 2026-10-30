"""Bounded offline v4.0.0/v4.0.1 Teams equivalence and timing evidence (not a gauntlet)."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import queue
import re
import statistics
import subprocess
import threading
import time


class Engine:
    def __init__(self, path):
        flags = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
        self.process = subprocess.Popen([str(path), "--four-player-uci"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", creationflags=flags)
        self.lines = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.lines.put(line.strip())
            self.lines.put(None)
        threading.Thread(target=read, daemon=True).start()
        self.send("uci")
        self.until("uciok")

    def send(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def until(self, prefix):
        deadline = time.monotonic() + 8
        result = []
        while True:
            line = self.lines.get(timeout=max(0.001, deadline - time.monotonic()))
            if line is None:
                raise RuntimeError("Engine stopped unexpectedly")
            result.append(line)
            if line.startswith(prefix):
                return result

    def search(self, moves, command):
        self.send("position startpos" + (" moves " + " ".join(moves) if moves else ""))
        self.send(command)
        started = time.monotonic()
        lines = self.until("bestmove ")
        wall_ms = (time.monotonic() - started) * 1000
        info = next(line for line in lines if line.startswith("info depth "))
        m = re.fullmatch(r"info depth (\d+) score cp (-?\d+) nodes (\d+) time (\d+) string emergency (true|false)", info)
        if not m:
            raise RuntimeError("Unexpected Teams search report")
        return dict(depth=int(m[1]), score=int(m[2]), nodes=int(m[3]), time_ms=int(m[4]),
                    emergency=m[5] == "true", bestmove=lines[-1].split()[1], wall_ms=wall_ms)

    def close(self):
        if self.process.poll() is None:
            self.send("quit")
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()  # Only this explicitly owned offline fixture.
                self.process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=pathlib.Path, required=True)
    parser.add_argument("--candidate", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite prior evidence")
    baseline = Engine(args.baseline.resolve(strict=True))
    candidate = Engine(args.candidate.resolve(strict=True))
    evidence = {"baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
                "fixed": [], "timing": [], "passed": False}
    try:
        moves = []
        for ply in range(8):
            for command in ["go depth 1 movetime 2000", "go nodes 2500 movetime 2000"]:
                a = baseline.search(moves, command)
                b = candidate.search(moves, command)
                evidence["fixed"].append({"moves": list(moves), "command": command, "baseline": a, "candidate": b})
                for field in ("bestmove", "score", "depth", "nodes", "emergency"):
                    if a[field] != b[field]:
                        raise RuntimeError(f"Fixed-work difference at ply {ply}: {field}")
            moves.append(a["bestmove"])
        for budget in (250, 500, 1000):
            for repeat in range(3):
                pair = {}
                order = [("baseline", baseline), ("candidate", candidate)]
                if repeat % 2:
                    order.reverse()
                for name, engine in order:
                    result = engine.search(moves[:4], f"go movetime {budget}")
                    if result["wall_ms"] > budget + 150 or result["emergency"]:
                        raise RuntimeError(f"Deadline/emergency regression: {name}")
                    pair[name] = result
                evidence["timing"].append({"budget_ms": budget, **pair})
        for budget in (250, 500, 1000):
            rows = [r for r in evidence["timing"] if r["budget_ms"] == budget]
            a = statistics.median(r["baseline"]["depth"] for r in rows)
            b = statistics.median(r["candidate"]["depth"] for r in rows)
            if b < a:
                raise RuntimeError(f"Median completed depth regressed at {budget}ms")
        evidence["passed"] = True
    finally:
        baseline.close()
        candidate.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"16 fixed-work comparisons and 9 paired timing checks passed: {args.output}")


if __name__ == "__main__":
    main()
