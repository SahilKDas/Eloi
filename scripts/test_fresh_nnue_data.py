"""Small offline integrity tests; no network, training, or engine execution."""
import io
import unittest
from unittest import mock
import fresh_nnue_data as fresh


class SamplingTests(unittest.TestCase):
    def test_partition_repeatable(self):
        self.assertEqual(fresh.split('game1234'), fresh.split('game1234'))
        self.assertEqual({fresh.split(str(i)) for i in range(1000)}, {'train', 'validation', 'test'})

    def test_game_identity(self):
        self.assertEqual(fresh.game_identity({'LichessURL': 'https://lichess.org/abcdefgh'}, 'x'), 'abcdefgh')
        self.assertEqual(fresh.game_identity({}, 'x'), fresh.game_identity({}, 'x'))

    def test_counters_do_not_leak(self):
        a = fresh.chess.Board()
        b = fresh.chess.Board()
        b.fullmove_number = 99
        b.halfmove_clock = 17
        self.assertEqual(fresh.board_key(a), fresh.board_key(b))
        b.turn = not b.turn
        self.assertNotEqual(fresh.board_key(a), fresh.board_key(b))

    def test_complete_game_traversal(self):
        text = '[Event "a"]\n\n1. e4 e5 1/2-1/2\n\n[Event "b"]\n\n1. d4 d5 1/2-1/2\n'
        games = list(fresh.pgn_chunks(io.StringIO(text)))
        self.assertEqual(len(games), 2)
        self.assertIn('d4', games[-1])

    def test_oversized_game_rejected(self):
        with self.assertRaises(RuntimeError):
            list(fresh.pgn_chunks(io.StringIO('x' * 1_000_001)))

    def test_exclusion_contains_match_openings(self):
        self.assertGreaterEqual(len(fresh.excluded_positions()), 500)

    def test_teacher_white_perspective(self):
        board = fresh.chess.Board()
        board.push_uci('e2e4')
        engine = mock.Mock()
        engine.analyse.return_value = {'score': fresh.chess.engine.PovScore(fresh.chess.engine.Cp(-70), fresh.chess.BLACK),
            'pv': [fresh.chess.Move.from_uci('e7e5')], 'depth': 10, 'nodes': 5000}
        self.assertEqual(fresh.teacher_eval(engine, board, 5000)['cp'], 70)

    def test_mate_not_centipawns(self):
        engine = mock.Mock()
        engine.analyse.return_value = {'score': fresh.chess.engine.PovScore(fresh.chess.engine.Mate(2), fresh.chess.WHITE), 'pv': []}
        self.assertIsNone(fresh.teacher_eval(engine, fresh.chess.Board(), 5000)['cp'])


if __name__ == '__main__':
    unittest.main()
