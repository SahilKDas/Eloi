#!/usr/bin/env python3
"""Freeze the search-recovery protocol and acquire the exact published opponent.

No NNUE training, installation, publishing, or package generation is performed.
Generated inputs are immutable: a different existing file causes a hard error.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "tmp" / "search-recovery"
WEIGHTS = "CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E"
BASELINE = "5F13AB2FEB05DE4171DB39E637FD1322409211872DEBB72AD7BEF88858B5AACF"
ZIP_HASH = "C4F1A19657174D16458323A8650274EA7A4E4FD0C6CBF9D444AAE4605BFE7DE9"
ZIP_URL = ("https://github.com/SahilKDas/Eloi/releases/download/v2.0.0/"
           "Eloi-v1.9.6-rc.1-windows-x64-standalone.zip")
PARTITIONS = (("diagnostic", 20), ("development", 30), ("confirmation", 30),
              ("final", 150), ("reserve", 270))
SEED = b"eloi-search-recovery-v1\0"
SCRATCH_CAP = 2_000_000_000
TOTAL_CAP = 10_000_000_000


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def encoded(document: object) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def immutable_write(path: pathlib.Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to replace frozen artifact: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def directory_bytes(path: pathlib.Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def resource_check(projected: int = 0) -> dict:
    """Conservatively count all dependencies, including pinned non-temporary ones."""
    roots = [ROOT / ".deps", ROOT / "tmp", ROOT / "dist", ROOT / "build"]
    roots += sorted(ROOT.glob("build-*"))
    usage = {str(p.relative_to(ROOT)): directory_bytes(p) for p in roots}
    scratch = directory_bytes(SCRATCH)
    total = sum(usage.values())
    free = shutil.disk_usage(ROOT).free
    if projected < 0 or scratch + projected > SCRATCH_CAP:
        raise ValueError("projected recovery scratch exceeds the 2 GB cap")
    if total + projected > TOTAL_CAP:
        raise ValueError("projected total temporary usage exceeds the 10 GB cap")
    if free < projected + 5_000_000_000:
        raise ValueError("insufficient free disk after the 5 GB safety reserve")
    if sha256(ROOT / "include/eloi/nnue_weights.hpp") != WEIGHTS:
        raise ValueError("production NNUE is not the frozen network")
    return {"conservative_usage_by_directory": usage, "total_bytes": total,
            "recovery_scratch_bytes": scratch, "projected_additional_bytes": projected,
            "scratch_cap_bytes": SCRATCH_CAP, "total_cap_bytes": TOTAL_CAP,
            "free_bytes": free, "weights_sha256": WEIGHTS}


def partition_openings(suite: dict) -> dict[str, dict]:
    rows = suite["positions"]
    if len(rows) != 500 or len({r["fen"] for r in rows}) != 500:
        raise ValueError("expected exactly 500 unique existing opening FENs")
    ordered = sorted(rows, key=lambda row: (
        hashlib.sha256(SEED + row["fen"].encode("utf-8")).digest(), row["fen"]))
    result = {}
    offset = 0
    for name, count in PARTITIONS:
        selected = ordered[offset:offset + count]
        result[name] = {"schema": 1, "name": f"Search recovery {name}",
                        "partition": name, "count": count,
                        "positions": selected}
        offset += count
    return result


def prepare(acquire: bool) -> dict:
    resources = resource_check(projected=1_000_000_000)
    suite_path = ROOT / "data/strength_openings.json"
    partitions = partition_openings(json.loads(suite_path.read_text(encoding="utf-8")))
    partition_hashes = {}
    for name, document in partitions.items():
        path = ROOT / f"data/search_recovery/{name}.json"
        payload = encoded(document)
        immutable_write(path, payload)
        partition_hashes[name] = {"path": path.relative_to(ROOT).as_posix(),
                                   "count": document["count"],
                                   "sha256": hashlib.sha256(payload).hexdigest().upper()}
    protocol = {
        "schema": 1, "name": "eloi-search-recovery-v1",
        "baseline_release": "v2.0.0", "baseline_sha256": BASELINE,
        "weights_sha256": WEIGHTS, "source_suite_sha256": sha256(suite_path),
        "ordering": "SHA256(UTF8(eloi-search-recovery-v1) + NUL + UTF8(FEN)); FEN tie-break",
        "partitions": partition_hashes,
        "engine": {"threads": 3, "hash_mb": 32, "own_book": False,
                   "noise_millipawns": 0, "parallel_mode": "RootSplit",
                   "move_overhead_ms": 0, "priority": "Windows Idle"},
        "development": {"games": 60, "nodes_per_move": 10000, "max_plies": 200,
                        "purpose": "development-only; not a strength claim"},
        "confirmation": {"games": 60, "nodes_per_move": 10000, "max_plies": 200,
                         "gate_metric": "score", "required_score": 0.52,
                         "attempts_per_selected_candidate": 1},
        "final": {"games": 300, "movetime_ms": 250, "max_plies": 200,
                  "gate_metric": "score", "required_score": 0.55,
                  "required_points": 165, "sealed_until_confirmation_passes": True},
        "performance": {"depths": [1, 5, 10], "samples": 3,
                        "maximum_time_ratio_depth_5_10": 1.15},
        "correctness": "all unit/EPD/SEE/TT/quiescence/perft/differential/SIMD gates",
        "reproducibility": "two clean builds; exact executable equality",
        "amendments_after_first_game": "forbidden; interruption may resume identical protocol",
        "maximum_evidence_selected_repairs": 1,
        "allowed_repair_classes": ["TT divergence", "selectivity divergence", "budget/ordering divergence"],
        "release": {"if_passed": "2.5.0-rc.2", "if_failed": "no package; retain v2.0 champion",
                    "push_or_publish": False},
        "scratch_cap_bytes": SCRATCH_CAP, "total_temporary_cap_bytes": TOTAL_CAP,
    }
    immutable_write(ROOT / "data/search_recovery_protocol.json", encoded(protocol))
    if acquire:
        destination = SCRATCH / "baseline/Eloi.exe"
        if destination.exists():
            if sha256(destination) != BASELINE:
                raise ValueError("existing baseline does not match the official hash")
        else:
            request = urllib.request.Request(ZIP_URL, headers={"User-Agent": "Eloi-search-recovery/1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = response.read(16_000_001)
            if len(payload) > 16_000_000 or hashlib.sha256(payload).hexdigest().upper() != ZIP_HASH:
                raise ValueError("official release ZIP failed size/hash verification")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = {i.filename for i in archive.infolist() if not i.is_dir()}
                if names != {"Eloi.exe", "config.yml"}:
                    raise ValueError(f"unexpected standalone ZIP members: {sorted(names)}")
                info = archive.getinfo("Eloi.exe")
                if info.file_size > 32_000_000:
                    raise ValueError("unexpected executable size")
                binary = archive.read(info)
            if hashlib.sha256(binary).hexdigest().upper() != BASELINE:
                raise ValueError("downloaded executable differs from the required published v2.0.0 hash")
            immutable_write(destination, binary)
        immutable_write(SCRATCH / "baseline/identity.json", encoded({
            "release": "v2.0.0", "url": ZIP_URL, "zip_sha256": ZIP_HASH,
            "executable_sha256": BASELINE,
            "note": "The v2.0.0 release assets retain the historical v1.9.6-rc.1 filenames."}))
    baseline_source = ROOT / "build-release/Eloi.exe"
    if baseline_source.exists():
        captured = SCRATCH / "pre-recovery/Eloi.exe"
        immutable_write(captured, baseline_source.read_bytes())
    return {"resources": resources, "protocol_sha256": sha256(ROOT / "data/search_recovery_protocol.json"),
            "baseline_acquired": acquire, "partitions": partition_hashes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preflight"))
    parser.add_argument("--acquire-baseline", action="store_true")
    args = parser.parse_args()
    report = prepare(args.acquire_baseline) if args.command == "prepare" else resource_check()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
