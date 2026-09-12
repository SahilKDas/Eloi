import unittest

import safe_speed_benchmark as benchmark


class SafeSpeedBenchmarkTests(unittest.TestCase):
    def test_corpus_is_unique_legal_standard_chess(self):
        self.assertEqual(len(benchmark.FENS), len(set(benchmark.FENS)))
        self.assertTrue(all(benchmark.chess.Board(fen).is_valid() for fen in benchmark.FENS))

    def test_summary_passes_required_thresholds(self):
        rows = []
        for time_ms in benchmark.TIMES_MS:
            for label, nps, depth in (("baseline", 100.0, 8), ("candidate", 106.0, 8)):
                rows.append({"time_ms": time_ms, "engine": label, "nps": nps,
                             "nodes": nps, "depth": depth, "deadline_overrun": False})
        self.assertTrue(benchmark.summarize(rows)["gate"]["passed"])

    def test_summary_rejects_one_slow_tier_and_depth_loss(self):
        rows = []
        for time_ms in benchmark.TIMES_MS:
            rows.append({"time_ms": time_ms, "engine": "baseline", "nps": 100.0,
                         "nodes": 100, "depth": 8, "deadline_overrun": False})
            rows.append({"time_ms": time_ms, "engine": "candidate",
                         "nps": 97.0 if time_ms == 500 else 110.0,
                         "nodes": 100, "depth": 7 if time_ms == 1000 else 8,
                         "deadline_overrun": False})
        gate = benchmark.summarize(rows)["gate"]
        self.assertFalse(gate["no_tier_slower_than_two_percent"])
        self.assertFalse(gate["no_median_depth_reduction"])
        self.assertFalse(gate["passed"])


if __name__ == "__main__":
    unittest.main()
