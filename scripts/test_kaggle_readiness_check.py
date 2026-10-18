import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kaggle_readiness_check import collect_checks, validate_manifest


class KaggleReadinessCheckTests(unittest.TestCase):
    def test_missing_identity_blocks_only_identity_in_dry_run_mode(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "kaggle_readiness_check.kaggle_identity", return_value=None
        ):
            checks = collect_checks(dry_run_only=True)
        local = [check for check in checks if check.name != "kaggle identity"]
        identity = next(check for check in checks if check.name == "kaggle identity")
        self.assertTrue(all(check.ok for check in local))
        self.assertFalse(identity.ok)
        self.assertIn("still no Kaggle", identity.detail)

    def test_manifest_validation_accepts_dry_run_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "mode": "ffa",
                        "target_positions": 500_000,
                        "materialized_positions": 512,
                        "dry_run": True,
                        "split_counts": {
                            "train": 410,
                            "validation": 50,
                            "sealed-test": 52,
                        },
                        "records_sha256": "A" * 64,
                    }
                ),
                encoding="utf-8",
            )
            validate_manifest(manifest, "ffa")

    def test_manifest_validation_rejects_wrong_target_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "mode": "teams",
                        "target_positions": 123,
                        "materialized_positions": 512,
                        "dry_run": True,
                        "split_counts": {
                            "train": 410,
                            "validation": 50,
                            "sealed-test": 52,
                        },
                        "records_sha256": "B" * 64,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                validate_manifest(manifest, "teams")

    def test_manifest_validation_rejects_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text("{nope", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_manifest(manifest, "ffa")


if __name__ == "__main__":
    unittest.main()
