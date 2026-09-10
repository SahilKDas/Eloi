#!/usr/bin/env python3
"""Train quantization-aware Caissa v1.2.5-network successors for Eloi."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import random
import struct
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess

BASE_SHA = "615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B"
MAGIC = 0x43534E4E
INPUTS = 24_576
WIDTH = 1_024
VARIANTS = 8
HEADER = 64
INPUT_BYTES = INPUTS * WIDTH * 2
BIAS_OFFSET = HEADER + INPUT_BYTES
HEAD_OFFSET = BIAS_OFFSET + WIDTH * 2
FILE_BYTES = 50_367_040
KING_BUCKET = (0,1,2,3,3,2,1,0,4,5,6,7,7,6,5,4,8,9,10,11,11,10,9,8,12,13,14,15,15,14,13,12,16,17,18,19,19,18,17,16,20,21,22,23,23,22,21,20,24,25,26,27,27,26,25,24,28,29,30,31,31,30,29,28)


def file_sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def feature_indices(board: chess.Board, perspective: chess.Color) -> np.ndarray:
    king = board.king(perspective)
    if king is None:
        raise ValueError("position has no perspective king")
    transformed_king = king ^ (0 if perspective else 56)
    file_flip = 7 if chess.square_file(transformed_king) >= 4 else 0
    bucket = KING_BUCKET[transformed_king ^ file_flip]
    result = []
    for relative_colour, colour in enumerate((perspective, not perspective)):
        for piece_type in range(chess.PAWN, chess.KING + 1):
            for square in board.pieces(piece_type, colour):
                transformed = square ^ (0 if perspective else 56) ^ file_flip
                result.append(bucket * 768 + relative_colour * 384 + (piece_type - 1) * 64 + transformed)
    return np.asarray(result, dtype=np.int32)


def material(board: chess.Board) -> tuple[int, float]:
    non_kings = len(board.piece_map()) - 2
    phase = sum(len(board.pieces(pt, colour)) * value for colour in chess.COLORS for pt, value in ((chess.KNIGHT, 1), (chess.BISHOP, 1), (chess.ROOK, 2), (chess.QUEEN, 4)))
    return min(non_kings // 4, 7), (52.0 + phase) / 64.0


def castling_adjustment(board: chess.Board) -> float:
    bonus = 0
    if board.king(chess.WHITE) != chess.E1:
        bonus += 5 * ((board.castling_rights & chess.BB_RANK_1).bit_count())
    if board.king(chess.BLACK) != chess.E8:
        bonus -= 5 * ((board.castling_rights & chess.BB_RANK_8).bit_count())
    return float(bonus if board.turn else -bonus)


def teacher_stm_cp(board: chess.Board, white_cp: int) -> float:
    return float(white_cp if board.turn else -white_cp)


class PackedNetwork:
    def __init__(self, source: pathlib.Path):
        self.source_bytes = bytearray(source.read_bytes())
        if len(self.source_bytes) != FILE_BYTES or struct.unpack_from("<2I", self.source_bytes) != (MAGIC, 12):
            raise ValueError("unsupported packed network")
        self.input = np.frombuffer(self.source_bytes, dtype="<i2", count=INPUTS * WIDTH, offset=HEADER).reshape(INPUTS, WIDTH).astype(np.float32) / 256.0
        self.bias = np.frombuffer(self.source_bytes, dtype="<i2", count=WIDTH, offset=BIAS_OFFSET).astype(np.float32) / 256.0
        self.heads = []
        self.head_biases = []
        for variant in range(VARIANTS):
            offset = HEAD_OFFSET + variant * 4_160
            self.heads.append(np.frombuffer(self.source_bytes, dtype="<i2", count=2 * WIDTH, offset=offset).astype(np.float32) / 1024.0)
            self.head_biases.append(float(struct.unpack_from("<i", self.source_bytes, offset + 4_096)[0]) / 262_144.0)

    def forward(self, board: chess.Board):
        stm = feature_indices(board, board.turn)
        nstm = feature_indices(board, not board.turn)
        stm_pre = self.bias + self.input[stm].sum(axis=0)
        nstm_pre = self.bias + self.input[nstm].sum(axis=0)
        stm_act = np.clip(stm_pre, 0.0, 1.0)
        nstm_act = np.clip(nstm_pre, 0.0, 1.0)
        variant, phase = material(board)
        head = self.heads[variant]
        logistic = self.head_biases[variant] + float(stm_act @ head[:WIDTH]) + float(nstm_act @ head[WIDTH:])
        internal = logistic * 174.0
        deployed = (internal * phase + castling_adjustment(board)) * 100.0 / 173.0
        return deployed, (stm, nstm, stm_pre, nstm_pre, stm_act, nstm_act, variant, phase)

    def update(self, board: chess.Board, target_cp: float, input_lr: float, head_lr: float, sample_weight: float = 1.0) -> float:
        prediction, cache = self.forward(board)
        error = float(np.clip(prediction - target_cp, -300.0, 300.0)) * sample_weight
        stm, nstm, stm_pre, nstm_pre, stm_act, nstm_act, variant, phase = cache
        head = self.heads[variant]
        old_stm = head[:WIDTH].copy()
        old_nstm = head[WIDTH:].copy()
        output_chain = 174.0 * phase * 100.0 / 173.0
        grad_logistic = error * output_chain
        head[:WIDTH] -= head_lr * grad_logistic * stm_act
        head[WIDTH:] -= head_lr * grad_logistic * nstm_act
        self.head_biases[variant] -= head_lr * grad_logistic
        stm_grad = input_lr * grad_logistic * old_stm * ((stm_pre > 0.0) & (stm_pre < 1.0))
        nstm_grad = input_lr * grad_logistic * old_nstm * ((nstm_pre > 0.0) & (nstm_pre < 1.0))
        self.input[stm] -= stm_grad
        self.input[nstm] -= nstm_grad
        self.bias -= stm_grad + nstm_grad
        np.clip(head, -31.999, 31.999, out=head)
        np.clip(self.input[stm], -127.99, 127.99, out=self.input[stm])
        np.clip(self.input[nstm], -127.99, 127.99, out=self.input[nstm])
        return abs(prediction - target_cp)

    def save(self, target: pathlib.Path) -> dict[str, int]:
        data = bytearray(self.source_bytes)
        original_input = np.frombuffer(self.source_bytes, dtype="<i2", count=INPUTS * WIDTH, offset=HEADER)
        quant_input = np.rint(np.clip(self.input * 256.0, -32768, 32767)).astype(np.int16).ravel()
        changed_input = int(np.count_nonzero(quant_input != original_input))
        np.frombuffer(data, dtype="<i2", count=INPUTS * WIDTH, offset=HEADER)[:] = quant_input
        quant_bias = np.rint(np.clip(self.bias * 256.0, -32768, 32767)).astype(np.int16)
        np.frombuffer(data, dtype="<i2", count=WIDTH, offset=BIAS_OFFSET)[:] = quant_bias
        changed_heads = 0
        for variant in range(VARIANTS):
            offset = HEAD_OFFSET + variant * 4_160
            original = np.frombuffer(self.source_bytes, dtype="<i2", count=2 * WIDTH, offset=offset)
            quant = np.rint(np.clip(self.heads[variant] * 1024.0, -32768, 32767)).astype(np.int16)
            changed_heads += int(np.count_nonzero(quant != original))
            np.frombuffer(data, dtype="<i2", count=2 * WIDTH, offset=offset)[:] = quant
            struct.pack_into("<i", data, offset + 4_096, round(self.head_biases[variant] * 262_144.0))
        target.write_bytes(data)
        return {"changed_input_weights": changed_input, "changed_output_weights": changed_heads}


def load_evaluations(path: pathlib.Path, partition: str) -> list[tuple[str, str, int, float]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if item.get("partition") != partition or item.get("score_type") != "cp" or not isinstance(item.get("score_white_cp"), int):
                continue
            rows.append((item["record_id"], item["fen"], item["score_white_cp"], 1.0))
    return rows


def load_hard_examples(path: pathlib.Path) -> list[tuple[str, str, int, float]]:
    rows = []
    if not path:
        return rows
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            rows.append((item["id"], item["fen"], int(item["score_white_cp"]), float(item.get("weight", 2.0))))
    return rows


def mae(network: PackedNetwork, rows, limit: int = 4_000) -> float:
    total = 0.0
    for _, fen, white_cp, _ in rows[:limit]:
        board = chess.Board(fen)
        prediction, _ = network.forward(board)
        total += abs(prediction - teacher_stm_cp(board, white_cp))
    return total / min(len(rows), limit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=pathlib.Path, required=True)
    parser.add_argument("--evaluations", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--name", choices=("C5", "C6"), required=True)
    parser.add_argument("--hard-examples", type=pathlib.Path)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--input-lr", type=float, default=2e-7)
    parser.add_argument("--head-lr", type=float, default=2e-8)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    base_hash = file_sha(args.base)
    if args.name == "C5" and base_hash != BASE_SHA:
        raise ValueError("C5 must start from production C0")
    train = load_evaluations(args.evaluations, "train")
    validation = load_evaluations(args.evaluations, "validation")
    test_count = len(load_evaluations(args.evaluations, "test"))
    hard = load_hard_examples(args.hard_examples)
    rows = train + hard
    rng = random.Random(args.seed)
    network = PackedNetwork(args.base)
    before = mae(network, validation)
    started = time.time()
    manifest = {"status":"running","candidate":args.name,"base_sha256":base_hash,"seed":args.seed,"epochs":args.epochs,"standard_only":True,"train_rows":len(train),"hard_rows":len(hard),"validation_rows":len(validation),"test_rows_sealed":test_count,"input_lr":args.input_lr,"head_lr":args.head_lr,"deployed_score_loss":True}
    (args.output / "run.lock.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    running_loss = 0.0
    updates = 0
    for epoch in range(args.epochs):
        rng.shuffle(rows)
        for _, fen, white_cp, weight in rows:
            board = chess.Board(fen)
            if len(board.piece_map()) - 2 <= 6:
                continue
            running_loss += network.update(board, teacher_stm_cp(board, white_cp), args.input_lr, args.head_lr, weight)
            updates += 1
            if updates % 1_000 == 0:
                checkpoint = dict(manifest, epoch=epoch+1, updates=updates, train_mae_running_cp=running_loss/updates, elapsed_seconds=time.time()-started)
                (args.output / "checkpoint.json").write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"epoch":epoch+1,"updates":updates,"mae":running_loss/updates,"seconds":round(time.time()-started,1)}), flush=True)
    candidate = args.output / f"{args.name}.pnn"
    delta = network.save(candidate)
    quantized = PackedNetwork(candidate)
    after = mae(quantized, validation)
    result = dict(manifest, status="complete", updates=updates, train_mae_cp=running_loss/updates, validation_mae_before_cp=before, validation_mae_after_cp=after, candidate_sha256=file_sha(candidate), elapsed_seconds=time.time()-started, **delta)
    if delta["changed_input_weights"] < 25_000:
        result["status"] = "rejected_quantization"
    (args.output / "checkpoint.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (args.output / "run.lock.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
