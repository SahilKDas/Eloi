#!/usr/bin/env python3
"""Resume the frozen fresh-data campaign without touching production weights."""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
import fresh_nnue_data as data
import train_nnue as trainer
import numpy as np
import chess
import engine_lab

ROOT, WORK = data.ROOT, data.WORK
PROTOCOL = ROOT / 'data/nnue_fresh_data_protocol.json'
BASELINE = ROOT / 'tmp/search-recovery/baseline/Eloi.exe'
CMAKE = 'C:/msys64/ucrt64/bin/cmake.exe'
MSYS = 'C:/msys64/ucrt64/bin'


def read(path):
    return json.loads(path.read_text())


def log(message):
    print(json.dumps(message), flush=True)


def identity():
    source_paths = [ROOT / 'CMakeLists.txt', *sorted((ROOT / 'src').rglob('*')),
                    *sorted((ROOT / 'include/eloi').rglob('*')), *sorted((ROOT / 'tests').rglob('*')),
                    ROOT / 'scripts/train_nnue.py', Path(__file__),
                    ROOT / 'scripts/fresh_nnue_data.py', ROOT / 'scripts/engine_lab.py']
    files = {p.relative_to(ROOT).as_posix(): data.sha(p) for p in source_paths if p.is_file()}
    return {'protocol_sha256': data.sha(PROTOCOL), 'labels_sha256': data.sha(WORK / 'labels.jsonl'),
            'source_files': files, 'source_fingerprint': data.digest(json.dumps(files, sort_keys=True))}


def check_identity():
    current = identity()
    data.immutable_json(WORK / 'training-identity.json', current)
    return current


def load_evaluations(include_test=False):
    result = {'train': [], 'validation': [], 'test': []}
    with (WORK / 'labels.jsonl').open() as stream:
        for line in stream:
            row = json.loads(line)
            if not row['accepted'] or (row['partition'] == 'test' and not include_test):
                continue
            board = chess.Board(row['fen'])
            result[row['partition']].append((trainer.features(board, chess.WHITE),
                trainer.features(board, chess.BLACK), float(row['high']['cp']), 1.0,
                {'record_id': row['id'], 'phase_bucket': row['phase']}))
    return result


def load_training_puzzles():
    held_groups, held_boards = set(), data.excluded_positions()
    with (WORK / 'positions.jsonl').open() as stream:
        for line in stream:
            row = json.loads(line)
            if row['partition'] != 'train':
                held_groups.add(row['group'])
                held_boards.add(data.board_key(chess.Board(row['fen'])))
    selected = []
    source = ROOT / '.deps/nnue-inputs-v2-broader1/canonical-puzzles.jsonl'
    expected = read(ROOT / 'data/nnue_broader_sample_manifest.json')['outputs']['canonical_puzzles']['sha256']
    if data.sha(source).upper() != expected.upper():
        raise RuntimeError('old puzzle source identity changed')
    with source.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row['partition'] != 'train' or row['game_id'] in held_groups:
                continue
            board = chess.Board(row['decision_fen'])
            best = chess.Move.from_uci(row['best_move'])
            if data.board_key(board) in held_boards or best not in board.legal_moves:
                continue
            legal = sorted((m for m in board.legal_moves if m != best), key=lambda m: m.uci())
            if not legal:
                continue
            alt = trainer.deterministic_choice(legal, trainer.SEED, 'canonical-random-negative', row['record_id'])
            best_board, alt_board = board.copy(), board.copy()
            best_board.push(best)
            alt_board.push(alt)
            if data.board_key(best_board) in held_boards or data.board_key(alt_board) in held_boards:
                continue
            selected.append((data.digest(f'{trainer.SEED}|canonical-limit|{row["record_id"]}'), row,
                             best_board, alt_board, board.turn))
    pairs = []
    for _, row, best, alt, turn in sorted(selected, key=lambda item: item[0])[:12000]:
        pairs.append((trainer.features(best, chess.WHITE), trainer.features(best, chess.BLACK),
                      trainer.features(alt, chess.WHITE), trainer.features(alt, chess.BLACK),
                      1 if turn == chess.WHITE else -1))
    data.immutable_json(WORK / 'puzzle-selection.json', {'count': len(pairs),
        'source_sha256': data.sha(source), 'held_out_groups_excluded': len(held_groups),
        'held_out_and_regression_boards_excluded': len(held_boards),
        'selected_ids': [item[1]['record_id'] for item in sorted(selected, key=lambda item: item[0])[:12000]]})
    return pairs


