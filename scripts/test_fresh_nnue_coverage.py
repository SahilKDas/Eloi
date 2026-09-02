import unittest
import report_fresh_nnue_coverage as coverage


class CoverageTests(unittest.TestCase):
    def row(self, partition='train', placement='board'):
        return {'partition': partition, 'accepted': True, 'fen': placement + ' w - - 0 1',
                'phase': 'middlegame', 'group': partition + '-game',
                'high': {'cp': -200, 'depth': 12}, 'audit_100k': {'cp': -220}}

    def test_held_out_targets_are_never_needed(self):
        rows = [self.row('validation'), self.row('test')]
        for row in rows:
            del row['high']
            del row['audit_100k']
        result = coverage.summarize(rows)
        self.assertEqual(result['counts']['usable'], 2)
        self.assertEqual(result['training_100k_audit']['count'], 0)

    def test_exclusions_apply_before_target_access(self):
        row = self.row()
        del row['high']
        result = coverage.summarize([row], {'board'})
        self.assertEqual(result['counts']['accepted_identity_exclusions'], 1)
        self.assertEqual(result['usable_partitions'], {})

    def test_training_only_audit_and_rejections(self):
        rejected = dict(self.row(), accepted=False, reasons=['unstable_teacher_score', 'tactical_best_move'])
        result = coverage.summarize([self.row(), rejected])
        self.assertEqual(result['training_100k_audit']['median_absolute_drift_cp'], 20)
        self.assertEqual(result['training_absolute_cp_buckets'], {'101..300': 1})
        self.assertEqual(result['training_rejection_reasons_nonexclusive']['tactical_best_move'], 1)


if __name__ == '__main__':
    unittest.main()
