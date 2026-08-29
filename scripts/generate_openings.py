#!/usr/bin/env python3
"""Generate Eloi's compact embedded opening table from Lichess CC0 data."""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / ".deps" / "python"))
import chess

SOURCE_COMMIT = "4b8622759e7ae6f93f011cc6c83a3823401ab45e"


def splitmix64(value: int) -> int:
    mask = (1 << 64) - 1
    value = (value + 0x9E3779B97F4A7C15) & mask
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
    return value ^ (value >> 31)


def zobrist(index: int) -> int:
    return splitmix64(0xE101C0265A17 + index * 0x9E3779B97F4A7C15)


def position_key(board: chess.Board) -> int:
    key = 0
    for square, piece in board.piece_map().items():
        color = 0 if piece.color == chess.WHITE else 1
        piece_plane = {chess.PAWN: 0, chess.BISHOP: 1, chess.KNIGHT: 2,
                       chess.ROOK: 3, chess.QUEEN: 4, chess.KING: 5}
        plane = color * 6 + piece_plane[piece.piece_type]
        key ^= zobrist(plane * 64 + square)
    for bit, right in enumerate((chess.BB_H1, chess.BB_A1,
                                 chess.BB_H8, chess.BB_A8)):
        if board.castling_rights & right:
            key ^= zobrist(768 + bit)
    if board.turn == chess.BLACK:
        key ^= zobrist(772)
    if board.ep_square is not None and board.has_legal_en_passant():
        key ^= zobrist(773 + chess.square_file(board.ep_square))
    return key


def encode(move: chess.Move) -> int:
    return move.from_square | (move.to_square << 6) | ((move.promotion or 0) << 12)


def family(name: str) -> int:
    if name.startswith("Italian Game"):
        return 1
    if name.startswith("Nimzo-Indian Defense"):
        return 2
    return 0


def add_line(entries, san_line: str, name: str, bonus: int = 1) -> None:
    board = chess.Board()
    family_id = family(name)
    try:
        for token in san_line.replace("...", " ").split():
            if token.endswith(".") or token[0].isdigit() or token in {"1-0", "0-1", "1/2-1/2"}:
                continue
            move = board.parse_san(token)
            entries[(position_key(board), encode(move), family_id)] += bonus
            board.push(move)
    except (ValueError, IndexError):
        return


SIGNATURE_LINES = (
    ("1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O", "Italian Game: Giuoco Pianissimo"),
    ("1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. b4 Bxb4 5. c3 Ba5 6. d4", "Italian Game: Evans Gambit"),
    ("1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. d3 Bc5 5. O-O d6", "Italian Game: Two Knights Defense"),
    ("1. e4 e5 2. Nf3 Nc6 3. Bc4 Be7 4. d4 d6 5. O-O Nf6", "Italian Game: Hungarian Defense"),
    ("1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 4. e3 O-O 5. Bd3 d5 6. Nf3 c5", "Nimzo-Indian Defense: Rubinstein Variation"),
    ("1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 4. Qc2 O-O 5. a3 Bxc3+ 6. Qxc3", "Nimzo-Indian Defense: Classical Variation"),
    ("1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 4. a3 Bxc3+ 5. bxc3 O-O", "Nimzo-Indian Defense: Saemisch Variation"),
    ("1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 4. Bg5 h6 5. Bh4 c5", "Nimzo-Indian Defense: Leningrad Variation"),
    ("1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 4. e3 c5 5. Bd3 Nc6 6. Nf3 Bxc3+", "Nimzo-Indian Defense: Huebner Variation"),
    ("1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 4. f3 d5 5. a3 Bxc3+", "Nimzo-Indian Defense: Kmoch Variation"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=pathlib.Path,
                        default=pathlib.Path(".deps/lichess-openings"))
    parser.add_argument("--output", type=pathlib.Path,
                        default=pathlib.Path("include/eloi/opening_data.hpp"))
    args = parser.parse_args()

    entries = defaultdict(int)
    for path in sorted(args.source.glob("?.tsv")):
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                add_line(entries, row["pgn"], row["name"])
    for line, name in SIGNATURE_LINES:
        add_line(entries, line, name, 10_000)

    rows = sorted((key, move, min(weight, 65535), family_id)
                  for (key, move, family_id), weight in entries.items())
    nodes = []
    edges = []
    index = 0
    while index < len(rows):
        key = rows[index][0]
        first = len(edges)
        while index < len(rows) and rows[index][0] == key:
            _, move, weight, family_id = rows[index]
            edges.append((move, weight, family_id))
            index += 1
        nodes.append((key, first, len(edges) - first))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        out.write("#pragma once\n\n#include <array>\n#include <cstdint>\n#include <string_view>\n\n")
        out.write("namespace eloi::opening_data {\n")
        out.write("struct Node { std::uint64_t key; std::uint32_t first; std::uint16_t count; };\n")
        out.write("struct Edge { std::uint16_t move; std::uint16_t weight; std::uint8_t family; };\n")
        out.write(f"inline constexpr std::string_view source_commit = \"{SOURCE_COMMIT}\";\n")
        out.write(f"inline constexpr std::array<Node, {len(nodes)}> nodes{{{{\n")
        for key, first, count in nodes:
            out.write(f"  {{0x{key:016x}ULL, {first}, {count}}},\n")
        out.write("}};\n")
        out.write(f"inline constexpr std::array<Edge, {len(edges)}> edges{{{{\n")
        for move, weight, family_id in edges:
            out.write(f"  {{0x{move:04x}, {weight}, {family_id}}},\n")
        out.write("}};\n}  // namespace eloi::opening_data\n")
    print(f"generated graph with {len(nodes)} nodes and {len(edges)} edges from {SOURCE_COMMIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
