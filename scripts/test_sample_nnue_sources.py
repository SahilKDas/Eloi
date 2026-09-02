#!/usr/bin/env python3
"""Fixture tests for bounded broader-source NNUE sampling."""

from __future__ import annotations

import csv
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_nnue_dataset as analysis
import sample_nnue_sources as sampler

chess = analysis.chess


def find_zstd() -> str | None:
    candidates = (
        shutil.which("zstd"),
        "C:/msys64/ucrt64/bin/zstd.exe",
    )
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).is_file():
            return str(pathlib.Path(candidate))
    return None


def compress(zstd: str, source: pathlib.Path, target: pathlib.Path) -> None:
    subprocess.run(
        [zstd, "-q", "-f", str(source), "-o", str(target)],
        check=True,
        timeout=30,
    )


def write_sources(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    evaluations = root / "evaluations.jsonl"
    with evaluations.open("w", encoding="utf-8", newline="\n") as stream:
        for index, first_move in enumerate(
            ("e2e4", "d2d4", "g1f3", "c2c4", "e2e3", "g2g3")
        ):
            board = chess.Board()
            board.push_uci(first_move)
            reply = sorted(board.legal_moves, key=lambda move: move.uci())[0]
            stream.write(
                json.dumps(
                    {
                        "id": f"evaluation-{index}",
                        "fen": board.fen(),
                        "evals": [{
                            "depth": 32,
                            "knodes": 25_000,
                            "pvs": [{
                                "cp": index * 10,
                                "line": reply.uci(),
                            }],
                        }],
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    puzzles = root / "puzzles.csv"
    with puzzles.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "PuzzleId",
                "FEN",
                "Moves",
                "Rating",
                "Themes",
                "GameUrl",
            ),
        )
        writer.writeheader()
        for index, moves in enumerate(
            (
                "e2e4 e7e5",
                "d2d4 d7d5",
                "g1f3 g8f6",
                "c2c4 e7e5",
                "e2e3 e7e6",
                "g2g3 g7g6",
            )
        ):
            writer.writerow({
                "PuzzleId": f"puzzle-{index}",
                "FEN": chess.STARTING_FEN,
                "Moves": moves,
                "Rating": 1200 + index * 100,
                "Themes": "opening test",
                "GameUrl": f"https://lichess.org/TEST{index:04d}#1",
            })
    return evaluations, puzzles


class ReservoirTests(unittest.TestCase):
    def test_priority_reservoir_is_order_invariant_and_covers_strata(self) -> None:
        records = [
            {
                "record_id": f"record-{index}",
                "stratum": f"stratum-{index % 4}",
            }
            for index in range(40)
        ]
        forward = sampler.PriorityReservoir(8, "seed")
        reverse = sampler.PriorityReservoir(8, "seed")
        for record in records:
            forward.add(record)
        for record in reversed(records):
            reverse.add(record)
        left = forward.finalize()
        right = reverse.finalize()
        self.assertEqual(
            {record["record_id"] for record in left},
            {record["record_id"] for record in right},
        )
        self.assertEqual({record["stratum"] for record in left}, {
            "stratum-0", "stratum-1", "stratum-2", "stratum-3"
        })

    def test_peak_budget_fails_before_a_cap_can_be_exceeded(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "10 GB"):
            sampler.ensure_peak_budget(
                analysis.TOTAL_TEMP_LIMIT_BYTES - 10,
                0,
                6,
                5,
            )
        with self.assertRaisesRegex(RuntimeError, "8 GB"):
            sampler.ensure_peak_budget(
                0,
                analysis.NNUE_TEMP_LIMIT_BYTES - 10,
                6,
                5,
            )


@unittest.skipUnless(find_zstd(), "zstd is required for stream fixture tests")
class StreamFixtureTests(unittest.TestCase):
    def test_compressed_fixture_scans_are_deterministic(self) -> None:
        zstd = find_zstd()
        assert zstd is not None
        with tempfile.TemporaryDirectory(
            prefix="eloi-broader-source-test-"
        ) as temporary:
            root = pathlib.Path(temporary)
            evaluations, puzzles = write_sources(root)
            evaluation_zst = root / "evaluations.zst"
            puzzle_zst = root / "puzzles.zst"
            compress(zstd, evaluations, evaluation_zst)
            compress(zstd, puzzles, puzzle_zst)
            first_evaluations = sampler.scan_evaluations(
                zstd, evaluation_zst, 100, 4, "seed"
            )
            second_evaluations = sampler.scan_evaluations(
                zstd, evaluation_zst, 100, 4, "seed"
            )
            first_puzzles = sampler.scan_puzzles(
                zstd, puzzle_zst, 100, 4, "seed"
            )
            second_puzzles = sampler.scan_puzzles(
                zstd, puzzle_zst, 100, 4, "seed"
            )
            self.assertEqual(first_evaluations.seen, 6)
            self.assertEqual(first_puzzles.seen, 6)
            self.assertEqual(first_evaluations.accepted, 6)
            self.assertEqual(first_puzzles.accepted, 6)
            self.assertEqual(
                sorted(
                    first_evaluations.records,
                    key=lambda record: record["record_id"],
                ),
                sorted(
                    second_evaluations.records,
                    key=lambda record: record["record_id"],
                ),
            )
            self.assertEqual(
                sorted(
                    first_puzzles.records,
                    key=lambda record: record["record_id"],
                ),
                sorted(
                    second_puzzles.records,
                    key=lambda record: record["record_id"],
                ),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
