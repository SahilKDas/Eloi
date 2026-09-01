# Embedded chess data

Eloi's production executable contains generated opening and NNUE tables. It
does not download data while running.

## Opening repertoire

The general ECO A00-E99 repertoire was generated from
[`lichess-org/chess-openings`](https://github.com/lichess-org/chess-openings)
at commit `4b8622759e7ae6f93f011cc6c83a3823401ab45e`. The collection is dedicated
to the public domain under CC0 1.0. Eloi adds original weighting for its
Italian Game and Nimzo-Indian personality.

`scripts/generate_openings.py` converts the pinned PGN lines into the sorted,
embedded `opening_data.hpp` graph. Positions are nodes, weighted legal moves
are edges, and transpositions naturally share nodes. Python and python-chess
are generation-time tools only.

## NNUE training

The quantized king-bucketed network in `nnue_weights.hpp` was trained on
12,000 Stockfish-evaluated positions and 12,000 move-ranking examples selected
from the Lichess evaluation and puzzle databases dated 2026-08-02. The puzzle
sample covers 73 tactical themes. Lichess database exports are made available
under CC0 1.0.

`scripts/train_nnue.py` documents and reproduces the training and quantization
step from local puzzle CSV and evaluation JSONL streams. It performs a
deterministic source-level training/validation split, evaluates 64- and
128-hidden-unit candidates, and writes `data/nnue_provenance.json` with input
hashes, parameters, validation metrics, and the selected compact-header hash.
Its temporary workspace has a hard 7 GiB ceiling and unsuccessful candidate
artifacts are removed. NumPy and python-chess are generation-time tools only;
they are not runtime or normal-build dependencies.
