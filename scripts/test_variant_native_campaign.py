import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("campaign", ROOT / "scripts/variant_native_campaign.py")
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


class VariantCampaignTests(unittest.TestCase):
    def test_partition_is_deterministic(self):
        self.assertEqual(campaign.partition_for("atomic", 7),
                         campaign.partition_for("atomic", 7))

    def test_feature_encoding_supports_missing_antichess_king(self):
        board = campaign.chess.variant.AntichessBoard("8/8/8/8/8/8/P7/7k w - - 0 1")
        values = campaign.feature_indices(board, campaign.chess.WHITE)
        self.assertGreater(len(values), 0)
        self.assertTrue((values >= 0).all())

    def test_protocols_are_variant_isolated(self):
        hashes = {campaign.protocol_hash(variant) for variant in campaign.VARIANTS}
        self.assertEqual(3, len(hashes))

    def test_exact_quotas(self):
        self.assertEqual(100_000, sum(campaign.QUOTAS.values()))
        self.assertEqual({"train": 80_000, "validation": 10_000, "test": 10_000},
                         campaign.QUOTAS)

    def test_sealed_test_evidence_is_distinct_from_selection_evidence(self):
        self.assertNotEqual("training.json", "sealed-test.json")
        self.assertEqual(10_000, campaign.QUOTAS["test"])


if __name__ == "__main__":
    unittest.main()
