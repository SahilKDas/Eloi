import unittest

import validate_v290_regressions as validation


def result(move, score, pv=None, strings=None):
    return {
        "bestmove": move,
        "last_info": (
            f"info depth 3 score cp {score} nodes 10 time 1 pv "
            + " ".join(pv or [move])
        ),
        "parsed_info": {
            "depth": 3, "score_kind": "cp", "score_value": score,
            "nodes": 10, "reported_time_ms": 1,
        },
        "elapsed_ms": 2,
        "info_strings": strings or ["info string E2 and Caissa agreed"],
    }


class V290RegressionValidationTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "id": "fixture",
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "depth": 3,
            "operations": {"stable": "1 3", "bm": "e2e4", "swing": "50"},
        }

    def test_stable_legal_hybrid_result_passes(self):
        row = validation.evaluate_case(
            self.case,
            {1: result("e2e4", 10), 3: result("e2e4", 20)},
        )
        self.assertTrue(row["passed"])

    def test_stable_move_change_and_large_swing_fail(self):
        row = validation.evaluate_case(
            self.case,
            {1: result("d2d4", -100), 3: result("e2e4", 20)},
        )
        self.assertFalse(row["passed"])
        self.assertTrue(any("changed" in item for item in row["failures"]))
        self.assertTrue(any("swing" in item for item in row["failures"]))

    def test_compare_allows_legal_move_refinement(self):
        self.case["operations"] = {
            "compare": "1 3", "bm": "e2e4", "swing": "250"
        }
        row = validation.evaluate_case(
            self.case,
            {1: result("d2d4", 5), 3: result("e2e4", 20)},
        )
        self.assertTrue(row["passed"])

    def test_forbidden_illegal_pv_and_missing_route_fail(self):
        self.case["operations"] = {"acd": "3", "am": "e2e4"}
        bad = result("e2e4", 0, ["e2e4", "e1e8"], ["info string unrelated"])
        row = validation.evaluate_case(self.case, {3: bad})
        self.assertFalse(row["passed"])
        self.assertGreaterEqual(len(row["failures"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
