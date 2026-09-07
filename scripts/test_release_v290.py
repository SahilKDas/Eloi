"""Preservation-safe v2.9.0 release-preflight regression tests."""
from __future__ import annotations

import json
from pathlib import Path
import time
import unittest
import zipfile

import release_v290 as release


class ReleaseV290Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = release.ROOT / "tmp" / "release-v2.9.0-unit-fixtures"
        parent.mkdir(parents=True, exist_ok=True)
        cls.root = parent / f"case-{time.time_ns()}"
        cls.root.mkdir()

    def test_quota_refuses_every_limit(self):
        release.quota(1, 1, 1, 6_000_000_000)
        bad = (
            (10_000_000_001, 1, 1, 6_000_000_000, 0),
            (1, 7 * 1024**3 + 1, 1, 6_000_000_000, 0),
            (1, 1, 2_000_000_001, 6_000_000_000, 0),
            (1, 1, 1, 4_999_999_999, 0),
            (1, 1, 1_900_000_000, 6_000_000_000, 100_000_001),
        )
        for values in bad:
            with self.subTest(values=values), self.assertRaises(
                release.ReleasePreflightError
            ):
                release.quota(*values)

    def test_collisions_are_refused_without_changing_contents(self):
        scratch = release.ROOT / "tmp" / f"v290-collision-{time.time_ns()}"
        output = release.ROOT / "dist" / f"v290-collision-{time.time_ns()}"
        scratch.mkdir()
        marker = scratch / "keep.txt"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(
            release.ReleasePreflightError, "scratch collision"
        ):
            release.refuse_destination_collisions(scratch, output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_deterministic_archive_retains_sources_and_refuses_overwrite(self):
        first = self.root / "zip-first"
        second = self.root / "zip-second"
        first.mkdir(); second.mkdir()
        for folder, names in ((first, ("b.txt", "a.txt")),
                              (second, ("a.txt", "b.txt"))):
            for name in names:
                (folder / name).write_text(name, encoding="utf-8")
        a = self.root / "a.zip"
        b = self.root / "b.zip"
        release.deterministic_zip(first, a, 1787961600)
        release.deterministic_zip(second, b, 1787961600)
        self.assertEqual(release.sha256_file(a), release.sha256_file(b))
        self.assertTrue((first / "a.txt").is_file())
        with zipfile.ZipFile(a) as archive:
            self.assertEqual(archive.namelist(), ["a.txt", "b.txt"])
        with self.assertRaisesRegex(
            release.ReleasePreflightError, "archive collision"
        ):
            release.deterministic_zip(first, a, 1787961600)

    def test_blocked_policy_is_rejected(self):
        policy = release.ROOT / "packaging/v2.9.0-hybrid-package-policy.json"
        with self.assertRaisesRegex(
            release.ReleasePreflightError, "not marked ready"
        ):
            release.verify_technical_policy(
                policy,
                "22249DE582912F46F73F7CF7410D6D72ECCC77696B0B857E99B97A45F3F37116",
            )

    def test_ready_policy_binds_implementation_evidence(self):
        evidence = self.root / "implementation.json"
        evidence.write_text('{"passed":true}\n', encoding="utf-8")
        policy = self.root / "ready-policy.json"
        network_sha = "A" * 64
        document = {
            "schema": release.POLICY_SCHEMA,
            "target_version": release.TARGET_VERSION,
            "status": "ready",
            "network_sha256": network_sha,
            "network_delivery": "embedded",
            "runtime_external_network_required": False,
            "runtime_downloads": False,
            "cmake_option": "ELOI_ENABLE_CAISSA_PRODUCTION",
            "threads_per_brain": 3,
            "verified_package_forms": list(release.REQUIRED_FORMS),
            "implementation_evidence": evidence.name,
            "implementation_evidence_sha256": release.sha256_file(evidence),
        }
        policy.write_text(json.dumps(document), encoding="utf-8")
        result = release.verify_technical_policy(policy, network_sha)
        self.assertEqual(result["status"], "passed")
        evidence.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(
            release.ReleasePreflightError, "differs from policy"
        ):
            release.verify_technical_policy(policy, network_sha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
