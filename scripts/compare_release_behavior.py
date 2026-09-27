#!/usr/bin/env python3
"""Compare deterministic fixed-depth Eloi behavior across two executables."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import validation_support


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def collect(executable: Path, scratch: Path, label: str) -> list[dict]:
    rows = []
    for case in validation_support.epd_cases():
        output = scratch / f"{label}-{case['id']}.json"
        subprocess.run(
            [str(executable), "--diagnose-search", "--fen", case["fen"],
             "--depth", str(case["depth"]), "--profile", "production",
             "--json", str(output)],
            cwd=executable.parent, check=True, timeout=30,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        trace = json.loads(output.read_text(encoding="utf-8"))
        if not trace.get("completed"):
            raise RuntimeError(f"{label}/{case['id']} did not complete")
        final = trace["final_result"]
        rows.append({
            "id": case["id"], "depth": final["depth"],
            "move": final["selected_move"], "score_cp": final["score_cp"],
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    baseline = args.baseline.resolve()
    candidate = args.candidate.resolve()
    with tempfile.TemporaryDirectory(prefix="eloi-behavior-") as temporary:
        scratch = Path(temporary)
        old = collect(baseline, scratch, "baseline")
        new = collect(candidate, scratch, "candidate")
    differences = [
        {"baseline": before, "candidate": after}
        for before, after in zip(old, new, strict=True)
        if before != after
    ]
    report = {
        "schema": "eloi-release-behavior-comparison-v1",
        "baseline": {"path": str(baseline), "sha256": sha256(baseline)},
        "candidate": {"path": str(candidate), "sha256": sha256(candidate)},
        "positions": len(old), "differences": differences,
        "passed": not differences,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
