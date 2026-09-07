"""Fail-closed redistribution gate for a Caissa neural-network artifact.

Local development and parity diagnostics do not need this gate. Any v2.9.0 build
or package that redistributes a Caissa network must call :func:`verify_gate`
before staging bytes. The manifest deliberately carries the artifact identity
instead of hard-coding one network, so a technically validated replacement can
be licensed and pinned without weakening the checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "eloi-caissa-network-permission-v1"
ARTIFACT_MODES = {"standalone", "exoskeleton"}
REQUIRED_RIGHTS = (
    "redistribute_unmodified",
    "embed_in_executable",
    "include_in_archive",
    "commercial_distribution",
)
PLACEHOLDERS = ("todo", "replace-me", "placeholder", "example.invalid")


class LicenseGateError(RuntimeError):
    """A redistribution prerequisite is absent, inconsistent, or unverified."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LicenseGateError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LicenseGateError(f"{label} must be non-empty text")
    result = value.strip()
    lowered = result.lower()
    if any(marker in lowered for marker in PLACEHOLDERS):
        raise LicenseGateError(f"{label} still contains a placeholder")
    return result


def _sha(value: Any, label: str) -> str:
    result = _text(value, label).upper()
    if len(result) != 64 or any(
        character not in "0123456789ABCDEF" for character in result
    ):
        raise LicenseGateError(f"{label} must be a SHA-256 hex digest")
    return result


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LicenseGateError(
            f"could not read permission manifest: {error}"
        ) from error
    return _object(manifest, "manifest")


def verify_gate(
    manifest_path: Path, network_path: Path, artifact_mode: str
) -> dict[str, Any]:
    if artifact_mode not in ARTIFACT_MODES:
        raise LicenseGateError(f"unknown artifact mode: {artifact_mode}")
    manifest_path = manifest_path.resolve()
    network_path = network_path.resolve()
    manifest = load_manifest(manifest_path)
    if manifest.get("schema") != SCHEMA:
        raise LicenseGateError(f"manifest schema must be {SCHEMA}")

    network = _object(manifest.get("network"), "network")
    network_id = _text(network.get("id"), "network.id")
    _text(network.get("source_url"), "network.source_url")
    expected_name = _text(network.get("filename"), "network.filename")
    expected_sha = _sha(network.get("sha256"), "network.sha256")
    expected_size = network.get("bytes")
    if not isinstance(expected_size, int) or expected_size <= 0:
        raise LicenseGateError("network.bytes must be a positive integer")
    if network_path.name != expected_name:
        raise LicenseGateError(
            "network filename differs from the permission manifest"
        )
    if not network_path.is_file():
        raise LicenseGateError(f"network is absent: {network_path}")
    if network_path.stat().st_size != expected_size:
        raise LicenseGateError(
            "network size differs from the permission manifest"
        )
    actual_network_sha = sha256_file(network_path)
    if actual_network_sha != expected_sha:
        raise LicenseGateError(
            "network SHA-256 differs from the permission manifest"
        )

    permission = _object(manifest.get("permission"), "permission")
    if permission.get("granted") is not True:
        raise LicenseGateError(
            "network redistribution permission is not explicitly granted"
        )
    _text(permission.get("grantor"), "permission.grantor")
    _text(permission.get("source_url"), "permission.source_url")
    _text(permission.get("summary"), "permission.summary")
    rights = _object(permission.get("rights"), "permission.rights")
    for right in REQUIRED_RIGHTS:
        if rights.get(right) is not True:
            raise LicenseGateError(
                f"required permission is absent: {right}"
            )
    modes = permission.get("artifact_modes")
    if not isinstance(modes, list) or artifact_mode not in modes:
        raise LicenseGateError(
            f"permission does not cover {artifact_mode} artifacts"
        )

    evidence_value = _text(
        permission.get("evidence_path"), "permission.evidence_path"
    )
    evidence_path = Path(evidence_value)
    if evidence_path.is_absolute():
        raise LicenseGateError(
            "permission.evidence_path must be relative to the manifest"
        )
    evidence_path = (manifest_path.parent / evidence_path).resolve()
    if manifest_path.parent.resolve() not in evidence_path.parents:
        raise LicenseGateError(
            "permission evidence escapes the manifest directory"
        )
    if not evidence_path.is_file():
        raise LicenseGateError(
            f"permission evidence is absent: {evidence_path}"
        )
    expected_evidence_sha = _sha(
        permission.get("evidence_sha256"),
        "permission.evidence_sha256",
    )
    actual_evidence_sha = sha256_file(evidence_path)
    if actual_evidence_sha != expected_evidence_sha:
        raise LicenseGateError(
            "permission evidence SHA-256 differs from the manifest"
        )

    return {
        "schema": SCHEMA,
        "status": "passed",
        "artifact_mode": artifact_mode,
        "network_id": network_id,
        "network_path": str(network_path),
        "network_bytes": expected_size,
        "network_sha256": actual_network_sha,
        "permission_manifest": str(manifest_path),
        "permission_manifest_sha256": sha256_file(manifest_path),
        "permission_evidence": str(evidence_path),
        "permission_evidence_sha256": actual_evidence_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument(
        "--artifact-mode", required=True, choices=sorted(ARTIFACT_MODES)
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify_gate(
            args.manifest, args.network, args.artifact_mode
        )
    except LicenseGateError as error:
        print(f"BLOCKED: {error}")
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists():
            print(f"BLOCKED: refusing to overwrite output: {args.output}")
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            rendered, encoding="utf-8", newline="\n"
        )
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
