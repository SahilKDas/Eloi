#!/usr/bin/env python3
"""Audit EPV2 train/validation rows without parsing the sealed test rows."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess

PARTITION_RE = re.compile(r'"partition"\s*:\s*"(train|validation|test)"')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    identities = {"train": set(), "validation": set()}
    groups = {"train": set(), "validation": set()}
    failures: list[dict] = []

    with args.dataset.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            marker = PARTITION_RE.search(line)
            if marker is None:
                failures.append({"line": line_number, "reason": "partition marker"})
                continue
            partition = marker.group(1)
            counts[partition] += 1
            if partition == "test":
                continue

            row = json.loads(line)
            if row.get("partition") != partition:
                failures.append({"line": line_number, "reason": "partition mismatch"})
                continue
            identity = row["canonical_key"]
            if identity in identities[partition]:
                failures.append({"line": line_number, "reason": "duplicate canonical key"})
            identities[partition].add(identity)
            groups[partition].add(row["group_id"])
            categories[f"{partition}:{row.get('primary_category', 'broad')}"] += 1

            board = chess.Board(row["fen"])
            legal = {move.uci() for move in board.legal_moves}
            policy = row["policy"]
            policy_moves = {entry["move"] for entry in policy}
            if not policy_moves or not policy_moves <= legal:
                failures.append({"line": line_number, "reason": "illegal policy move"})
            if abs(sum(float(entry["probability"]) for entry in policy) - 1.0) > 1e-5:
                failures.append({"line": line_number, "reason": "policy normalization"})
            if set(row["value_wdl"]) != {"win", "draw", "loss"}:
                failures.append({"line": line_number, "reason": "value keys"})
            if abs(sum(float(value) for value in row["value_wdl"].values()) - 1.0) > 1e-5:
                failures.append({"line": line_number, "reason": "value normalization"})

    overlap = {
        "canonical_keys": len(identities["train"] & identities["validation"]),
        "groups": len(groups["train"] & groups["validation"]),
    }
    expected = {"train": 120000, "validation": 15000, "test": 15000}
    passed = dict(counts) == expected and not failures and not any(overlap.values())
    report = {
        "schema": "eloi-epv2-dataset-audit-v1",
        "passed": passed,
        "dataset_sha256": sha256(args.dataset),
        "counts": dict(counts),
        "expected_counts": expected,
        "category_counts": dict(sorted(categories.items())),
        "partition_overlap": overlap,
        "failures": failures[:100],
        "failure_count": len(failures),
        "sealed_test_handling": "partition marker counted; row skipped before JSON parsing",
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
