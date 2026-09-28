import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gauntlet", ROOT / "scripts/run_faloi_variant_gauntlet.py")
gauntlet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gauntlet)


class VariantGauntletScheduleTests(unittest.TestCase):
    def test_confirmation_partition_is_disjoint_from_screen(self):
        for variant in ("chess960", "atomic", "antichess"):
            screen = gauntlet.schedule(variant, 60, 0)
            confirmation = gauntlet.schedule(variant, 200, 30)
            self.assertTrue({row["fen"] for row in screen}.isdisjoint(
                {row["fen"] for row in confirmation}))

    def test_schedule_is_mirrored(self):
        rows = gauntlet.schedule("atomic", 4, 30)
        self.assertEqual(4, len(rows))
        self.assertEqual(rows[0]["fen"], rows[1]["fen"])
        self.assertEqual(rows[2]["fen"], rows[3]["fen"])
        self.assertTrue(rows[0]["candidate_white"])
        self.assertFalse(rows[1]["candidate_white"])
        self.assertEqual([31, 31, 32, 32], [row["pair"] for row in rows])


if __name__ == "__main__":
    unittest.main()
