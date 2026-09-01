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
import random
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


def train_evaluations(weights, bias, output, samples, epochs=2):
    rng = random.Random(0x5A17)
    for epoch in range(epochs):
        rng.shuffle(samples)
        absolute_error = 0.0
        for white, black, target in samples:
            score, aw, ab = forward(
                weights, bias, output, white, black
            )
            error = float(np.clip(target - score, -200, 200))
            absolute_error += abs(target - score)
            old_output = output.copy()
            output += 0.0000015 * error * (aw - ab)
            gradient = 0.000004 * error * old_output / SCALE
            np.add.at(weights, white, gradient * ((aw > 0) & (aw < 127)))
            np.add.at(
                weights, black, -gradient * ((ab > 0) & (ab < 127))
            )
        mean_error = absolute_error / max(1, len(samples))
        print(f"eval epoch {epoch + 1}: mean absolute error {mean_error:.1f} cp")
    return weights, bias, output


def train_pairs(weights, bias, output, pairs, epochs):
    rng = random.Random(0xC026)
    for epoch in range(epochs):
        rng.shuffle(pairs)
        correct = 0
        rate = 0.0007 / (1 + epoch * 0.4)
        for best_white, best_black, alt_white, alt_black, side in pairs:
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
            output += rate * side * ((baw - bab) - (aaw - aab))
            gradient = rate * side * old_output / SCALE
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
    return weights, bias, output


def validation_metrics(weights, bias, output, evaluations, pairs):
    errors = [
        abs(forward(weights, bias, output, white, black)[0] - target)
        for white, black, target in evaluations
    ]
    correct = 0
    for best_white, best_black, alt_white, alt_black, side in pairs:
        best = forward(
            weights, bias, output, best_white, best_black
        )[0]
        other = forward(
            weights, bias, output, alt_white, alt_black
        )[0]
        correct += side * (best - other) > 0
    return {
        "evaluation_mae_cp": float(np.mean(errors)) if errors else None,
        "tactical_accuracy": correct / len(pairs) if pairs else None,
    }


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


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


def write_header(path, weights, bias, output, counts, themes):
    hidden = len(output)
    values = np.clip(
        np.rint(weights), -127, 127
    ).astype(np.int8).reshape(-1)
    quantized_bias = np.rint(bias).astype(np.int16)
    quantized_output = np.rint(output).astype(np.int16)
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
            '"Lichess CC0 evaluations and puzzles; see provenance JSON";\n'
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
            "input{{{{\n"
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
    args = parser.parse_args()

    if not 0 < args.max_temp_gb <= 7.0:
        parser.error("--max-temp-gb must be greater than zero and at most 7")
    if not 0 < args.validation_fraction < 0.5:
        parser.error("--validation-fraction must be between 0 and 0.5")
    if any(hidden not in (64, 128) for hidden in args.architectures):
        parser.error("--architectures accepts only 64 and 128")
    if not args.puzzles.is_file() or not args.evaluations.is_file():
        parser.error("both streamed NNUE input files must exist")

    budget_bytes = int(args.max_temp_gb * 1024**3)
    args.temp_dir.mkdir(parents=True, exist_ok=True)
    enforce_budget(args.temp_dir, budget_bytes)

    train_pairs_data, validation_pairs, themes = load_pairs(
        args.puzzles, args.limit, args.validation_fraction
    )
    train_evals, validation_evals = load_evaluations(
        args.evaluations, args.eval_limit, args.validation_fraction
    )
    if not train_pairs_data or not train_evals:
        raise RuntimeError("training inputs yielded no usable Standard positions")
    dataset = Dataset(
        train_evals,
        validation_evals,
        train_pairs_data,
        validation_pairs,
        themes,
    )
    counts = {
        "train_evaluations": len(dataset.train_evaluations),
        "validation_evaluations": len(dataset.validation_evaluations),
        "train_pairs": len(dataset.train_pairs),
        "validation_pairs": len(dataset.validation_pairs),
    }

    candidates = []
    for hidden in sorted(set(args.architectures)):
        print(f"training {hidden}-hidden-unit candidate")
        weights, bias, output = initialize(hidden)
        weights, bias, output = train_evaluations(
            weights, bias, output, dataset.train_evaluations
        )
        weights, bias, output = train_pairs(
            weights, bias, output, dataset.train_pairs, args.epochs
        )
        metrics = validation_metrics(
            weights,
            bias,
            output,
            dataset.validation_evaluations,
            dataset.validation_pairs,
        )
        print(f"validation {hidden}: {json.dumps(metrics, sort_keys=True)}")
        candidates.append((model_quality(metrics), hidden, metrics,
                           weights, bias, output))

    _, hidden, selected_metrics, weights, bias, output = max(
        candidates, key=lambda candidate: candidate[0]
    )
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

    provenance = {
        "schema": 1,
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
        "parameters": {
            "architectures": sorted(set(args.architectures)),
            "epochs": args.epochs,
            "puzzle_limit_per_split": args.limit,
            "evaluation_limit_per_split": args.eval_limit,
            "validation_fraction": args.validation_fraction,
        },
        "counts": counts,
        "candidates": [
            {"hidden": candidate[1], **candidate[2]}
            for candidate in candidates
        ],
        "selected_hidden": hidden,
        "selected_validation": selected_metrics,
        "selected_weights_sha256": file_sha256(staged_weights),
    }
    staged_provenance = stage / "nnue_provenance.json"
    staged_provenance.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    enforce_budget(args.temp_dir, budget_bytes)

    for target in (args.output, args.architecture_output, args.provenance):
        target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_weights, args.output)
    os.replace(staged_architecture, args.architecture_output)
    os.replace(staged_provenance, args.provenance)
    shutil.rmtree(stage)
    enforce_budget(args.temp_dir, budget_bytes)
    print(
        f"selected {hidden} hidden units; compact outputs written and "
        "temporary candidate artifacts removed"
    )


if __name__ == "__main__":
    main()
