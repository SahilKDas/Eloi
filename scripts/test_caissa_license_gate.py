import json
from pathlib import Path
import tempfile
import unittest

import caissa_license_gate as gate


class CaissaLicenseGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.network = self.root / "test.pnn"
        self.network.write_bytes(b"licensed-network")
        self.evidence = self.root / "permission.txt"
        self.evidence.write_text(
            "The rights holder grants all listed rights.\n",
            encoding="utf-8",
        )
        self.manifest = self.root / "permission.json"
        self.document = {
            "schema": gate.SCHEMA,
            "network": {
                "id": "test-network-v1",
                "filename": self.network.name,
                "source_url": "https://rights-holder.example/network",
                "bytes": self.network.stat().st_size,
                "sha256": gate.sha256_file(self.network),
            },
            "permission": {
                "granted": True,
                "grantor": "The rights holder",
                "source_url": "https://rights-holder.example/permission",
                "summary": "Explicit permission for Eloi redistribution.",
                "evidence_path": self.evidence.name,
                "evidence_sha256": gate.sha256_file(self.evidence),
                "artifact_modes": ["standalone", "exoskeleton"],
                "rights": {
                    right: True for right in gate.REQUIRED_RIGHTS
                },
            },
        }
        self._write_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_manifest(self):
        self.manifest.write_text(
            json.dumps(self.document), encoding="utf-8"
        )

    def test_valid_exact_artifact_passes_both_package_forms(self):
        for mode in sorted(gate.ARTIFACT_MODES):
            result = gate.verify_gate(
                self.manifest, self.network, mode
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                result["network_sha256"],
                gate.sha256_file(self.network),
            )

    def test_permission_must_be_explicit(self):
        self.document["permission"]["granted"] = False
        self._write_manifest()
        with self.assertRaisesRegex(
            gate.LicenseGateError, "not explicitly granted"
        ):
            gate.verify_gate(
                self.manifest, self.network, "standalone"
            )

    def test_every_required_right_is_enforced(self):
        for right in gate.REQUIRED_RIGHTS:
            with self.subTest(right=right):
                self.document["permission"]["rights"][right] = False
                self._write_manifest()
                with self.assertRaisesRegex(
                    gate.LicenseGateError, right
                ):
                    gate.verify_gate(
                        self.manifest, self.network, "standalone"
                    )
                self.document["permission"]["rights"][right] = True

    def test_network_tampering_is_rejected(self):
        self.network.write_bytes(b"short")
        with self.assertRaisesRegex(
            gate.LicenseGateError, "size differs"
        ):
            gate.verify_gate(
                self.manifest, self.network, "standalone"
            )

    def test_same_size_network_tampering_is_rejected(self):
        data = bytearray(self.network.read_bytes())
        data[0] ^= 1
        self.network.write_bytes(data)
        with self.assertRaisesRegex(
            gate.LicenseGateError, "SHA-256 differs"
        ):
            gate.verify_gate(
                self.manifest, self.network, "standalone"
            )

    def test_evidence_tampering_is_rejected(self):
        self.evidence.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(
            gate.LicenseGateError, "evidence SHA-256 differs"
        ):
            gate.verify_gate(
                self.manifest, self.network, "standalone"
            )

    def test_artifact_scope_is_enforced(self):
        self.document["permission"]["artifact_modes"] = ["standalone"]
        self._write_manifest()
        with self.assertRaisesRegex(
            gate.LicenseGateError, "exoskeleton"
        ):
            gate.verify_gate(
                self.manifest, self.network, "exoskeleton"
            )

    def test_placeholder_is_rejected(self):
        self.document["permission"]["source_url"] = (
            "https://example.invalid/TODO"
        )
        self._write_manifest()
        with self.assertRaisesRegex(
            gate.LicenseGateError, "placeholder"
        ):
            gate.verify_gate(
                self.manifest, self.network, "standalone"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
