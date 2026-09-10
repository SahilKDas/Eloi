import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("trainer", ROOT / "scripts/train_caissa_successor.py")
TRAINER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRAINER)


class CaissaSuccessorTrainingTests(unittest.TestCase):
    def test_starting_position_feature_shape_and_range(self):
        board = TRAINER.chess.Board()
        for colour in TRAINER.chess.COLORS:
            features = TRAINER.feature_indices(board, colour)
            self.assertEqual(len(features), 32)
            self.assertEqual(len(set(features.tolist())), 32)
            self.assertTrue(((features >= 0) & (features < TRAINER.INPUTS)).all())

    def test_material_variant_and_phase(self):
        variant, phase = TRAINER.material(TRAINER.chess.Board())
        self.assertEqual(variant, 7)
        self.assertEqual(phase, 76 / 64)

    def test_teacher_score_is_side_to_move_relative(self):
        white = TRAINER.chess.Board()
        black = TRAINER.chess.Board()
        black.turn = TRAINER.chess.BLACK
        self.assertEqual(TRAINER.teacher_stm_cp(white, 123), 123)
        self.assertEqual(TRAINER.teacher_stm_cp(black, 123), -123)

    def test_castling_adjustment_is_zero_in_start_position(self):
        self.assertEqual(TRAINER.castling_adjustment(TRAINER.chess.Board()), 0.0)


if __name__ == "__main__":
    unittest.main()
