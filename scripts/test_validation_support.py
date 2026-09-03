import tempfile
import unittest
from pathlib import Path

import validation_support as support


class ValidationSupportTests(unittest.TestCase):
    def test_current_suite_depths_and_required_operations(self):
        cases = {row['id']: row for row in support.epd_cases()}
        self.assertEqual(len(cases), 15)
        self.assertEqual(cases['lichess-001XA']['depth'], 7)
        self.assertEqual(cases['lichess-001XA']['operations']['bm'], 'b1b7')
        self.assertEqual(cases['poisoned-pawn-capture']['depth'], 3)
        self.assertIn('stable', cases['free-queen-capture']['operations'])

    def test_limits(self):
        support.check_limits(1, 1, 1, 6_000_000_000, 1)
        for args in ((1, 1, 1, 6_000_000_000, -1),
                     (10_000_000_000, 1, 1, 6_000_000_000, 1),
                     (1, 7 * 1024**3 + 1, 1, 6_000_000_000, 0),
                     (1, 1, 2_000_000_000, 6_000_000_000, 1),
                     (1, 1, 1, 5_000_000_000, 1)):
            with self.assertRaises(ValueError):
                support.check_limits(*args)

    def test_refuses_broad_or_outside_scratch_roots(self):
        for path in (support.ROOT, support.ROOT / 'tmp', Path(tempfile.gettempdir()), support.ROOT / 'src'):
            with self.assertRaises(ValueError):
                support.resource_snapshot(path)


if __name__ == '__main__':
    unittest.main()
