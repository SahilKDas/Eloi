import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "teacher_dataset", ROOT / "scripts/build_eloi_teacher_dataset.py")
DATASET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATASET)


class TeacherDatasetTests(unittest.TestCase):
    def test_partition_is_deterministic_and_complete(self):
        observed = {DATASET.assigned_partition(f"game-{i}", "seed") for i in range(200)}
        self.assertEqual(observed, set(DATASET.PARTITIONS))
        self.assertEqual(DATASET.assigned_partition("same", "seed"),
                         DATASET.assigned_partition("same", "seed"))

    def test_source_partition_and_group_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "roots.jsonl"
            path.write_text(
                '{"record_id":"a","group_id":"game","partition":"test",'
                '"fen":"8/8/8/8/8/3k4/8/R2K4 w - - 0 1"}\n', encoding="utf-8")
            rows = DATASET.load_roots(path, 10, "seed")
            self.assertEqual(rows[0]["partition"], "test")
            self.assertEqual(rows[0]["group_id"], "game")

    def test_candidates_always_include_both_brains(self):
        board = DATASET.chess.Board()
        moves = DATASET.candidate_moves(board, "e2e4", "d2d4", 2, "seed", "id")
        self.assertEqual(moves, ["d2d4", "e2e4"])

    def test_policy_is_normalized_and_teacher_ranked(self):
        policy = DATASET.policy_targets([("a2a3", -80), ("e2e4", 30), ("d2d4", 10)])
        self.assertEqual(policy[0]["move"], "e2e4")
        self.assertAlmostEqual(sum(row["probability"] for row in policy), 1.0, places=7)

    def test_wdl_is_normalized_and_monotonic(self):
        losing = DATASET.wdl_target(-300)
        winning = DATASET.wdl_target(300)
        self.assertGreater(winning["win"], losing["win"])
        self.assertAlmostEqual(sum(winning.values()), 1.0, places=7)

    def test_illegal_brain_move_is_rejected(self):
        with self.assertRaises(DATASET.DatasetError):
            DATASET.candidate_moves(DATASET.chess.Board(), "e2e5", "e2e4", 8, "s", "r")


if __name__ == "__main__":
    unittest.main(verbosity=2)
