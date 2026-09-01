#!/usr/bin/env python3
"""Regression tests for deterministic, fair NNUE architecture comparison."""

from __future__ import annotations

import csv
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAINER = ROOT / "scripts" / "train_nnue.py"


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
