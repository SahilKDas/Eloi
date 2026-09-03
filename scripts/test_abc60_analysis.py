"""In-memory tests for conservative interpretation of bounded diagnostics."""
import unittest

from summarize_abc60_diagnostics import interpret


def trace(complete=True):
    rows = [{"depth": depth, "selected_move": move, "score_cp": score, "pv": [move], "nodes": 10,
             "pruning": {}} for depth, move, score in [(1, "d4g7", 388), (3, "d4e5", 369)]]
    return {"iterations": rows, "final_result": rows[-1], "completed": complete, "requested_depth": 3,
            "static_eval_cp": 200, "total_nodes_consumed": 20}


class AnalysisTests(unittest.TestCase):
    def test_changed_move_is_not_forbidden_move(self):
        result = interpret(trace(), {"am": "d4d5", "stable": "1 3", "swing": "250"})
        self.assertFalse(result["same_move_at_stability_depths"])
        self.assertFalse(result["forbidden_move_repeated"])
        self.assertEqual(result["score_swing_cp"], 19)

    def test_censored_search_cannot_satisfy_tactical_target(self):
        result = interpret(trace(False), {"bm": "d4e5", "am": "d4d5"})
        self.assertIsNone(result["required_move_satisfied"])
        self.assertIsNone(result["forbidden_move_repeated"])

    def test_missing_depth_is_not_stability_success(self):
        result = interpret(trace(), {"stable": "5 7"})
        self.assertIsNone(result["same_move_at_stability_depths"])


if __name__ == "__main__":
    unittest.main()
