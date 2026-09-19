#!/usr/bin/env python3
"""Evaluate one already-frozen EPV2 model on the sealed test partition."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import train_eloi_policy_value_v2 as training
import verify_policy_value_parity_v2 as parity

PARTITION_RE = re.compile(r'"partition"\s*:\s*"(train|validation|test)"')


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes())
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--training-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = json.loads(args.training_manifest.read_text(encoding="utf-8"))
    model_hash = sha256(args.model)
    if manifest["status"] != "complete" or manifest["selected_epoch"] < 1:
        raise RuntimeError("checkpoint selection is not frozen")
    if manifest["model_sha256"] != model_hash:
        raise RuntimeError("model does not match the frozen training manifest")
    rows = []
    with args.dataset.open(encoding="utf-8") as stream:
        for line in stream:
            marker = PARTITION_RE.search(line)
            if marker and marker.group(1) == "test":
                rows.append(json.loads(line))
    if len(rows) != manifest["rows"]["test_sealed"]:
        raise RuntimeError("sealed test count does not match the frozen manifest")
    network = parity.load_python(args.model)
    metrics = training.evaluate(network, rows)
    report = {"schema": "eloi-epv2-sealed-test-v1", "status": "complete",
              "selection_was_frozen": True, "selected_epoch": manifest["selected_epoch"],
              "model_sha256": model_hash, "dataset_sha256": sha256(args.dataset),
              "rows": len(rows), "metrics": metrics,
              "selection_effect": "none; no retraining or checkpoint reselection permitted"}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
