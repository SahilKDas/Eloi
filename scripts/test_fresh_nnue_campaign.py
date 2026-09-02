"""Fast checks for campaign inference and pre-match fail-closed behavior."""
import unittest
from unittest import mock
import run_fresh_nnue_campaign as campaign
import numpy as np
import subprocess
import time
import datetime as dt
import continue_fresh_nnue_campaign as continuation


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

    def test_learning_identity_ignores_unencoded_fen_fields(self):
        placement = campaign.chess.STARTING_FEN.split()[0]
        a = placement + ' w KQkq - 0 1'
        b = placement + ' b - - 20 30'
        self.assertEqual(campaign.learning_key(a), campaign.learning_key(b))
        board = campaign.chess.Board(a)
        board.push_uci('e2e4')
        self.assertNotEqual(campaign.learning_key(a), campaign.learning_key(board.fen()))

    def test_export_roundtrip_and_cpp_syntax(self):
        model = campaign.trainer.load_quantized_header(campaign.ROOT / 'include/eloi/nnue_weights.hpp')
        scratch = campaign.WORK / 'integrity-checks' / str(time.time_ns())
        scratch.mkdir(parents=True)
        campaign.data.preflight(5_000_000)
        header = scratch / 'weights.hpp'
        duplicate = scratch / 'duplicate.hpp'
        params = tuple(a.astype(np.float32) for a in model)
        counts = {'train_evaluations': 32000, 'train_pairs': 0}
        for output in (header, duplicate):
            campaign.trainer.write_header(output, *params, counts, set(),
                source_description='Offline label export integrity check')
        self.assertEqual(campaign.data.sha(header), campaign.data.sha(duplicate))
        for before, after in zip(model, campaign.trainer.load_quantized_header(header)):
            np.testing.assert_array_equal(before, after)
        compiler = campaign.MSYS + '/c++.exe'
        source = f'#include "{header.as_posix()}"\nstatic_assert(eloi::nnue_weights::input.size() == 6144 * 64);\nint main(){{return 0;}}\n'
        result = subprocess.run([compiler, '-std=c++2c', '-x', 'c++', '-fsyntax-only', '-'],
                                input=source, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_incomplete_match_does_not_pass(self):
        result = {'identity': {'games': 300, 'gate_metric': 'score', 'required_half_points': 330},
                  'results': [{'result': 'win', 'candidate_color': 'white'}] * 299}
        campaign.engine_lab.summarize_strength(result)
        self.assertFalse(result['passed'])

    def test_exact_final_threshold(self):
        result = {'identity': {'games': 300, 'gate_metric': 'score', 'required_half_points': 330},
                  'results': ([{'result': 'win', 'candidate_color': 'white'}] * 100
                              + [{'result': 'draw', 'candidate_color': 'black'}] * 130
                              + [{'result': 'loss', 'candidate_color': 'white'}] * 70)}
        campaign.engine_lab.summarize_strength(result)
        self.assertEqual(result['points'], 165)
        self.assertTrue(result['passed'])
        result['results'][100]['result'] = 'loss'
        campaign.engine_lab.summarize_strength(result)
        self.assertFalse(result['passed'])

    def test_continuation_rejects_different_protocol(self):
        with mock.patch.object(campaign, 'read', return_value={'original_protocol_sha256': 'expected'}), \
             mock.patch.object(campaign.data, 'sha', return_value='different'), \
             mock.patch.object(campaign.data, 'immutable_json') as write:
            with self.assertRaisesRegex(RuntimeError, 'not bound'):
                continuation.apply_runtime_extension()
            write.assert_not_called()

    def test_continuation_only_changes_runtime_clock(self):
        expected = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
        document = {'original_protocol_sha256': 'expected', 'runtime_deadline_utc': expected.isoformat(),
                    'scope': 'runtime only'}
        with mock.patch.object(campaign, 'read', return_value=document), \
             mock.patch.object(campaign.data, 'sha', side_effect=['expected', 'extension', 'wrapper']), \
             mock.patch.object(campaign.data, 'immutable_json') as write, \
             mock.patch.object(campaign.data, 'DEADLINE', campaign.data.DEADLINE):
            continuation.apply_runtime_extension()
            self.assertEqual(campaign.data.DEADLINE, expected)
            write.assert_called_once()


if __name__ == '__main__':
    unittest.main()
