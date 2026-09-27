#!/usr/bin/env python3
"""Run bounded repeated Eloi benchmarks and report median changes."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
from pathlib import Path


def run(executable: Path, depth: int) -> dict:
    completed = subprocess.run(
        [str(executable), "--bench", "--depth", str(depth)],
        cwd=executable.parent, check=True, timeout=90,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    line = next(row for row in completed.stdout.splitlines()
                if row.startswith("bench summary"))
    values = {key: int(value) for key, value in
              re.findall(r"(depth|nodes|time|nps)\s+(\d+)", line)}
    if values.get("depth") != depth:
        raise RuntimeError(f"unexpected benchmark summary: {line}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    rows = []
    summary = {}
    for depth in (1, 5, 10):
        for repetition in range(args.repetitions):
            for name, executable in (("baseline", args.baseline.resolve()),
                                     ("candidate", args.candidate.resolve())):
                rows.append({"name": name, "repetition": repetition,
                             **run(executable, depth)})
        medians = {}
        for name in ("baseline", "candidate"):
            selected = [row for row in rows
                        if row["name"] == name and row["depth"] == depth]
            medians[name] = {
                key: statistics.median(row[key] for row in selected)
                for key in ("nodes", "time", "nps")
            }
        summary[str(depth)] = {
            **medians,
            "nps_change_percent": 100.0 *
                (medians["candidate"]["nps"] / medians["baseline"]["nps"] - 1.0),
        }
    report = {"schema": "eloi-release-benchmark-comparison-v1",
              "repetitions": args.repetitions, "rows": rows,
              "summary": summary}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
