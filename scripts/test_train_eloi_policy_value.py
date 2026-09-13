import importlib.util
import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "policy_value", ROOT / "scripts/train_eloi_policy_value.py")
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)


class PolicyValueTests(unittest.TestCase):
    def test_features_are_side_to_move_oriented(self):
        white = MODEL.chess.Board()
        black = MODEL.chess.Board()
        black.push_uci("e2e4")
        self.assertEqual(MODEL.board_features(white).shape, (MODEL.INPUTS,))
        self.assertEqual(MODEL.board_features(black).shape, (MODEL.INPUTS,))
        self.assertEqual(int(MODEL.board_features(white)[:768].sum()), 32)

    def test_predictions_are_normalized_over_legal_candidates(self):
        board = MODEL.chess.Board()
        moves = [MODEL.chess.Move.from_uci(move) for move in ("e2e4", "d2d4")]
        value, policy = MODEL.Network(7).predict(board, moves)
        self.assertAlmostEqual(float(value.sum()), 1.0, places=6)
        self.assertAlmostEqual(float(policy.sum()), 1.0, places=6)

    def test_one_update_is_finite(self):
        row = {
            "fen": MODEL.chess.Board().fen(), "tactical_weight": 1.0,
            "value_wdl": {"win": 0.5, "draw": 0.3, "loss": 0.2},
            "policy": [
                {"move": "e2e4", "probability": 0.75},
                {"move": "d2d4", "probability": 0.25},
            ],
        }
        losses = MODEL.Network(9).update(row, 0.001)
        self.assertTrue(all(np.isfinite(loss) for loss in losses))

    def test_snapshot_restore_is_exact(self):
        network = MODEL.Network(11)
        state = network.snapshot()
        network.bias[0] = 99
        network.restore(state)
        self.assertEqual(float(network.bias[0]), float(state[1][0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