def regression_metrics(model, samples):
    quant = trainer.quantize_model(*model)
    predictions, targets = [], []
    phase = collections.defaultdict(lambda: [[], []])
    max_acc = 0
    for white, black, target, _, meta in samples:
        score, aw, ab = trainer.forward_quantized(*quant, white, black)
        max_acc = max(max_acc, int(np.abs(aw).max()), int(np.abs(ab).max()))
        predictions.append(score)
        targets.append(target)
        phase[meta['phase_bucket']][0].append(score)
        phase[meta['phase_bucket']][1].append(target)
    result = trainer._regression_summary(predictions, targets)
    result['phase_slices'] = {k: trainer._regression_summary(*v) for k, v in phase.items()}
    result['max_abs_accumulator'] = max_acc
    return result


def emit(name, model, validation, counts, recipe):
    directory = WORK / 'candidates' / name
    include = directory / 'include/eloi'
    include.mkdir(parents=True, exist_ok=True)
    data.preflight(12_000_000)
    for a in model:
        if not np.isfinite(a).all():
            raise RuntimeError('nonfinite training parameters')
    if np.abs(np.rint(model[1])).max() > 32767 or np.abs(np.rint(model[2])).max() > 32767:
        raise RuntimeError('int16 parameter overflow')
    checkpoint = directory / 'float.npz'
    if not checkpoint.exists():
        np.savez(checkpoint, weights=model[0], bias=model[1], output=model[2])
    header = include / 'nnue_weights.hpp'
    if not header.exists():
        trainer.write_header(header, *model, counts, set(),
            source_description='Lichess Elite games; offline Stockfish 17.1 labels; see fresh-data provenance')
    else:
        if any(not np.array_equal(a, b) for a, b in zip(trainer.load_quantized_header(header), trainer.quantize_model(*model))):
            raise RuntimeError('candidate header does not match checkpoint')
    report = {'id': name, 'recipe': recipe, 'weights_sha256': data.sha(header),
              'checkpoint_sha256': data.sha(checkpoint), 'counts': counts,
              'quantized_validation': regression_metrics(model, validation)}
    data.immutable_json(directory / 'training.json', report)
    log({'stage': 'trained', 'candidate': name, 'validation': report['quantized_validation']})
    return report


def checkpoint_model(name):
    with np.load(WORK / 'candidates' / name / 'float.npz') as saved:
        return tuple(saved[k].copy() for k in ('weights', 'bias', 'output'))


