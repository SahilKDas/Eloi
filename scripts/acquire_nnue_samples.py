#!/usr/bin/env python3
"""Acquire bounded, reproducible samples from official Lichess CC0 archives.

Only an exact byte prefix of each zstd archive is downloaded. The script
refuses a non-range response before reading its body, extracts a bounded number
of complete records, hashes every retained input, and deletes compressed
prefixes after validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFIX_BYTES = 16 * 1024 * 1024
SAMPLE_ROWS = 20_000
SOURCES = {
    "puzzles": {
        "url": "https://database.lichess.org/lichess_db_puzzle.csv.zst",
        "total_bytes": 304_384_407,
        "etag": '"6a6ef08b-12248997"',
        "last_modified": "Sun, 02 Aug 2026 07:23:55 GMT",
        "output": "lichess-puzzles-2026-08-02.csv",
        "kind": "csv",
    },
    "evaluations": {
        "url": "https://database.lichess.org/lichess_db_eval.jsonl.zst",
        "total_bytes": 21_681_515_630,
        "etag": '"6a6fbb7e-50c51ac6e"',
        "last_modified": "Sun, 02 Aug 2026 21:49:50 GMT",
        "output": "lichess-evaluations-2026-08-02.jsonl",
        "kind": "jsonl",
    },
}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def download_prefix(source: dict, target: pathlib.Path, prefix_bytes: int) -> dict:
    request = urllib.request.Request(
        source["url"],
        headers={
            "Range": f"bytes=0-{prefix_bytes - 1}",
            "User-Agent": "Eloi-NNUE-sampler/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        status = getattr(response, "status", response.getcode())
        content_range = response.headers.get("Content-Range", "")
        match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", content_range)
        if status != 206 or not match:
            raise RuntimeError(
                "server did not honor the bounded Range request; refusing body"
            )
        received_end = int(match.group(1))
        total_bytes = int(match.group(2))
        if received_end + 1 != prefix_bytes:
            raise RuntimeError(f"unexpected range length: {content_range}")
        if total_bytes != source["total_bytes"]:
            raise RuntimeError(
                f"upstream size changed: {total_bytes} != {source['total_bytes']}"
            )
        if response.headers.get("ETag") != source["etag"]:
            raise RuntimeError("upstream ETag changed; update provenance deliberately")
        if response.headers.get("Last-Modified") != source["last_modified"]:
            raise RuntimeError(
                "upstream Last-Modified changed; update provenance deliberately"
            )
        with target.open("wb") as output:
            remaining = prefix_bytes
            while remaining:
                chunk = response.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("bounded response ended early")
                output.write(chunk)
                remaining -= len(chunk)
            if response.read(1):
                raise RuntimeError("bounded response exceeded requested prefix")
    return {
        "content_range": content_range,
        "prefix_bytes": target.stat().st_size,
        "prefix_sha256": sha256(target),
    }


def find_zstd(explicit: str | None) -> str:
    candidates = [
        explicit,
        shutil.which("zstd"),
        r"C:\msys64\ucrt64\bin\zstd.exe",
    ]
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).is_file():
            return str(pathlib.Path(candidate).resolve())
    raise FileNotFoundError("zstd executable was not found")


def extract_records(
    zstd: str,
    prefix: pathlib.Path,
    output: pathlib.Path,
    kind: str,
    rows: int,
) -> None:
    process = subprocess.Popen(
        [zstd, "-dc", str(prefix)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    try:
        with output.open("wb") as target:
            if kind == "csv":
                header = process.stdout.readline()
                if not header.startswith(b"PuzzleId,FEN,Moves,"):
                    raise RuntimeError("unexpected puzzle CSV header")
                target.write(header)
            for index in range(rows):
                line = process.stdout.readline()
                if not line.endswith(b"\n"):
                    raise RuntimeError(
                        f"compressed prefix ended before record {index + 1}"
                    )
                target.write(line)
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def validate_sample(path: pathlib.Path, kind: str, rows: int) -> None:
    if kind == "csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            parsed = list(csv.DictReader(stream))
        if len(parsed) != rows:
            raise RuntimeError(f"puzzle sample has {len(parsed)} rows, expected {rows}")
        required = {"PuzzleId", "FEN", "Moves", "Themes"}
        if not required.issubset(parsed[0]):
            raise RuntimeError("puzzle sample is missing required columns")
    else:
        count = 0
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if "fen" not in row or "evals" not in row:
                    raise RuntimeError("evaluation sample is missing required fields")
                count += 1
        if count != rows:
            raise RuntimeError(f"evaluation sample has {count} rows, expected {rows}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=ROOT / ".deps" / "nnue-inputs",
    )
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--prefix-mib", type=int, default=16)
    parser.add_argument("--rows", type=int, default=SAMPLE_ROWS)
    parser.add_argument("--zstd")
    args = parser.parse_args()
    if not 1 <= args.prefix_mib <= 64:
        parser.error("--prefix-mib must be between 1 and 64")
    if not 12_000 <= args.rows <= 100_000:
        parser.error("--rows must be between 12000 and 100000")

    prefix_bytes = args.prefix_mib * 1024 * 1024
    zstd = find_zstd(args.zstd)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (
        args.manifest.resolve()
        if args.manifest
        else ROOT / "data" / "nnue_input_manifest.json"
    )
    documents = {}
    for name, source in SOURCES.items():
        prefix = output_dir / f".{name}.prefix.zst"
        output = output_dir / source["output"]
        try:
            range_document = download_prefix(source, prefix, prefix_bytes)
            extract_records(zstd, prefix, output, source["kind"], args.rows)
            validate_sample(output, source["kind"], args.rows)
            documents[name] = {
                "license": "CC0 1.0",
                "source_url": source["url"],
                "upstream_total_bytes": source["total_bytes"],
                "upstream_etag": source["etag"],
                "upstream_last_modified": source["last_modified"],
                **range_document,
                "sample_method": "first complete records from exact zstd byte prefix",
                "sample_rows": args.rows,
                "sample_filename": source["output"],
                "sample_bytes": output.stat().st_size,
                "sample_sha256": sha256(output),
            }
        finally:
            prefix.unlink(missing_ok=True)

    manifest = {
        "schema": 1,
        "acquisition_script": "scripts/acquire_nnue_samples.py",
        "prefix_limit_bytes_per_source": prefix_bytes,
        "retained_inputs": documents,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
