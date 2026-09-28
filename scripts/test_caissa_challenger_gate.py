import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'challenger_gate', ROOT / 'scripts' / 'run_caissa_challenger_gate.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class ChallengerGateTests(unittest.TestCase):
    def test_schedule_is_400_mirrored_games(self):
        positions = [{'fen': f'fen-{index}'} for index in range(500)]
        rows = GATE.schedule(positions)
        self.assertEqual(len(rows), 400)
        for first, second in zip(rows[::2], rows[1::2]):
            self.assertEqual(first['fen'], second['fen'])
            self.assertNotEqual(first['candidate_white'], second['candidate_white'])

    def test_challenger_must_strictly_beat_baseline_points(self):
        baseline = {'completed': 400, 'score_points': 180.0}
        tied = {'completed': 400, 'score_points': 180.0}
        better = {'completed': 400, 'score_points': 180.5}
        self.assertFalse(GATE.qualification(tied, baseline)['passed'])
        self.assertTrue(GATE.qualification(better, baseline)['passed'])
        self.assertFalse(GATE.qualification(better, baseline)['beat_caissa'])

    def test_beating_caissa_requires_more_than_half(self):
        baseline = {'completed': 400, 'score_points': 190.0}
        even = {'completed': 400, 'score_points': 200.0}
        win = {'completed': 400, 'score_points': 200.5}
        self.assertFalse(GATE.qualification(even, baseline)['beat_caissa'])
        self.assertTrue(GATE.qualification(win, baseline)['beat_caissa'])

    def test_summary_keeps_frozen_denominator(self):
        partial = GATE.summarize([{'score': 1.0}, {'score': 0.5}])
        self.assertEqual(partial['completed'], 2)
        self.assertEqual(partial['score_points'], 1.5)
        self.assertEqual(partial['score_percent'], 100.0 * 1.5 / 400)


if __name__ == '__main__':
    unittest.main()
