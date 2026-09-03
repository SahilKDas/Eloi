#!/usr/bin/env python3
"""Train, validate, and provenance-lock Eloi's embedded NNUE.

Inputs are streamed and deterministically split by source identity. Temporary
artifacts are quota-checked before every write and can never exceed 7 GiB.
"""

import argparse
import csv
import hashlib
import json
import os
import pathlib
import platform
import random
import re
import shutil
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
for dependency_root in (
    ROOT / ".deps" / "python",
    ROOT / ".deps" / "lichess-bot" / ".venv" / "Lib" / "site-packages",
):
    if dependency_root.is_dir():
        sys.path.insert(0, str(dependency_root))

import numpy as np
import chess

BUCKETS = 8
FEATURES = BUCKETS * 12 * 64
SCALE = 8.0
SEED = 0xE101
MAX_TEMP_BYTES = 7 * 1024**3


@dataclass
class Dataset:
    train_evaluations: list
    validation_evaluations: list
    train_pairs: list
    validation_pairs: list
    themes: set[str]
    test_evaluations: list | None = None
    test_pairs: list | None = None
    metadata: dict | None = None


def orient(square, side):
    return square if side == chess.WHITE else square ^ 56


def features(board, side):
    king_square = board.king(side)
    if king_square is None:
        raise ValueError("Standard NNUE samples require both kings")
    king = orient(king_square, side)
    bucket = (chess.square_file(king) >= 4) + 2 * (
        chess.square_rank(king) // 2
    )
    result = []
    piece_plane = {
        chess.PAWN: 0,
        chess.BISHOP: 1,
        chess.KNIGHT: 2,
        chess.ROOK: 3,
        chess.QUEEN: 4,
        chess.KING: 5,
    }
    for square, piece in board.piece_map().items():
        plane = (
            (0 if piece.color == side else 6) + piece_plane[piece.piece_type]
        )
        result.append(
            (bucket * 12 + plane) * 64 + orient(square, side)
        )
    return np.asarray(result, dtype=np.int32)


def source_is_validation(source, fraction):
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return bucket < fraction


def reservoir_add(items, item, seen, limit, rng):
    if limit <= 0:
        return
    if len(items) < limit:
        items.append(item)
        return
    replacement = rng.randrange(seen)
    if replacement < limit:
        items[replacement] = item


def deterministic_choice(items, *identity_parts):
    if not items:
        raise ValueError("cannot select from an empty sequence")
    identity = "|".join(str(part) for part in identity_parts)
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return items[int.from_bytes(digest[:8], "big") % len(items)]


def bounded_by_record_identity(items, limit):
    if limit <= 0 or len(items) <= limit:
        return items
    return sorted(
        items,
        key=lambda item: hashlib.sha256(
            f"{SEED}|canonical-limit|{item[-1]['record_id']}".encode("utf-8")
        ).digest(),
    )[:limit]


