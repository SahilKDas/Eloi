import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "epv2_gauntlet", ROOT / "scripts/run_epv2_gauntlet.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EPV2GauntletTests(unittest.TestCase):
    def test_frozen_partitions_are_disjoint_and_sized(self):
        self.assertEqual(len(module.SCREEN_INDICES), 30)
        self.assertEqual(len(module.CONFIRMATION_INDICES), 100)
        self.assertFalse(set(module.SCREEN_INDICES) &
                         set(module.CONFIRMATION_INDICES))

    def test_schedule_is_mirrored(self):
        positions = [{"fen": str(index)} for index in range(270)]
        rows = module.schedule(module.SCREEN_INDICES, positions)
        self.assertEqual(len(rows), 60)
        for index in range(0, len(rows), 2):
            self.assertEqual(rows[index]["fen"], rows[index + 1]["fen"])
            self.assertNotEqual(rows[index]["candidate_white"],
                                rows[index + 1]["candidate_white"])


if __name__ == "__main__":
    unittest.main()
