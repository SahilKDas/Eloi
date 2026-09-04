import tempfile
import unittest
from pathlib import Path

import caissa_adapter_parity as parity


class CaissaAdapterParityTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