def verify_canonical_manifest(manifest_path, evaluations_path, puzzles_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise RuntimeError("canonical NNUE manifest is not complete")
    if manifest.get("production_outputs_written") is not False:
        raise RuntimeError("canonical NNUE input manifest is not analysis-only")
    for name, path in (
        ("canonical_evaluations", evaluations_path),
        ("canonical_puzzles", puzzles_path),
    ):
        expected = manifest.get("outputs", {}).get(name, {})
        actual_size = path.stat().st_size
        actual_hash = file_sha256(path)
        if actual_size != expected.get("bytes"):
            raise RuntimeError(
                f"{name} size mismatch: {actual_size} != {expected.get('bytes')}"
            )
        if actual_hash != expected.get("sha256"):
            raise RuntimeError(
                f"{name} SHA-256 mismatch: {actual_hash} != "
                f"{expected.get('sha256')}"
            )
    return manifest


def _register_group_partition(group_partitions, row):
    group_id = row["group_id"]
    partition = row["partition"]
    previous = group_partitions.setdefault(group_id, partition)
    if previous != partition:
        raise RuntimeError(
            f"canonical group {group_id} crosses {previous} and {partition}"
        )


def _canonical_metadata(row, fields):
    metadata = {
        "record_id": row["record_id"],
        "partition": row["partition"],
        "group_id": row["group_id"],
    }
    for field in fields:
        if field in row:
            metadata[field] = row[field]
    return metadata


def load_canonical_evaluations(
    path,
    limit,
    confidence_policy,
    open_test,
    group_partitions,
):
    partitions = {"train": [], "validation": [], "test": []}
    source_counts = {"train": 0, "validation": 0, "test": 0}
    weights = {"low": 0.5, "medium": 1.0, "high": 1.5}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
                if row.get("schema") != 2:
                    raise ValueError("unsupported canonical evaluation schema")
                partition = row["partition"]
                if partition not in partitions:
                    raise ValueError(f"invalid partition {partition}")
                _register_group_partition(group_partitions, row)
                source_counts[partition] += 1
                if partition == "test" and not open_test:
                    continue
                board = chess.Board(row["fen"])
                weight = (
                    weights[row["confidence_bucket"]]
                    if confidence_policy == "bucket"
                    else 1.0
                )
                metadata = _canonical_metadata(
                    row,
                    (
                        "confidence_bucket",
                        "phase_bucket",
                        "score_bucket",
                        "score_type",
                        "side_to_move",
                        "tactical_surface",
                    ),
                )
                if row["score_type"] == "mate":
                    mate_distance = row.get("mate_distance_white")
                    if not isinstance(mate_distance, int) or mate_distance == 0:
                        raise ValueError("mate record lacks signed mate distance")
                    target_score = 1500.0 if mate_distance > 0 else -1500.0
                else:
                    target_score = float(row["score_white_cp"])
                partitions[partition].append((
                    features(board, chess.WHITE),
                    features(board, chess.BLACK),
                    target_score,
                    weight,
                    metadata,
                ))
            except (
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ) as error:
                raise RuntimeError(
                    f"invalid canonical evaluation row {line_number}: {error}"
                ) from error
    for partition in partitions:
        partitions[partition] = bounded_by_record_identity(
            partitions[partition], limit
        )
    return partitions, source_counts


def load_canonical_pairs(
    path,
    limit,
    negative_mode,
    open_test,
    group_partitions,
):
    partitions = {"train": [], "validation": [], "test": []}
    source_counts = {"train": 0, "validation": 0, "test": 0}
    themes = set()
    puzzle_records = {"train": [], "validation": [], "test": []}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
                if row.get("schema") != 2:
                    raise ValueError("unsupported canonical puzzle schema")
                partition = row["partition"]
                if partition not in partitions:
                    raise ValueError(f"invalid partition {partition}")
                _register_group_partition(group_partitions, row)
                source_counts[partition] += 1
                themes.update(row.get("themes", []))
                if partition == "test" and not open_test:
                    continue
                board = chess.Board(row["decision_fen"])
                best = chess.Move.from_uci(row["best_move"])
                if best not in board.legal_moves:
                    raise ValueError("stored best move is illegal")
                alternatives = []
                if negative_mode == "hard":
                    for alternative in row.get("hard_alternatives", []):
                        move = chess.Move.from_uci(alternative["move"])
                        if move in board.legal_moves and move != best:
                            alternatives.append((move, alternative["tier"]))
                else:
                    legal = sorted(
                        (move for move in board.legal_moves if move != best),
                        key=lambda move: move.uci(),
                    )
                    move = deterministic_choice(
                        legal, SEED, "canonical-random-negative", row["record_id"]
                    )
                    alternatives.append((move, "random"))
                if not alternatives:
                    raise ValueError("no legal negative alternative")
                puzzle_records[partition].append((row, board, best, alternatives))
            except (
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ) as error:
                raise RuntimeError(
                    f"invalid canonical puzzle row {line_number}: {error}"
                ) from error

    for partition, records in puzzle_records.items():
        selected = bounded_by_record_identity(
            [
                (row, board, best, alternatives, {"record_id": row["record_id"]})
                for row, board, best, alternatives in records
            ],
            limit,
        )
        for row, board, best, alternatives, _ in selected:
            side = 1 if board.turn == chess.WHITE else -1
            best_board = board.copy(stack=False)
            best_board.push(best)
            best_white = features(best_board, chess.WHITE)
            best_black = features(best_board, chess.BLACK)
            for alternative, tier in alternatives:
                alt_board = board.copy(stack=False)
                alt_board.push(alternative)
                metadata = _canonical_metadata(
                    row,
                    (
                        "best_move_class",
                        "phase_bucket",
                        "rating_bucket",
                        "theme_family",
                    ),
                )
                metadata["negative_tier"] = tier
                metadata["alternative_move"] = alternative.uci()
                partitions[partition].append((
                    best_white,
                    best_black,
                    features(alt_board, chess.WHITE),
                    features(alt_board, chess.BLACK),
                    side,
                    1.0,
                    metadata,
                ))
    return partitions, themes, source_counts


def load_canonical_dataset(
    evaluations_path,
    puzzles_path,
    manifest_path,
    eval_limit,
    puzzle_limit,
    confidence_policy,
    negative_mode,
    open_test,
):
    manifest = verify_canonical_manifest(
        manifest_path, evaluations_path, puzzles_path
    )
    group_partitions = {}
    evaluations, evaluation_source_counts = load_canonical_evaluations(
        evaluations_path,
        eval_limit,
        confidence_policy,
        open_test,
        group_partitions,
    )
    pairs, themes, puzzle_source_counts = load_canonical_pairs(
        puzzles_path,
        puzzle_limit,
        negative_mode,
        open_test,
        group_partitions,
    )
    return Dataset(
        train_evaluations=evaluations["train"],
        validation_evaluations=evaluations["validation"],
        train_pairs=pairs["train"],
        validation_pairs=pairs["validation"],
        themes=themes,
        test_evaluations=evaluations["test"] if open_test else None,
        test_pairs=pairs["test"] if open_test else None,
        metadata={
            "format": "canonical-schema-2",
            "sample_id": manifest["sample_id"],
            "manifest_sha256": file_sha256(manifest_path),
            "source_partition_counts": {
                "evaluations": evaluation_source_counts,
                "puzzles": puzzle_source_counts,
            },
            "group_count": len(group_partitions),
            "confidence_policy": confidence_policy,
            "negative_mode": negative_mode,
            "test_opened": open_test,
        },
    )


def initialize(hidden):
    rng = np.random.default_rng(SEED + hidden)
    weights = rng.normal(0, 0.12, (FEATURES, hidden)).astype(np.float32)
    bias = np.full(hidden, 8, dtype=np.float32)
    output = rng.normal(0, 0.04, hidden).astype(np.float32)
    material = np.array([100, 325, 315, 500, 900, 0], dtype=np.float32)
    output[: min(6, hidden)] = material[: min(6, hidden)]
    if hidden >= 18:
        output[12:18] = np.array(
            [1.2, 2, 2.3, 0.8, 0.4, 0], dtype=np.float32
        )
    for feature in range(FEATURES):
        plane, square = (feature // 64) % 12, feature % 64
        if plane < 6 and plane < hidden:
            weights[feature, plane] += 8
            center = (
                7
                - abs(chess.square_file(square) * 2 - 7)
                - abs(chess.square_rank(square) * 2 - 7)
            )
            if 12 + plane < hidden:
                weights[feature, 12 + plane] += center * 0.35
    return weights, bias, output


def forward(weights, bias, output, white, black):
    aw = np.clip(bias + weights[white].sum(axis=0), 0, 127)
    ab = np.clip(bias + weights[black].sum(axis=0), 0, 127)
    return float(np.dot(aw - ab, output) / SCALE), aw, ab


def quantize_model(weights, bias, output):
    return (
        np.clip(np.rint(weights), -127, 127).astype(np.int8),
        np.rint(bias).astype(np.int16),
        np.rint(output).astype(np.int16),
    )


def forward_quantized(weights, bias, output, white, black):
    raw_white = (
        bias.astype(np.int64)
        + weights[white].sum(axis=0, dtype=np.int64)
    )
    raw_black = (
        bias.astype(np.int64)
        + weights[black].sum(axis=0, dtype=np.int64)
    )
    active_white = np.clip(raw_white, 0, 127)
    active_black = np.clip(raw_black, 0, 127)
    total = int(np.dot(active_white - active_black, output.astype(np.int64)))
    score = int(total / int(SCALE))
    return score, raw_white, raw_black


def load_pairs(path, limit, validation_fraction):
    rng = random.Random(SEED)
    train, validation, themes = [], [], set()
    seen = [0, 0]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), 2):
            moves = row.get("Moves", "").split()
            try:
                board = chess.Board(row["FEN"])
                board.push_uci(moves[0])
                side = board.turn
                best = chess.Move.from_uci(moves[1])
                legal = list(board.legal_moves)
                alternatives = [move for move in legal if move != best]
                if best not in legal or not alternatives:
                    continue
                best_board = board.copy(stack=False)
                alt_board = board.copy(stack=False)
                best_board.push(best)
                alt_board.push(rng.choice(alternatives))
                item = (
                    features(best_board, chess.WHITE),
                    features(best_board, chess.BLACK),
                    features(alt_board, chess.WHITE),
                    features(alt_board, chess.BLACK),
                    1 if side == chess.WHITE else -1,
                )
                source = (
                    row.get("GameId")
                    or row.get("Source")
                    or row.get("PuzzleId")
                    or f"puzzle-row-{row_number}"
                )
                split = int(source_is_validation(source, validation_fraction))
                target = validation if split else train
                seen[split] += 1
                reservoir_add(target, item, seen[split], limit, rng)
                themes.update(row.get("Themes", "").split())
            except (ValueError, KeyError, IndexError, TypeError):
                continue
    return train, validation, themes


