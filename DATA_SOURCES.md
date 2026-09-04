# Eloi data provenance

Eloi embeds generated opening and NNUE tables. It does not download databases
or call another chess engine while playing. Python, NumPy and python-chess
are development-only tools.

## Opening repertoire

The ECO A00-E99 repertoire comes from
[lichess-org/chess-openings](https://github.com/lichess-org/chess-openings)
commit `4b8622759e7ae6f93f011cc6c83a3823401ab45e`, under CC0 1.0.
Eloi adds its Italian Game/Nimzo-Indian weighting.
`scripts/generate_openings.py` produces the tracked position graph in
`include/eloi/opening_data.hpp`; CMake does not regenerate it.

## Current NNUE: C, 64 hidden units

Canonical lineage: [data/nnue_provenance.json](data/nnue_provenance.json).

- Header SHA-256:
  `6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD`.
- Float checkpoint SHA-256:
  `48A40465E1E7A0AB7B408501FBEF78319D62612F6928891AD2B33B58D51AACE9`.
- Warm-start parent header SHA-256:
  `CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E`.

### Sources and sampling

Fresh positions came from the January 2025
[Lichess Elite collection](https://database.nikonoel.fr/), a filtered subset
of [Lichess database exports](https://database.lichess.org/).
The underlying exports are CC0 1.0. The Elite source describes its
2500+ versus 2300+ filter, excluding bullet.

Archive SHA-256:
`F2FA14565BCDABA7AD6DE6A4F8F2348D0F9F8F262935C46E61925C5ACCE6F7B7`.
Acquisition URL/size/hash are in
[data/nnue_fresh_data_acquisition.json](data/nnue_fresh_data_acquisition.json).
Sampling traversed 289,776 games, selected 32,000 by seeded hash and retained
150,690 phase-sampled candidate positions before labeling/filtering.
The retained protocol, sample and training audits record filtering and
game/board/NNUE-input-equivalence exclusions.

Historical offline labels used Stockfish 17.1 at 5,000/25,000 nodes, with
sampled 100,000-node audits. Accepted labels excluded mates, checks,
capture/promotion best moves, low depth, excessive score drift and extremes.
The final accepted evaluation split was **32,015 training, 4,000 validation,
3,985 test positions**. Test labels were not used to select C.

Labels SHA-256:
`D39429903DDD13FB722EE84073322532415A0D22DF4951202EB89F79110E4038`.
The canonical puzzle input SHA-256 is
`D3E78A34A458964DDE73A3A3316F6195D3455E23AEAD5094303396074A903016`.
Its source and sampling hashes remain in `data/nnue_input_manifest.json`
and `data/nnue_broader_sample_manifest.json`.

### Recipe and quantization

1. Convert the previous production quantized parameters to float32.
2. Train two fresh-evaluation epochs to produce A.
3. Train three epochs on 12,000 canonical TRAIN puzzle examples to produce B.
4. Recalibrate with one fresh-evaluation epoch to produce C.

Input weights use NumPy rounding and clipping to [-127,127] int8;
bias/output weights use rounded int16. Checkpoint-to-export integer-array
correspondence was verified. The exact C header was copied into production,
not regenerated or reformatted for release.

C's quantized validation MAE was 181.22 cp versus 211.5815 cp for the parent
on the fresh validation data. Offline accuracy alone is not playing strength.
The maintainer's release decision is in [RELEASE_V2_5_0.md](RELEASE_V2_5_0.md),
with the retained 20-game result and its limitations.

The warm start has **41 dormant channels**; this is a documented limitation,
not a problem solved by release packaging. See [FUTURE_WORK.md](FUTURE_WORK.md).
Stockfish supplied historical numeric labels only. Its code, executable,
weights and backend are not part of Eloi or either release package.

### Why earlier provenance remains

C depends on its parent network. The parent's original 12,000 evaluation
positions and 12,000 puzzle-ranking examples came from the 2026-08-02 Lichess
CC0 samples. Preserve [the parent provenance](data/nnue_provenance_pre_v2_5_0.json),
input manifest and canonical-sample manifest even though obsolete architecture
playoff plans and duplicate reports have been removed from the current tree.

Reusable bounded acquisition, sampling, analysis, training, equivalence and
channel-audit tools remain under `scripts/`. They enforce data/partition
integrity and are development tools, not automatic release steps.
C's frozen fresh-data records retain their original outcome fields; the later
release acceptance decision does not rewrite them.

## Post-v2.5.0 architecture experiments

The E1 dormant-channel revival and 32-unit compaction/training experiments
reuse the exact frozen C inputs above. They do not download or generate new
labels, execute Stockfish, open the sealed test partition, or change production
weights. Candidate identities, correctness outcomes and the preliminary
E1-versus-C screen are recorded in
[data/nnue_e1_e32.json](data/nnue_e1_e32.json).

## E2 standard-only successor experiment

E2 reused C's 40,000 accepted orthodox evaluation positions and 12,000
orthodox training puzzles, then added 166 standard positions mined from E1's
worst mirrored results against C. Stockfish 17.1 supplied offline best-move,
evaluation and restricted-root labels at 100,000/25,000 nodes. The corrected
salted split contained 130 training and 36 validation positions and produced
365 best-versus-plausible-alternative pairs.

No Chess960 or Horde position was used for training, offline selection or
strength play. Variant differential tests were mechanical correctness checks
only. Stockfish remains absent from Eloi runtime and release packages.

The authoritative 125-game final excluded all training, screening and
confirmation learning keys. A valid earlier final with screening/confirmation
overlap is retained as superseded evidence and is not used for the decision.

E2-ranking's retained header is
`E3DFBE02F4DC765C45E243EFD4437E9EC3390D4F167531D6F54765CECB899C9F`.
It is not the production header. Its staged evidence and limitations are in
[E2_STANDARD_CAMPAIGN.md](E2_STANDARD_CAMPAIGN.md) and
[data/nnue_e2_standard_results.json](data/nnue_e2_standard_results.json).

## Regression and strength data

`tests/epd/v2_5_regressions.epd` contains the permanent 15-position tactical
corpus, derived from the same CC0 puzzle sample plus factual FEN snapshots of
Eloi's online games `Lc65wiSv` and `bIw09dp9`. The latter forbid `c6a7`
and `c6e5`. It contains no credentials, chat or executable data.

`data/strength_openings.json` and the five frozen
`data/search_recovery/` opening partitions remain to preserve holdouts and
prevent accidental reuse. The old campaign policy is not an active gate.
C's parallel-screen results, PGNs, protocol and independent audit remain
because the current release cites them.

The unused 2021/2023 Morlock game and tournament collections, retired plans
and superseded campaign reports are available in Git history at
`24e8a4538fd1fcf164ad1747a62e91a01acdccec`.
They are not required to build, run or validate current Eloi.
See [data/README.md](data/README.md) for the retained-file index.
