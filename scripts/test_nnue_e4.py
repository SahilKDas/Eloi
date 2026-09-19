#!/usr/bin/env python3
import unittest
import numpy as np
import nnue_e4 as e4


class E4Tests(unittest.TestCase):
    def test_anchor_endpoints(self):
        base = (np.ones((2, 2)), np.ones(2), np.ones(2))
        candidate = tuple(array * 3 for array in base)
        for left, right in zip(e4.anchor(candidate, base, 0.0), base):
            self.assertTrue(np.array_equal(left, right))
        for value in e4.anchor(candidate, base, 0.25):
            self.assertTrue(np.all(value == 1.5))

    def test_distillation_preserves_e2_majority(self):
        class SampleModel:
            pass
        original = e4.e2_score
        try:
            e4.e2_score = lambda model, sample: 100.0
            sample = (np.array([1]), np.array([2]), 300.0, 1.0, {})
            self.assertEqual(e4.distilled([sample], SampleModel())[0][2], 140.0)
        finally:
            e4.e2_score = original

    def test_regression_replay_is_nonempty_and_legal(self):
        pairs, cases = e4.regression_pairs()
        self.assertGreaterEqual(len(cases), 8)
        self.assertGreater(len(pairs), len(cases))


if __name__ == "__main__":
    unittest.main()
