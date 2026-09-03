"""In-memory and small preserved-fixture release-tooling regression tests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import release_v250 as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        parent = release.WORK / "unit-fixtures"
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=parent))
        self.guard = patch.object(release, "resources", return_value={})
        self.guard.start()

    def tearDown(self):
        self.guard.stop()  # Deliberately retain every fixture; never delete.

    def test_quota_refuses_each_limit(self):
        release.quota(1, 1, 1, 6_000_000_000)
        for values in ((10_000_000_001, 1, 1, 6_000_000_000),
                       (1, 7 * 1024**3 + 1, 1, 6_000_000_000),
                       (1, 1, 2_000_000_001, 6_000_000_000),
                       (1, 1, 1, 4_999_999_999),
                       (1, 1, 1_900_000_000, 6_000_000_000, 100_000_001)):
            with self.assertRaises(RuntimeError):
                release.quota(*values)

    def test_copy_refuses_collision_preserves_original(self):
        source, target = self.root / "source", self.root / "target"
        source.write_bytes(b"new")
        target.write_bytes(b"old")
        with self.assertRaises(RuntimeError):
            release.copy_new(source, target)
        self.assertEqual(target.read_bytes(), b"old")

    def test_deterministic_zip_and_preserved_sources(self):
        first, second = self.root / "first", self.root / "second"
        first.mkdir(); second.mkdir()
        for folder, names in ((first, ("b.txt", "a.txt")), (second, ("a.txt", "b.txt"))):
            for name in names:
                (folder / name).write_bytes(name.encode())
        os.utime(second / "a.txt", (1_000_000_000, 1_000_000_000))
        release.deterministic_zip(first, self.root / "a.zip", 1787961600)
        release.deterministic_zip(second, self.root / "b.zip", 1787961600)
        self.assertEqual(release.sha(self.root / "a.zip"), release.sha(self.root / "b.zip"))
        self.assertTrue((first / "a.txt").exists())
        with zipfile.ZipFile(self.root / "a.zip") as archive:
            self.assertEqual(archive.namelist(), ["a.txt", "b.txt"])
        with self.assertRaises(RuntimeError):
            release.deterministic_zip(first, self.root / "a.zip", 1787961600)

    def test_extraction_refuses_collision_and_traversal(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "x") as zipped:
            zipped.writestr("../escape", "no")
        with self.assertRaises(RuntimeError):
            release.extract_new(archive, self.root / "out")
        with self.assertRaises(RuntimeError):
            release.extract_new(archive, self.root)
        self.assertFalse((self.root / "escape").exists())

    def test_standalone_contents_and_empty_token(self):
        folder = self.root / "package"
        folder.mkdir()
        (folder / "Eloi.exe").write_bytes(b"test fixture, not an executable")
        (folder / "config.yml").write_bytes((release.ROOT / "config.example.yml").read_bytes())
        release.package_files_valid(folder, False)
        (folder / "unwanted.txt").write_bytes(b"not allowed")
        with self.assertRaises(RuntimeError):
            release.package_files_valid(folder, False)
        (folder / "config.yml").write_text('token: "test_secret_not_real"')
        with self.assertRaises(RuntimeError):
            release.package_files_valid(folder, False)


if __name__ == "__main__":
    unittest.main()
