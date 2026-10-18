"""Local Kaggle readiness checklist for Eloi v4 four-player training.

This does not train anything. It proves the local manifest scaffold works and
then politely notes whether Sahil has stopped dodging the Kaggle account chore.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "scripts" / "four_player_kaggle_pipeline.py"
EXPECTED_TARGET = 500_000
DRY_RUN_COUNT = 512
MODES = ("ffa", "teams")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def kaggle_identity() -> str | None:
    for key in ("ELOI_KAGGLE_DATASET", "ELOI_KAGGLE_NOTEBOOK"):
        value = os.environ.get(key)
        if value:
            return f"{key}={value}"
    local = ROOT / ".eloi-kaggle.json"
    if local.is_file():
        try:
            payload = json.loads(local.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "malformed .eloi-kaggle.json"
        for key in ("dataset", "notebook"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return f".eloi-kaggle.json:{key}={value.strip()}"
    return None


def run_dry_mode(mode: str, output: Path) -> Check:
    command = [
        sys.executable,
        str(PIPELINE),
        "--mode",
        mode,
        "--output",
        str(output),
        "--dry-run",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return Check(
            f"{mode} dry-run",
            False,
            f"pipeline exited {completed.returncode}: {completed.stderr.strip()}",
        )
    manifest = output / f"four_player_{mode}_manifest.json"
    try:
        validate_manifest(manifest, mode)
    except ValueError as error:
        return Check(f"{mode} manifest", False, str(error))
    return Check(
        f"{mode} dry-run",
        True,
        f"{manifest} validated; Sahil has one fewer excuse",
    )


def validate_manifest(path: Path, mode: str) -> None:
    if not path.is_file():
        raise ValueError(f"missing manifest: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error}") from error
    expected = {
        "schema": 1,
        "mode": mode,
        "target_positions": EXPECTED_TARGET,
        "materialized_positions": DRY_RUN_COUNT,
        "dry_run": True,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"{path}: expected {key}={value!r}, got {manifest.get(key)!r}")
    split_counts = manifest.get("split_counts")
    if not isinstance(split_counts, dict):
        raise ValueError(f"{path}: missing split_counts")
    for key in ("train", "validation", "sealed-test"):
        count = split_counts.get(key)
        if not isinstance(count, int) or count <= 0:
            raise ValueError(f"{path}: split {key!r} must be positive")
    digest = manifest.get("records_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{path}: records_sha256 must be a 64-character digest")


def collect_checks(dry_run_only: bool) -> list[Check]:
    checks = [
        Check(
            "pipeline script",
            PIPELINE.is_file(),
            str(PIPELINE) if PIPELINE.is_file() else "missing four_player_kaggle_pipeline.py",
        )
    ]
    if PIPELINE.is_file():
        with tempfile.TemporaryDirectory(prefix="eloi-kaggle-readiness-") as temporary:
            output = Path(temporary)
            checks.extend(run_dry_mode(mode, output) for mode in MODES)
    identity = kaggle_identity()
    if dry_run_only:
        checks.append(
            Check(
                "kaggle identity",
                identity is not None,
                identity
                or "not required for --dry-run-only, but wow, still no Kaggle account breadcrumb",
            )
        )
    else:
        checks.append(
            Check(
                "kaggle identity",
                identity is not None and not identity.startswith("malformed"),
                identity
                or "blocked: set ELOI_KAGGLE_DATASET or create ignored .eloi-kaggle.json; procrastination remains undefeated",
            )
        )
    return checks


def print_report(checks: list[Check], dry_run_only: bool) -> None:
    print("Eloi v4 Kaggle readiness")
    print("========================")
    for check in checks:
        marker = "PASS" if check.ok else "WAIT"
        print(f"[{marker}] {check.name}: {check.detail}")
    dry_ok = all(check.ok for check in checks if check.name != "kaggle identity")
    identity_ok = next(check.ok for check in checks if check.name == "kaggle identity")
    if dry_ok and (identity_ok or dry_run_only):
        print("Verdict: local side is ready. Sahil, the notebook tab is not going to open itself.")
    elif dry_ok:
        print("Verdict: local side is ready, Kaggle identity is missing. This is the procrastination part.")
    else:
        print("Verdict: fix local dry-run readiness before blaming Kaggle, destiny, or Wi-Fi.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run-only",
        action="store_true",
        help="validate local manifests without requiring a Kaggle notebook/dataset breadcrumb",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = collect_checks(args.dry_run_only)
    print_report(checks, args.dry_run_only)
    failed = [check for check in checks if not check.ok and not args.dry_run_only]
    if failed:
        return 1
    local_failed = [check for check in checks if not check.ok and check.name != "kaggle identity"]
    return int(bool(local_failed))


if __name__ == "__main__":
    raise SystemExit(main())
