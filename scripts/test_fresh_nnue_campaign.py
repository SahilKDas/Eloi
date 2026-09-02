"""Fast checks for campaign inference and pre-match fail-closed behavior."""
import unittest
from unittest import mock
import run_fresh_nnue_campaign as campaign
import numpy as np


class CampaignTests(unittest.TestCase):
    def test_production_weights_identity(self):
        path = campaign.ROOT / 'include/eloi/nnue_weights.hpp'
        self.assertEqual(campaign.data.sha(path), campaign.data.WEIGHTS)

    def test_default_header_source_unchanged(self):
        import inspect
        self.assertEqual(inspect.signature(campaign.trainer.write_header).parameters['source_description'].default,
                         'Lichess CC0 evaluations and puzzles; see provenance JSON')

    def test_quantized_reference_equals_production_header(self):
        model = campaign.trainer.load_quantized_header(campaign.ROOT / 'include/eloi/nnue_weights.hpp')
        float_model = tuple(a.astype(np.float32) for a in model)
        board = campaign.chess.Board()
        white = campaign.trainer.features(board, campaign.chess.WHITE)
        black = campaign.trainer.features(board, campaign.chess.BLACK)
        score = campaign.trainer.forward_quantized(*model, white, black)[0]
        report = campaign.regression_metrics(float_model, [(white, black, score, 1.0, {'phase_bucket': 'opening'})])
        self.assertEqual(report['mae_cp'], 0)

    def test_unqualified_candidate_never_starts_match(self):
        with mock.patch.object(campaign, 'read', side_effect=[{}, {'eligible': False}]), \
             mock.patch.object(campaign, 'run_command') as run:
            with self.assertRaisesRegex(RuntimeError, 'not eligible'):
                campaign.match('fixture', 'final')
            run.assert_not_called()

    def test_wrong_baseline_never_starts_match(self):
        protocol = {'baseline_sha256': 'official'}
        with mock.patch.object(campaign, 'read', side_effect=[protocol, {'eligible': True, 'binary_sha256': 'candidate'}]), \
             mock.patch.object(campaign.data, 'sha', side_effect=['candidate', 'wrong']), \
             mock.patch.object(campaign, 'run_command') as run:
            with self.assertRaisesRegex(RuntimeError, 'published v2.0'):
                campaign.match('fixture', 'final')
            run.assert_not_called()

    def test_test_labels_excluded_by_default(self):
        import inspect
        self.assertFalse(inspect.signature(campaign.load_evaluations).parameters['include_test'].default)


if __name__ == '__main__':
    unittest.main()
