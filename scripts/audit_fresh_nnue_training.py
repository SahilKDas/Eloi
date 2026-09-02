"""Read-only diagnostic of production on fresh TRAIN groups; never reads test targets.

This does not select or train candidates. It accepts the currently completed
prefix of the append-only label checkpoint and reports coverage explicitly.
"""
import argparse
import collections
import json
import statistics
import fresh_nnue_data as data
import train_nnue as trainer


def audit(limit):
    model = trainer.load_quantized_header(data.ROOT / 'include/eloi/nnue_weights.hpp')
    slices = collections.defaultdict(list)
    targets, predictions = [], []
    groups = set()
    with (data.WORK / 'labels.jsonl').open() as stream:
        for line in stream:
            if not line.endswith('\n'):
                break  # A writer may currently be completing the last record.
            row = json.loads(line)
            if row['partition'] != 'train' or not row['accepted']:
                continue
            board = data.chess.Board(row['fen'])
            white = trainer.features(board, data.chess.WHITE)
            black = trainer.features(board, data.chess.BLACK)
            predicted = trainer.forward_quantized(*model, white, black)[0]
            target = row['high']['cp']
            predictions.append(predicted)
            targets.append(target)
            groups.add(row['group'])
            slices[row['phase']].append((predicted, target))
            if len(targets) == limit:
                break
    return {'purpose': 'training-only diagnostic; not candidate selection or strength evidence',
            'source': 'currently completed accepted training prefix, ordered by seeded hash',
            'weights_sha256': data.sha(data.ROOT / 'include/eloi/nnue_weights.hpp'),
            'count': len(targets), 'game_groups': len(groups),
            'regression': trainer._regression_summary(predictions, targets),
            'mean_absolute_teacher_cp': statistics.mean(map(abs, targets)) if targets else None,
            'mean_absolute_prediction_cp': statistics.mean(map(abs, predictions)) if predictions else None,
            'phases': {phase: trainer._regression_summary([p for p, _ in rows], [t for _, t in rows])
                       for phase, rows in slices.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=2000)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error('limit must be in 1..10000')
    print(json.dumps(audit(args.limit), indent=2))