def load_evaluations(path, limit, validation_fraction):
    rng = random.Random(SEED ^ 0x5A17)
    train, validation = [], []
    seen = [0, 0]
    with path.open(encoding="utf-8-sig") as stream:
        for row_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
                fen = row["fen"]
                if len(fen.split()) == 4:
                    fen += " 0 1"
                board = chess.Board(fen)
                evaluation = max(
                    row["evals"], key=lambda item: item.get("depth", 0)
                )
                pv = evaluation["pvs"][0]
                if "cp" in pv:
                    target_score = float(np.clip(pv["cp"], -1500, 1500))
                else:
                    target_score = (
                        1500.0 if pv.get("mate", 0) > 0 else -1500.0
                    )
                if board.turn == chess.BLACK:
                    target_score = -target_score
                item = (
                    features(board, chess.WHITE),
                    features(board, chess.BLACK),
                    target_score,
                )
                source = str(
                    row.get("game_id")
                    or row.get("source")
                    or row.get("id")
                    or fen.split(" ")[0]
                    or f"evaluation-row-{row_number}"
                )
                split = int(source_is_validation(source, validation_fraction))
                target = validation if split else train
                seen[split] += 1
                reservoir_add(target, item, seen[split], limit, rng)
            except (
                ValueError,
                KeyError,
                IndexError,
                TypeError,
                json.JSONDecodeError,
            ):
                continue
    return train, validation


def _trainable_channel_mask(output, trainable_channels):
    if trainable_channels is None:
        return None
    indices = sorted(set(int(index) for index in trainable_channels))
    if any(index < 0 or index >= len(output) for index in indices):
        raise ValueError("trainable channel index is outside the network")
    mask = np.zeros(len(output), dtype=np.float32)
    mask[indices] = 1.0
    return mask


def train_evaluations(weights, bias, output, samples, epochs=2,
                      trainable_channels=None, epoch_callback=None):
    channel_mask = _trainable_channel_mask(output, trainable_channels)
    rng = random.Random(0x5A17)
    for epoch in range(epochs):
        rng.shuffle(samples)
        absolute_error = 0.0
        for sample in samples:
            white, black, target = sample[:3]
            sample_weight = sample[3] if len(sample) > 3 else 1.0
            score, aw, ab = forward(
                weights, bias, output, white, black
            )
            error = float(np.clip(target - score, -200, 200)) * sample_weight
            absolute_error += abs(target - score)
            old_output = output.copy()
            output_update = 0.0000015 * error * (aw - ab)
            output += (
                output_update
                if channel_mask is None
                else output_update * channel_mask
            )
            gradient = 0.000004 * error * old_output / SCALE
            if channel_mask is not None:
                gradient *= channel_mask
            np.add.at(weights, white, gradient * ((aw > 0) & (aw < 127)))
            np.add.at(
                weights, black, -gradient * ((ab > 0) & (ab < 127))
            )
        mean_error = absolute_error / max(1, len(samples))
        print(f"eval epoch {epoch + 1}: mean absolute error {mean_error:.1f} cp")
        if epoch_callback is not None:
            epoch_callback(
                epoch + 1,
                weights,
                bias,
                output,
                {"mean_absolute_error_cp": mean_error},
            )
    return weights, bias, output


