"""Describe a completed label prefix without opening held-out target values.

This report is descriptive, never a candidate-selection or training input.
--freeze is allowed only after labels-complete.json pins the exact bytes.
"""
import argparse
import collections
import hashlib
import json
import statistics
import fresh_nnue_data as data


def summarize(rows, excluded=()):
    counts = collections.Counter()
    partitions = collections.Counter()
    phases = collections.defaultdict(collections.Counter)
    groups = collections.defaultdict(set)
    training_rejections = collections.Counter()
    training_depths = collections.Counter()
    training_targets = collections.Counter()
    training_turns = collections.Counter()
    audit_deltas = []
    for row in rows:
        counts['examined'] += 1
        partition = row['partition']
        if not row['accepted']:
            if partition == 'train':
                training_rejections.update(row['reasons'])
            continue
        counts['accepted_before_identity_exclusions'] += 1
        if row['fen'].split()[0] in excluded:
            counts['accepted_identity_exclusions'] += 1
            continue
        counts['usable'] += 1
        partitions[partition] += 1
        phases[partition][row['phase']] += 1
        groups[partition].add(row['group'])
        # Everything below reads targets from TRAIN only. Validation/test
        # contribute metadata counts, never target distributions or audit CP.
        if partition != 'train':
            continue
        high = row['high']
        training_depths[str(high['depth'])] += 1
        absolute = abs(high['cp'])
        bucket = ('0..25' if absolute <= 25 else '26..100' if absolute <= 100
                  else '101..300' if absolute <= 300 else '301..600' if absolute <= 600
                  else '601..1200')
        training_targets[bucket] += 1
        training_turns[row['fen'].split()[1]] += 1
        if 'audit_100k' in row:
            audit_cp = row['audit_100k']['cp']
            audit_deltas.append(abs(high['cp'] - audit_cp) if audit_cp is not None else 30000)
    overlap = {a + '/' + b: len(groups[a] & groups[b])
               for a, b in [('train', 'validation'), ('train', 'test'), ('validation', 'test')]}
    return {'purpose': 'coverage description only; no held-out target inspection or selection',
            'counts': dict(counts), 'usable_partitions': dict(partitions),
            'usable_phase_counts': {k: dict(v) for k, v in phases.items()},
            'usable_game_groups': {k: len(v) for k, v in groups.items()},
            'game_group_overlap': overlap,
            'training_rejection_reasons_nonexclusive': dict(training_rejections),
            'training_high_depth_histogram': dict(sorted(training_depths.items(), key=lambda p: int(p[0]))),
            'training_absolute_cp_buckets': dict(training_targets),
            'training_side_to_move': dict(training_turns),
            'training_100k_audit': {'count': len(audit_deltas),
                'median_absolute_drift_cp': statistics.median(audit_deltas) if audit_deltas else None,
                'fraction_drift_above_150cp': sum(x > 150 for x in audit_deltas) / len(audit_deltas)
                    if audit_deltas else None,
                'purpose': 'descriptive follow-up; not a new or modified gate'}}


def report():
    exclusion_path = data.WORK / 'learning-identity-exclusions.json'
    exclusions = json.loads(exclusion_path.read_text())['conflicting_piece_placements']
    prefix_hash = hashlib.sha256()
    prefix_bytes = 0

    def rows():
        nonlocal prefix_bytes
        with (data.WORK / 'labels.jsonl').open('rb') as stream:
            for line in stream:
                if not line.endswith(b'\n'):
                    break
                prefix_hash.update(line)
                prefix_bytes += len(line)
                yield json.loads(line)

    result = summarize(rows(), set(exclusions))
    result.update({'completed_prefix_bytes': prefix_bytes,
                   'completed_prefix_sha256': prefix_hash.hexdigest().upper(),
                   'protocol_sha256': data.sha(data.ROOT / 'data/nnue_fresh_data_protocol.json'),
                   'exclusions_sha256': data.sha(exclusion_path),
                   'report_script_sha256': data.sha(__file__)})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    result = report()
    if args.freeze:
        complete = json.loads((data.WORK / 'labels-complete.json').read_text())
        if result['completed_prefix_sha256'] != complete['labels_sha256']:
            raise RuntimeError('coverage report does not cover the frozen label bytes')
        data.immutable_json(data.WORK / 'coverage.json', result)
    print(json.dumps(result, indent=2))
