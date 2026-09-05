#!/usr/bin/env python3
"""Machine-readable Caissa network redistribution gate utilities.

The gate records the exact network identity and explicit redistribution permission
evidence required before Caissa-enabled release packaging.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GATE_SCHEMA = "eloi-caissa-license-gate-v1"
DEFAULT_NETWORK = ROOT / ".deps" / "caissa" / "eval-82-383B.pnn"
DEFAULT_GATE = ROOT / ".deps" / "caissa" / "caissa-license-gate-v1.json"
TEMPLATE_GATE = ROOT / "third_party" / "caissa" / "caissa-license-gate-template.v1.json"
REQUIRED_SCOPE = {"binary", "zip"}


class GateError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise GateError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_gate(path: Path) -> dict:
    require(path.is_file(), f"Caissa license gate missing: {path}")
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    require(isinstance(payload, dict), f"Gate is not an object: {path}")
    require(
        payload.get("schema") == GATE_SCHEMA,
        f"Unexpected gate schema in {path}: {payload.get('schema')}",
    )
    return payload


def require_scopes(granted: list[str], required: set[str], path: Path) -> None:
    require(
        isinstance(granted, list),
        f"Gate scope is not a list: {path}",
    )
    granted_set = set(granted)
    require(
        required <= granted_set,
        f"Gate scope {sorted(granted_set)} in {path} does not include required terms: "
        f"{sorted(required)}",
    )


def default_gate_path() -> Path:
    if DEFAULT_GATE.is_file():
        return DEFAULT_GATE
    if TEMPLATE_GATE.is_file():
        return TEMPLATE_GATE
    return DEFAULT_GATE


def validate_gate(
    network_path: Path,
    expected_sha256: str,
    expected_bytes: int,
    gate_path: Path = DEFAULT_GATE,
    required_scope: set[str] | None = None,
) -> dict:
    required_scope = REQUIRED_SCOPE if required_scope is None else set(required_scope)
    gate = load_gate(gate_path)

    require(network_path.is_file(), f"Caissa network file is absent: {network_path}")
    require(
        network_path.stat().st_size == expected_bytes,
        "Caissa network size does not match the frozen identity",
    )
    require(
        sha256_file(network_path) == expected_sha256.upper(),
        "Caissa network SHA-256 does not match the frozen identity",
    )

    network_gate = gate.get("network")
    require(
        isinstance(network_gate, dict),
        f"Missing network section in {gate_path}",
    )
    require(
        network_gate.get("sha256", "").upper() == expected_sha256.upper(),
        "Gate network SHA-256 does not match expected frozen identity",
    )
    require(
        int(network_gate.get("bytes", -1)) == expected_bytes,
        "Gate network byte-size does not match expected frozen identity",
    )
    require(
        isinstance(network_gate.get("source"), str) and network_gate["source"].strip(),
        f"Gate missing network source attribution: {gate_path}",
    )

    permission = gate.get("permission")
    require(
        isinstance(permission, dict),
        f"Missing permission section in {gate_path}",
    )
    require(
        bool(permission.get("granted")),
        "Permission is not currently granted in gate file",
    )
    require(
        isinstance(permission.get("scope"), list),
        f"Permission scope missing in {gate_path}",
    )
    require_scopes(permission.get("scope", []), required_scope, gate_path)
    require(
        isinstance(permission.get("source"), str) and permission["source"].strip(),
        f"Permission source is missing in {gate_path}",
    )

    evidence = permission.get("evidence")
    require(
        isinstance(evidence, dict),
        f"Permission evidence section missing in {gate_path}",
    )
    evidence_path = evidence.get("path")
    require(
        isinstance(evidence_path, str) and evidence_path.strip(),
        f"Permission evidence path missing in {gate_path}",
    )
    evidence_path = (Path(evidence_path) if os.path.isabs(evidence_path)
                     else gate_path.parent / evidence_path).resolve()
    require(evidence_path.is_file(), f"Permission evidence file is absent: {evidence_path}")
    expected_evidence = evidence.get("sha256")
    require(
        isinstance(expected_evidence, str) and expected_evidence.strip(),
        f"Permission evidence SHA-256 missing in {gate_path}",
    )
    require(
        sha256_file(evidence_path) == expected_evidence.upper(),
        "Permission evidence SHA-256 mismatch",
    )
    require(
        isinstance(evidence.get("granted_text"), str) and evidence["granted_text"].strip(),
        f"Permission evidence text summary is missing in {gate_path}",
    )

    return {
        "network_identity": {
            "path": str(network_path),
            "sha256": expected_sha256.upper(),
            "bytes": expected_bytes,
            "source": network_gate.get("source"),
        },
        "permission": {
            "source": permission["source"],
            "scope": permission["scope"],
            "evidence_sha256": expected_evidence.upper(),
            "evidence_path": str(evidence_path),
            "granted_text": evidence["granted_text"],
        },
        "gate": str(gate_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--gate", type=Path, default=None)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--bytes", type=int, required=True)
    parser.add_argument(
        "--require-scope",
        action="append",
        default=["binary", "zip"],
        help="Required permission scopes (repeat as needed)",
    )
    args = parser.parse_args()

    gate_path = args.gate if args.gate is not None else default_gate_path()

    try:
        result = validate_gate(
            network_path=args.network.resolve(),
            expected_sha256=args.sha256,
            expected_bytes=args.bytes,
            gate_path=gate_path.resolve(),
            required_scope=set(args.require_scope),
        )
    except GateError as error:
        print(f"Caissa license gate blocked release: {error}")
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
