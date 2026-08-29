#!/usr/bin/env python3
"""Train Eloi's embedded king-bucketed NNUE from Lichess CC0 puzzles."""

import argparse, csv, json, pathlib, random, sys
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / ".deps" / "python"))
import chess

HIDDEN, BUCKETS = 64, 8
FEATURES, SCALE = BUCKETS * 12 * 64, 8.0

def orient(square, side):
    return square if side == chess.WHITE else square ^ 56

def features(board, side):
    king = orient(board.king(side), side)
    bucket = (chess.square_file(king) >= 4) + 2 * (chess.square_rank(king) // 2)
    result = []
    for square, piece in board.piece_map().items():
        piece_plane = {chess.PAWN: 0, chess.BISHOP: 1, chess.KNIGHT: 2,
                       chess.ROOK: 3, chess.QUEEN: 4, chess.KING: 5}
        plane = (0 if piece.color == side else 6) + piece_plane[piece.piece_type]
        result.append((bucket * 12 + plane) * 64 + orient(square, side))
    return np.asarray(result, dtype=np.int32)

def initialize():
    rng = np.random.default_rng(0xE101)
    weights = rng.normal(0, .12, (FEATURES, HIDDEN)).astype(np.float32)
    bias = np.full(HIDDEN, 8, dtype=np.float32)
    output = rng.normal(0, .04, HIDDEN).astype(np.float32)
    output[:6] = np.array([100, 325, 315, 500, 900, 0], dtype=np.float32)
    output[12:18] = np.array([1.2, 2, 2.3, .8, .4, 0], dtype=np.float32)
    for feature in range(FEATURES):
        plane, square = (feature // 64) % 12, feature % 64
        if plane < 6:
            weights[feature, plane] += 8
            center = 7 - abs(chess.square_file(square) * 2 - 7) \
                       - abs(chess.square_rank(square) * 2 - 7)
            weights[feature, 12 + plane] += center * .35
    return weights, bias, output

def forward(weights, bias, output, white, black):
    aw = np.clip(bias + weights[white].sum(axis=0), 0, 127)
    ab = np.clip(bias + weights[black].sum(axis=0), 0, 127)
    return float(np.dot(aw - ab, output) / SCALE), aw, ab

def load_pairs(path, limit):
    rng, pairs, themes = random.Random(0xE101), [], set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            moves = row["Moves"].split()
            try:
                board = chess.Board(row["FEN"])
                board.push_uci(moves[0])
                side = board.turn
                best = chess.Move.from_uci(moves[1])
                alternatives = [m for m in board.legal_moves if m != best]
                if best not in board.legal_moves or not alternatives: continue
                best_board, alt_board = board.copy(stack=False), board.copy(stack=False)
                best_board.push(best); alt_board.push(rng.choice(alternatives))
                pairs.append((features(best_board, chess.WHITE),
                              features(best_board, chess.BLACK),
                              features(alt_board, chess.WHITE),
                              features(alt_board, chess.BLACK),
                              1 if side == chess.WHITE else -1))
                themes.update(row["Themes"].split())
            except (ValueError, IndexError, TypeError):
                continue
            if len(pairs) >= limit: break
    return pairs, themes

def load_evaluations(path, limit):
    samples = []
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            try:
                row = json.loads(line)
                fen = row["fen"]
                if len(fen.split()) == 4: fen += " 0 1"
                board = chess.Board(fen)
                evaluation = max(row["evals"], key=lambda item: item.get("depth", 0))
                pv = evaluation["pvs"][0]
                if "cp" in pv: target = float(np.clip(pv["cp"], -1500, 1500))
                else: target = 1500.0 if pv.get("mate", 0) > 0 else -1500.0
                if board.turn == chess.BLACK: target = -target
                samples.append((features(board, chess.WHITE),
                                features(board, chess.BLACK), target))
            except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
                continue
            if len(samples) >= limit: break
    return samples

def train_evaluations(weights, bias, output, samples, epochs=2):
    rng = random.Random(0x5A17)
    for epoch in range(epochs):
        rng.shuffle(samples); absolute_error = 0.0
        for white, black, target in samples:
            score, aw, ab = forward(weights, bias, output, white, black)
            error = float(np.clip(target - score, -200, 200))
            absolute_error += abs(target - score)
            old_output = output.copy()
            output += .0000015 * error * (aw - ab)
            gradient = .000004 * error * old_output / SCALE
            np.add.at(weights, white, gradient * ((aw > 0) & (aw < 127)))
            np.add.at(weights, black, -gradient * ((ab > 0) & (ab < 127)))
        print(f"eval epoch {epoch + 1}: mean absolute error {absolute_error / len(samples):.1f} cp")
    return weights, bias, output

def train(weights, bias, output, pairs, epochs):
    rng = random.Random(0xC026)
    for epoch in range(epochs):
        rng.shuffle(pairs); correct = 0; rate = .0007 / (1 + epoch * .4)
        for bw, bb, aw, ab, side in pairs:
            bs, baw, bab = forward(weights, bias, output, bw, bb)
            other, aaw, aab = forward(weights, bias, output, aw, ab)
            difference = side * (bs - other)
            correct += difference > 0
            if difference >= 35: continue
            old_output = output.copy()
            output += rate * side * ((baw - bab) - (aaw - aab))
            gradient = rate * side * old_output / SCALE
            np.add.at(weights, bw, gradient * ((baw > 0) & (baw < 127)))
            np.add.at(weights, bb, -gradient * ((bab > 0) & (bab < 127)))
            np.add.at(weights, aw, -gradient * ((aaw > 0) & (aaw < 127)))
            np.add.at(weights, ab, gradient * ((aab > 0) & (aab < 127)))
        print(f"epoch {epoch + 1}: tactical ranking {correct / len(pairs):.1%}")
    return weights, bias, output

def write_header(path, weights, bias, output, eval_count, puzzle_count, themes):
    values = np.clip(np.rint(weights), -127, 127).astype(np.int8).reshape(-1)
    bias = np.rint(bias).astype(np.int16); output = np.rint(output).astype(np.int16)
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("#pragma once\n\n#include <array>\n#include <cstdint>\n#include <string_view>\n\n")
        out.write("namespace eloi::nnue_weights {\n")
        out.write(f"inline constexpr int feature_count = {FEATURES};\n")
        out.write(f"inline constexpr int evaluation_positions = {eval_count};\n")
        out.write(f"inline constexpr int puzzle_positions = {puzzle_count};\n")
        out.write("inline constexpr std::string_view source = \"Lichess CC0 evaluations and puzzles 2026-08-02\";\n")
        for name, array, kind in (("bias", bias, "int16_t"), ("output", output, "int16_t")):
            out.write(f"inline constexpr std::array<std::{kind}, {HIDDEN}> {name}{{{{\n  ")
            out.write(", ".join(map(str, array.tolist())) + "\n}};\n")
        out.write(f"inline constexpr std::array<std::int8_t, {values.size}> input{{{{\n")
        for start in range(0, values.size, 32):
            out.write("  " + ", ".join(map(str, values[start:start+32].tolist())) + ",\n")
        out.write("}};\n}  // namespace eloi::nnue_weights\n")
    print(f"wrote {path}: {eval_count} evaluations, {puzzle_count} puzzles, {len(themes)} themes")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=pathlib.Path,
                        default=pathlib.Path(".deps/lichess_puzzle_sample.csv"))
    parser.add_argument("--evaluations", type=pathlib.Path,
                        default=pathlib.Path(".deps/lichess_eval_sample.jsonl"))
    parser.add_argument("--output", type=pathlib.Path,
                        default=pathlib.Path("include/eloi/nnue_weights.hpp"))
    parser.add_argument("--limit", type=int, default=12000)
    parser.add_argument("--eval-limit", type=int, default=12000)
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()
    pairs, themes = load_pairs(args.puzzles, args.limit)
    evaluations = load_evaluations(args.evaluations, args.eval_limit)
    weights, bias, output = train_evaluations(*initialize(), evaluations)
    weights, bias, output = train(weights, bias, output, pairs, args.epochs)
    write_header(args.output, weights, bias, output,
                 len(evaluations), len(pairs), themes)

if __name__ == "__main__": main()