def train_pairs(weights, bias, output, pairs, epochs,
                trainable_channels=None, epoch_callback=None):
    channel_mask = _trainable_channel_mask(output, trainable_channels)
    rng = random.Random(0xC026)
    for epoch in range(epochs):
        rng.shuffle(pairs)
        correct = 0
        rate = 0.0007 / (1 + epoch * 0.4)
        for sample in pairs:
            best_white, best_black, alt_white, alt_black, side = sample[:5]
            sample_weight = sample[5] if len(sample) > 5 else 1.0
            best, baw, bab = forward(
                weights, bias, output, best_white, best_black
            )
            other, aaw, aab = forward(
                weights, bias, output, alt_white, alt_black
            )
            difference = side * (best - other)
            correct += difference > 0
            if difference >= 35:
                continue
            old_output = output.copy()
            output_update = (
                rate
                * sample_weight
                * side
                * ((baw - bab) - (aaw - aab))
            )
            output += (
                output_update
                if channel_mask is None
                else output_update * channel_mask
            )
            gradient = rate * sample_weight * side * old_output / SCALE
            if channel_mask is not None:
                gradient *= channel_mask
            np.add.at(
                weights,
                best_white,
                gradient * ((baw > 0) & (baw < 127)),
            )
            np.add.at(
                weights,
                best_black,
                -gradient * ((bab > 0) & (bab < 127)),
            )
            np.add.at(
                weights,
                alt_white,
                -gradient * ((aaw > 0) & (aaw < 127)),
            )
            np.add.at(
                weights,
                alt_black,
                gradient * ((aab > 0) & (aab < 127)),
            )
        accuracy = correct / max(1, len(pairs))
        print(f"epoch {epoch + 1}: tactical ranking {accuracy:.1%}")
        if epoch_callback is not None:
            epoch_callback(
                epoch + 1,
                weights,
                bias,
                output,
                {"pairwise_accuracy": accuracy},
            )
    return weights, bias, output


def _regression_summary(predictions, targets):
    if not predictions:
        return {
            "count": 0,
            "mae_cp": None,
            "median_absolute_error_cp": None,
            "rmse_cp": None,
            "sign_accuracy_outside_25cp": None,
        }
    predicted = np.asarray(predictions, dtype=np.float64)
    expected = np.asarray(targets, dtype=np.float64)
    errors = np.abs(predicted - expected)
    decisive = np.abs(expected) > 25
    sign_accuracy = (
        float(np.mean(np.sign(predicted[decisive]) == np.sign(expected[decisive])))
        if np.any(decisive)
        else None
    )
    return {
        "count": len(predictions),
        "mae_cp": float(np.mean(errors)),
        "median_absolute_error_cp": float(np.median(errors)),
        "rmse_cp": float(np.sqrt(np.mean((predicted - expected) ** 2))),
        "sign_accuracy_outside_25cp": sign_accuracy,
    }


def _ranking_summary(margins, record_ids):
    if not margins:
        return {
            "pair_count": 0,
            "puzzle_count": 0,
            "pairwise_accuracy": None,
            "top1_accuracy": None,
            "mean_margin_cp": None,
            "margin_35cp_fraction": None,
        }
    grouped = {}
    for record_id, margin in zip(record_ids, margins):
        grouped.setdefault(record_id, []).append(margin)
    return {
        "pair_count": len(margins),
        "puzzle_count": len(grouped),
        "pairwise_accuracy": float(np.mean(np.asarray(margins) > 0)),
        "top1_accuracy": float(
            np.mean([min(values) > 0 for values in grouped.values()])
        ),
        "mean_margin_cp": float(np.mean(margins)),
        "margin_35cp_fraction": float(np.mean(np.asarray(margins) >= 35)),
    }


def _slice_regression(samples, float_predictions, quantized_predictions):
    fields = (
        "phase_bucket",
        "confidence_bucket",
        "score_bucket",
        "score_type",
        "side_to_move",
        "tactical_surface",
    )
    result = {}
    for field in fields:
        buckets = {}
        for index, sample in enumerate(samples):
            metadata = sample[-1] if isinstance(sample[-1], dict) else {}
            value = metadata.get(field)
            if value is None:
                continue
            bucket = buckets.setdefault(
                str(value), {"float": [], "quantized": [], "targets": []}
            )
            bucket["float"].append(float_predictions[index])
            bucket["quantized"].append(quantized_predictions[index])
            bucket["targets"].append(sample[2])
        if buckets:
            result[field] = {
                value: {
                    "float": _regression_summary(
                        values["float"], values["targets"]
                    ),
                    "quantized": _regression_summary(
                        values["quantized"], values["targets"]
                    ),
                }
                for value, values in sorted(buckets.items())
            }
    return result


def _slice_rankings(samples, float_margins, quantized_margins, record_ids):
    fields = (
        "negative_tier",
        "phase_bucket",
        "rating_bucket",
        "theme_family",
        "best_move_class",
    )
    result = {}
    for field in fields:
        buckets = {}
        for index, sample in enumerate(samples):
            metadata = sample[-1] if isinstance(sample[-1], dict) else {}
            value = metadata.get(field)
            if value is None:
                continue
            bucket = buckets.setdefault(
                str(value), {"float": [], "quantized": [], "ids": []}
            )
            bucket["float"].append(float_margins[index])
            bucket["quantized"].append(quantized_margins[index])
            bucket["ids"].append(record_ids[index])
        if buckets:
            result[field] = {
                value: {
                    "float": _ranking_summary(values["float"], values["ids"]),
                    "quantized": _ranking_summary(
                        values["quantized"], values["ids"]
                    ),
                }
                for value, values in sorted(buckets.items())
            }
    return result


