#!/usr/bin/env python3
"""Select deterministic tactical regressions from the Lichess CC0 sample."""

import csv, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / ".deps" / "python"))
import chess

root = pathlib.Path(__file__).parents[1]
source = root / ".deps" / "lichess_puzzle_sample.csv"
output = root / "tests" / "tactical_data.hpp"
wanted = {"mateIn1": 12, "mateIn2": 24, "mateIn3": 12}
rows = {theme: [] for theme in wanted}

with source.open(encoding="utf-8-sig", newline="") as stream:
    for row in csv.DictReader(stream):
        themes = set(row["Themes"].split())
        for theme, limit in wanted.items():
            if theme not in themes or len(rows[theme]) >= limit: continue
            try:
                board = chess.Board(row["FEN"])
                moves = row["Moves"].split()
                board.push_uci(moves[0])
                best = chess.Move.from_uci(moves[1])
                if best not in board.legal_moves: continue
                rows[theme].append((board.fen(), moves[1]))
            except (ValueError, IndexError):
                pass
        if all(len(rows[t]) == n for t, n in wanted.items()): break

with output.open("w", encoding="utf-8", newline="\n") as out:
    out.write("#pragma once\n\n#include <array>\n#include <string_view>\n\n")
    out.write("namespace tactical_data {\nstruct Case { std::string_view fen; std::string_view best; };\n")
    for theme, cases in rows.items():
        out.write(f"inline constexpr std::array<Case, {len(cases)}> {theme}{{{{\n")
        for fen, best in cases:
            out.write(f"  {{\"{fen}\", \"{best}\"}},\n")
        out.write("}};\n")
    out.write("}  // namespace tactical_data\n")

print(", ".join(f"{theme}={len(cases)}" for theme, cases in rows.items()))
