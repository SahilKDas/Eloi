import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import benchmark_caissa_speed as benchmark


class BenchmarkCaissaSpeedTests(unittest.TestCase):
    def test_corpus_is_standard_and_unique(self):
        self.assertEqual(len(benchmark.FENS), len(set(benchmark.FENS)))
        for fen in benchmark.FENS:
            board = benchmark.chess.Board(fen)
            self.assertTrue(board.is_valid())
            self.assertFalse(board.chess960)


if __name__ == "__main__":
    unittest.main()
