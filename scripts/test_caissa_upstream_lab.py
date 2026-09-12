import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import caissa_upstream_lab as lab


class CaissaUpstreamLabTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.release = lab.load_release(
            lab.DEFAULT_MANIFEST, "1.26"
        )

    def test_126_is_source_only_and_not_redistributable(self):
        self.assertEqual(self.release["status"], "source-only-lab")
        self.assertEqual(self.release["evaluator_family"], "SCReLU eval-82")
        self.assertFalse(self.release["network_redistributable"])
        self.assertNotEqual(
            self.release["required_network"],
            self.manifest["releases"]["1.25"]["required_network"],
        )

    def test_missing_model_blocks_runnable_lab_and_promotion(self):
        model = lab.model_inventory(None, self.release)
        evidence = {"model": model, "qualification_gates": {},
                    "confirmation_score_percent": None}
        decision = lab.promotion_decision(self.manifest, self.release, evidence)
        self.assertFalse(model["runnable"])
        self.assertFalse(decision["eligible"])

    def test_wrong_generation_filename_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            wrong = Path(directory) / "eval-71-v1.25.pnn"
            wrong.write_bytes(b"not a 1.26 model")
            with self.assertRaisesRegex(lab.LabError, "filename"):
                lab.model_inventory(wrong, self.release)

    def test_unpinned_model_hash_cannot_be_runnable(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / self.release["required_network"]
            model.write_bytes(b"locally supplied")
            row = lab.model_inventory(model, self.release)
            self.assertTrue(row["present"])
            self.assertFalse(row["matching_identity"])
            self.assertFalse(row["runnable"])

    def test_score_must_be_strictly_above_fifty(self):
        release = dict(self.release, network_redistributable=True)
        base = {"model": {"matching_identity": True},
                "qualification_gates": {"all": True}}
        self.assertFalse(lab.promotion_decision(
            self.manifest, release,
            dict(base, confirmation_score_percent=50.0))["eligible"])
        self.assertTrue(lab.promotion_decision(
            self.manifest, release,
            dict(base, confirmation_score_percent=50.01))["eligible"])

    def test_evidence_write_refuses_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            lab.write_evidence(output, {"first": True})
            with self.assertRaises(FileExistsError):
                lab.write_evidence(output, {"second": True})

    @mock.patch("caissa_upstream_lab.subprocess.run")
    def test_repository_model_must_be_ignored(self, run):
        run.return_value = subprocess.CompletedProcess([], 1)
        path = lab.ROOT / self.release["required_network"]
        with mock.patch.object(Path, "is_file", return_value=True):
            with self.assertRaisesRegex(lab.LabError, "gitignored"):
                lab.model_inventory(path, self.release)


if __name__ == "__main__":
    unittest.main()
