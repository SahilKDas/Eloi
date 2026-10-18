from pathlib import Path
import json
import tempfile
import unittest


from four_player_kaggle_pipeline import (
    DRY_RUN_COUNT,
    TARGET_POSITIONS,
    Campaign,
    build_manifest,
    split_for_game,
    write_records,
)


class FourPlayerKagglePipelineTests(unittest.TestCase):
    def test_source_game_split_is_deterministic(self) -> None:
        game = "00000008abcdef0000000000"
        self.assertEqual(split_for_game(game), "validation")
        self.assertEqual(split_for_game(game), "validation")

    def test_dry_run_manifest_keeps_sealed_test_separate(self) -> None:
        manifest = build_manifest(
            Campaign(
                mode="ffa",
                seed=1234,
                target_positions=TARGET_POSITIONS,
                output=Path("unused"),
                dry_run=True,
            )
        )
        self.assertIs(manifest["dry_run"], True)
        self.assertEqual(manifest["materialized_positions"], DRY_RUN_COUNT)
        self.assertEqual(manifest["label_status"], "bootstrap-not-final-teacher-labels")
        counts = manifest["split_counts"]
        self.assertGreater(counts["train"], counts["validation"])
        self.assertGreater(counts["validation"], 0)
        self.assertGreater(counts["sealed-test"], 0)
        self.assertIn("pickle", manifest["artifact_policy"])

    def test_dry_run_writes_jsonl_record_shards(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eloi-four-player-test-") as temporary:
            campaign = Campaign(
                mode="teams",
                seed=4321,
                target_positions=TARGET_POSITIONS,
                output=Path(temporary),
                dry_run=True,
            )
            shards = write_records(campaign, shard_size=128)
            self.assertEqual(len(shards), 4)
            first = json.loads(shards[0].read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(first["schema"], 1)
            self.assertEqual(first["mode"], "teams")
            self.assertEqual(first["teacher_kind"], "bootstrap-handcrafted-baseline")
            self.assertIn(first["split"], {"train", "validation", "sealed-test"})

    def test_protocol_target_size_is_frozen(self) -> None:
        self.assertEqual(TARGET_POSITIONS, 500_000)


if __name__ == "__main__":
    unittest.main()
