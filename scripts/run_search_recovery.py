#!/usr/bin/env python3
"""Fail-closed staged runner for the frozen search-first campaign.

Stages cannot skip earlier gates. A failed correctness gate never starts an
opponent, a match, or packaging. No training, installation, or publishing code
exists in this runner. Final openings are loaded only after confirmation passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import engine_lab as lab
import search_recovery as recovery

PROTOCOL = recovery.ROOT / "data/search_recovery_protocol.json"


def source_identity() -> str:
    paths = [recovery.ROOT / "CMakeLists.txt"]
    for directory in ("src", "include", "tests"):
        paths.extend(p for p in (recovery.ROOT / directory).rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(recovery.ROOT).as_posix().encode() + b"\0")
        # Ignore checkout newline conversion, not meaningful source bytes.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest().upper()


def require_report(path: pathlib.Path, candidate_hash: str, *, complete_only=False) -> dict:
    if not path.is_file():
        raise ValueError(f"required earlier gate is missing: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    identity = report.get("identity", {})
    bound_hash = identity.get("candidate_sha256", report.get("candidate", {}).get("sha256"))
    if bound_hash != candidate_hash:
        raise ValueError(f"earlier gate belongs to another executable: {path}")
    if identity.get("protocol_sha256") != lab.sha256(PROTOCOL):
        raise ValueError(f"earlier gate belongs to another protocol: {path}")
    if complete_only:
        if len(report.get("results", [])) != identity.get("games") or report.get("protocol_failures", 0):
            raise ValueError("development run is incomplete or had a protocol failure")
    elif not report.get("passed"):
        raise ValueError(f"earlier gate failed: {path}")
    return report


def correctness(candidate: pathlib.Path, test: pathlib.Path, directory: pathlib.Path) -> dict:
    report = {"schema": 1, "kind": "search-recovery-correctness", "started_utc": lab.utc_now(),
              "identity": {"candidate_sha256": lab.sha256(candidate),
                           "test_executable_sha256": lab.sha256(test),
                           "protocol_sha256": lab.sha256(PROTOCOL),
                           "weights_sha256": recovery.WEIGHTS,
                           "source_state_sha256": source_identity(),
                           "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                               cwd=recovery.ROOT, text=True).strip(),
                           "epd_sha256": lab.sha256(recovery.ROOT / "tests/epd/v2_5_regressions.epd")},
              "checks": [], "passed": False}
    checks = [
        ("unit-epd-see-tt-quiescence-simd", [str(test)]),
        ("perft-depth-4", [str(candidate), "--perft", "--depth", "4"]),
        ("differential-96-positions", [sys.executable, str(recovery.ROOT / "scripts/differential_movegen.py"),
                                     "--engine", str(candidate), "--samples", "32", "--output",
                                     str(directory / "differential.json")]),
    ]
    for name, command in checks:
        done = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=120)
        payload = (done.stdout + done.stderr).encode("utf-8")
        log = directory / f"{name}.txt"
        log.write_bytes(payload)
        report["checks"].append({"name": name, "exit_code": done.returncode, "command": command,
                                  "log": str(log.relative_to(recovery.ROOT)), "sha256": lab.sha256(log)})
        print(f"{name}: {'PASS' if done.returncode == 0 else 'FAIL'}", flush=True)
        print(done.stdout + done.stderr, flush=True)
        if done.returncode != 0:
            report["failed_gate"] = name
            report["later_gates_not_run"] = ["reproducibility", "performance", "development",
                                               "confirmation", "final", "installation", "packaging"]
            break
    else:
        report["passed"] = True
    report["finished_utc"] = lab.utc_now()
    lab.atomic_json(directory / "correctness.json", report)
    return report


def validate_protocol() -> dict:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["baseline_sha256"] != recovery.BASELINE or protocol["weights_sha256"] != recovery.WEIGHTS:
        raise ValueError("frozen baseline or NNUE identity changed")
    expected = {"games": 300, "movetime_ms": 250, "max_plies": 200,
                "gate_metric": "score", "required_score": 0.55, "required_points": 165,
                "sealed_until_confirmation_passes": True}
    if protocol["final"] != expected:
        raise ValueError("final protocol differs from the approved 300-game gate")
    for name, count in recovery.PARTITIONS:
        entry = protocol["partitions"][name]
        if entry["count"] != count or lab.sha256(recovery.ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError(f"frozen partition identity changed: {name}")
    return protocol


def run(stage: str, candidate: pathlib.Path, test: pathlib.Path | None, proof: pathlib.Path | None) -> dict:
    recovery.resource_check(projected=100_000_000)
    protocol = validate_protocol()
    decision_path = recovery.ROOT / "data/search_recovery_rejection.json"
    if stage != "correctness" and decision_path.is_file():
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if (decision.get("protocol_sha256") == lab.sha256(PROTOCOL) and
                decision.get("status") == "rejected_at_deterministic_correctness"):
            raise ValueError("this campaign is closed after its one repair failed; a new scope/protocol is required")
    baseline = recovery.SCRATCH / "baseline/Eloi.exe"
    if lab.sha256(baseline) != recovery.BASELINE:
        raise ValueError("official opponent hash mismatch")
    digest = lab.sha256(candidate)
    directory = recovery.SCRATCH / "runs" / digest.lower()[:16]
    directory.mkdir(parents=True, exist_ok=True)
    if stage == "correctness":
        if (directory / "correctness.json").exists():
            cached = json.loads((directory / "correctness.json").read_text())
            if cached["identity"]["candidate_sha256"] != digest:
                raise ValueError("candidate directory hash-prefix collision")
            return cached
        return correctness(candidate, test or candidate.parent / "eloi_tests.exe", directory)
    previous = require_report(directory / "correctness.json", digest)
    if previous["identity"]["source_state_sha256"] != source_identity():
        raise ValueError("current source differs from the correctness-tested source")
    if stage == "reproducibility":
        if proof is None:
            raise ValueError("reproducibility requires --proof from verify-reproducible.ps1")
        report = json.loads(proof.read_text(encoding="utf-8"))
        if not report.get("passed") or report.get("executable_sha256") != digest:
            raise ValueError("two-build proof does not match candidate")
        if report.get("build_a_sha256") != digest or report.get("build_b_sha256") != digest:
            raise ValueError("both independent builds must match the candidate")
        if report.get("weights_sha256") != recovery.WEIGHTS or not report.get("both_ctest_passed"):
            raise ValueError("reproducibility proof lacks frozen NNUE/correctness verification")
        if not report.get("build_a_path") or report.get("build_a_path") == report.get("build_b_path"):
            raise ValueError("reproducibility proof must identify two independent build paths")
        report["identity"] = {"candidate_sha256": digest, "protocol_sha256": lab.sha256(PROTOCOL)}
        recovery.immutable_write(directory / "reproducibility.json", recovery.encoded(report))
        return report
    require_report(directory / "reproducibility.json", digest)
    if stage == "performance":
        path = directory / "performance.json"
        if path.exists():
            return require_report(path, digest)
        report = lab.speed_gate(candidate, baseline, path, (1, 5, 10), 3, 1.0, 1.15)
        report["identity"] = {"candidate_sha256": digest, "protocol_sha256": lab.sha256(PROTOCOL)}
        lab.atomic_json(path, report)
        return report
    require_report(directory / "performance.json", digest)
    if stage in ("confirmation", "final"):
        require_report(directory / "development.json", digest, complete_only=True)
    if stage == "final":
        require_report(directory / "confirmation.json", digest)
    settings = protocol[stage]
    suite = recovery.ROOT / protocol["partitions"][stage]["path"]
    if stage in ("confirmation", "final"):
        # A campaign-wide seal prevents selecting another candidate after
        # seeing confirmation/final results. Resume of the same binary is OK.
        recovery.immutable_write(recovery.SCRATCH / f"{stage}-selection.json", recovery.encoded({
            "candidate_sha256": digest, "protocol_sha256": lab.sha256(PROTOCOL)}))
    report = lab.strength_gate(candidate, baseline, suite, directory / f"{stage}.json",
                               directory / f"{stage}.pgn", movetime_ms=settings.get("movetime_ms"),
                               nodes=settings.get("nodes_per_move"), games=settings["games"],
                               max_plies=settings["max_plies"], gate_metric="score",
                               required_score=settings.get("required_score", 0.5),
                               idle_priority=True, protocol_path=PROTOCOL)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("correctness", "reproducibility", "performance",
                                          "development", "confirmation", "final"))
    parser.add_argument("--candidate", type=pathlib.Path, required=True)
    parser.add_argument("--correctness-test", type=pathlib.Path)
    parser.add_argument("--proof", type=pathlib.Path)
    args = parser.parse_args()
    result = run(args.stage, args.candidate.resolve(), args.correctness_test.resolve() if args.correctness_test else None,
                 args.proof.resolve() if args.proof else None)
    print(json.dumps({k: v for k, v in result.items() if k not in ("results", "depths")}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
