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

### Current v2.5.0 network: C

Production embeds the exact 64-unit C header with SHA-256
`6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD`.
`data/nnue_provenance.json` records its current lineage; the previous
production provenance is preserved separately.

The source is the January 2025 [Lichess Elite collection](https://database.nikonoel.fr/),
a filtered subset of [Lichess database exports](https://database.lichess.org/).
The underlying Lichess exports are CC0 1.0; the Elite site describes its
2500+ versus 2300+ selection, excluding bullet. Archive URL, size and hash
are retained in `data/nnue_fresh_data_acquisition.json`. Eloi traversed all
289,776 source games, selected 32,000 by seeded hash, and retained 150,690
phase-sampled candidate positions before labeling and filtering.

Historical offline labels used isolated Stockfish 17.1 searches (5,000 and
25,000 nodes, sampled 100,000-node audits). Accepted labels excluded mates,
checks, capture/promotion best moves, low depth, excessive evaluation drift
and extreme scores. The accepted split contains 32,015 training, 4,000
validation and 3,985 test positions. Group/board and NNUE-input-equivalence
exclusions prevent cross-partition learning overlap; test labels were not
used for candidate selection. Sampling and exclusions are documented in the
frozen fresh-data protocol and results.

C warm-started from the previous production network: two fresh-evaluation
epochs (A), three epochs on 12,000 canonical TRAIN puzzle examples (B), then
one fresh-evaluation recalibration epoch (C). Quantization rounds input
weights and clips them to [-127,127] int8; biases/output weights are rounded
to int16. The retained checkpoint was checked against the exact exported
integer arrays; this release performs no retraining.

Stockfish supplied offline numeric training labels only. No Stockfish code,
process, weights, executable or backend is included in Eloi's runtime or
release packages. Python/NumPy/python-chess are development-only tools.
The 41 dormant warm-start channels remain a documented limitation.

### Previous production training (historical)

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

`scripts/acquire_nnue_samples.py` reproduces the bounded local inputs without
storing either complete upstream archive. It verifies the official
2026-08-02 Lichess archive size, ETag, Last-Modified value, and HTTP byte range;
downloads only the first 16 MiB of each zstd stream; retains 20,000 complete
records per source; hashes the compressed prefixes and retained samples; and
deletes the prefixes. The tracked `data/nnue_input_manifest.json` records those
identities and hashes. The approximately 16 MiB of retained CSV/JSONL inputs
remain ignored under `.deps/nnue-inputs` and are never packaged.

The repeated full 64/128 report-only run is recorded in
`data/nnue_training_comparison.json`. It binds the input hashes, interpreter
and library versions, fixed parameters, split counts, validation metrics, and
both candidate-header hashes. The offline comparison recommended 64 hidden
units. Both architectures then passed identical engine correctness gates, and
the completed 110-game architecture sample selected 64 after the 128 candidate
scored 43.64%. `data/nnue_architecture_playoff.json` records the post-start
sample-size changes, result, selected architecture, and hashes for all retained
evidence. Future larger-data candidates must repeat these gates.

## v2.5 tactical regression corpus

`tests/epd/v2_5_regressions.epd` is a small, human-readable test corpus rather
than an embedded runtime asset. Its Lichess puzzle positions were selected from
the same ignored CC0 puzzle sample described above. Two additional factual FEN
snapshots permanently reproduce Eloi's recorded online failures in Lichess
games `Lc65wiSv` and `bIw09dp9`; the forbidden moves are `c6a7` and `c6e5`.
The corpus contains no credentials, chat text, executable data, or downloaded
PGN, and it is never packaged into either release ZIP.
