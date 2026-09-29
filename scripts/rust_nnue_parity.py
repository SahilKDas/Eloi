"""Compare Rust inference with independent scalar production-header arithmetic."""

from __future__ import annotations

import argparse
from pathlib import Path
import random
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess
import chess.variant


def arrays(header: Path) -> dict:
    text = header.read_text(encoding="utf-8")
    return {name: [int(v) for v in re.findall(r"-?\d+", re.search(rf"\b{name}\s*\{{\{{(.*?)\}}\}}", text, re.S).group(1))]
            for name in ("bias", "output", "input")}


def reference(board, weights: dict) -> int:
    scores = []
    piece_index = {chess.PAWN: 0, chess.BISHOP: 1, chess.KNIGHT: 2, chess.ROOK: 3, chess.QUEEN: 4, chess.KING: 5}
    for perspective in (chess.WHITE, chess.BLACK):
        orientation = 0 if perspective == chess.WHITE else 56
        king = board.king(perspective)
        oriented = king ^ orientation if king is not None else None
        bucket = int(chess.square_file(oriented) >= 4) + 2 * (chess.square_rank(oriented) // 2) if oriented is not None else 0
        acc = weights["bias"].copy()
        for square, piece in board.piece_map().items():
            feature = (bucket * 12 + int(piece.color != perspective) * 6 + piece_index[piece.piece_type]) * 64 + (square ^ orientation)
            base = feature * 64
            for hidden in range(64):
                acc[hidden] += weights["input"][base + hidden]
        scores.append(sum(max(0, min(127, value)) * weight for value, weight in zip(acc, weights["output"])))
    difference = scores[0] - scores[1]
    score = (abs(difference) // 8) * (-1 if difference < 0 else 1)
    return (score if board.turn == chess.WHITE else -score) + 10


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=32)
    args = parser.parse_args()
    rng = random.Random(0xE101A11)
    headers = {"production": arrays(ROOT / "include/eloi/nnue_weights.hpp"), "koth": arrays(ROOT / "include/eloi/nnue_koth_weights.hpp"), "atomic": arrays(ROOT / "include/eloi/nnue_atomic_weights.hpp")}
    checked = 0
    for key, constructor, model in (
        ("standard", chess.Board, "production"),
        ("chess960", lambda: chess.Board.from_chess960_pos(rng.randrange(960)), "production"),
        ("horde", chess.variant.HordeBoard, "production"),
        ("kingOfTheHill", chess.variant.KingOfTheHillBoard, "koth"),
        ("atomic", chess.variant.AtomicBoard, "atomic"),
        ("antichess", chess.variant.AntichessBoard, "production"),
        ("crazyhouse", chess.variant.CrazyhouseBoard, "production"),
    ):
        for _ in range(args.samples):
            board = constructor()
            for _ in range(rng.randrange(40)):
                if board.is_game_over(): break
                board.push(rng.choice(list(board.legal_moves)))
            fen = board.shredder_fen() if board.chess960 else board.fen()
            expected = reference(board, headers[model])
            actual = int(subprocess.check_output([str(args.engine.resolve()), "--nnue", "--variant", key, "--fen", fen], text=True, timeout=10))
            if actual != expected: raise AssertionError(f"{key}: expected {expected}, actual {actual}; {fen}")
            checked += 1
    print(f"Python/Rust scalar NNUE parity: {checked}/{checked} exact")


if __name__ == "__main__":
    main()
