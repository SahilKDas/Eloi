import contextlib
import io
import unittest
import numpy as np
import audit_fresh_nnue_channels as audit


class ChannelTests(unittest.TestCase):
    def model(self):
        weights = np.zeros((4, 2), dtype=np.float32)
        weights[0, 0], weights[1, 0] = 1, -1
        return weights, np.array([8, 8], dtype=np.float32), np.array([2, 0], dtype=np.float32)

    def assert_dead_channel(self, model):
        self.assertTrue(np.all(model[0][:, 1] == 0))
        self.assertEqual(model[2][1], 0)
        self.assertNotEqual(model[2][0], 2)  # The nonzero channel did receive updates.

    def test_evaluation_updates_cannot_wake_zero_channel(self):
        samples = [(np.array([0]), np.array([1]), 100)]
        with contextlib.redirect_stdout(io.StringIO()):
            model = audit.campaign.trainer.train_evaluations(*self.model(), samples, epochs=2)
        self.assert_dead_channel(model)

    def test_pair_updates_cannot_wake_zero_channel(self):
        pairs = [(np.array([0]), np.array([1]), np.array([1]), np.array([0]), 1)]
        with contextlib.redirect_stdout(io.StringIO()):
            model = audit.campaign.trainer.train_pairs(*self.model(), pairs, epochs=3)
        self.assert_dead_channel(model)

    def test_channel_statistics(self):
        stats = audit.channel_stats(self.model())
        self.assertEqual(stats['zero_input_and_output_indices'], [1])
        self.assertEqual(stats['nonzero_output_coefficients'], 1)


if __name__ == '__main__':
    unittest.main()
