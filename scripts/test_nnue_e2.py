#!/usr/bin/env python3
"""Unit tests for the standard-only E2 campaign helpers."""
from __future__ import annotations

import unittest
import nnue_e2
import chess


class E2Tests(unittest.TestCase):
    def test_standard_board_forces_orthodox_rules(self) -> None:
        board = nnue_e2.standard_board(chess.STARTING_FEN)
        self.assertIs(type(board), chess.Board)
        self.assertFalse(board.chess960)

    def test_invalid_standard_position_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            nnue_e2.standard_board("8/8/8/8/8/8/8/8 w - - 0 1")

    def test_chess_points(self) -> None:
        self.assertEqual(nnue_e2.chess_points("win"), 1.0)
        self.assertEqual(nnue_e2.chess_points("draw"), 0.5)
        self.assertEqual(nnue_e2.chess_points("loss"), 0.0)
        with self.assertRaises(ValueError):
            nnue_e2.chess_points("unfinished")

    def test_poor_pairs_ignore_odd_final_game(self) -> None:
        rows = []
        for opening in range(62):
            labels = ("loss", "draw") if opening in (2, 9) else ("win", "draw")
            rows.extend({"opening": opening, "result": label} for label in labels)
        rows.append({"opening": 62, "result": "loss"})
        self.assertEqual(nnue_e2.poor_pair_indexes(rows), [2, 9])

    def test_anchor_keeps_declared_fraction_of_delta(self) -> None:
        import numpy as np
        baseline = tuple(np.asarray([value]) for value in (1.0, 2.0, 3.0))
        candidate = tuple(np.asarray([value]) for value in (5.0, 6.0, 7.0))
        anchored = nnue_e2.anchor_to_c(candidate, baseline, 0.25)
        self.assertEqual([float(array[0]) for array in anchored], [2.0, 3.0, 4.0])

    def test_hard_partition_uses_independent_balanced_hash(self) -> None:
        partitions = [nnue_e2.hard_partition(f"row-{index}") for index in range(1000)]
        self.assertGreater(partitions.count("validation"), 150)
        self.assertLess(partitions.count("validation"), 250)


if __name__ == "__main__":
    unittest.main(verbosity=2)
