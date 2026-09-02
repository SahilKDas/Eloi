"""Retain compact, hash-bound campaign evidence; never change models or gates."""
import datetime as dt
import json
import run_fresh_nnue_campaign as campaign


def retain():
    root, work, data = campaign.ROOT, campaign.WORK, campaign.data
    campaign.check_identity()
    outcome = campaign.read(work / 'campaign-result.json')
    training = campaign.read(work / 'training-complete.json')
    snapshot = work / 'final-resource-check.json'
    if not snapshot.exists():
        data.immutable_json(snapshot, {'measured_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'usage': data.preflight(), 'note': 'retained-file measurement, not an OS-level peak measurement'})
    paths = {
        'protocol': root / 'data/nnue_fresh_data_protocol.json',
        'continuation': root / 'data/nnue_fresh_data_continuation.json',
        'acquisition': work / 'acquisition.json', 'sample': work / 'sample.json',
        'labels': work / 'labels.jsonl', 'label_summary': work / 'labels-complete.json',
        'coverage': work / 'coverage.json', 'position_validity': work / 'position-validity-audit.json',
        'learning_equivalence_exclusions': work / 'learning-equivalence-exclusions.json',
        'training_identity': work / 'training-identity.json', 'training': work / 'training-complete.json',
        'channel_capacity': work / 'channel-capacity-audit.json',
        'production_control': work / 'production-control.json',
        'integrity_tests': work / 'integrity-final.json',
        'outcome': work / 'campaign-result.json', 'resources': snapshot}
    artifacts = {name: {'path': path.relative_to(root).as_posix(),
                       'bytes': path.stat().st_size, 'sha256': data.sha(path)}
                 for name, path in paths.items()}
    candidates = []
    match_games = {'development': 0, 'confirmation': 0, 'final': 0}
    for trained in training['candidates']:
        name = trained['id']
        folder = work / 'candidates' / name
        gate = campaign.read(folder / 'correctness.json')
        if data.sha(folder / 'build/Eloi.exe') != gate['binary_sha256']:
            raise RuntimeError('candidate executable changed after its gate')
        if data.sha(folder / 'include/eloi/nnue_weights.hpp') != trained['weights_sha256']:
            raise RuntimeError('candidate weights changed after training')
        failures = []
        for check in gate['checks']:
            path = root / check['log']
            if data.sha(path) != check['log_sha256']:
                raise RuntimeError('candidate gate log changed')
            failures.extend(line for line in path.read_text().splitlines() if line.startswith('FAIL:'))
        candidates.append({'training': trained, 'correctness': gate, 'failures': failures})
        for stage in match_games:
            path = work / 'matches' / name / (stage + '.json')
            if path.exists():
                match_games[stage] += len(campaign.read(path)['results'])
    report = {'schema': 1, 'campaign': 'eloi-fresh-data-v1', 'outcome': outcome,
        'artifacts': artifacts, 'production_validation': training['baseline'],
        'candidates': candidates, 'match_games': match_games,
        'test_target_evaluation_performed': (work / 'selected-test.json').exists(),
        'puzzle_stage_validation_mae_change_cp': training['puzzle_stage_mae_change_cp'],
        'label_summary': campaign.read(paths['label_summary']),
        'coverage': campaign.read(paths['coverage']),
        'position_validity': campaign.read(paths['position_validity']),
        'channel_capacity': campaign.read(paths['channel_capacity']),
        'production_control': campaign.read(paths['production_control']),
        'integrity_tests': campaign.read(paths['integrity_tests']),
        'resources': campaign.read(snapshot)}
    output = root / 'data/nnue_fresh_data_results.json'
    data.immutable_json(output, report)
    print(json.dumps({'output': str(output), 'sha256': data.sha(output),
                      'status': outcome['status'], 'match_games': match_games}))


if __name__ == '__main__':
    retain()
