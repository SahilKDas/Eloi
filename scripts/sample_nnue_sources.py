#!/usr/bin/env python3
"""Acquire broader bounded NNUE samples without retaining full archives.

Each pinned Lichess source is processed sequentially. The program downloads one
declared zstd prefix, scans complete records throughout the traversed portion,
keeps a deterministic priority-plus-coverage reservoir, removes the compressed
prefix, and emits analysis-only canonical inputs and a manifest. It never
trains or installs an NNUE.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import pathlib
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import acquire_nnue_samples as acquisition
import analyze_nnue_dataset as analysis


DEFAULT_PREFIX_MIB = 128
DEFAULT_RECORD_LIMIT = 250_000
DEFAULT_RETAINED_LIMIT = 100_000
DEFAULT_OUTPUT_LIMIT_MIB = 512


@dataclass
class PriorityReservoir:
    limit: int
    seed: str
    heap: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    coverage: dict[str, tuple[int, dict[str, Any]]] = field(default_factory=dict)

    def add(self, record: dict[str, Any]) -> None:
        record_id = record["record_id"]
        priority = int(
            analysis.stable_hash(self.seed, "population", record_id), 16
        )
        item = (-priority, record_id, record)
        if len(self.heap) < self.limit:
            heapq.heappush(self.heap, item)
        elif priority < -self.heap[0][0]:
            heapq.heapreplace(self.heap, item)
        stratum = record["stratum"]
        coverage_priority = int(
            analysis.stable_hash(
                self.seed, "coverage", stratum, record_id
            ),
            16,
        )
        previous = self.coverage.get(stratum)
        if previous is None or coverage_priority < previous[0]:
            self.coverage[stratum] = (coverage_priority, record)

    def finalize(self) -> list[dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {
            item[2]["record_id"]: item[2] for item in self.heap
        }
        for _, record in self.coverage.values():
            candidates[record["record_id"]] = record
        return analysis.deterministic_select(
            list(candidates.values()), self.limit, self.seed
        )


@dataclass
class ScanResult:
    records: list[dict[str, Any]]
    seen: int
    accepted: int
    duplicate_positions: int
    rejected: Counter[str]
    stopped_at_record_limit: bool
    complete_lines: int


def ensure_peak_budget(
    baseline_total: int,
    baseline_nnue: int,
    prefix_bytes: int,
    output_limit_bytes: int,
) -> None:
    projected = prefix_bytes + output_limit_bytes
    if baseline_total + projected > analysis.TOTAL_TEMP_LIMIT_BYTES:
        raise RuntimeError("bounded acquisition could exceed the 10 GB total cap")
    if baseline_nnue + projected > analysis.NNUE_TEMP_LIMIT_BYTES:
        raise RuntimeError("bounded acquisition could exceed the 8 GB training cap")
    if baseline_nnue + projected > analysis.STRICT_NNUE_LIMIT_BYTES:
        raise RuntimeError(
            "bounded acquisition could exceed the current stricter 7 GiB cap"
        )


def finish_process(process: subprocess.Popen) -> None:
    assert process.stdout is not None
    process.stdout.close()
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def scan_evaluations(
    zstd: str,
    prefix: pathlib.Path,
    record_limit: int,
    retained_limit: int,
    seed: str,
) -> ScanResult:
    process = subprocess.Popen(
        [zstd, "-dc", str(prefix)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    reservoir = PriorityReservoir(retained_limit, seed + "/evaluations")
    rejected: Counter[str] = Counter()
    seen_positions: set[str] = set()
    seen = accepted = duplicates = complete_lines = 0
    stopped = False
    try:
        while seen < record_limit:
            raw = process.stdout.readline()
            if not raw:
                break
            if not raw.endswith(b"\n"):
                rejected["truncated-final-record"] += 1
                break
            complete_lines += 1
            seen += 1
            try:
                text = raw.decode("utf-8")
                row = json.loads(text)
                if not isinstance(row, dict):
                    raise analysis.RejectedRecord("non-object-json")
                record = analysis.evaluation_record(row, text, seen)
                if record["learning_state_key"] in seen_positions:
                    duplicates += 1
                else:
                    seen_positions.add(record["learning_state_key"])
                reservoir.add(record)
                accepted += 1
            except UnicodeDecodeError:
                rejected["invalid-utf8"] += 1
            except json.JSONDecodeError:
                rejected["malformed-json"] += 1
            except analysis.RejectedRecord as error:
                rejected[error.reason] += 1
            except (TypeError, ValueError):
                rejected["unexpected-value"] += 1
        stopped = seen >= record_limit
    finally:
        finish_process(process)
    return ScanResult(
        reservoir.finalize(),
        seen,
        accepted,
        duplicates,
        rejected,
        stopped,
        complete_lines,
    )


def scan_puzzles(
    zstd: str,
    prefix: pathlib.Path,
    record_limit: int,
    retained_limit: int,
    seed: str,
) -> ScanResult:
    process = subprocess.Popen(
        [zstd, "-dc", str(prefix)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    reservoir = PriorityReservoir(retained_limit, seed + "/puzzles")
    rejected: Counter[str] = Counter()
    seen_positions: set[str] = set()
    seen = accepted = duplicates = complete_lines = 0
    stopped = False
    try:
        header_raw = process.stdout.readline()
        if not header_raw.endswith(b"\n"):
            raise RuntimeError("puzzle prefix does not contain a complete CSV header")
        header = header_raw.decode("utf-8-sig")
        if not header.startswith("PuzzleId,FEN,Moves,"):
            raise RuntimeError("unexpected puzzle CSV header")
        while seen < record_limit:
            raw = process.stdout.readline()
            if not raw:
                break
            if not raw.endswith(b"\n"):
                rejected["truncated-final-record"] += 1
                break
            complete_lines += 1
            seen += 1
            try:
                text = raw.decode("utf-8")
                row = next(csv.DictReader([header, text]))
                record = analysis.puzzle_record(row, seen + 1, seed)
                if record["learning_state_key"] in seen_positions:
                    duplicates += 1
                else:
                    seen_positions.add(record["learning_state_key"])
                reservoir.add(record)
                accepted += 1
            except UnicodeDecodeError:
                rejected["invalid-utf8"] += 1
            except (csv.Error, StopIteration):
                rejected["malformed-csv"] += 1
            except analysis.RejectedRecord as error:
                rejected[error.reason] += 1
            except (TypeError, ValueError):
                rejected["unexpected-value"] += 1
        stopped = seen >= record_limit
    finally:
        finish_process(process)
    return ScanResult(
        reservoir.finalize(),
        seen,
        accepted,
        duplicates,
        rejected,
        stopped,
        complete_lines,
    )


def result_document(result: ScanResult) -> dict[str, Any]:
    return {
        "records_seen": result.seen,
        "complete_lines": result.complete_lines,
        "records_accepted": result.accepted,
        "records_retained": len(result.records),
        "duplicate_learning_states_seen": result.duplicate_positions,
        "rejections": dict(sorted(result.rejected.items())),
        "stopped_at_record_limit": result.stopped_at_record_limit,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=ROOT / ".deps" / "nnue-inputs-v2",
    )
    parser.add_argument("--prefix-mib", type=int, default=DEFAULT_PREFIX_MIB)
    parser.add_argument(
        "--record-limit-per-source", type=int, default=DEFAULT_RECORD_LIMIT
    )
    parser.add_argument(
        "--retain-per-source", type=int, default=DEFAULT_RETAINED_LIMIT
    )
    parser.add_argument(
        "--max-output-mib", type=int, default=DEFAULT_OUTPUT_LIMIT_MIB
    )
    parser.add_argument("--seed", default=analysis.DEFAULT_SEED + "/broader-1")
    parser.add_argument("--zstd")
    args = parser.parse_args()
    if not 16 <= args.prefix_mib <= 1024:
        parser.error("--prefix-mib must be between 16 and 1024")
    if not 20_000 <= args.record_limit_per_source <= 2_000_000:
        parser.error(
            "--record-limit-per-source must be between 20000 and 2000000"
        )
    if not 20_000 <= args.retain_per_source <= args.record_limit_per_source:
        parser.error(
            "--retain-per-source must be between 20000 and the record limit"
        )
    if not 1 <= args.max_output_mib <= 2048:
        parser.error("--max-output-mib must be between 1 and 2048")
    analysis.validate_output_directory(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prefix_bytes = args.prefix_mib * 1024**2
    output_limit_bytes = args.max_output_mib * 1024**2
    baseline_nnue = analysis.directory_bytes(ROOT / ".deps" / "nnue-inputs")
    baseline_total = analysis.directory_bytes(ROOT / "tmp") + baseline_nnue
    ensure_peak_budget(
        baseline_total, baseline_nnue, prefix_bytes, output_limit_bytes
    )
    budget = analysis.OutputBudget(
        output_limit_bytes, baseline_total, baseline_nnue
    )
    zstd = acquisition.find_zstd(args.zstd)
    incomplete = args.output_dir / "INCOMPLETE.json"
    analysis.atomic_write_bytes(
        incomplete,
        (
            json.dumps(
                {
                    "schema": analysis.SCHEMA,
                    "status": "incomplete",
                    "seed": args.seed,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
        budget,
    )

    source_results: dict[str, ScanResult] = {}
    source_documents: dict[str, dict[str, Any]] = {}
    for name in ("evaluations", "puzzles"):
        source = acquisition.SOURCES[name]
        prefix = args.output_dir / f".{name}.prefix.zst"
        try:
            downloaded = acquisition.download_prefix(
                source, prefix, prefix_bytes
            )
            if name == "evaluations":
                result = scan_evaluations(
                    zstd,
                    prefix,
                    args.record_limit_per_source,
                    args.retain_per_source,
                    args.seed,
                )
            else:
                result = scan_puzzles(
                    zstd,
                    prefix,
                    args.record_limit_per_source,
                    args.retain_per_source,
                    args.seed,
                )
            source_results[name] = result
            source_documents[name] = {
                "license": "CC0 1.0",
                "source_url": source["url"],
                "upstream_total_bytes": source["total_bytes"],
                "upstream_etag": source["etag"],
                "upstream_last_modified": source["last_modified"],
                **downloaded,
                **result_document(result),
                "sample_method": (
                    "deterministic priority-plus-coverage reservoir over "
                    "complete valid records in a bounded sequential prefix"
                ),
            }
        finally:
            prefix.unlink(missing_ok=True)

    evaluations = source_results["evaluations"].records
    puzzles = source_results["puzzles"].records
    overlap = analysis.assign_group_clusters(evaluations, puzzles, args.seed)
    evaluations = analysis.sorted_records(evaluations)
    puzzles = analysis.sorted_records(puzzles)
    evaluation_output = args.output_dir / "canonical-evaluations.jsonl"
    puzzle_output = args.output_dir / "canonical-puzzles.jsonl"
    analysis.atomic_write_jsonl(evaluation_output, evaluations, budget)
    analysis.atomic_write_jsonl(puzzle_output, puzzles, budget)

    manifest = {
        "schema": analysis.SCHEMA,
        "kind": "bounded-broader-nnue-sample",
        "status": "complete",
        "mode": "analysis-only",
        "production_outputs_written": False,
        "seed": args.seed,
        "parameters": {
            "prefix_bytes_per_source": prefix_bytes,
            "record_limit_per_source": args.record_limit_per_source,
            "retain_per_source": args.retain_per_source,
            "max_output_bytes": output_limit_bytes,
            "total_temp_limit_bytes": analysis.TOTAL_TEMP_LIMIT_BYTES,
            "training_temp_limit_bytes": analysis.NNUE_TEMP_LIMIT_BYTES,
            "strict_current_limit_bytes": analysis.STRICT_NNUE_LIMIT_BYTES,
        },
        "sources": source_documents,
        "cross_source_overlap": overlap,
        "distributions": {
            "evaluations": analysis.distribution(
                evaluations,
                (
                    "partition",
                    "phase_bucket",
                    "score_type",
                    "score_bucket",
                    "confidence_bucket",
                    "tactical_surface",
                ),
            ),
            "puzzles": analysis.distribution(
                puzzles,
                (
                    "partition",
                    "phase_bucket",
                    "rating_bucket",
                    "theme_family",
                    "best_move_class",
                ),
            ),
        },
        "storage_model": {
            "evaluations": analysis.corpus_projection(evaluations),
            "puzzles": analysis.corpus_projection(puzzles),
        },
        "outputs": {
            "canonical_evaluations": {
                "path": evaluation_output.name,
                "bytes": evaluation_output.stat().st_size,
                "sha256": analysis.sha256_file(evaluation_output),
            },
            "canonical_puzzles": {
                "path": puzzle_output.name,
                "bytes": puzzle_output.stat().st_size,
                "sha256": analysis.sha256_file(puzzle_output),
            },
        },
        "resource_usage": {
            "analysis_output_bytes_before_manifest": budget.written,
            "analysis_output_limit_bytes": budget.output_limit,
            "compressed_prefixes_retained": False,
        },
    }
    manifest["sample_id"] = analysis.stable_hash(
        args.seed,
        prefix_bytes,
        args.record_limit_per_source,
        args.retain_per_source,
        source_documents["evaluations"]["prefix_sha256"],
        source_documents["puzzles"]["prefix_sha256"],
        manifest["outputs"]["canonical_evaluations"]["sha256"],
        manifest["outputs"]["canonical_puzzles"]["sha256"],
    )
    manifest_path = args.output_dir / "manifest.json"
    analysis.atomic_write_bytes(
        manifest_path,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        budget,
    )
    incomplete.unlink()
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
