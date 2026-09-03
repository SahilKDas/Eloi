import tempfile
import unittest
from pathlib import Path

import numpy as np

import nnue_e1_e32 as experiment
import train_nnue as trainer


class E1E32Tests(unittest.TestCase):
    def blank_model(self, hidden):
        return (
            np.zeros((trainer.FEATURES, hidden), dtype=np.float32),
            np.full(hidden, 8, dtype=np.float32),
            np.zeros(hidden, dtype=np.float32),
        )

    def test_revival_is_deterministic_and_quantized_active(self):
        first = experiment.revive_channels(
            self.blank_model(64), [2, 7], experiment.E1_SEED
        )
        second = experiment.revive_channels(
            self.blank_model(64), [2, 7], experiment.E1_SEED
        )
        self.assertTrue(all(
            np.array_equal(left, right) for left, right in zip(first, second)
        ))
        quantized = trainer.quantize_model(*first)
        for channel in (2, 7):
            self.assertNotEqual(np.count_nonzero(quantized[0][:, channel]), 0)
            self.assertNotEqual(quantized[2][channel], 0)

    def test_masked_training_preserves_unselected_channels(self):
        model = experiment.revive_channels(
            self.blank_model(4), [0, 1, 2, 3], 123
        )
        before = tuple(array.copy() for array in model)
        sample = [(np.array([0]), np.array([1]), 100.0)]
        trained = trainer.train_evaluations(
            *model, sample, epochs=1, trainable_channels=[3]
        )
        self.assertTrue(np.array_equal(trained[0][:, :3], before[0][:, :3]))
        self.assertTrue(np.array_equal(trained[1][:3], before[1][:3]))
        self.assertTrue(np.array_equal(trained[2][:3], before[2][:3]))

    def test_compaction_preserves_quantized_predictions(self):
        model = self.blank_model(64)
        model[0][0, 5] = 4
        model[0][1, 17] = -3
        model[2][5] = 10
        model[2][17] = -7
        compact, selected, trainable = experiment.compact_c_to_32(model)
        self.assertEqual(selected, [5, 17])
        self.assertEqual(trainable, list(range(2, 32)))
        samples = [
            (np.array([0]), np.array([1]), 0),
            (np.array([1]), np.array([0]), 0),
        ]
        self.assertEqual(
            experiment.quantized_predictions(model, samples),
            experiment.quantized_predictions(compact, samples),
        )

    def test_32_unit_header_round_trip(self):
        model = experiment.revive_channels(
            self.blank_model(32), list(range(32)), experiment.E32_SEED
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weights.hpp"
            trainer.write_header(
                path, *model,
                {"train_evaluations": 1, "train_pairs": 1},
                set(),
            )
            loaded = trainer.load_quantized_header(path)
        expected = trainer.quantize_model(*model)
        self.assertTrue(all(
            np.array_equal(left, right)
            for left, right in zip(loaded, expected)
        ))

    def test_invalid_training_mask_is_rejected(self):
        model = self.blank_model(4)
        with self.assertRaises(ValueError):
            trainer.train_evaluations(
                *model, [], epochs=1, trainable_channels=[4]
            )


if __name__ == "__main__":
    unittest.main()
