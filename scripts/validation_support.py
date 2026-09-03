"""Version-independent regression inputs and bounded device preflight."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def epd_cases(path=None):
    rows = []
    for line in Path(path or ROOT / 'tests/epd/v2_5_regressions.epd').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        fields = line.split(maxsplit=4)
        operations = {}
        for clause in fields[4].split(';'):
            values = shlex.split(clause)
            if values:
                operations[values[0]] = ' '.join(values[1:])
        depths = [int(operations.get('acd', '1'))]
        for key in ('stable', 'compare'):
            depths.extend(int(n) for n in operations.get(key, '').split())
        if min(depths) < 1:
            raise ValueError('Regression depths must be positive')
        rows.append({'id': operations['id'],
                     'fen': ' '.join(fields[:4]) + ' ' + operations.get('hmvc', '0') + ' ' + operations.get('fmvn', '1'),
                     'depth': max(depths), 'operations': operations})
    return rows


def external_scratch_roots():
    # Inspect only Eloi-named project scratch, never all user temporary data.
    return sorted(p for p in Path(tempfile.gettempdir()).glob('Eloi-*') if p.is_dir())


def directory_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file()) if Path(path).exists() else 0


def training_artifact_bytes():
    roots = [*ROOT.glob('.deps/nnue-*'), *ROOT.glob('tmp/nnue-*'), *ROOT.glob('build-nnue-*')]
    return sum(directory_bytes(p) for p in roots)


def check_limits(total, training, scratch, free, projected):
    if projected < 0:
        raise ValueError('Projected bytes must be nonnegative')
    if total + projected > 10_000_000_000:
        raise ValueError('Total temporary usage would exceed 10 GB')
    if training > min(8_000_000_000, 7 * 1024**3):
        raise ValueError('Training usage exceeds the stricter nested cap')
    if scratch + projected > 2_000_000_000:
        raise ValueError('Build scratch would exceed 2 GB')
    if free - projected < 5_000_000_000:
        raise ValueError('At least 5 GB free space must remain')


def resource_snapshot(scratch, projected=0):
    scratch = Path(scratch).resolve()
    parents = ((ROOT / 'tmp').resolve(), Path(tempfile.gettempdir()).resolve())
    if not any(scratch != p and scratch.is_relative_to(p) for p in parents):
        raise ValueError('Scratch must be a dedicated subdirectory of repository tmp or system temp')
    roots = [ROOT / name for name in ('.deps', 'tmp', 'dist', 'pkg', 'build')]
    roots += sorted(ROOT.glob('build-*')) + external_scratch_roots()
    if not any(scratch == p.resolve() or scratch.is_relative_to(p.resolve()) for p in roots):
        roots.append(scratch)
    usage = {str(p): directory_bytes(p) for p in roots}
    training = training_artifact_bytes()
    own, free = directory_bytes(scratch), shutil.disk_usage(ROOT).free
    check_limits(sum(usage.values()), training, own, free, projected)
    return {'total_bytes': sum(usage.values()), 'training_bytes': training,
            'scratch_bytes': own, 'free_bytes': free, 'projected_bytes': projected, 'roots': usage}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', required=True, type=Path)
    parser.add_argument('--projected-bytes', type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(resource_snapshot(args.scratch, args.projected_bytes), indent=2))
