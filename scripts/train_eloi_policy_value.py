#!/usr/bin/env python3
"""Train Eloi's compact dual-head policy/value laboratory network.

The model consumes ordinary Standard-chess piece planes. A shared hidden layer
feeds W/D/L value logits and a factorized legal-move policy head. It is a lab
artifact until search integration, tactical gates and gauntlets qualify it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import struct
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess

MAGIC = b"EPV1"
INPUTS = 781  # 12x64 pieces, side, four castling bits, eight en-passant files
HIDDEN = 64
PROMOTIONS = 5
PIECES = 6


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def board_features(board: chess.Board) -> np.ndarray:
    result = np.zeros(INPUTS, dtype=np.float32)
    for square, piece in board.piece_map().items():
        plane = (0 if piece.color == board.turn else 6) + piece.piece_type - 1
        oriented = square if board.turn == chess.WHITE else square ^ 56
        result[plane * 64 + oriented] = 1.0
    result[768] = 1.0
    rights = (
        board.has_kingside_castling_rights(board.turn),
        board.has_queenside_castling_rights(board.turn),
        board.has_kingside_castling_rights(not board.turn),
        board.has_queenside_castling_rights(not board.turn),
    )
    result[769:773] = rights
    if board.ep_square is not None:
        result[773 + chess.square_file(board.ep_square)] = 1.0
    return result


def move_features(board: chess.Board, move: chess.Move) -> tuple[int, int, int, int]:
    source = move.from_square if board.turn == chess.WHITE else move.from_square ^ 56
    target = move.to_square if board.turn == chess.WHITE else move.to_square ^ 56
    piece = board.piece_type_at(move.from_square)
    promotion = move.promotion or 0
    if promotion:
        promotion -= 1
    if piece is None:
        raise ValueError("policy move has no source piece")
    return source, target, promotion, piece - 1


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    values = np.exp(shifted)
    return values / values.sum()


class Network:
    def __init__(self, seed: int):
        rng = np.random.default_rng(seed)
        self.input = rng.normal(0, 0.025, (INPUTS, HIDDEN)).astype(np.float32)
        self.bias = np.zeros(HIDDEN, dtype=np.float32)
        self.value = rng.normal(0, 0.025, (HIDDEN, 3)).astype(np.float32)
        self.value_bias = np.zeros(3, dtype=np.float32)
        self.policy_from = rng.normal(0, 0.025, (64, HIDDEN)).astype(np.float32)
        self.policy_to = rng.normal(0, 0.025, (64, HIDDEN)).astype(np.float32)
        self.policy_promotion = np.zeros((PROMOTIONS, HIDDEN), dtype=np.float32)
        self.policy_piece = np.zeros((PIECES, HIDDEN), dtype=np.float32)

    def hidden(self, features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pre = features @ self.input + self.bias
        return pre, np.maximum(pre, 0)

    def predict(self, board: chess.Board, moves: list[chess.Move]) -> tuple[np.ndarray, np.ndarray]:
        _, hidden = self.hidden(board_features(board))
        value = softmax(hidden @ self.value + self.value_bias)
        logits = []
        for move in moves:
            source, target, promotion, piece = move_features(board, move)
            weights = (self.policy_from[source] + self.policy_to[target] +
                       self.policy_promotion[promotion] + self.policy_piece[piece])
            logits.append(float(hidden @ weights))
        return value, softmax(np.asarray(logits, dtype=np.float32))

    def update(self, row: dict, learning_rate: float) -> tuple[float, float]:
        board = chess.Board(row["fen"])
        policy_rows = row["policy"]
        moves = [chess.Move.from_uci(item["move"]) for item in policy_rows]
        target_policy = np.asarray([item["probability"] for item in policy_rows], dtype=np.float32)
        target_policy /= target_policy.sum()
        target_value = np.asarray([row["value_wdl"][key] for key in ("win", "draw", "loss")], dtype=np.float32)
        features = board_features(board)
        pre, hidden = self.hidden(features)
        value = softmax(hidden @ self.value + self.value_bias)
        move_weights = []
        indices = []
        for move in moves:
            indices.append(move_features(board, move))
            source, target, promotion, piece = indices[-1]
            move_weights.append(self.policy_from[source] + self.policy_to[target] +
                                self.policy_promotion[promotion] + self.policy_piece[piece])
        move_weights = np.asarray(move_weights)
        policy = softmax(move_weights @ hidden)
        value_error = value - target_value
        policy_error = (policy - target_policy) * float(row.get("tactical_weight", 1.0))
        hidden_grad = self.value @ value_error + move_weights.T @ policy_error
        old_value = self.value.copy()
        self.value -= learning_rate * np.outer(hidden, value_error)
        self.value_bias -= learning_rate * value_error
        for error, (source, target, promotion, piece) in zip(policy_error, indices):
            gradient = learning_rate * error * hidden
            self.policy_from[source] -= gradient
            self.policy_to[target] -= gradient
            self.policy_promotion[promotion] -= gradient
            self.policy_piece[piece] -= gradient
        hidden_grad = (old_value @ value_error + move_weights.T @ policy_error) * (pre > 0)
        self.input -= learning_rate * np.outer(features, hidden_grad)
        self.bias -= learning_rate * hidden_grad
        return (-float(np.sum(target_value * np.log(value + 1e-9))),
                -float(np.sum(target_policy * np.log(policy + 1e-9))))

    def save(self, path: Path) -> None:
        arrays = (self.input, self.bias, self.value, self.value_bias,
                  self.policy_from, self.policy_to,
                  self.policy_promotion, self.policy_piece)
        with path.open("xb") as stream:
            stream.write(struct.pack("<4sIIII", MAGIC, INPUTS, HIDDEN,
                                     PROMOTIONS, PIECES))
            for array in arrays:
                stream.write(np.asarray(array, dtype="<f4").tobytes())

    def snapshot(self) -> tuple[np.ndarray, ...]:
        return tuple(array.copy() for array in (
            self.input, self.bias, self.value, self.value_bias,
            self.policy_from, self.policy_to,
            self.policy_promotion, self.policy_piece))

    def restore(self, state: tuple[np.ndarray, ...]) -> None:
        (self.input, self.bias, self.value, self.value_bias,
         self.policy_from, self.policy_to,
         self.policy_promotion, self.policy_piece) = state


def load_rows(path: Path) -> dict[str, list[dict]]:
    result = {name: [] for name in ("train", "validation", "test")}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            result[row["partition"]].append(row)
    if not result["train"] or not result["validation"]:
        raise ValueError("training and validation partitions must both be nonempty")
    return result


def evaluate(network: Network, rows: list[dict]) -> dict[str, float]:
    value_loss = policy_loss = top1 = 0.0
    for row in rows:
        board = chess.Board(row["fen"])
        policy_rows = row["policy"]
        moves = [chess.Move.from_uci(item["move"]) for item in policy_rows]
        value, policy = network.predict(board, moves)
        value_target = np.asarray([row["value_wdl"][key] for key in ("win", "draw", "loss")])
        policy_target = np.asarray([item["probability"] for item in policy_rows])
        value_loss -= float(np.sum(value_target * np.log(value + 1e-9)))
        policy_loss -= float(np.sum(policy_target * np.log(policy + 1e-9)))
        top1 += int(np.argmax(policy) == np.argmax(policy_target))
    count = len(rows)
    return {"value_cross_entropy": value_loss / count,
            "policy_cross_entropy": policy_loss / count,
            "policy_top1": top1 / count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.002)
    parser.add_argument("--seed", type=int, default=20260913)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    validation_support = __import__("validation_support")
    validation_support.resource_snapshot(args.output, projected=2_000_000)
    rows = load_rows(args.dataset)
    # Test remains sealed: count it, but never evaluate it during selection.
    network = Network(args.seed)
    before = evaluate(network, rows["validation"])
    rng = random.Random(args.seed)
    started = time.monotonic()
    history = []
    best_metric = float("inf")
    best_epoch = 0
    best_state = network.snapshot()
    for epoch in range(args.epochs):
        rng.shuffle(rows["train"])
        value_loss = policy_loss = 0.0
        for row in rows["train"]:
            value, policy = network.update(row, args.learning_rate)
            value_loss += value
            policy_loss += policy
        validation = evaluate(network, rows["validation"])
        history.append({"epoch": epoch + 1,
                        "train_value_loss": value_loss / len(rows["train"]),
                        "train_policy_loss": policy_loss / len(rows["train"]),
                        "validation": validation})
        print(json.dumps(history[-1]), flush=True)
        metric = (validation["policy_cross_entropy"] +
                  0.25 * validation["value_cross_entropy"])
        if metric < best_metric:
            best_metric = metric
            best_epoch = epoch + 1
            best_state = network.snapshot()
    network.restore(best_state)
    model = args.output / "eloi-policy-value.epv"
    network.save(model)
    manifest = {
        "schema": "eloi-policy-value-training-v1", "status": "complete",
        "dataset_sha256": sha256_file(args.dataset), "model_sha256": sha256_file(model),
        "architecture": {"inputs": INPUTS, "hidden": HIDDEN,
                         "value_outputs": ["win", "draw", "loss"],
                         "policy": "factorized from/to/promotion/piece"},
        "rows": {key: len(value) for key, value in rows.items()},
        "test_partition_opened": False, "seed": args.seed,
        "epochs": args.epochs, "learning_rate": args.learning_rate,
        "selected_epoch": best_epoch,
        "selection_metric": "policy_cross_entropy + 0.25 * value_cross_entropy",
        "selected_validation": evaluate(network, rows["validation"]),
        "validation_before": before, "history": history,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "promotion_status": "laboratory_only",
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
