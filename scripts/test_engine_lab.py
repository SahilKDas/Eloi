#!/usr/bin/env python3
"""Unit tests for Eloi Engine Lab gate semantics."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

import engine_lab


def rows(*labels: str) -> list[dict[str, object]]:
    return [
        {"game": index + 1, "result": label}
        for index, label in enumerate(labels)
    ]


class EngineLabGateTests(unittest.TestCase):
    def test_final_gate_counts_raw_wins_only(self) -> None:
        report = {
            "identity": {
                "games": 4,
                "gate_metric": "raw-wins",
                "required_wins": 3,
            },
            "results": rows("win", "draw", "draw", "loss"),
        }
        engine_lab.summarize_strength(report)
        self.assertEqual(report["score"], 0.5)
        self.assertEqual(report["wins"], 1)
        self.assertFalse(report["passed"])

    def test_architecture_thresholds_and_inconclusive_default(self) -> None:
        identity = {
            "games": 20,
            "gate_metric": "score",
            "candidate_hidden": 128,
            "baseline_hidden": 64,
            "select_candidate_at_score": 0.55,
            "select_baseline_at_or_below_score": 0.45,
        }
        cases = (
            (("win",) * 11 + ("loss",) * 9, 128,
             "candidate-scored-at-least-55-percent"),
            (("win",) * 9 + ("loss",) * 11, 64,
             "candidate-scored-at-most-45-percent"),
            (("win",) * 10 + ("loss",) * 10, 64,
             "inconclusive-band-prefers-smaller-faster-baseline"),
        )
        for labels, selected, reason in cases:
            with self.subTest(selected=selected, reason=reason):
                report = {"identity": identity, "results": rows(*labels)}
                engine_lab.summarize_strength(report)
                self.assertTrue(report["passed"])
                self.assertEqual(report["selected_hidden"], selected)
                self.assertEqual(report["selection_reason"], reason)

    def test_incomplete_playoff_never_selects(self) -> None:
        report = {
            "identity": {
                "games": 4,
                "gate_metric": "score",
                "candidate_hidden": 128,
                "baseline_hidden": 64,
                "select_candidate_at_score": 0.55,
                "select_baseline_at_or_below_score": 0.45,
            },
            "results": rows("win", "win"),
        }
        engine_lab.summarize_strength(report)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["selected_hidden"])
        self.assertEqual(report["selection_reason"], "incomplete")

    def test_shortened_playoff_preserves_original_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eloi-playoff-test-") as raw:
            root = pathlib.Path(raw)
            candidate = root / "candidate.exe"
            baseline = root / "baseline.exe"
            candidate.write_bytes(b"candidate")
            baseline.write_bytes(b"baseline")
            checkpoint = root / "playoff.json"
            pgn = root / "playoff.pgn"
            archive = root / "raw.json"
            identity = {
                "candidate_sha256": engine_lab.sha256(candidate),
                "baseline_sha256": engine_lab.sha256(baseline),
                "games": 4,
                "gate_metric": "score",
                "candidate_hidden": 128,
                "baseline_hidden": 64,
                "select_candidate_at_score": 0.55,
                "select_baseline_at_or_below_score": 0.45,
            }
            checkpoint.write_text(json.dumps({
                "schema": 1,
                "kind": "architecture-playoff",
                "identity": identity,
                "results": rows("loss", "draw"),
            }), encoding="utf-8")
            pgn.write_text(
                '[Event "one"]\n\n1. e4 e5 1/2-1/2\n\n'
                '[Event "two"]\n\n1. d4 d5 1/2-1/2\n\n',
                encoding="utf-8",
            )
            report = engine_lab.finalize_shortened_playoff(
                candidate, baseline, checkpoint, pgn, archive, 2,
                ["reduced from 4 to 2 after game 2"],
            )
            self.assertTrue(archive.is_file())
            self.assertEqual(report["identity"]["games"], 2)
            self.assertEqual(report["original_identity"]["games"], 4)
            self.assertTrue(report["shortened_after_start"])
            self.assertEqual(report["selected_hidden"], 64)
            self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
