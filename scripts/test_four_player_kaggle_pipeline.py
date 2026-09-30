from pathlib import Path
import unittest


from four_player_kaggle_pipeline import (
    TARGET_POSITIONS,
    Campaign,
    build_manifest,
    split_for_game,
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
        self.assertEqual(manifest["materialized_positions"], 512)
        counts = manifest["split_counts"]
        self.assertGreater(counts["train"], counts["validation"])
        self.assertGreater(counts["validation"], 0)
        self.assertGreater(counts["sealed-test"], 0)
        self.assertIn("pickle", manifest["artifact_policy"])

    def test_protocol_target_size_is_frozen(self) -> None:
        self.assertEqual(TARGET_POSITIONS, 500_000)


if __name__ == "__main__":
    unittest.main()
