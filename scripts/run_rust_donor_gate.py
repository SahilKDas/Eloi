#!/usr/bin/env python3
"""Frozen 100-game contained Caissa 2.0 versus Caissa 1.26 qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.deps/lichess-bot/.venv/Lib/site-packages'))
import chess
import chess.engine
import chess.pgn

PAIR_INDICES = tuple(range(0, 50))
GAMES = 100
MOVETIME_MS = 250
MAX_PLIES = 200


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest().upper()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n',
                         encoding='utf-8')
    temporary.replace(path)


def schedule(positions: list[dict]) -> list[dict]:
    if len(positions) <= PAIR_INDICES[-1]:
        raise ValueError('opening reserve does not contain the frozen indices')
    rows = []
    for pair, index in enumerate(PAIR_INDICES, 1):
        for candidate_white in (True, False):
            rows.append({'game': len(rows) + 1, 'pair': pair,
                         'reserve_index': index,
                         'candidate_white': candidate_white,
                         'fen': positions[index]['fen']})
    if len(rows) != GAMES:
        raise AssertionError('frozen schedule has the wrong denominator')
    return rows


def configure(engine: chess.engine.SimpleEngine) -> None:
    values = {}
    for name, value in (('Threads', 3), ('Hash', 32), ('OwnBook', False),
                        ('Noise', 0), ('Move Overhead', 0)):
        if name in engine.options:
            values[name] = value
    if values:
        engine.configure(values)


def summarize(results: list[dict]) -> dict:
    wins = sum(row['score'] == 1 for row in results)
    draws = sum(row['score'] == .5 for row in results)
    losses = sum(row['score'] == 0 for row in results)
    points = wins + draws / 2
    return {'completed': len(results), 'wins': wins, 'draws': draws,
            'losses': losses, 'score_points': points,
            'score_percent': 100.0 * points / GAMES}


def qualification(candidate: dict, baseline: dict | None) -> dict:
    complete = candidate['completed'] == GAMES
    beat_caissa = complete and candidate['score_points'] > GAMES / 2
    if baseline is None:
        return {'baseline_complete': complete, 'improved_over_e4': None,
                'beat_caissa': beat_caissa, 'passed': beat_caissa}
    improved = (complete and baseline['completed'] == GAMES and
                candidate['score_points'] > baseline['score_points'])
    return {'baseline_complete': baseline['completed'] == GAMES,
            'improved_over_e4': improved, 'beat_caissa': beat_caissa,
            'passed': improved}


class ProtocolFailure(RuntimeError):
    def __init__(self, message: str, board: chess.Board,
                 response: chess.engine.PlayResult, played_plies: int):
        super().__init__(message)
        self.fen = board.fen()
        self.moves = [move.uci() for move in board.move_stack]
        self.engine_info = {key: str(value) for key, value in response.info.items()}
        self.played_plies = played_plies


def play(candidate_command: list[str], caissa_command: list[str], row: dict):
    flags = subprocess.IDLE_PRIORITY_CLASS if os.name == 'nt' else 0
    candidate = chess.engine.SimpleEngine.popen_uci(candidate_command, timeout=30,
                                                     creationflags=flags)
    caissa = chess.engine.SimpleEngine.popen_uci(caissa_command, timeout=30,
                                                 creationflags=flags)
    board = chess.Board(row['fen'])
    opening_ply = board.ply()
    played_plies = 0
    started = time.monotonic()
    try:
        configure(candidate)
        configure(caissa)
        limit = chess.engine.Limit(time=MOVETIME_MS / 1000)
        while not board.is_game_over(claim_draw=True) and played_plies < MAX_PLIES:
            engine = candidate if board.turn == row['candidate_white'] else caissa
            response = engine.play(board, limit, info=chess.engine.INFO_ALL)
            if response.move is None or response.move not in board.legal_moves:
                raise ProtocolFailure(
                    f'illegal or missing move at ply {board.ply()}: {response.move}',
                    board, response, played_plies)
            board.push(response.move)
            played_plies += 1
    finally:
        candidate.quit()
        caissa.quit()
    outcome = board.outcome(claim_draw=True)
    if outcome is None or outcome.winner is None:
        score, result_text = .5, '1/2-1/2'
    else:
        score = 1.0 if outcome.winner == row['candidate_white'] else 0.0
        result_text = '1-0' if outcome.winner else '0-1'
    game = chess.pgn.Game.from_board(board)
    game.headers.update({
        'Event': 'Eloi Rust donor qualification',
        'Round': str(row['game']),
        'White': 'Caissa-2.0-contained' if row['candidate_white'] else 'Caissa-1.26',
        'Black': 'Caissa-1.26' if row['candidate_white'] else 'Caissa-2.0-contained',
        'Result': result_text, 'Pair': str(row['pair']),
        'ReserveIndex': str(row['reserve_index']),
    })
    return ({**row, 'score': score, 'result': result_text,
             'opening_ply': opening_ply,
             'played_plies': played_plies,
             'final_absolute_ply': board.ply(),
             'elapsed_seconds': round(time.monotonic() - started, 3),
             'final_fen': board.fen()}, game)


def verify_pgn(path: Path) -> dict:
    count = 0
    with path.open(encoding='utf-8') as stream:
        while game := chess.pgn.read_game(stream):
            board = chess.Board(game.headers['FEN'])
            for move in game.mainline_moves():
                if move not in board.legal_moves:
                    raise RuntimeError(f'illegal replay move in game {count + 1}: {move}')
                board.push(move)
            actual = board.result(claim_draw=True)
            adjudicated = actual == '*' and game.headers['Result'] == '1/2-1/2'
            if actual != game.headers['Result'] and not adjudicated:
                raise RuntimeError(f'result mismatch in replay game {count + 1}')
            count += 1
    return {'verified_games': count, 'expected_games': GAMES,
            'passed': count == GAMES}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('baseline', 'challenger'), required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--caissa', type=Path, required=True)
    parser.add_argument('--network', type=Path, required=True)
    parser.add_argument('--reserve', type=Path,
                        default=ROOT / 'data' / 'strength_openings.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-results', type=Path)
    parser.add_argument('--candidate-arg', action='append', default=[])
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.stage == 'challenger' and not args.baseline_results:
        raise ValueError('challenger stage requires --baseline-results')
    args.output.mkdir(parents=True)
    reserve = json.loads(args.reserve.read_text(encoding='utf-8'))
    frozen = schedule(reserve['positions'])
    candidate_command = [str(args.candidate.resolve()), '--uci', *args.candidate_arg]
    caissa_command = [str(args.caissa.resolve())]
    protocol = {
        'schema': 'eloi-rust-donor-gate-v1', 'stage': args.stage,
        'games': GAMES, 'pairs': len(PAIR_INDICES), 'mirrored': True,
        'movetime_ms': MOVETIME_MS, 'max_plies': MAX_PLIES,
        'threads_per_engine': 3, 'hash_mb': 32, 'priority': 'idle',
        'candidate_sha256': sha256(args.candidate),
        'caissa_sha256': sha256(args.caissa),
        'network_sha256': sha256(args.network),
        'reserve_sha256': sha256(args.reserve),
        'runner_sha256': sha256(Path(__file__)),
        'candidate_args': args.candidate_arg,
        'indices': list(PAIR_INDICES), 'schedule': frozen,
        'qualification': 'Contained Caissa 2.0 score_points strictly greater than 50/100 against Caissa 1.26',
    }
    atomic_json(args.output / 'protocol.json', protocol)
    results, failures = [], []
    pgn_path = args.output / 'games.pgn'
    for row in frozen:
        try:
            result, game = play(candidate_command, caissa_command, row)
            results.append(result)
            with pgn_path.open('a', encoding='utf-8', newline='\n') as stream:
                print(game, file=stream, end='\n\n')
        except Exception as error:
            failure = {**row, 'error': f'{type(error).__name__}: {error}'}
            if isinstance(error, ProtocolFailure):
                failure.update({'failure_fen': error.fen,
                                'partial_moves': error.moves,
                                'played_plies': error.played_plies,
                                'engine_info': error.engine_info})
            failures.append(failure)
        summary = summarize(results)
        evidence = {'schema': 'eloi-rust-donor-results-v1',
                    'stage': args.stage,
                    'complete': len(results) + len(failures) == GAMES,
                    'summary': summary, 'results': results,
                    'protocol_failures': failures}
        atomic_json(args.output / 'results.json', evidence)
        print(json.dumps({'game': row['game'], **summary,
                          'failures': len(failures)}), flush=True)
        if failures:
            return 2
    evidence['replay_verification'] = verify_pgn(pgn_path)
    baseline = None
    if args.baseline_results:
        baseline_evidence = json.loads(args.baseline_results.read_text(encoding='utf-8'))
        if baseline_evidence.get('protocol_failures'):
            raise RuntimeError('baseline contains protocol failures')
        baseline = baseline_evidence['summary']
        evidence['baseline_results_sha256'] = sha256(args.baseline_results)
        evidence['baseline_summary'] = baseline
    evidence['qualification'] = qualification(evidence['summary'], baseline)
    evidence['passed'] = (evidence['replay_verification']['passed'] and
                          evidence['qualification']['passed'])
    atomic_json(args.output / 'results.json', evidence)
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