def validation_metrics(weights, bias, output, evaluations, pairs):
    quantized_weights, quantized_bias, quantized_output = quantize_model(
        weights, bias, output
    )
    float_predictions = []
    quantized_predictions = []
    targets = []
    max_abs_accumulator = 0
    for sample in evaluations:
        white, black, target = sample[:3]
        float_predictions.append(
            forward(weights, bias, output, white, black)[0]
        )
        score, raw_white, raw_black = forward_quantized(
            quantized_weights,
            quantized_bias,
            quantized_output,
            white,
            black,
        )
        quantized_predictions.append(score)
        targets.append(target)
        max_abs_accumulator = max(
            max_abs_accumulator,
            int(np.max(np.abs(raw_white))),
            int(np.max(np.abs(raw_black))),
        )

    float_margins = []
    quantized_margins = []
    record_ids = []
    ranking_flips = 0
    for index, sample in enumerate(pairs):
        best_white, best_black, alt_white, alt_black, side = sample[:5]
        float_best = forward(
            weights, bias, output, best_white, best_black
        )[0]
        float_other = forward(
            weights, bias, output, alt_white, alt_black
        )[0]
        quantized_best = forward_quantized(
            quantized_weights,
            quantized_bias,
            quantized_output,
            best_white,
            best_black,
        )[0]
        quantized_other = forward_quantized(
            quantized_weights,
            quantized_bias,
            quantized_output,
            alt_white,
            alt_black,
        )[0]
        float_margin = side * (float_best - float_other)
        quantized_margin = side * (quantized_best - quantized_other)
        float_margins.append(float_margin)
        quantized_margins.append(quantized_margin)
        metadata = sample[-1] if isinstance(sample[-1], dict) else {}
        record_ids.append(metadata.get("record_id", f"pair-{index}"))
        ranking_flips += (float_margin > 0) != (quantized_margin > 0)

    float_regression = _regression_summary(float_predictions, targets)
    quantized_regression = _regression_summary(quantized_predictions, targets)
    float_ranking = _ranking_summary(float_margins, record_ids)
    quantized_ranking = _ranking_summary(quantized_margins, record_ids)
    prediction_deltas = np.abs(
        np.asarray(float_predictions) - np.asarray(quantized_predictions)
    )
    return {
        "evaluation_mae_cp": float_regression["mae_cp"],
        "tactical_accuracy": float_ranking["pairwise_accuracy"],
        "float": {
            "evaluations": float_regression,
            "tactical": float_ranking,
        },
        "quantized": {
            "evaluations": quantized_regression,
            "tactical": quantized_ranking,
            "reference_arithmetic": {
                "input_type": "int8",
                "bias_type": "int16",
                "output_type": "int16",
                "accumulator_type": "int32",
                "activation_clamp": [0, 127],
                "division": int(SCALE),
                "division_rounding": "truncate-toward-zero",
            },
            "float_to_quantized_mae_cp": (
                float(np.mean(prediction_deltas))
                if len(prediction_deltas)
                else None
            ),
            "float_to_quantized_max_absolute_cp": (
                float(np.max(prediction_deltas))
                if len(prediction_deltas)
                else None
            ),
            "tactical_ranking_flips": ranking_flips,
            "tactical_ranking_flip_fraction": (
                ranking_flips / len(pairs) if pairs else None
            ),
            "maximum_absolute_accumulator": max_abs_accumulator,
            "int32_accumulator_safe": (
                max_abs_accumulator <= np.iinfo(np.int32).max
            ),
        },
        "slices": {
            "evaluations": _slice_regression(
                evaluations, float_predictions, quantized_predictions
            ),
            "tactical": _slice_rankings(
                pairs, float_margins, quantized_margins, record_ids
            ),
        },
    }


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _read_cpp_array(text, name):
    match = re.search(
        rf"\b{name}\{{\{{(.*?)\}}\}};",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"NNUE header does not contain array {name}")
    return [int(value) for value in re.findall(r"-?\d+", match.group(1))]


def load_quantized_header(path):
    text = path.read_text(encoding="utf-8")
    bias_values = _read_cpp_array(text, "bias")
    output_values = _read_cpp_array(text, "output")
    input_values = _read_cpp_array(text, "input")
    hidden = len(bias_values)
    if hidden not in (32, 64, 128):
        raise RuntimeError(f"unsupported NNUE header width {hidden}")
    if len(output_values) != hidden:
        raise RuntimeError("NNUE header bias/output widths differ")
    if len(input_values) != FEATURES * hidden:
        raise RuntimeError(
            "NNUE header input size mismatch: "
            f"{len(input_values)} != {FEATURES * hidden}"
        )
    return (
        np.asarray(input_values, dtype=np.int8).reshape(FEATURES, hidden),
        np.asarray(bias_values, dtype=np.int16),
        np.asarray(output_values, dtype=np.int16),
    )


def quantized_header_metrics(path, evaluations, pairs):
    weights, bias, output = load_quantized_header(path)
    full = validation_metrics(
        weights.astype(np.float32),
        bias.astype(np.float32),
        output.astype(np.float32),
        evaluations,
        pairs,
    )
    slices = {}
    for family, fields in full["slices"].items():
        slices[family] = {
            field: {
                value: metrics["quantized"]
                for value, metrics in values.items()
            }
            for field, values in fields.items()
        }
    return {
        "hidden": len(output),
        "weights_sha256": file_sha256(path),
        "metrics": full["quantized"],
        "slices": slices,
    }


