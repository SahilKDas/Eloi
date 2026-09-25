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

## Current native NNUE: E4-10, 64 hidden units

Canonical lineage: [data/nnue_provenance.json](data/nnue_provenance.json).

- Header SHA-256:
  `4C705496950E27204C976F0D027CAA9C73B209961584F7998742AA481B524E88`.
- Float checkpoint SHA-256:
  `D613B853FE534B6AD3604080E559DB26D9CCC55E124005FE60B9ABBCD508EE99`.
- Parent E2 header SHA-256:
  `E3DFBE02F4DC765C45E243EFD4437E9EC3390D4F167531D6F54765CECB899C9F`.
- Archived E2 provenance:
  [data/nnue_provenance_e2.json](data/nnue_provenance_e2.json).

### E4-10 correction and selection

E4-10 starts from the exact E2-ranking network. Its targets blend 80% E2
static evaluation with 20% bounded corrected teacher evaluation, retain 12,000
E2-preservation ranking pairs, and add 55 high-weight child-position rankings
from eight regression cases. The selected export applies 10% of the learned
delta over E2.

E4-10 passed the retained correctness suite and scored 7W/7D/6L against E2
in its initial screen. In 400 disjoint direct games against E4-20, it scored
129W/153D/118L, 205.5/400 (51.375%), with zero protocol failures and
complete independent legal replay. Caissa 1.25 remains the default Standard
brain; E4-10 is the selectable native GUI brain and the required brain for
Chess960, Horde, explicit native mode, and emergency fallback.

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
3,985 test positions**. Test labels were not used to select C or E2.

Labels SHA-256:
`D39429903DDD13FB722EE84073322532415A0D22DF4951202EB89F79110E4038`.
The canonical puzzle input SHA-256 is
`D3E78A34A458964DDE73A3A3316F6195D3455E23AEAD5094303396074A903016`.
Its source and sampling hashes remain in `data/nnue_input_manifest.json`
and `data/nnue_broader_sample_manifest.json`.

### E2 parent recipe and quantization

1. Start from exact C, whose A→B→C recipe remains in
   [its archived provenance](data/nnue_provenance_v2_5_0.json).
2. Mine 166 orthodox hard positions from E1's worst mirrored games and split
   them into 130 training and 36 validation positions with an independent salt.
3. Blend C and 100,000-node offline teacher targets at fraction 0.50.
4. Retain canonical tactical rankings and emphasize 365 new hard-ranking pairs
   at weight 1.50 for three epochs.
5. Anchor the trained parameter delta toward C, retaining 70% of the delta.
6. Quantize the selected float checkpoint directly into the 64-unit header.

Input weights use NumPy rounding and clipping to [-127,127] int8;
bias/output weights use rounded int16. Checkpoint-to-export integer-array
correspondence was verified. The exact E2-ranking header was copied into
production, not regenerated or reformatted for release.

E2-ranking's standard validation MAE was 178.10225 cp and its mean absolute
drift from C was 43.10625 cp. Its held-out hard-pair accuracy remained only
30.303%; offline accuracy alone is not playing strength. The maintainer's
promotion decision is in [RELEASE_V2_7_5.md](RELEASE_V2_7_5.md).

The C parent had **41 dormant channels**. E2 did not claim a separate channel
revival result, so this lineage concern remains documented rather than silently
declared fixed. See [FUTURE_WORK.md](FUTURE_WORK.md).
Stockfish supplied historical numeric labels only. Its code, executable,
weights and backend are not part of Eloi or either release package.

### Why earlier provenance remains

E2 depends on C, whose exact provenance is preserved in
[data/nnue_provenance_v2_5_0.json](data/nnue_provenance_v2_5_0.json). C in
turn depends on its parent network. The parent's original 12,000 evaluation
positions and 12,000 puzzle-ranking examples came from the 2026-08-02 Lichess
CC0 samples. Preserve [the parent provenance](data/nnue_provenance_pre_v2_5_0.json),
input manifest and canonical-sample manifest even though obsolete architecture
playoff plans and duplicate reports have been removed from the current tree.

Reusable bounded acquisition, sampling, analysis, training, equivalence and
channel-audit tools remain under `scripts/`. They enforce data/partition
integrity and are development tools, not automatic release steps.
C's frozen fresh-data records retain their original outcome fields; E2's later
promotion does not rewrite them.

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

E2-ranking's production header is
`E3DFBE02F4DC765C45E243EFD4437E9EC3390D4F167531D6F54765CECB899C9F`.
Its staged evidence and limitations are in
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

## Eloi-native policy/value v2 laboratory corpus

The EPV2 campaign consumes the retained canonical Lichess CC0 evaluation and
puzzle JSONL files only. It selects exactly 150,000 Standard positions with
source-group isolation, exact 80/10/10 train/validation/sealed-test counts,
canonical and color-mirrored deduplication, explicit source-game deduplication,
and exclusion of Eloi regression fixtures. Caissa 1.25 and its pinned local
network provide offline labels at 10,000 nodes; neither becomes an EPV2 runtime
dependency. Rare category shortfalls are reported and backfilled from unique
broad positions rather than duplicated.

The generated dataset, screening rows, checkpoints, and EPV2 models remain
ignored laboratory artifacts under `tmp/`. Their source, runner, executable,
network, partition, category, and output hashes are recorded by the campaign
manifest. The sealed test partition is not opened during checkpoint selection.
See [ELOI_NATIVE_POLICY_VALUE_V2.md](ELOI_NATIVE_POLICY_VALUE_V2.md).

## E4-KOTH variant model

E4-KOTH starts from the preserved E4-10 checkpoint and uses 20,000
deterministic, unique, nonterminal King of the Hill positions: 17,953 for
training and 2,047 for validation. Half use broad random play and half bias
king movement toward the four hill squares. Targets are E4-10 evaluations plus
the frozen 120 cp relative hill-distance adjustment. No Stockfish, Caissa,
network download, live game, Standard regression fixture, Chess960 position,
or Horde position entered this campaign.

The promoted v3.4.3 source header is byte-derived from the qualified header
whose SHA-256 is
`E06F0B3A71445933BF066E8FE6B03A9271B94DB522A15180C63DA4703E5FBF8E`;
only its C++ namespace changes during embedding. The selected checkpoint is
`D2DC34D6CA95AC280B6093E6EA2F6D6DA6148291152043DA2C2961B3B272361C`.
Its use is restricted to KOTH by model-aware accumulator and transposition
identity. See [E4_KOTH_CAMPAIGN.md](E4_KOTH_CAMPAIGN.md) and
[data/nnue_e4_koth_results.json](data/nnue_e4_koth_results.json).
