#!/usr/bin/env python3
"""Generate Eloi's deterministic, mirrored Standard-chess opening suite.

The generator deliberately keeps material equal and may optionally ask a
specific UCI engine to reject positions outside a centipawn balance window.
The resulting JSON is stable for a fixed seed, engine hash, and arguments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / ".deps" / "python"))
import chess
import chess.engine


SEED = 0xE101_500
ROOT = pathlib.Path(__file__).parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "strength_openings.json"
OPENING_ROOTS = (
    ("e2e4", "e7e5"),
    ("e2e4", "c7c5"),
    ("e2e4", "e7e6"),
    ("e2e4", "c7c6"),
    ("d2d4", "d7d5"),
    ("d2d4", "g8f6"),
    ("c2c4", "e7e5"),
    ("c2c4", "g8f6"),
    ("g1f3", "d7d5"),
    ("g1f3", "g8f6"),
    ("b2b3", "d7d5"),
    ("g2g3", "d7d5"),
)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def material_balance(board: chess.Board) -> int:
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
        chess.KING: 0,
    }
    return sum(
        (1 if piece.color == chess.WHITE else -1) * values[piece.piece_type]
        for piece in board.piece_map().values()
    )


def quiet_candidates(board: chess.Board) -> list[chess.Move]:
    result = [
        move for move in board.legal_moves
        if not board.is_capture(move) and move.promotion is None
    ]
    return result or list(board.legal_moves)


def move_weight(board: chess.Board, move: chess.Move) -> int:
    piece = board.piece_at(move.from_square)
    weight = 8
    if board.is_castling(move):
        weight += 20
    if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        if chess.square_rank(move.from_square) in (0, 7):
            weight += 8
    if chess.square_file(move.to_square) in (2, 3, 4, 5):
        weight += 5
    if chess.square_rank(move.to_square) in (2, 3, 4, 5):
        weight += 3
    if board.gives_check(move):
        weight = max(1, weight - 5)
    return weight


def candidate_positions(count: int) -> list[chess.Board]:
    rng = random.Random(SEED)
    positions: list[chess.Board] = []
    seen: set[str] = set()
    attempts = 0
    while len(positions) < count * 8 and attempts < count * 200:
        attempts += 1
        board = chess.Board()
        root = OPENING_ROOTS[attempts % len(OPENING_ROOTS)]
        try:
            for text in root:
                board.push_uci(text)
        except ValueError:
            continue
        target_plies = 8 + 2 * (attempts % 3)
        while board.ply() < target_plies and not board.is_game_over():
            moves = quiet_candidates(board)
            weights = [move_weight(board, move) for move in moves]
            board.push(rng.choices(moves, weights=weights, k=1)[0])
        if board.turn != chess.WHITE or board.is_check() or board.is_game_over():
            continue
        if material_balance(board) != 0:
            continue
        identity = " ".join(board.fen().split()[:4])
        if identity in seen:
            continue
        seen.add(identity)
        positions.append(board.copy(stack=False))
    return positions


def configure(engine: chess.engine.SimpleEngine) -> None:
    settings: dict[str, object] = {}
    if "OwnBook" in engine.options:
        settings["OwnBook"] = False
    if "Hash" in engine.options:
        settings["Hash"] = 32
    if "Threads" in engine.options:
        settings["Threads"] = 3
    if settings:
        engine.configure(settings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--filter-engine", type=pathlib.Path)
    parser.add_argument("--filter-depth", type=int, default=5)
    parser.add_argument("--max-abs-cp", type=int, default=80)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")

    candidates = candidate_positions(args.count)
    selected: list[dict[str, object]] = []
    engine = None
    engine_hash = None
    if args.filter_engine:
        args.filter_engine = args.filter_engine.resolve()
        engine_hash = sha256(args.filter_engine)
        engine = chess.engine.SimpleEngine.popen_uci(
            [str(args.filter_engine), "--uci"], timeout=60.0)
        configure(engine)
    try:
        for board in candidates:
            score_cp = 0
            if engine:
                info = engine.analyse(
                    board, chess.engine.Limit(depth=args.filter_depth),
                    game=object())
                score = info["score"].pov(chess.WHITE).score(mate_score=30_000)
                if score is None or abs(score) > args.max_abs_cp:
                    continue
                score_cp = int(score)
            selected.append({"fen": board.fen(), "filter_cp": score_cp})
            if len(selected) >= args.count:
                break
    finally:
        if engine:
            engine.quit()
    if len(selected) != args.count:
        raise SystemExit(
            f"only {len(selected)} positions passed; need {args.count}")

    document = {
        "schema": 1,
        "name": "Eloi Standard strength gate openings",
        "generator_seed": SEED,
        "count": len(selected),
        "mirrored_games": len(selected) * 2,
        "plies": [8, 10, 12],
        "constraints": {
            "standard_chess": True,
            "white_to_move": True,
            "equal_material": True,
            "not_in_check": True,
            "max_abs_filter_cp": args.max_abs_cp if engine else None,
        },
        "filter": {
            "engine_sha256": engine_hash,
            "depth": args.filter_depth if engine else None,
        },
        "positions": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(selected)} openings to {args.output}")
    if engine_hash:
        print(f"filter engine SHA-256 {engine_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
