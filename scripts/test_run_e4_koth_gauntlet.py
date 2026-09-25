import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_e4_koth_gauntlet import schedule, summarize


class KothGauntletTests(unittest.TestCase):
    def test_sixty_game_schedule_is_thirty_mirrored_pairs(self):
        games = schedule(60)
        self.assertEqual(len(games), 60)
        for offset in range(0, 60, 2):
            self.assertEqual(games[offset]["fen"], games[offset + 1]["fen"])
            self.assertTrue(games[offset]["candidate_white"])
            self.assertFalse(games[offset + 1]["candidate_white"])

    def test_score_percentage_uses_frozen_denominator(self):
        results = ([{"score": 1.0}] * 20 + [{"score": 0.5}] * 22 +
                   [{"score": 0.0}] * 18)
        summary = summarize(results, 60)
        self.assertEqual(summary["score_points"], 31.0)
        self.assertAlmostEqual(summary["score_percent"], 51.6666666667)

    def test_odd_schedule_is_rejected(self):
        with self.assertRaises(ValueError):
            schedule(59)


if __name__ == "__main__":
    unittest.main()
