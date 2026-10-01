from pathlib import Path
import json
import tempfile
import unittest

import four_player_kaggle_real_pipeline as pipeline


class FourPlayerKaggleRealPipelineTests(unittest.TestCase):
    def test_initial_position_has_four_armies_and_legal_moves(self) -> None:
        position = pipeline.initial_position("ffa")
        self.assertEqual(len(position.board), 64)
        self.assertGreater(len(pipeline.legal_moves(position)), 0)

    def test_generated_records_are_teacher_labeled_self_play(self) -> None:
        campaign = pipeline.Campaign(
            mode="teams",
            seed=12345,
            target_positions=pipeline.TARGET_POSITIONS,
            output=Path("unused"),
            dry_run=True,
        )
        record = next(pipeline.generate_records(campaign, 1))
        self.assertEqual(record["teacher_kind"], "deterministic-four-player-handcrafted-search-v1")
        self.assertEqual(record["label_status"] if "label_status" in record else record["schema"], 2)
        self.assertIn("pieces", record)
        self.assertIn("policy_target", record)
        self.assertIn("teacher_score", record)

    def test_dry_run_manifest_marks_real_teacher_labels(self) -> None:
        campaign = pipeline.Campaign(
            mode="ffa",
            seed=999,
            target_positions=pipeline.TARGET_POSITIONS,
            output=Path("unused"),
            dry_run=True,
        )
        manifest = pipeline.build_manifest(campaign)
        self.assertEqual(manifest["label_status"], "self-play-handcrafted-teacher-labels")
        self.assertEqual(manifest["materialized_positions"], pipeline.DRY_RUN_COUNT)
        self.assertGreater(manifest["split_counts"]["train"], 0)
        self.assertGreater(manifest["split_counts"]["validation"], 0)
        self.assertGreater(manifest["split_counts"]["sealed-test"], 0)

    def test_dry_run_writes_jsonl_shards(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eloi-v4-real-pipeline-") as temporary:
            campaign = pipeline.Campaign(
                mode="ffa",
                seed=111,
                target_positions=pipeline.TARGET_POSITIONS,
                output=Path(temporary),
                dry_run=True,
            )
            shards = pipeline.write_records(campaign, shard_size=128)
            self.assertEqual(len(shards), 4)
            first = json.loads(shards[0].read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(first["mode"], "ffa")
            self.assertEqual(first["schema"], 2)


if __name__ == "__main__":
    unittest.main()
