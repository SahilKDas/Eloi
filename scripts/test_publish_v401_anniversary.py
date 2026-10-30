"""Offline tests: never wait, connect, publish, or inspect credentials."""
import copy
import datetime as dt
import hashlib
import json
import pathlib
import unittest
from unittest.mock import patch

import publish_v401_anniversary as publisher
from publish_v401_anniversary import GATES, NAMES, TARGET, validate_release


class PublicationGateTests(unittest.TestCase):
    def setUp(self):
        self.commit = "a" * 40
        self.proof = {"source_commit": self.commit, "publish_at": TARGET.isoformat(),
                      "gates": dict.fromkeys(GATES, True), "sha256": dict.fromkeys(NAMES, "b" * 64)}
        self.release = {"tag_name": "v4.0.1", "name": "Eloi v4.0.1", "draft": True,
                        "prerelease": False, "assets": [
                            {"name": name, "state": "uploaded", "size": 123,
                             "digest": "sha256:" + "b" * 64} for name in sorted(NAMES)]}
        self.update_body()

    def update_body(self):
        self.release["body"] = "<!-- eloi-v401-gate: " + json.dumps(self.proof) + " -->"

    def test_complete_exact_source_proof(self):
        self.assertEqual(validate_release(self.release, self.commit), self.proof)

    def test_draft_lookup_uses_authenticated_paginated_listing(self):
        for pages, valid in [([[{"tag_name": "old"}], [self.release]], True),
                             ([[self.release, self.release]], False), ([[]], False)]:
            with patch.object(publisher, "gh", return_value=json.dumps(pages)) as call:
                if valid:
                    self.assertEqual(publisher.fetch_release(), self.release)
                else:
                    with self.assertRaises(ValueError):
                        publisher.fetch_release()
                self.assertIn("--slurp", call.call_args.args)

    def test_each_missing_or_failed_gate_blocks(self):
        for gate in GATES:
            for value in [False, "true", None]:
                with self.subTest(gate=gate, value=value):
                    self.proof["gates"][gate] = value
                    self.update_body()
                    with self.assertRaises(ValueError):
                        validate_release(self.release, self.commit)
                    self.proof["gates"][gate] = True

    def test_wrong_identity_assets_and_digest_block(self):
        for key, value in [("draft", False), ("prerelease", True), ("tag_name", "v4.0.0"),
                           ("name", "oops"), ("body", "no proof"), ("assets", [])]:
            bad = copy.deepcopy(self.release)
            bad[key] = value
            with self.assertRaises(ValueError):
                validate_release(bad, self.commit)
        self.release["assets"][0]["digest"] = "sha256:" + "c" * 64
        with self.assertRaises(ValueError):
            validate_release(self.release, self.commit)

    def test_wrong_commit_time_and_hash_block(self):
        for key, value in [("source_commit", "d" * 40), ("publish_at", "2026-10-30T04:00:00+00:00"),
                           ("sha256", dict.fromkeys(NAMES, "not-a-hash"))]:
            original = self.proof[key]
            self.proof[key] = value
            self.update_body()
            with self.assertRaises(ValueError):
                validate_release(self.release, self.commit)
            self.proof[key] = original

    def test_waits_until_target_and_publishes_only_after_download_verification(self):
        data = b"offline golden fixture"
        digest = hashlib.sha256(data).hexdigest()
        self.proof["sha256"] = dict.fromkeys(NAMES, digest)
        self.release["id"] = 10
        for i, asset in enumerate(self.release["assets"]):
            asset.update(id=i, updated_at="frozen", digest="sha256:" + digest)
        self.update_body()
        final = copy.deepcopy(self.release)
        final.update(draft=False, html_url="https://github.com/SahilKDas/Eloi/releases/tag/v4.0.1")

        class Clock(dt.datetime):
            current = TARGET - dt.timedelta(seconds=1)

            @classmethod
            def now(cls, tz=None):
                return cls.current

        calls = []

        def fake_gh(*args):
            calls.append(args)
            if args[:2] == ("release", "download"):
                folder = pathlib.Path(args[args.index("--dir") + 1])
                for name in NAMES:
                    (folder / name).write_bytes(data)
            if args[:2] == ("release", "edit"):
                self.assertGreaterEqual(Clock.current, TARGET)
            return ""

        def advance(seconds):
            Clock.current += dt.timedelta(seconds=seconds)

        with patch.object(publisher.dt, "datetime", Clock), \
             patch.object(publisher.time, "sleep", advance), \
             patch.object(publisher, "fetch_release", side_effect=[self.release, self.release, final]), \
             patch.object(publisher, "gh", side_effect=fake_gh), \
             patch("sys.argv", ["publish", "--commit", self.commit]):
            publisher.main()
        self.assertEqual(sum(args[:2] == ("release", "edit") for args in calls), 1)
        # The maintainer may explicitly prioritize quality over the clock.
        # This permits late publication, never early or without the same gates.
        self.proof["late_release_authorized"] = True
        self.update_body()
        final = copy.deepcopy(self.release)
        final.update(draft=False, html_url="https://github.com/SahilKDas/Eloi/releases/tag/v4.0.1")
        Clock.current = TARGET + dt.timedelta(minutes=2)
        calls.clear()
        with patch.object(publisher.dt,"datetime",Clock), \
             patch.object(publisher.time,"sleep",advance), \
             patch.object(publisher,"fetch_release",side_effect=[self.release,self.release,final]), \
             patch.object(publisher,"gh",side_effect=fake_gh), \
             patch("sys.argv",["publish","--commit",self.commit,"--allow-late"]):
            publisher.main()
        self.assertEqual(sum(args[:2] == ("release", "edit") for args in calls), 1)

    def test_late_start_never_contacts_github(self):
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return TARGET

        with patch.object(publisher.dt, "datetime", Clock), \
             patch.object(publisher, "gh") as call, \
             patch("sys.argv", ["publish", "--commit", self.commit]):
            with self.assertRaises(SystemExit):
                publisher.main()
            call.assert_not_called()

    def test_late_override_requires_explicit_proof_before_any_asset_download(self):
        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return TARGET + dt.timedelta(minutes=2)
        with patch.object(publisher.dt,"datetime",Clock), \
             patch.object(publisher,"fetch_release",return_value=self.release), \
             patch.object(publisher,"gh") as call, \
             patch("sys.argv",["publish","--commit",self.commit,"--allow-late"]):
            with self.assertRaises(SystemExit):
                publisher.main()
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
