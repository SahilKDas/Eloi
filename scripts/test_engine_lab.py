#!/usr/bin/env python3
"""Unit tests for Eloi Engine Lab gate semantics."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
