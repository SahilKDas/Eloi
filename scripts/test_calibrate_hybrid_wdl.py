import json
from pathlib import Path
import tempfile
import unittest

import calibrate_hybrid_wdl as calibration


class HybridWdlCalibrationTests(unittest.TestCase):
    def test_mapping_is_monotonic_and_symmetric(self):
        values = [
            calibration.expected_score(cp, 400.0)
            for cp in (-600, -100, 0, 100, 600)
        ]
        self.assertTrue(
            all(a < b for a, b in zip(values, values[1:]))
        )
        self.assertAlmostEqual(
            calibration.expected_score(275, 400.0)
            + calibration.expected_score(-275, 400.0),
            1.0,
            places=14,
        )

    def test_split_is_deterministic_and_keeps_games_together(self):
        samples = [
            calibration.Sample(
                f"g{game}", brain, cp, outcome
            )
            for game in range(40)
            for brain, cp, outcome in (
                ("eloi", game * 5 - 100, 0.5),
                ("caissa", 100 - game * 5, 0.5),
            )
        ]
        first = calibration.split_samples(
            samples, "seed", 0.25
        )
        second = calibration.split_samples(
            samples, "seed", 0.25
        )
        self.assertEqual(first, second)
        calibration_games = {
            row.game_id for row in first["calibration"]
        }
        validation_games = {
            row.game_id for row in first["validation"]
        }
        self.assertFalse(calibration_games & validation_games)
        self.assertEqual(
            calibration_games | validation_games,
            {row.game_id for row in samples},
        )

    def test_metrics_include_brier_log_loss_and_ece(self):
        samples = [
            calibration.Sample("a", "eloi", -200, 0.0),
            calibration.Sample("b", "eloi", 0, 0.5),
            calibration.Sample("c", "eloi", 200, 1.0),
        ]
        result = calibration.metrics(samples, 400.0)
        self.assertEqual(
            set(result),
            {"samples", "brier", "log_loss", "ece_10"},
        )
        self.assertTrue(
            all(
                value >= 0
                for key, value in result.items()
                if key != "samples"
            )
        )

    def test_evaluation_keeps_current_candidates_without_leakage(self):
        samples = []
        for game in range(100):
            outcome = [0.0, 0.5, 1.0][game % 3]
            cp = (-240, 0, 240)[game % 3]
            for brain in calibration.BRAINS:
                samples.append(
                    calibration.Sample(
                        f"g{game}", brain, cp, outcome
                    )
                )
        result = calibration.evaluate(
            samples, [300.0, 500.0], "unit-seed", 0.25
        )
        self.assertEqual(
            result["partition"]["game_overlap"], []
        )
        self.assertEqual(
            result["source_change"],
            "none; this report is evidence only",
        )
        for brain, current in calibration.CURRENT_SCALES.items():
            scales = {
                row["scale"]
                for row in result["brains"][brain]["candidates"]
            }
            self.assertIn(current, scales)

    def test_loader_excludes_mates_and_rejects_bad_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            rows = [
                {
                    "game_id": "a",
                    "brain": "eloi",
                    "centipawns": 50,
                    "outcome": 1,
                },
                {
                    "game_id": "b",
                    "brain": "caissa",
                    "centipawns": 0,
                    "outcome": 0.5,
                    "mate": 3,
                },
            ]
            path.write_text(
                "\n".join(json.dumps(row) for row in rows),
                encoding="utf-8",
            )
            samples, excluded = calibration.load_samples(path)
            self.assertEqual(len(samples), 1)
            self.assertEqual(excluded, 1)
            path.write_text(
                json.dumps(
                    {
                        "game_id": "bad",
                        "brain": "eloi",
                        "centipawns": 0,
                        "outcome": 0.25,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(
                calibration.CalibrationError
            ):
                calibration.load_samples(path)

    def test_external_validation_is_disjoint_and_uses_selected_scales(self):
        samples = [
            calibration.Sample(
                f"cal-{game}", brain, (-100, 100)[game % 2],
                (0.0, 1.0)[game % 2],
            )
            for game in range(20)
            for brain in calibration.BRAINS
        ]
        external = [
            calibration.Sample(
                f"ext-{game}", brain, (-80, 80)[game % 2],
                (0.0, 1.0)[game % 2],
            )
            for game in range(10)
            for brain in calibration.BRAINS
        ]
        report = calibration.evaluate(
            samples, [300.0, 500.0], "external-test", 0.25
        )
        calibration.add_external_validation(
            report, samples, external
        )
        self.assertEqual(
            report["external_validation"]["game_overlap"], []
        )
        for brain in calibration.BRAINS:
            self.assertEqual(
                report["brains"][brain]["external_validation"][
                    "selected_scale"
                ],
                report["brains"][brain]["selected_on_calibration"],
            )
        with self.assertRaises(calibration.CalibrationError):
            calibration.add_external_validation(
                report, samples, samples
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
