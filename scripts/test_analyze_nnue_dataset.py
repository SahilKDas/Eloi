#!/usr/bin/env python3
"""Regression tests for the deterministic NNUE dataset analysis prototype."""

from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
ANALYZER_PATH = ROOT / "scripts" / "analyze_nnue_dataset.py"
SPEC = importlib.util.spec_from_file_location("analyze_nnue_dataset", ANALYZER_PATH)
assert SPEC is not None and SPEC.loader is not None
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)
chess = analyzer.chess


def evaluation_row(
    identifier: str, board: chess.Board, score: int = 20
) -> dict:
    move = sorted(board.legal_moves, key=lambda item: item.uci())[0]
    return {
        "id": identifier,
        "fen": board.fen(),
        "evals": [{
            "depth": 30,
            "knodes": 20_000,
            "pvs": [{"cp": score, "line": move.uci()}],
        }],
    }


def write_fixtures(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    evaluation_paths = (
        (),
        ("e2e4",),
        ("d2d4",),
        ("g1f3",),
        ("c2c4",),
        ("e2e3",),
        ("g2g3",),
        ("b2b3",),
    )
    evaluations = root / "evaluations.jsonl"
    with evaluations.open("w", encoding="utf-8", newline="\n") as stream:
        for index, moves in enumerate(evaluation_paths):
            board = chess.Board()
            for move in moves:
                board.push_uci(move)
            stream.write(
                json.dumps(
                    evaluation_row(f"evaluation-{index}", board, index * 5),
                    sort_keys=True,
                )
                + "\n"
            )
        stream.write('{"fen":"not a fen","evals":[]}\n')

    puzzle_lines = (
        ("e2e4", "e7e5"),
        ("d2d4", "d7d5"),
        ("g1f3", "g8f6"),
        ("c2c4", "e7e5"),
        ("e2e3", "e7e6"),
        ("g2g3", "g7g6"),
        ("b2b3", "b7b6"),
        ("f2f4", "e7e5"),
    )
    puzzles = root / "puzzles.csv"
    fields = (
        "PuzzleId",
        "FEN",
        "Moves",
        "Rating",
        "Themes",
        "GameUrl",
    )
    with puzzles.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, moves in enumerate(puzzle_lines):
            writer.writerow({
                "PuzzleId": f"puzzle-{index}",
                "FEN": chess.STARTING_FEN,
                "Moves": " ".join(moves),
                "Rating": str(900 + index * 250),
                "Themes": "opening test",
                "GameUrl": f"https://lichess.org/GAME{index:04d}#1",
            })
        writer.writerow({
            "PuzzleId": "broken",
            "FEN": chess.STARTING_FEN,
            "Moves": "e2e5 e7e5",
            "Rating": "1200",
            "Themes": "test",
            "GameUrl": "",
        })
    return evaluations, puzzles


def run_analyzer(
    root: pathlib.Path,
    evaluations: pathlib.Path,
    puzzles: pathlib.Path,
    name: str,
) -> pathlib.Path:
    output = root / name
    subprocess.run(
        [
            sys.executable,
            str(ANALYZER_PATH),
            "--evaluations",
            str(evaluations),
            "--puzzles",
            str(puzzles),
            "--output-dir",
            str(output),
            "--limit-per-source",
            "6",
            "--max-output-mib",
            "1",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return output


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


class CanonicalizationTests(unittest.TestCase):
    def test_four_field_fen_is_canonical_and_invalid_position_rejected(self) -> None:
        board, fen = analyzer.canonical_fen(
            "8/8/8/8/8/8/4K3/7k w - -"
        )
        self.assertTrue(board.is_valid())
        self.assertEqual(fen, "8/8/8/8/8/8/4K3/7k w - - 0 1")
        with self.assertRaisesRegex(analyzer.RejectedRecord, "invalid-standard"):
            analyzer.canonical_fen("8/8/8/8/8/8/8/7k w - -")

    def test_evaluation_score_uses_white_perspective_and_validates_pv(self) -> None:
        board = chess.Board()
        board.push_uci("e2e4")
        row = evaluation_row("black-turn", board, 75)
        record = analyzer.evaluation_record(
            row, json.dumps(row, sort_keys=True), 1
        )
        self.assertEqual(record["side_to_move"], "black")
        self.assertEqual(record["score_white_cp"], -75)
        self.assertEqual(record["confidence_bucket"], "high")

        row["evals"][0]["pvs"][0]["line"] = "e2e5"
        with self.assertRaisesRegex(analyzer.RejectedRecord, "illegal-pv"):
            analyzer.evaluation_record(row, json.dumps(row), 1)

    def test_puzzle_decision_point_and_negatives_are_deterministic(self) -> None:
        row = {
            "PuzzleId": "fixture",
            "FEN": chess.STARTING_FEN,
            "Moves": "e2e4 e7e5 g1f3",
            "Rating": "1800",
            "Themes": "hangingPiece middlegame",
            "GameUrl": "https://lichess.org/ABCDEFGH/black#2",
        }
        first = analyzer.puzzle_record(row, 2, "seed")
        second = analyzer.puzzle_record(row, 99, "seed")
        expected = chess.Board()
        expected.push_uci("e2e4")
        self.assertEqual(first["decision_fen"], expected.fen())
        self.assertEqual(first["best_move"], "e7e5")
        self.assertEqual(first["game_id"], "ABCDEFGH")
        self.assertEqual(first["hard_alternatives"], second["hard_alternatives"])
        self.assertNotIn(
            "e7e5",
            {item["move"] for item in first["hard_alternatives"]},
        )


class IdentityAndQuotaTests(unittest.TestCase):
    def test_group_clusters_prevent_cross_source_partition_leakage(self) -> None:
        shared = analyzer.stable_hash("shared")
        evaluations = [{
            "source": "lichess-evaluations-2026-08-02",
            "group_id": "evaluation-group",
            "learning_state_key": shared,
        }]
        puzzles = [{
            "source": "lichess-puzzles-2026-08-02",
            "group_id": "puzzle-game",
            "learning_state_key": shared,
        }]
        overlap = analyzer.assign_group_clusters(evaluations, puzzles, "seed")
        self.assertEqual(overlap["exact_learning_state_count"], 1)
        self.assertEqual(evaluations[0]["group_id"], puzzles[0]["group_id"])
        self.assertEqual(evaluations[0]["partition"], puzzles[0]["partition"])

    def test_selection_and_partition_are_input_order_invariant(self) -> None:
        records = [
            {
                "record_id": f"record-{index}",
                "stratum": f"stratum-{index % 3}",
            }
            for index in range(20)
        ]
        forward = analyzer.deterministic_select(records, 8, "seed")
        reverse = analyzer.deterministic_select(list(reversed(records)), 8, "seed")
        self.assertEqual(
            {row["record_id"] for row in forward},
            {row["record_id"] for row in reverse},
        )
        self.assertEqual(
            analyzer.partition_for_group("group", "seed"),
            analyzer.partition_for_group("group", "seed"),
        )

    def test_quota_failure_occurs_before_accounting_overrun(self) -> None:
        budget = analyzer.OutputBudget(
            output_limit=10,
            baseline_total=0,
            baseline_nnue=0,
        )
        budget.reserve(8)
        with self.assertRaisesRegex(RuntimeError, "output quota"):
            budget.reserve(3)
        self.assertEqual(budget.written, 8)

    def test_production_directories_are_rejected(self) -> None:
        for path in (ROOT / "include", ROOT / "src", ROOT / "data", ROOT / "dist"):
            with self.assertRaises(ValueError):
                analyzer.validate_output_directory(path)


class EndToEndTests(unittest.TestCase):
    def test_fixture_runs_are_byte_identical_and_analysis_only(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="eloi-dataset-analysis-test-"
        ) as temporary:
            root = pathlib.Path(temporary)
            evaluations, puzzles = write_fixtures(root)
            first = run_analyzer(root, evaluations, puzzles, "run-a")
            second = run_analyzer(root, evaluations, puzzles, "run-b")
            for name in (
                "canonical-evaluations.jsonl",
                "canonical-puzzles.jsonl",
                "report.json",
            ):
                self.assertEqual(
                    (first / name).read_bytes(),
                    (second / name).read_bytes(),
                    name,
                )
            self.assertFalse((first / "INCOMPLETE.json").exists())
            report = json.loads((first / "report.json").read_text("utf-8"))
            self.assertEqual(report["mode"], "analysis-only")
            self.assertFalse(report["production_outputs_written"])
            self.assertEqual(report["counts"]["evaluations_seen"], 9)
            self.assertEqual(report["counts"]["puzzles_seen"], 9)
            self.assertEqual(report["counts"]["evaluations_selected"], 6)
            self.assertEqual(report["counts"]["puzzles_selected"], 6)
            self.assertEqual(
                report["rejections"]["evaluations"],
                {"fen-field-count": 1},
            )
            self.assertEqual(
                report["rejections"]["puzzles"],
                {"illegal-puzzle-line": 1},
            )
            self.assertGreaterEqual(
                report["cross_source_overlap"]["exact_learning_state_count"],
                1,
            )
            groups: dict[str, str] = {}
            for name in (
                "canonical-evaluations.jsonl",
                "canonical-puzzles.jsonl",
            ):
                for record in read_jsonl(first / name):
                    previous = groups.setdefault(
                        record["group_id"], record["partition"]
                    )
                    self.assertEqual(previous, record["partition"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