def quantized_metric_deltas(candidate_metrics, baseline_metrics):
    return {
        "evaluation_mae_cp": (
            candidate_metrics["evaluations"]["mae_cp"]
            - baseline_metrics["evaluations"]["mae_cp"]
        ),
        "evaluation_median_absolute_error_cp": (
            candidate_metrics["evaluations"]["median_absolute_error_cp"]
            - baseline_metrics["evaluations"]["median_absolute_error_cp"]
        ),
        "tactical_pairwise_accuracy": (
            candidate_metrics["tactical"]["pairwise_accuracy"]
            - baseline_metrics["tactical"]["pairwise_accuracy"]
        ),
        "tactical_top1_accuracy": (
            candidate_metrics["tactical"]["top1_accuracy"]
            - baseline_metrics["tactical"]["top1_accuracy"]
        ),
    }


def directory_bytes(path):
    if not path.exists():
        return 0
    return sum(
        item.stat().st_size for item in path.rglob("*") if item.is_file()
    )


def enforce_budget(temp_dir, budget_bytes, additional=0):
    used = directory_bytes(temp_dir)
    if used + additional > budget_bytes:
        raise RuntimeError(
            "NNUE temporary-disk quota would be exceeded: "
            f"{used + additional:,} > {budget_bytes:,} bytes"
        )
    return used


def write_header(path, weights, bias, output, counts, themes,
                 source_description="Lichess CC0 evaluations and puzzles; see provenance JSON"):
    hidden = len(output)
    quantized_weights, quantized_bias, quantized_output = quantize_model(
        weights, bias, output
    )
    values = quantized_weights.reshape(-1)
    estimated = values.size * 5 + hidden * 24 + 1024
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(
            "#pragma once\n\n#include <array>\n#include <cstdint>\n"
            "#include <string_view>\n\nnamespace eloi::nnue_weights {\n"
        )
        out.write(f"inline constexpr int feature_count = {FEATURES};\n")
        out.write(
            f"inline constexpr int evaluation_positions = "
            f"{counts['train_evaluations']};\n"
        )
        out.write(
            f"inline constexpr int puzzle_positions = "
            f"{counts['train_pairs']};\n"
        )
        out.write(
            'inline constexpr std::string_view source = '
            + json.dumps(source_description) + ';\n'
        )
        for name, array, kind in (
            ("bias", quantized_bias, "int16_t"),
            ("output", quantized_output, "int16_t"),
        ):
            out.write(
                f"inline constexpr std::array<std::{kind}, {hidden}> "
                f"{name}{{{{\n  "
            )
            out.write(", ".join(map(str, array.tolist())) + "\n}};\n")
        out.write(
            f"inline constexpr std::array<std::int8_t, {values.size}> "
            "input{{\n"
        )
        for start in range(0, values.size, 32):
            out.write(
                "  "
                + ", ".join(map(str, values[start : start + 32].tolist()))
                + ",\n"
            )
        out.write("}};\n}  // namespace eloi::nnue_weights\n")
    if path.stat().st_size > estimated * 2:
        raise RuntimeError("unexpected NNUE header expansion")
    print(
        f"staged {path}: {counts['train_evaluations']} evaluations, "
        f"{counts['train_pairs']} puzzles, {len(themes)} themes"
    )


def write_architecture(path, hidden):
    path.write_text(
        "#pragma once\n\nnamespace eloi {\n"
        f"inline constexpr int nnue_hidden_size = {hidden};\n"
        "}  // namespace eloi\n",
        encoding="utf-8",
        newline="\n",
    )


def model_quality(metrics):
    accuracy = metrics["tactical_accuracy"]
    mae = metrics["evaluation_mae_cp"]
    return (
        -1.0 if accuracy is None else accuracy,
        float("-inf") if mae is None else -mae,
    )


