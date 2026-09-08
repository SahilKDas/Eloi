import tempfile
import sys
import time
import unittest
from pathlib import Path

import caissa_adapter_parity as parity


class CaissaAdapterParityTests(unittest.TestCase):
    def test_info_parser_and_sanity(self):
        parsed = parity.parse_info(
            "info depth 7 score cp -42 nodes 1234 time 19 pv e2e4"
        )
        self.assertEqual(parsed["depth"], 7)
        self.assertEqual(parsed["score_kind"], "cp")
        result = {
            "bestmove": "e2e4",
            "parsed_info": parsed,
            "elapsed_ms": 25,
        }
        self.assertTrue(
            parity.probe_sanity(result, 1.0, require_info=True)["passed"]
        )

    def test_sanity_rejects_bad_move_score_and_timing(self):
        result = {
            "bestmove": "not-a-move",
            "parsed_info": {
                "depth": -1,
                "score_kind": "cp",
                "score_value": 32_000,
                "nodes": -1,
                "reported_time_ms": -1,
            },
            "elapsed_ms": 2_000,
        }
        checks = parity.probe_sanity(result, 1.0, require_info=True)
        self.assertFalse(checks["passed"])
        self.assertFalse(checks["uci_move_shape"])
        self.assertFalse(checks["score_or_mate_sane"])

    def test_depth_one_can_omit_optional_telemetry(self):
        result = {
            "bestmove": "e2e4",
            "parsed_info": None,
            "elapsed_ms": 25,
        }
        optional = parity.probe_sanity(
            result, 1.0, require_info=False
        )
        required = parity.probe_sanity(
            result, 1.0, require_info=True
        )
        self.assertTrue(optional["passed"])
        self.assertFalse(required["passed"])
        self.assertIsNone(optional["completed_search"])

    def test_info_parser_requires_score_and_counters(self):
        with self.assertRaises(parity.ProbeError):
            parity.parse_info("info depth 1 nodes 10 time 1")

    def test_default_cases_are_standard_and_stable(self):
        rows = parity.selected_cases(parity.DEFAULT_CASE_IDS)
        self.assertEqual([row["id"] for row in rows], list(parity.DEFAULT_CASE_IDS))
        self.assertTrue(all(len(row["fen"].split()) == 6 for row in rows))
        self.assertEqual(len(parity.CAISSA_COMMIT), 40)

    def test_unknown_case_is_rejected(self):
        with self.assertRaises(parity.ProbeError):
            parity.selected_cases(("not-a-real-case",))

    def test_identity_rejects_wrong_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            official = root / "official.exe"
            embedded = root / "embedded.exe"
            network = root / "network.pnn"
            for path in (official, embedded, network):
                path.write_bytes(b"wrong")
            with self.assertRaises(parity.ProbeError):
                parity.verify_inputs(official, embedded, network)

    def test_evidence_write_refuses_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            parity.write_evidence(output, {"first": True})
            with self.assertRaises(FileExistsError):
                parity.write_evidence(output, {"second": True})

    def test_watchdog_reports_an_os_level_child_crash(self):
        with self.assertRaisesRegex(parity.ProbeError, "engine exited"):
            parity.run_probe(
                Path(sys.executable), Path.cwd(),
                ["-c", "import os; os._exit(23)"],
                parity.INITIAL_FEN, "go depth 1", 1.0,
            )

    def test_watchdog_stops_a_hung_owned_child(self):
        started = time.monotonic()
        with self.assertRaisesRegex(parity.ProbeError, "timeout"):
            parity.run_probe(
                Path(sys.executable), Path.cwd(),
                ["-c", "import time; time.sleep(5)"],
                parity.INITIAL_FEN, "go depth 1", 0.1,
            )
        self.assertLess(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
