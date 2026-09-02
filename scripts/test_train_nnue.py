#!/usr/bin/env python3
"""Regression tests for deterministic, fair NNUE architecture comparison."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAINER = ROOT / "scripts" / "train_nnue.py"


def compiler_path() -> str | None:
    configured = os.environ.get("CXX")
    if configured:
        return configured
    pinned = pathlib.Path("C:/msys64/ucrt64/bin/c++.exe")
    if pinned.is_file():
        return str(pinned)
    return shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")


def assert_header_compiles(root: pathlib.Path, header: pathlib.Path) -> None:
    compiler = compiler_path()
    if compiler is None:
        raise AssertionError("a C++ compiler is required to validate NNUE headers")
    source = root / f"compile-{header.parent.name}.cpp"
    source.write_text(
        f'#include "{header.as_posix()}"\n'
        "int main() {\n"
        "  return eloi::nnue_weights::input[0];\n"
        "}\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(
        [compiler, "-std=c++2c", "-fsyntax-only", str(source)],
        cwd=ROOT,
        check=True,
        timeout=180,
    )


def write_fixtures(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    puzzles = root / "puzzles.csv"
    with puzzles.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("PuzzleId", "FEN", "Moves", "Themes")
        )
        writer.writeheader()
        for index in range(40):
            writer.writerow({
                "PuzzleId": f"fixture-puzzle-{index}",
                "FEN": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "Moves": "e2e4 e7e5",
                "Themes": "opening test",
            })

    evaluations = root / "evaluations.jsonl"
    with evaluations.open("w", encoding="utf-8", newline="\n") as stream:
        for index in range(40):
            row = {
                "id": f"fixture-evaluation-{index}",
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "evals": [{
                    "depth": 12,
                    "pvs": [{"cp": (index % 9 - 4) * 8}],
                }],
            }
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return puzzles, evaluations


def write_canonical_fixtures(
    root: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    evaluations = root / "canonical-evaluations.jsonl"
    puzzles = root / "canonical-puzzles.jsonl"
    partitions = ("train", "train", "validation", "test")
    with evaluations.open("w", encoding="utf-8", newline="\n") as stream:
        for index, partition in enumerate(partitions):
            row = {
                "schema": 2,
                "record_id": f"evaluation:fixture-{index}",
                "group_id": f"group:eval-{index}",
                "partition": partition,
                "fen": (
                    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/"
                    "RNBQKBNR w KQkq - 0 1"
                ),
                "score_white_cp": None if index == 1 else (index - 2) * 12,
                "mate_distance_white": -3 if index == 1 else None,
                "confidence_bucket": ("low", "medium", "high", "high")[index],
                "phase_bucket": "opening",
                "score_bucket": "0-25",
                "score_type": "mate" if index == 1 else "cp",
                "side_to_move": "white",
                "tactical_surface": "quiet",
            }
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    with puzzles.open("w", encoding="utf-8", newline="\n") as stream:
        for index, partition in enumerate(partitions):
            row = {
                "schema": 2,
                "record_id": f"puzzle:fixture-{index}",
                "puzzle_id": f"fixture-{index}",
                "group_id": f"group:puzzle-{index}",
                "partition": partition,
                "decision_fen": (
                    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/"
                    "RNBQKBNR b KQkq - 0 1"
                ),
                "best_move": "e7e5",
                "hard_alternatives": [
                    {"move": "c7c5", "tier": "forcing"},
                    {"move": "g8f6", "tier": "quiet"},
                ],
                "themes": ["opening", "fixture"],
                "best_move_class": "quiet",
                "phase_bucket": "opening",
                "rating_bucket": "1000-1499",
                "theme_family": "other",
            }
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "complete",
                "production_outputs_written": False,
                "sample_id": "fixture-sample",
                "outputs": {
                    "canonical_evaluations": {
                        "bytes": evaluations.stat().st_size,
                        "sha256": hashlib.sha256(
                            evaluations.read_bytes()
                        ).hexdigest().upper(),
                    },
                    "canonical_puzzles": {
                        "bytes": puzzles.stat().st_size,
                        "sha256": hashlib.sha256(
                            puzzles.read_bytes()
                        ).hexdigest().upper(),
                    },
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return puzzles, evaluations, manifest


def run_trainer(
    root: pathlib.Path,
    puzzles: pathlib.Path,
    evaluations: pathlib.Path,
    name: str,
    architectures: tuple[int, ...],
    report_only: bool = False,
) -> tuple[dict, pathlib.Path]:
    run_root = root / name
    output = run_root / "nnue_weights.hpp"
    architecture = run_root / "nnue_architecture.hpp"
    provenance = run_root / "provenance.json"
    run_root.mkdir(parents=True)
    if report_only:
        output.write_text("weights sentinel\n", encoding="utf-8")
        architecture.write_text("architecture sentinel\n", encoding="utf-8")
    command = [
        sys.executable,
        str(TRAINER),
        "--puzzles", str(puzzles),
        "--evaluations", str(evaluations),
        "--output", str(output),
        "--architecture-output", str(architecture),
        "--provenance", str(provenance),
        "--temp-dir", str(run_root / "work"),
        "--max-temp-gb", "0.1",
        "--limit", "32",
        "--eval-limit", "32",
        "--epochs", "1",
        "--validation-fraction", "0.25",
        "--architectures", *(str(value) for value in architectures),
    ]
    if report_only:
        command.append("--report-only")
    subprocess.run(command, cwd=ROOT, check=True, timeout=180)
    if report_only:
        if output.read_text(encoding="utf-8") != "weights sentinel\n":
            raise AssertionError("report-only mode replaced the weights output")
        if architecture.read_text(encoding="utf-8") != "architecture sentinel\n":
            raise AssertionError("report-only mode replaced the architecture output")
    if (run_root / "work" / "candidates").exists():
        raise AssertionError("candidate staging directory was not removed")
    if (run_root / "work" / "selected").exists():
        raise AssertionError("selected staging directory was not removed")
    return json.loads(provenance.read_text(encoding="utf-8")), output


class TrainNnueTests(unittest.TestCase):
    def test_quota_above_hard_limit_is_rejected(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TRAINER), "--max-temp-gb", "7.1"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at most 7", result.stderr)

    def test_combined_and_solo_candidates_are_identical(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eloi-nnue-test-") as temporary:
            root = pathlib.Path(temporary)
            puzzles, evaluations = write_fixtures(root)
            combined_a, _ = run_trainer(
                root, puzzles, evaluations, "combined-a", (64, 128), True
            )
            combined_b, _ = run_trainer(
                root, puzzles, evaluations, "combined-b", (64, 128), True
            )
            solo_64, output_64 = run_trainer(
                root, puzzles, evaluations, "solo-64", (64,)
            )
            solo_128, output_128 = run_trainer(
                root, puzzles, evaluations, "solo-128", (128,)
            )

            self.assertEqual(combined_a, combined_b)
            self.assertEqual(combined_a["mode"], "comparison-report-only")
            self.assertFalse(combined_a["outputs_written"])
            self.assertIn("python_version", combined_a["environment"])
            self.assertIn("numpy_version", combined_a["environment"])
            self.assertIn("python_chess_version", combined_a["environment"])

            combined = {
                candidate["hidden"]: candidate
                for candidate in combined_a["candidates"]
            }
            for solo, output, hidden in (
                (solo_64, output_64, 64),
                (solo_128, output_128, 128),
            ):
                candidate = solo["candidates"][0]
                self.assertEqual(candidate, combined[hidden])
                self.assertEqual(
                    candidate["weights_sha256"], solo["selected_weights_sha256"]
                )
                self.assertTrue(output.is_file())
                assert_header_compiles(root, output)

    def test_canonical_inputs_honor_frozen_partitions_and_seal_test(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eloi-nnue-canonical-") as temporary:
            root = pathlib.Path(temporary)
            puzzles, evaluations, manifest = write_canonical_fixtures(root)
            run_root = root / "canonical"
            run_root.mkdir()
            provenance = run_root / "provenance.json"
            subprocess.run(
                [
                    sys.executable,
                    str(TRAINER),
                    "--puzzles", str(puzzles),
                    "--evaluations", str(evaluations),
                    "--canonical-manifest", str(manifest),
                    "--provenance", str(provenance),
                    "--output", str(run_root / "weights-sentinel.hpp"),
                    "--architecture-output", str(run_root / "arch-sentinel.hpp"),
                    "--temp-dir", str(run_root / "work"),
                    "--max-temp-gb", "0.1",
                    "--limit", "8",
                    "--eval-limit", "8",
                    "--epochs", "1",
                    "--architectures", "64",
                    "--report-only",
                ],
                cwd=ROOT,
                check=True,
                timeout=180,
            )
            report = json.loads(provenance.read_text(encoding="utf-8"))
            self.assertEqual(report["dataset"]["format"], "canonical-schema-2")
            self.assertEqual(report["dataset"]["sample_id"], "fixture-sample")
            self.assertEqual(report["counts"]["train_evaluations"], 2)
            self.assertEqual(report["counts"]["validation_evaluations"], 1)
            self.assertEqual(report["counts"]["train_pairs"], 2)
            self.assertEqual(report["counts"]["validation_pairs"], 1)
            self.assertIsNone(report["counts"]["test_evaluations"])
            self.assertIsNone(report["counts"]["test_pairs"])
            self.assertFalse(report["dataset"]["test_opened"])

    def test_canonical_manifest_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eloi-nnue-manifest-") as temporary:
            root = pathlib.Path(temporary)
            puzzles, evaluations, manifest = write_canonical_fixtures(root)
            evaluations.write_text(
                evaluations.read_text(encoding="utf-8") + "{}\n",
                encoding="utf-8",
                newline="\n",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(TRAINER),
                    "--puzzles", str(puzzles),
                    "--evaluations", str(evaluations),
                    "--canonical-manifest", str(manifest),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("size mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