def train_candidate(hidden, dataset, epochs):
    """Train one architecture without mutating the shared dataset order."""
    weights, bias, output = initialize(hidden)
    weights, bias, output = train_evaluations(
        weights, bias, output, list(dataset.train_evaluations)
    )
    weights, bias, output = train_pairs(
        weights, bias, output, list(dataset.train_pairs), epochs
    )
    metrics = validation_metrics(
        weights,
        bias,
        output,
        dataset.validation_evaluations,
        dataset.validation_pairs,
    )
    return metrics, weights, bias, output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--puzzles",
        type=pathlib.Path,
        default=pathlib.Path(".deps/lichess_puzzle_sample.csv"),
    )
    parser.add_argument(
        "--evaluations",
        type=pathlib.Path,
        default=pathlib.Path(".deps/lichess_eval_sample.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("include/eloi/nnue_weights.hpp"),
    )
    parser.add_argument(
        "--architecture-output",
        type=pathlib.Path,
        default=pathlib.Path("include/eloi/nnue_architecture.hpp"),
    )
    parser.add_argument(
        "--provenance",
        type=pathlib.Path,
        default=pathlib.Path("data/nnue_provenance.json"),
    )
    parser.add_argument(
        "--temp-dir",
        type=pathlib.Path,
        default=pathlib.Path("tmp/nnue-training"),
    )
    parser.add_argument("--max-temp-gb", type=float, default=7.0)
    parser.add_argument("--limit", type=int, default=12000)
    parser.add_argument("--eval-limit", type=int, default=12000)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument(
        "--architectures", type=int, nargs="+", default=[64, 128]
    )
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument(
        "--canonical-manifest",
        type=pathlib.Path,
        help=(
            "consume schema-2 canonical JSONL inputs using their stored group "
            "partitions and verify them against this manifest"
        ),
    )
    parser.add_argument(
        "--confidence-policy",
        choices=("none", "bucket"),
        default="none",
    )
    parser.add_argument(
        "--negative-mode",
        choices=("random", "hard"),
        default="random",
    )
    parser.add_argument(
        "--open-test",
        action="store_true",
        help="explicitly load the frozen canonical test partition",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "compare architectures and write provenance without replacing "
            "the configured weight or architecture outputs"
        ),
    )
    parser.add_argument(
        "--retain-report-candidate",
        action="store_true",
        help=(
            "in report-only mode, retain the selected weights and architecture "
            "under TEMP_DIR/retained for later validation"
        ),
    )
    parser.add_argument(
        "--baseline-weights",
        type=pathlib.Path,
        help=(
            "evaluate this exact quantized NNUE header on the same validation "
            "rows and report candidate-minus-baseline deltas"
        ),
    )
    args = parser.parse_args()

    if not 0 < args.max_temp_gb <= 7.0:
        parser.error("--max-temp-gb must be greater than zero and at most 7")
    if not 0 < args.validation_fraction < 0.5:
        parser.error("--validation-fraction must be between 0 and 0.5")
    if any(hidden not in (32, 64, 128) for hidden in args.architectures):
        parser.error("--architectures accepts only 32, 64 and 128")
    if (
        args.report_only
        and args.canonical_manifest is None
        and len(set(args.architectures)) < 2
    ):
        parser.error("--report-only requires at least two architectures")
    if not args.puzzles.is_file() or not args.evaluations.is_file():
        parser.error("both streamed NNUE input files must exist")
    if args.canonical_manifest is not None and not args.canonical_manifest.is_file():
        parser.error("--canonical-manifest must name an existing manifest")
    if args.open_test and args.canonical_manifest is None:
        parser.error("--open-test requires --canonical-manifest")
    if args.retain_report_candidate and not args.report_only:
        parser.error("--retain-report-candidate requires --report-only")
    if args.baseline_weights is not None and not args.baseline_weights.is_file():
        parser.error("--baseline-weights must name an existing NNUE header")
    if args.canonical_manifest is None and (
        args.confidence_policy != "none" or args.negative_mode != "random"
    ):
        parser.error("confidence and negative policies require canonical inputs")

    budget_bytes = int(args.max_temp_gb * 1024**3)
    args.temp_dir.mkdir(parents=True, exist_ok=True)
    enforce_budget(args.temp_dir, budget_bytes)

    if args.canonical_manifest is not None:
        dataset = load_canonical_dataset(
            args.evaluations,
            args.puzzles,
            args.canonical_manifest,
            args.eval_limit,
            args.limit,
            args.confidence_policy,
            args.negative_mode,
            args.open_test,
        )
    else:
        train_pairs_data, validation_pairs, themes = load_pairs(
            args.puzzles, args.limit, args.validation_fraction
        )
        train_evals, validation_evals = load_evaluations(
            args.evaluations, args.eval_limit, args.validation_fraction
        )
        dataset = Dataset(
            train_evaluations=train_evals,
            validation_evaluations=validation_evals,
            train_pairs=train_pairs_data,
            validation_pairs=validation_pairs,
            themes=themes,
            metadata={"format": "legacy-streamed"},
        )
    if not dataset.train_pairs or not dataset.train_evaluations:
        raise RuntimeError("training inputs yielded no usable Standard positions")
    counts = {
        "train_evaluations": len(dataset.train_evaluations),
        "validation_evaluations": len(dataset.validation_evaluations),
        "train_pairs": len(dataset.train_pairs),
        "validation_pairs": len(dataset.validation_pairs),
        "test_evaluations": (
            len(dataset.test_evaluations)
            if dataset.test_evaluations is not None
            else None
        ),
        "test_pairs": (
            len(dataset.test_pairs)
            if dataset.test_pairs is not None
            else None
        ),
    }

    candidates = []
    for hidden in sorted(set(args.architectures)):
        print(f"training {hidden}-hidden-unit candidate")
        metrics, weights, bias, output = train_candidate(
            hidden, dataset, args.epochs
        )
        print(
            f"validation {hidden}: "
            f"float MAE={metrics['float']['evaluations']['mae_cp']:.3f} cp, "
            f"quantized MAE="
            f"{metrics['quantized']['evaluations']['mae_cp']:.3f} cp, "
            f"float tactical="
            f"{metrics['float']['tactical']['pairwise_accuracy']:.1%}, "
            f"quantized tactical="
            f"{metrics['quantized']['tactical']['pairwise_accuracy']:.1%}, "
            f"ranking flips={metrics['quantized']['tactical_ranking_flips']}"
        )
        candidates.append((model_quality(metrics), hidden, metrics,
                           weights, bias, output))

    _, hidden, selected_metrics, weights, bias, output = max(
        candidates, key=lambda candidate: candidate[0]
    )
    baseline_reference = None
    if args.baseline_weights is not None:
        baseline_reference = quantized_header_metrics(
            args.baseline_weights,
            dataset.validation_evaluations,
            dataset.validation_pairs,
        )
        baseline_metrics = baseline_reference["metrics"]
        candidate_metrics = selected_metrics["quantized"]
        baseline_reference["candidate_minus_baseline"] = (
            quantized_metric_deltas(candidate_metrics, baseline_metrics)
        )

    test_evaluation = None
    if args.open_test:
        if dataset.test_evaluations is None or dataset.test_pairs is None:
            raise RuntimeError("test partition requested but not loaded")
        candidate_test = validation_metrics(
            weights,
            bias,
            output,
            dataset.test_evaluations,
            dataset.test_pairs,
        )
        test_evaluation = {
            "candidate": candidate_test,
            "selection_influenced": False,
        }
        if args.baseline_weights is not None:
            baseline_test = quantized_header_metrics(
                args.baseline_weights,
                dataset.test_evaluations,
                dataset.test_pairs,
            )
            test_evaluation["baseline"] = baseline_test
            test_evaluation["candidate_minus_baseline"] = (
                quantized_metric_deltas(
                    candidate_test["quantized"],
                    baseline_test["metrics"],
                )
            )
        print(
            "test opened after selection: "
            f"quantized MAE="
            f"{candidate_test['quantized']['evaluations']['mae_cp']:.3f} cp, "
            f"quantized tactical="
            f"{candidate_test['quantized']['tactical']['pairwise_accuracy']:.1%}"
        )
    candidate_stage = args.temp_dir / "candidates"
    if candidate_stage.exists():
        shutil.rmtree(candidate_stage)
    candidate_stage.mkdir(parents=True)
    candidate_documents = []
    for candidate in candidates:
        candidate_path = candidate_stage / f"nnue_weights_{candidate[1]}.hpp"
        enforce_budget(
            args.temp_dir,
            budget_bytes,
            additional=FEATURES * candidate[1] * 5 + candidate[1] * 24 + 1024,
        )
        write_header(
            candidate_path,
            candidate[3],
            candidate[4],
            candidate[5],
            counts,
            dataset.themes,
        )
        candidate_documents.append({
            "hidden": candidate[1],
            **candidate[2],
            "weights_sha256": file_sha256(candidate_path),
        })
        enforce_budget(args.temp_dir, budget_bytes)

    stage = args.temp_dir / "selected"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    staged_weights = stage / "nnue_weights.hpp"
    staged_architecture = stage / "nnue_architecture.hpp"
    enforce_budget(
        args.temp_dir,
        budget_bytes,
        additional=FEATURES * hidden * 5 + hidden * 24 + 1024,
    )
    write_header(
        staged_weights, weights, bias, output, counts, dataset.themes
    )
    write_architecture(staged_architecture, hidden)
    enforce_budget(args.temp_dir, budget_bytes)

    retained_candidate = None
    if args.retain_report_candidate:
        retained = args.temp_dir / "retained"
        if retained.exists():
            shutil.rmtree(retained)
        retained.mkdir(parents=True)
        retained_weights = retained / "nnue_weights.hpp"
        retained_architecture = retained / "nnue_architecture.hpp"
        enforce_budget(
            args.temp_dir,
            budget_bytes,
            additional=staged_weights.stat().st_size
            + staged_architecture.stat().st_size,
        )
        shutil.copy2(staged_weights, retained_weights)
        shutil.copy2(staged_architecture, retained_architecture)
        enforce_budget(args.temp_dir, budget_bytes)
        retained_candidate = {
            "weights_path": retained_weights.as_posix(),
            "weights_sha256": file_sha256(retained_weights),
            "architecture_path": retained_architecture.as_posix(),
            "architecture_sha256": file_sha256(retained_architecture),
        }

    provenance = {
        "schema": 1,
        "mode": "comparison-report-only" if args.report_only else "selected-output",
        "outputs_written": not args.report_only,
        "seed": SEED,
        "temporary_disk_hard_limit_bytes": MAX_TEMP_BYTES,
        "temporary_disk_configured_limit_bytes": budget_bytes,
        "inputs": {
            "puzzles": {
                "path": args.puzzles.as_posix(),
                "sha256": file_sha256(args.puzzles),
            },
            "evaluations": {
                "path": args.evaluations.as_posix(),
                "sha256": file_sha256(args.evaluations),
            },
        },
        "environment": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "python_chess_version": getattr(chess, "__version__", "unknown"),
        },
        "parameters": {
            "architectures": sorted(set(args.architectures)),
            "epochs": args.epochs,
            "puzzle_limit_per_split": args.limit,
            "evaluation_limit_per_split": args.eval_limit,
            "validation_fraction": args.validation_fraction,
            "confidence_policy": args.confidence_policy,
            "negative_mode": args.negative_mode,
            "test_opened": args.open_test,
        },
        "counts": counts,
        "dataset": dataset.metadata,
        "candidates": candidate_documents,
        "selected_hidden": hidden,
        "selected_validation": selected_metrics,
        "selected_weights_sha256": file_sha256(staged_weights),
        "retained_candidate": retained_candidate,
        "baseline_reference": baseline_reference,
        "test_evaluation": test_evaluation,
    }
    staged_provenance = stage / "nnue_provenance.json"
    staged_provenance.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    enforce_budget(args.temp_dir, budget_bytes)

    if args.report_only:
        args.provenance.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_provenance, args.provenance)
        shutil.rmtree(stage)
        shutil.rmtree(candidate_stage)
        enforce_budget(args.temp_dir, budget_bytes)
        print(
            f"recommended {hidden} hidden units; comparison provenance written "
            "without replacing model outputs"
        )
        return

    for target in (args.output, args.architecture_output, args.provenance):
        target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_weights, args.output)
    os.replace(staged_architecture, args.architecture_output)
    os.replace(staged_provenance, args.provenance)
    shutil.rmtree(stage)
    shutil.rmtree(candidate_stage)
    enforce_budget(args.temp_dir, budget_bytes)
    print(
        f"selected {hidden} hidden units; compact outputs written and "
        "temporary candidate artifacts removed"
    )


if __name__ == "__main__":
    main()
