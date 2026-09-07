#!/usr/bin/env python3
"""Fail-closed, preservation-safe preflight for Eloi v2.9.0 packages.

This module does not build or publish a release.  It proves that the exact
Caissa network may legally be redistributed and that a separately reviewed
technical policy says both package forms can use it without discovery or a
runtime download.  No scratch or output directory is created on failure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import caissa_license_gate
import validation_support


ROOT = Path(__file__).resolve().parents[1]
TARGET_VERSION = "2.9.0"
POLICY_SCHEMA = "eloi-v2.9.0-hybrid-package-policy-v1"
REQUIRED_FORMS = ("standalone", "exoskeleton")


class ReleasePreflightError(RuntimeError):
    """A release prerequisite is missing or inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleasePreflightError(message)


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()


def quota(
    total: int,
    training: int,
    scratch: int,
    free: int,
    projected: int = 0,
) -> None:
    require(total + projected <= 10_000_000_000,
            "total temporary quota would be exceeded")
    require(training <= min(8_000_000_000, 7 * 1024**3),
            "training quota would be exceeded")
    require(scratch + projected <= 2_000_000_000,
            "v2.9.0 release scratch quota would be exceeded")
    require(free - projected >= 5_000_000_000,
            "five-gigabyte free-space reserve would be breached")


def _inside(path: Path, parent: Path, label: str) -> Path:
    resolved = path.resolve()
    root = parent.resolve()
    require(resolved != root and resolved.is_relative_to(root),
            f"{label} must be a child of {root}")
    return resolved


def refuse_destination_collisions(scratch: Path, output: Path) -> tuple[Path, Path]:
    scratch = _inside(scratch, ROOT / "tmp", "scratch")
    output = _inside(output, ROOT / "dist", "output")
    require(not scratch.exists(), f"scratch collision: {scratch}")
    require(not output.exists(), f"output collision: {output}")
    return scratch, output


def deterministic_zip(
    folder: Path,
    target: Path,
    epoch: int,
    *,
    quota_guard=None,
) -> None:
    folder = Path(folder)
    target = Path(target)
    require(folder.is_dir(), f"package directory is absent: {folder}")
    require(not target.exists(), f"archive collision: {target}")
    paths = sorted(path for path in folder.rglob("*") if path.is_file())
    require(bool(paths), "refusing to archive an empty package")
    if quota_guard is not None:
        quota_guard(sum(path.stat().st_size for path in paths))
    stamp = dt.datetime.fromtimestamp(epoch, dt.timezone.utc).timetuple()[:6]
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in paths:
            require(not path.is_symlink(), "package symlink rejected")
            item = zipfile.ZipInfo(
                path.relative_to(folder).as_posix(), date_time=stamp
            )
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, path.read_bytes(), compresslevel=9)


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleasePreflightError(f"could not read {label}: {error}") from error
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def verify_technical_policy(path: Path, network_sha256: str) -> dict:
    path = path.resolve()
    policy = _read_json(path, "package policy")
    require(policy.get("schema") == POLICY_SCHEMA,
            f"package policy schema must be {POLICY_SCHEMA}")
    require(policy.get("target_version") == TARGET_VERSION,
            "package policy targets the wrong version")
    require(policy.get("status") == "ready",
            "hybrid package implementation is not marked ready")
    require(policy.get("network_sha256", "").upper() == network_sha256.upper(),
            "package policy refers to a different network")
    require(policy.get("network_delivery") == "embedded",
            "both package forms must carry the network inside their executable")
    require(policy.get("runtime_external_network_required") is False,
            "release executable still requires an external network path")
    require(policy.get("runtime_downloads") is False,
            "runtime network downloads are forbidden")
    require(policy.get("cmake_option") == "ELOI_ENABLE_CAISSA_PRODUCTION",
            "package policy names the wrong production integration option")
    require(policy.get("threads_per_brain") == 3,
            "release policy must preserve exactly three threads per brain")
    forms = policy.get("verified_package_forms")
    require(isinstance(forms, list) and sorted(forms) == sorted(REQUIRED_FORMS),
            "both standalone and exoskeleton must be technically verified")

    evidence_name = policy.get("implementation_evidence")
    evidence_sha = str(policy.get("implementation_evidence_sha256", "")).upper()
    require(isinstance(evidence_name, str) and evidence_name.strip(),
            "implementation evidence path is absent")
    require(re.fullmatch(r"[0-9A-F]{64}", evidence_sha) is not None,
            "implementation evidence SHA-256 is invalid")
    evidence_relative = Path(evidence_name)
    require(not evidence_relative.is_absolute() and ".." not in evidence_relative.parts,
            "implementation evidence must stay beside the package policy")
    evidence = (path.parent / evidence_relative).resolve()
    require(path.parent.resolve() in evidence.parents,
            "implementation evidence escapes the policy directory")
    require(evidence.is_file(), "implementation evidence is absent")
    require(sha256_file(evidence) == evidence_sha,
            "implementation evidence SHA-256 differs from policy")
    return {
        "schema": POLICY_SCHEMA,
        "status": "passed",
        "policy_path": str(path),
        "policy_sha256": sha256_file(path),
        "implementation_evidence": str(evidence),
        "implementation_evidence_sha256": evidence_sha,
        "network_sha256": network_sha256.upper(),
    }


def source_identity() -> dict:
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    version = re.search(r"project\(Eloi VERSION ([0-9.]+)", cmake)
    prerelease = re.search(r'set\(ELOI_PRERELEASE "([^"]*)"\)', cmake)
    require(version is not None and version.group(1) == TARGET_VERSION,
            "CMake product version is not stable 2.9.0")
    require(prerelease is not None and prerelease.group(1) == "",
            "ELOI_PRERELEASE must be empty")
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    require(not status.strip(), "release preflight requires a clean worktree")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None,
            "could not resolve source commit")
    return {"version": TARGET_VERSION, "source_commit": commit}


def preflight(
    manifest: Path,
    network: Path,
    policy: Path,
    scratch: Path,
    output: Path,
    projected_bytes: int,
) -> dict:
    require(0 <= projected_bytes <= 2_000_000_000,
            "projected bytes must be within the two-gigabyte scratch cap")
    scratch, output = refuse_destination_collisions(scratch, output)
    snapshot = validation_support.resource_snapshot(scratch, projected_bytes)
    quota(
        snapshot["total_bytes"], snapshot["training_bytes"],
        snapshot["scratch_bytes"], snapshot["free_bytes"], projected_bytes,
    )
    permissions = {
        mode: caissa_license_gate.verify_gate(manifest, network, mode)
        for mode in REQUIRED_FORMS
    }
    technical = verify_technical_policy(
        policy, permissions["standalone"]["network_sha256"]
    )
    source = source_identity()
    return {
        "schema": "eloi-v2.9.0-release-preflight-v1",
        "status": "passed",
        "source": source,
        "permissions": permissions,
        "technical_policy": technical,
        "resources": snapshot,
        "reserved_scratch": str(scratch),
        "reserved_output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--projected-bytes", type=int, default=2_000_000_000)
    args = parser.parse_args()
    try:
        result = preflight(
            args.manifest, args.network, args.policy, args.scratch,
            args.output, args.projected_bytes,
        )
    except (ReleasePreflightError, caissa_license_gate.LicenseGateError,
            ValueError) as error:
        print(f"BLOCKED: {error}")
        return 2

    scratch = Path(result["reserved_scratch"])
    scratch.mkdir(parents=True, exist_ok=False)
    evidence = scratch / "preflight.json"
    evidence.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