def train():
    check_identity()
    summary = read(WORK / 'labels-complete.json')
    if data.sha(WORK / 'labels.jsonl') != summary['labels_sha256']:
        raise RuntimeError('labels are not frozen')
    for part, minimum in [('train', 20000), ('validation', 2000), ('test', 2000)]:
        if summary['accepted'].get(part, 0) < minimum:
            raise RuntimeError(f'insufficient accepted {part} data')
    if (WORK / 'training-complete.json').exists():
        return
    samples = load_evaluations()
    production = tuple(a.astype(np.float32) for a in trainer.load_quantized_header(ROOT / 'include/eloi/nnue_weights.hpp'))
    base = regression_metrics(production, samples['validation'])
    data.immutable_json(WORK / 'production-validation.json', base)
    counts = {'train_evaluations': len(samples['train']), 'train_pairs': 0}
    reports = []
    data.check_time()
    if (WORK / 'candidates/A/float.npz').exists():
        a = checkpoint_model('A')
    else:
        a = trainer.train_evaluations(*(x.copy() for x in production), list(samples['train']), epochs=2)
    reports.append(emit('A', a, samples['validation'], counts.copy(), 'production + two fresh-evaluation epochs'))
    data.check_time()
    puzzles = load_training_puzzles()
    counts['train_pairs'] = len(puzzles)
    if (WORK / 'candidates/B/float.npz').exists():
        b = checkpoint_model('B')
    else:
        b = trainer.train_pairs(*(x.copy() for x in a), list(puzzles), epochs=3)
    reports.append(emit('B', b, samples['validation'], counts.copy(), 'A + three legacy-training-puzzle epochs'))
    data.check_time()
    if (WORK / 'candidates/C/float.npz').exists():
        c = checkpoint_model('C')
    else:
        c = trainer.train_evaluations(*(x.copy() for x in b), list(samples['train']), epochs=1)
    reports.append(emit('C', c, samples['validation'], counts.copy(), 'B + one fresh-evaluation recalibration epoch'))
    selected = min(reports, key=lambda r: (r['quantized_validation']['mae_cp'], r['id']))
    selected_model = {'A': a, 'B': b, 'C': c}[selected['id']]
    for name, fraction in [('blend25', 0.25), ('blend50', 0.50)]:
        model = tuple((1 - fraction) * x + fraction * y for x, y in zip(production, selected_model))
        reports.append(emit(name, model, samples['validation'], selected['counts'],
                            f'{fraction} interpolation from production toward {selected["id"]}'))
    data.immutable_json(WORK / 'training-complete.json', {'baseline': base, 'candidates': reports,
        'puzzle_stage_mae_change_cp': reports[1]['quantized_validation']['mae_cp'] - reports[0]['quantized_validation']['mae_cp'],
        'test_labels_used_for_selection': False})


def run_command(command, logfile, timeout=1800):
    data.check_time()
    data.preflight(100_000_000)
    remaining = (data.DEADLINE - dt.datetime.now(dt.timezone.utc)).total_seconds()
    if remaining < 60:
        raise TimeoutError('not enough campaign window for another command')
    env = dict(os.environ)
    env['PATH'] = MSYS + os.pathsep + env.get('PATH', '')
    env['SOURCE_DATE_EPOCH'] = str(read(ROOT / 'reproducibility.lock.json')['source_date_epoch'])
    flags = subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with logfile.open('a', encoding='utf-8') as log_file:
        log_file.write('\nCOMMAND ' + json.dumps([str(x) for x in command]) + '\n')
        log_file.flush()
        result = subprocess.run([str(x) for x in command], cwd=ROOT, env=env,
            stdout=log_file, stderr=subprocess.STDOUT, timeout=min(timeout, remaining), creationflags=flags)
    return {'command': [str(x) for x in command], 'exit_code': result.returncode,
            'log': logfile.relative_to(ROOT).as_posix(), 'log_sha256': data.sha(logfile)}


def build(name, suffix='build'):
    directory = WORK / 'candidates' / name
    build_dir = directory / suffix
    data.preflight(150_000_000)
    commands = [
        [CMAKE, '-S', ROOT, '-B', build_dir, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
         '-DELOI_BUILD_TESTS=ON', '-DCMAKE_CXX_COMPILER=' + MSYS + '/c++.exe',
         '-DCMAKE_MAKE_PROGRAM=' + MSYS + '/ninja.exe', '-DCMAKE_RC_COMPILER=' + MSYS + '/windres.exe',
         '-DELOI_NNUE_INCLUDE_DIR=' + str(directory / 'include')],
        [CMAKE, '--build', build_dir, '--target', 'Eloi', 'eloi_tests', '-j', '2']]
    for index, cmd in enumerate(commands):
        result = run_command(cmd, directory / f'{suffix}-{index}.log')
        if result['exit_code']:
            raise RuntimeError(f'{name} build failed: {result}')
    return build_dir / 'Eloi.exe', build_dir / 'eloi_tests.exe'


