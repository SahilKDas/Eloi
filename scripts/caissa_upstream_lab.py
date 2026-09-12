"""Audit an ignored, source-only upstream Caissa laboratory.

This tool never downloads, builds, packages, promotes, or modifies a donor.
It verifies caller-supplied source and an optional matching model, then writes
collision-safe evidence under ignored scratch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import validation_support

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data/caissa_upstream_releases.json"


class LabError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_release(manifest_path: Path, release: str) -> tuple[dict, dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "eloi-caissa-upstream-releases-v1":
        raise LabError("unsupported upstream manifest schema")
    try:
        row = manifest["releases"][release]
    except KeyError as error:
        raise LabError(f"release {release!r} is not pinned") from error
    return manifest, row


def git_output(source: Path, *arguments: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source), *arguments], text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except subprocess.CalledProcessError as error:
        raise LabError(f"source checkout is not auditable: {error.output.strip()}") from error


def source_inventory(source: Path, expected: dict) -> dict:
    if not source.is_dir():
        raise LabError(f"source checkout is absent: {source}")
    commit = git_output(source, "rev-parse", "HEAD")
    if commit != expected["source_commit"]:
        raise LabError("source commit does not match the pinned donor identity")
    if git_output(source, "status", "--porcelain"):
        raise LabError("source checkout has local modifications")
    files = git_output(source, "ls-files").splitlines()
    digest = hashlib.sha256()
    for relative in sorted(files):
        blob = git_output(source, "rev-parse", f"HEAD:{relative}")
        digest.update(relative.encode() + b"\0" + blob.encode("ascii") + b"\n")
    license_path = source / "LICENSE"
    if not license_path.is_file():
        raise LabError("source checkout has no LICENSE")
    license_hash = sha256_file(license_path)
    if license_hash != expected["source_license_sha256"]:
        raise LabError("source LICENSE hash mismatch")
    downloader_hits = []
    for relative in ("CMakeLists.txt", "src/makefile"):
        path = source / relative
        if path.is_file() and "Caissa-Nets" in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            downloader_hits.append(relative)
    return {
        "commit": commit,
        "tracked_file_count": len(files),
        "tracked_tree_manifest_sha256": digest.hexdigest().upper(),
        "license": expected["source_license"],
        "license_sha256": license_hash,
        "upstream_downloaders_detected": downloader_hits,
        "eloi_policy_allows_downloaders": False,
    }


def path_is_ignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", str(path)], cwd=ROOT, check=False
    )
    return result.returncode == 0


def model_inventory(path: Path | None, expected: dict) -> dict:
    if path is None:
        return {"present": False, "matching_identity": False,
                "redistributable": bool(expected["network_redistributable"]),
                "runnable": False, "reason": "matching model was not supplied"}
    path = path.resolve()
    if not path.is_file():
        raise LabError(f"model is absent: {path}")
    if path.is_relative_to(ROOT) and not path_is_ignored(path):
        raise LabError("a laboratory model inside the repository must be gitignored")
    if path.name != expected["required_network"]:
        raise LabError("model filename does not match the pinned evaluator generation")
    actual_hash = sha256_file(path)
    expected_hash = expected.get("network_sha256")
    matching = expected_hash is not None and actual_hash == expected_hash
    return {"present": True, "path": str(path), "sha256": actual_hash,
            "size": path.stat().st_size, "expected_sha256": expected_hash,
            "matching_identity": matching,
            "redistributable": bool(expected["network_redistributable"]),
            "runnable": matching,
            "reason": ("hash matches the pinned model identity" if matching else
                       "no matching model hash has been approved and pinned")}


def promotion_decision(manifest: dict, release: dict, evidence: dict) -> dict:
    gates = evidence.get("qualification_gates", {})
    all_gates = bool(gates) and all(value is True for value in gates.values())
    score = evidence.get("confirmation_score_percent")
    threshold = manifest["policy"]["promotion_score_percent_strictly_greater_than"]
    reasons = []
    if not release["network_redistributable"]:
        reasons.append("matching model lacks affirmative redistribution permission")
    if not evidence["model"]["matching_identity"]:
        reasons.append("matching model identity is not pinned")
    if not all_gates:
        reasons.append("qualification gates are incomplete")
    if score is None or score <= threshold:
        reasons.append(f"confirmation score must be greater than {threshold}%")
    return {"eligible": not reasons, "blocking_reasons": reasons}


def write_evidence(path: Path, evidence: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--release", default="1.26")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-runnable", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise LabError(f"refusing to overwrite evidence: {output}")
    validation_support.resource_snapshot(output.parent, projected=1_000_000)
    manifest, release = load_release(args.manifest.resolve(), args.release)
    source = source_inventory(args.source.resolve(), release)
    archive = None
    if args.source_archive:
        archive_path = args.source_archive.resolve()
        if not archive_path.is_file():
            raise LabError(f"source archive is absent: {archive_path}")
        archive = {"path": str(archive_path), "sha256": sha256_file(archive_path)}
        if archive["sha256"] != release["source_archive_sha256"]:
            raise LabError("source archive hash mismatch")
    model = model_inventory(args.model, release)
    if args.require_runnable and not model["runnable"]:
        raise LabError(model["reason"])
    evidence = {
        "schema": "eloi-caissa-upstream-lab-audit-v1", "release": args.release,
        "status": release["status"], "production_unchanged": True,
        "source": source, "source_archive": archive, "model": model,
        "qualification_gates": {
            "provenance_and_license": True,
            "matching_model_identity": model["matching_identity"],
            "adapter_parity": False,
            "deadline_stop_and_crash_containment": False,
            "official_fixed_node_comparison": False,
            "regressions_and_protocol_smoke": False,
            "mirrored_screening": False,
            "sealed_250ms_confirmation": False,
            "reproducible_packages": False,
        },
        "confirmation_score_percent": None,
    }
    evidence["promotion"] = promotion_decision(manifest, release, evidence)
    write_evidence(output, evidence)
    print(json.dumps(evidence["promotion"], sort_keys=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
