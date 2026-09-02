#!/usr/bin/env python3
"""Bounded full-source sampling and offline-only Stockfish labeling for Eloi.

Nothing here changes production headers, runs a playing bot, or deletes files.
Use the bundled NumPy Python runtime; python-chess is loaded from Eloi's venv.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import heapq
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.deps/lichess-bot/.venv/Lib/site-packages'))
import chess
import chess.engine
import chess.pgn

WORK = ROOT / 'tmp/nnue-fresh-data'
WEIGHTS = 'CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E'
SOURCE = 'https://database.nikonoel.fr/lichess_elite_2025-01.zip'
TEACHER = 'https://github.com/official-stockfish/Stockfish/releases/download/sf_17.1/stockfish-windows-x86-64-avx2.zip'
DEADLINE = dt.datetime(2026, 9, 2, 22, 35, tzinfo=dt.timezone.utc)
SEED = 'eloi-fresh-data-v1'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest().upper()


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def size(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.exists() else 0


def preflight(projected=0):
    roots = [ROOT / '.deps', ROOT / 'tmp', ROOT / 'dist', ROOT / 'build', *ROOT.glob('build-*')]
    usage = {str(p.relative_to(ROOT)): size(p) for p in roots}
    training_roots = [*ROOT.glob('.deps/nnue-*'), *ROOT.glob('tmp/nnue-*'), *ROOT.glob('build-nnue-*')]
    training = sum(size(p) for p in training_roots)
    total = sum(usage.values())
    if projected < 0 or training + projected > min(8_000_000_000, 7 * 1024**3):
        raise RuntimeError('nested training quota would be exceeded')
    if total + projected > 10_000_000_000:
        raise RuntimeError('total temporary quota would be exceeded')
    if shutil.disk_usage(ROOT).free < projected + 5_000_000_000:
        raise RuntimeError('5 GB free-space reserve would be violated')
    if sha(ROOT / 'include/eloi/nnue_weights.hpp') != WEIGHTS:
        raise RuntimeError('production network changed; stop and investigate')
    return {'training_bytes': training, 'total_bytes': total,
            'projected_bytes': projected, 'usage': usage,
            'free_bytes': shutil.disk_usage(ROOT).free}


def check_time():
    if dt.datetime.now(dt.timezone.utc) >= DEADLINE:
        raise TimeoutError('campaign window ended; retain resumable artifacts')


def immutable_json(path, obj):
    data = (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode()
    preflight(len(data))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f'refusing to replace artifact: {path}')
        return
    with path.open('xb') as f:
        f.write(data)


def download(url, path, maximum):
    """Bounded resumable download; preserve partial data on any failure."""
    meta = path.with_suffix(path.suffix + '.json')
    if meta.exists():
        saved = json.loads(meta.read_text())
        if saved['url'] != url or sha(path) != saved['sha256']:
            raise RuntimeError('download identity mismatch')
        return saved
    path.parent.mkdir(parents=True, exist_ok=True)
    offset = path.stat().st_size if path.exists() else 0
    preflight(maximum - offset)
    headers = {'User-Agent': 'Eloi-fresh-data-research/1'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
        if offset and (response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-')):
            raise RuntimeError('server did not honor resume; partial file preserved')
        length = int(response.headers.get('Content-Length', '0'))
        if offset + length > maximum:
            raise RuntimeError('source exceeds download reservation')
        with path.open('ab' if offset else 'xb') as out:
            total = offset
            while True:
                check_time()
                block = response.read(min(1024 * 1024, maximum - total + 1))
                if not block:
                    break
                if total + len(block) > maximum:
                    raise RuntimeError('download byte cap reached')
                out.write(block)
                total += len(block)
        if length and total != offset + length:
            raise RuntimeError('truncated download')
    result = {'url': url, 'bytes': path.stat().st_size, 'sha256': sha(path),
              'upstream_signature': False}
    immutable_json(meta, result)
    return result


def acquire():
    source = download(SOURCE, WORK / 'source.zip', 500_000_000)
    teacher = download(TEACHER, WORK / 'teacher.zip', 70_000_000)
    executable = WORK / 'teacher/stockfish.exe'
    if not executable.exists():
        with zipfile.ZipFile(WORK / 'teacher.zip') as archive:
            entries = [i for i in archive.infolist() if i.filename.endswith('.exe')]
            if len(entries) != 1 or entries[0].file_size > 100_000_000:
                raise RuntimeError('unexpected teacher archive')
            preflight(entries[0].file_size)
            executable.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entries[0]) as inp, executable.open('xb') as out:
                shutil.copyfileobj(inp, out, 1024 * 1024)
    immutable_json(WORK / 'acquisition.json', {'source': source, 'teacher_archive': teacher,
                   'teacher_executable_sha256': sha(executable), 'teacher_role': 'offline labels only'})
    print(json.dumps({'stage': 'acquired', 'resources': preflight()}), flush=True)


def pgn_chunks(stream):
    current = []
    length = 0
    for line in stream:
        if line.startswith('[Event ') and current:
            yield ''.join(current)
            current, length = [], 0
        current.append(line)
        length += len(line)
        if length > 1_000_000:
            raise RuntimeError('unexpectedly oversized PGN game')
    if current:
        yield ''.join(current)


def game_identity(headers, text):
    url = headers.get('LichessURL', headers.get('Site', ''))
    match = re.search(r'lichess\.org/([A-Za-z0-9]{8})(?:\b|/)', url)
    return match.group(1) if match else digest(text)


def split(group):
    value = int(digest(SEED + '|split|' + group)[:8], 16) % 100
    return 'train' if value < 80 else 'validation' if value < 90 else 'test'


def board_key(board):
    # Ignore counters; retain side, castling and legally relevant en passant.
    return ' '.join(board.fen(en_passant='legal').split()[:4])


def excluded_positions():
    result = set()
    for path in (ROOT / 'tests/epd').glob('*.epd'):
        for line in path.read_text().splitlines():
            fields = line.split()
            if len(fields) >= 4 and not line.startswith('#'):
                try:
                    result.add(board_key(chess.Board(' '.join(fields[:4]) + ' 0 1')))
                except ValueError:
                    pass
    for row in json.loads((ROOT / 'data/strength_openings.json').read_text())['positions']:
        result.add(board_key(chess.Board(row['fen'])))
    return result


def sample():
    done = WORK / 'sample.json'
    if done.exists():
        report = json.loads(done.read_text())
        if sha(WORK / 'positions.jsonl') != report['positions_sha256']:
            raise RuntimeError('sample hash mismatch')
        return
    preflight(350_000_000)
    reservoir = []
    counts = collections.Counter()
    with zipfile.ZipFile(WORK / 'source.zip') as archive:
        members = [i for i in archive.infolist() if i.filename.lower().endswith('.pgn')]
        if len(members) != 1 or members[0].file_size > 2_000_000_000:
            raise RuntimeError('unexpected PGN archive layout/size')
        with archive.open(members[0]) as raw, io.TextIOWrapper(raw, encoding='utf-8-sig') as stream:
            for text in pgn_chunks(stream):
                counts['games_scanned'] += 1
                headers = dict(re.findall(r'^\[(\w+) "(.*)"\]$', text, re.MULTILINE))
                try:
                    ratings = sorted([int(headers['WhiteElo']), int(headers['BlackElo'])])
                except (KeyError, ValueError):
                    counts['missing_rating'] += 1
                    continue
                if ratings[0] < 2300 or ratings[1] < 2500:
                    continue
                if headers.get('Variant', 'Standard') != 'Standard' or 'bullet' in headers.get('Event', '').lower():
                    continue
                if headers.get('Result') not in ('1-0', '0-1', '1/2-1/2'):
                    continue
                counts['eligible_games'] += 1
                group = game_identity(headers, text)
                priority = int(digest(SEED + '|game|' + group), 16)
                entry = (-priority, group, text)
                if len(reservoir) < 32000:
                    heapq.heappush(reservoir, entry)
                elif entry > reservoir[0]:
                    heapq.heapreplace(reservoir, entry)
                if counts['games_scanned'] % 20000 == 0:
                    check_time()
                    print(json.dumps({'stage': 'scan', **counts}), flush=True)
    counts['full_source_traversed'] = True
    excluded = excluded_positions()
    records = {}
    conflicts = set()
    seen_games = set()
    for _, group, text in sorted(reservoir, reverse=True):
        if group in seen_games:
            continue
        seen_games.add(group)
        game = chess.pgn.read_game(io.StringIO(text))
        if game is None or game.errors:
            counts['parse_errors'] += 1
            continue
        board = game.board()
        candidates = {'opening': [], 'middlegame': [], 'endgame': []}
        for ply, move in enumerate(game.mainline_moves(), 1):
            board.push(move)
            if ply < 16 or board.is_check() or board.is_game_over():
                continue
            key = board_key(board)
            if key in excluded:
                counts['excluded_regression_or_opening'] += 1
                continue
            pieces = len(board.piece_map())
            phase = 'endgame' if pieces <= 12 else 'opening' if ply <= 30 else 'middlegame'
            candidates[phase].append((digest(SEED + '|position|' + group + '|' + key), board.fen(), key, ply))
        for phase, rows in candidates.items():
            for rid, fen, key, ply in sorted(rows)[:2]:
                record = {'id': rid, 'group': group, 'partition': split(group),
                          'fen': fen, 'phase': phase, 'ply': ply, 'game_result': game.headers['Result']}
                if key in records:
                    if records[key]['partition'] != record['partition']:
                        conflicts.add(key)
                    counts['duplicate_positions'] += 1
                else:
                    records[key] = record
        if len(seen_games) % 2000 == 0:
            check_time()
            print(json.dumps({'stage': 'parse', 'games': len(seen_games), 'positions': len(records)}), flush=True)
    kept = [r for k, r in records.items() if k not in conflicts]
    kept.sort(key=lambda r: r['id'])
    path = WORK / 'positions.jsonl'
    with path.open('x', encoding='utf-8', newline='\n') as out:
        for row in kept:
            out.write(json.dumps(row, sort_keys=True) + '\n')
    counts.update({'selected_games': len(seen_games), 'positions': len(kept), 'cross_partition_boards_removed': len(conflicts)})
    immutable_json(done, {'counts': dict(counts), 'partitions': dict(collections.Counter(r['partition'] for r in kept)),
                         'phases': dict(collections.Counter(r['phase'] for r in kept)),
                         'source_sha256': sha(WORK / 'source.zip'), 'positions_sha256': sha(path)})
    print(done.read_text(), flush=True)


def start_teacher():
    kwargs = {'creationflags': subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    engine = chess.engine.SimpleEngine.popen_uci(str(WORK / 'teacher/stockfish.exe'), timeout=30, **kwargs)
    engine.configure({'Threads': 1, 'Hash': 64})
    return engine


def teacher_eval(engine, board, nodes):
    # A fresh hash per position makes labels independent of processing order.
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes), game=object())
    pv = info.get('pv', [])
    score = info['score'].white()
    return {'cp': score.score(), 'mate': score.mate(), 'depth': info.get('depth', 0),
            'nodes': info.get('nodes', 0), 'pv': [m.uci() for m in pv],
            'quiet_best': bool(pv) and not board.is_capture(pv[0]) and pv[0].promotion is None}


def label():
    protocol = json.loads((ROOT / 'data/nnue_fresh_data_protocol.json').read_text())
    if not protocol['offline_stockfish_labels_authorized']:
        raise RuntimeError('offline teacher not authorized')
    sample_report = json.loads((WORK / 'sample.json').read_text())
    if sha(WORK / 'positions.jsonl') != sample_report['positions_sha256']:
        raise RuntimeError('sample changed')
    acquisition = json.loads((WORK / 'acquisition.json').read_text())
    if sha(WORK / 'teacher/stockfish.exe') != acquisition['teacher_executable_sha256']:
        raise RuntimeError('teacher executable changed')
    if not (WORK / 'teacher-audit.json').exists():
        audit_teacher()
    if not json.loads((WORK / 'teacher-audit.json').read_text())['passed']:
        raise RuntimeError('teacher audit failed; do not scale labels')
    path = WORK / 'labels.jsonl'
    processed, accepted = set(), collections.Counter()
    if path.exists():
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                if row['id'] in processed:
                    raise RuntimeError('duplicate label checkpoint record')
                processed.add(row['id'])
                if row['accepted']:
                    accepted[row['partition']] += 1
    if (WORK / 'labels-complete.json').exists():
        report = json.loads((WORK / 'labels-complete.json').read_text())
        if sha(path) != report['labels_sha256']:
            raise RuntimeError('labels changed')
        return
    preflight(350_000_000)
    started = time.monotonic()
    with start_teacher() as engine, path.open('a', encoding='utf-8', newline='\n') as out, (WORK / 'positions.jsonl').open() as positions:
        for line in positions:
            check_time()
            row = json.loads(line)
            if row['id'] in processed:
                continue
            board = chess.Board(row['fen'])
            low = teacher_eval(engine, board, 5000)
            high = teacher_eval(engine, board, 25000)
            reasons = []
            if low['cp'] is None or high['cp'] is None:
                reasons.append('mate_label_excluded')
            elif abs(high['cp']) > 1200:
                reasons.append('outside_training_score_range')
            elif abs(high['cp'] - low['cp']) > 75:
                reasons.append('unstable_teacher_score')
            if not high['quiet_best']:
                reasons.append('tactical_best_move')
            if high['depth'] < 8:
                reasons.append('insufficient_depth')
            row.update({'low': low, 'high': high, 'accepted': not reasons, 'reasons': reasons})
            if int(row['id'][:8], 16) % 200 == 0:
                row['audit_100k'] = teacher_eval(engine, board, 100000)
            out.write(json.dumps(row, sort_keys=True) + '\n')
            out.flush()
            processed.add(row['id'])
            if row['accepted']:
                accepted[row['partition']] += 1
            if len(processed) % 128 == 0:
                preflight(2_000_000)
                print(json.dumps({'stage': 'label', 'processed': len(processed), 'accepted': dict(accepted),
                                  'elapsed_this_run_s': round(time.monotonic() - started)}), flush=True)
            if sum(accepted.values()) >= protocol['maximum_accepted_positions']:
                break
    immutable_json(WORK / 'labels-complete.json', {'processed': len(processed), 'accepted': dict(accepted),
                   'labels_sha256': sha(path), 'protocol_sha256': sha(ROOT / 'data/nnue_fresh_data_protocol.json'),
                   'teacher_sha256': acquisition['teacher_executable_sha256']})


def audit_teacher():
    """Independent larger-budget audit on training groups only, before scaling."""
    import statistics
    records = []
    with start_teacher() as engine, (WORK / 'positions.jsonl').open() as positions:
        for line in positions:
            check_time()
            row = json.loads(line)
            if row['partition'] != 'train':
                continue
            board = chess.Board(row['fen'])
            low = teacher_eval(engine, board, 5000)
            high = teacher_eval(engine, board, 25000)
            audit = teacher_eval(engine, board, 100000)
            eligible = (low['cp'] is not None and high['cp'] is not None
                        and abs(high['cp']) <= 1200 and abs(high['cp'] - low['cp']) <= 75
                        and high['quiet_best'] and high['depth'] >= 8)
            records.append({'id': row['id'], 'fen': row['fen'], 'low': low, 'high': high,
                            'audit': audit, 'eligible': eligible})
            if len(records) % 64 == 0:
                print(json.dumps({'stage': 'teacher-audit', 'positions': len(records)}), flush=True)
            if len(records) == 512:
                break
    deltas = [abs(r['high']['cp'] - r['audit']['cp']) if r['audit']['cp'] is not None else 30000
              for r in records if r['eligible']]
    median = statistics.median(deltas) if deltas else None
    outliers = sum(d > 150 for d in deltas) / max(1, len(deltas))
    passed = len(deltas) >= 50 and median <= 35 and outliers <= 0.10
    immutable_json(WORK / 'teacher-audit.json', {'passed': passed, 'eligible_count': len(deltas),
                   'median_drift_cp': median, 'outlier_fraction': outliers, 'records': records})
    if not passed:
        raise RuntimeError('initial teacher label audit failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['preflight', 'acquire', 'sample', 'label', 'prepare'])
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    if args.stage == 'preflight':
        print(json.dumps(preflight(), indent=2))
    elif args.stage == 'prepare':
        acquire()
        sample()
    else:
        globals()[args.stage]()