def validate(name):
    check_identity()
    directory = WORK / 'candidates' / name
    if (directory / 'correctness.json').exists():
        saved = read(directory / 'correctness.json')
        if data.sha(directory / 'include/eloi/nnue_weights.hpp') != saved['weights_sha256']:
            raise RuntimeError('validated candidate weights changed')
        return saved
    binary, test = build(name)
    commands = [[test], [binary, '--perft', '--depth', '4'],
                [sys.executable, ROOT / 'scripts/differential_movegen.py', '--engine', binary, '--samples', '32']]
    checks = []
    for index, cmd in enumerate(commands):
        result = run_command(cmd, directory / f'correctness-{index}.log', timeout=600)
        checks.append(result)
        if result['exit_code']:
            break
        if index == 1 and ',4,197281,' not in (directory / f'correctness-{index}.log').read_text():
            raise RuntimeError('perft node count mismatch')
    training = read(directory / 'training.json')
    calibration = training['quantized_validation']['mae_cp'] <= read(WORK / 'production-validation.json')['mae_cp']
    report = {'candidate': name, 'passed': len(checks) == 3 and all(c['exit_code'] == 0 for c in checks),
              'calibration_passed': calibration, 'checks': checks, 'binary_sha256': data.sha(binary),
              'weights_sha256': data.sha(directory / 'include/eloi/nnue_weights.hpp')}
    report['eligible'] = report['passed'] and calibration
    data.immutable_json(directory / 'correctness.json', report)
    log({'stage': 'correctness', **report})
    return report


def match(name, stage):
    protocol = read(PROTOCOL)
    binary = WORK / 'candidates' / name / 'build/Eloi.exe'
    correctness = read(WORK / 'candidates' / name / 'correctness.json')
    if not correctness['eligible'] or data.sha(binary) != correctness['binary_sha256']:
        raise RuntimeError('candidate not eligible or executable changed')
    if data.sha(BASELINE) != protocol['baseline_sha256']:
        raise RuntimeError('not the published v2.0 baseline')
    spec = protocol[stage]
    directory = WORK / 'matches' / name
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = directory / f'{stage}.json'
    if checkpoint.exists() and len(read(checkpoint)['results']) == spec['games']:
        saved = read(checkpoint)
        expected = dict(saved['identity'])
        requirements = {'candidate_sha256': data.sha(binary), 'baseline_sha256': data.sha(BASELINE),
            'suite_sha256': data.sha(ROOT / spec['partition']), 'protocol_sha256': data.sha(PROTOCOL),
            'games': spec['games'], 'movetime_ms': spec['movetime_ms'], 'max_plies': spec['max_plies'],
            'threads': 3, 'hash_mb': 32, 'gate_metric': 'score', 'required_score': spec.get('required_score', 0.52)}
        if any(expected.get(k) != v for k, v in requirements.items()):
            raise RuntimeError('completed match identity no longer matches frozen protocol')
        engine_lab.validate_resume(saved, expected, directory / f'{stage}.pgn')
        return saved
    # Do not begin a match that cannot fit even its declared worst-case move budget.
    expected_seconds = spec['games'] * spec['max_plies'] * spec['movetime_ms'] / 1000 + 600
    if (data.DEADLINE - dt.datetime.now(dt.timezone.utc)).total_seconds() < expected_seconds:
        raise TimeoutError(f'insufficient remaining window for fixed {stage} match')
    command = [sys.executable, ROOT / 'scripts/engine_lab.py', '--candidate', binary, '--baseline', BASELINE,
               'strength', '--suite', ROOT / spec['partition'], '--checkpoint', checkpoint,
               '--pgn', directory / f'{stage}.pgn', '--games', str(spec['games']),
               '--movetime-ms', str(spec['movetime_ms']), '--max-plies', str(spec['max_plies']),
               '--gate-metric', 'score', '--required-score', str(spec.get('required_score', 0.52)),
               '--protocol', PROTOCOL, '--idle-priority']
    result = run_command(command, directory / f'{stage}.log', timeout=int(expected_seconds + 600))
    if not checkpoint.exists():
        raise RuntimeError(f'match produced no checkpoint: {result}')
    report = read(checkpoint)
    if len(report['results']) != spec['games'] or report.get('protocol_failures', 0):
        raise RuntimeError('match incomplete or protocol failure; do not advance')
    return report


