#!/usr/bin/env python3
import unittest

import numpy as np

import nnue_e3 as e3
import train_nnue as trainer


class E3Tests(unittest.TestCase):
    def test_partition_is_deterministic_and_group_based(self):
        self.assertEqual(e3.partition("game-1"), e3.partition("game-1"))
        self.assertIn(e3.partition("game-1"), {"train", "validation", "test"})

    def test_expand_preserves_e2_exactly_before_training(self):
        rng = np.random.default_rng(7)
        model = (rng.normal(size=(trainer.FEATURES, 64)).astype(np.float32),
                 rng.normal(size=64).astype(np.float32),
                 rng.normal(size=64).astype(np.float32))
        expanded = e3.expand_e2(model, 128)
        self.assertTrue(np.array_equal(expanded[0][:, :64], model[0]))
        self.assertTrue(np.array_equal(expanded[1][:64], model[1]))
        self.assertTrue(np.array_equal(expanded[2][:64], model[2]))
        self.assertTrue(np.any(expanded[0][:, 64:]))
        self.assertTrue(np.all(expanded[1][64:] == 8.0))
        self.assertTrue(np.any(expanded[2][64:]))
        repeated = e3.expand_e2(model, 128)
        for left, right in zip(expanded, repeated):
            self.assertTrue(np.array_equal(left, right))

    def test_invalid_expansion_is_rejected(self):
        model = (np.zeros((trainer.FEATURES, 32), np.float32),
                 np.zeros(32, np.float32), np.zeros(32, np.float32))
        with self.assertRaises(ValueError):
            e3.expand_e2(model, 128)


if __name__ == "__main__":
    unittest.main()