def gates():
    check_identity()
    if (WORK / 'campaign-result.json').exists():
        return
    training = read(WORK / 'training-complete.json')
    development = []
    for candidate in training['candidates']:
        name = candidate['id']
        report = validate(name)
        if report['eligible']:
            played = match(name, 'development')
            development.append({'id': name, 'score': played['score'], 'mae': candidate['quantized_validation']['mae_cp']})
    if not development or max(d['score'] for d in development) < 0.52:
        data.immutable_json(WORK / 'campaign-result.json', {'status': 'no_qualifying_development_candidate',
            'development': development, 'production_unchanged': True, 'release_created': False})
        return
    selected = sorted(development, key=lambda d: (-d['score'], d['mae'], d['id']))[0]
    data.immutable_json(WORK / 'selection.json', selected)
    name = selected['id']
    # Open held-out labels once, only after the recipe and candidate selection.
    test = load_evaluations(include_test=True)['test']
    candidate_metrics = regression_metrics(checkpoint_model(name), test)
    production = tuple(a.astype(np.float32) for a in trainer.load_quantized_header(ROOT / 'include/eloi/nnue_weights.hpp'))
    data.immutable_json(WORK / 'selected-test.json', {'candidate': name,
        'candidate_metrics': candidate_metrics, 'production_metrics': regression_metrics(production, test),
        'influenced_selection': False})
    confirmation = match(name, 'confirmation')
    if not confirmation['passed']:
        data.immutable_json(WORK / 'campaign-result.json', {'status': 'confirmation_failed',
            'selected': name, 'score': confirmation['score'], 'production_unchanged': True, 'release_created': False})
        return
    first = WORK / 'candidates' / name / 'build/Eloi.exe'
    second, second_test = build(name, 'repro-build')
    repro_test = run_command([second_test], WORK / 'candidates' / name / 'repro-tests.log', 600)
    reproducible = data.sha(first) == data.sha(second) and repro_test['exit_code'] == 0
    data.immutable_json(WORK / 'reproducibility.json', {'passed': reproducible,
        'first_sha256': data.sha(first), 'second_sha256': data.sha(second), 'tests': repro_test})
    if not reproducible:
        raise RuntimeError('two isolated builds did not qualify')
    speed = WORK / 'speed.json'
    if not speed.exists():
        result = run_command([sys.executable, ROOT / 'scripts/engine_lab.py', '--candidate', first,
            '--baseline', BASELINE, 'speed', '--output', speed, '--depths', '1', '5', '10',
            '--samples', '3', '--maximum-time-ratio', '1.15'], WORK / 'speed.log', timeout=1800)
        if result['exit_code']:
            raise RuntimeError('performance gate failed')
    if not read(speed)['passed']:
        raise RuntimeError('performance gate failed')
    final = match(name, 'final')
    data.immutable_json(WORK / 'campaign-result.json', {'status': 'strength_gate_passed' if final['passed'] else 'final_failed',
        'selected': name, 'wins': final['wins'], 'draws': final['draws'], 'losses': final['losses'],
        'score': final['score'], 'points': final['points'], 'uncertainty': final['score_95pct_interval'],
        'production_unchanged': True, 'release_created': False})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['train', 'gates', 'run'])
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    # OS-owned lock survives crashes without requiring deletion of a lock file.
    import msvcrt
    with (WORK / 'campaign.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            log({'stage': 'start', 'pid': os.getpid(), 'resources': data.preflight()})
            if args.stage == 'run':
                data.acquire()
                data.sample()
                data.label()
                train()
                gates()
            else:
                globals()[args.stage]()
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
