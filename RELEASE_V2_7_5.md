# Eloi v2.7.5 source promotion

## Decision

The maintainer selected the 64-unit E2-ranking network as Eloi v2.7.5. The
production header was copied byte-for-byte from the frozen candidate; it was
not regenerated or reformatted.

- Production header SHA-256:
  `E3DFBE02F4DC765C45E243EFD4437E9EC3390D4F167531D6F54765CECB899C9F`
- Float checkpoint SHA-256:
  `E3E3D98C7CDF85E0D8AE82A7F07777E81C9C0FBE6F1BB31774F2DDA2118FCD29`
- Frozen candidate executable SHA-256:
  `966E4E87FB75664F96B2B50DA1603C179EFE380D1D341469B97BA6EAD94BEB66`
- Parent C header SHA-256:
  `6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD`

## Strength evidence

E2-ranking first passed a fully disjoint 125-game qualification against C at
45W/56D/24L, or 73/125 points (58.4%). A separate promotion confirmation used
125 mirrored standard-chess openings excluded from training and all prior E2
match suites.

The 250-game confirmation finished **93W/94D/63L**, or **140/250 points
(56.0%)**. The descriptive paired-opening 95% interval was 51.36%–60.64%, and
the raw-score Elo transform was +41.9. All 250 PGNs replayed legally and no
protocol failure occurred.

Both matches used 10,000 nodes per move, exactly three threads per engine,
32 MB hash, no books or noise, zero move overhead, a 200-ply cap and Windows
Idle priority. These results support E2 over C under that protocol; they do not
establish 250 ms or online-blitz superiority.

## Boundaries

Training, offline validation and strength selection used FIDE standard chess
only. Chess960 and Horde appeared only in mechanical move-generation checks.
Stockfish 17.1 supplied offline labels only and is not Eloi code, a runtime
backend or a release dependency.

## Source validation

A fresh production build consumed the tracked header with no experimental
NNUE include override and reported `Eloi 2.7.5`.

- Clean-build executable SHA-256:
  `80002F4AC83AD3D87DA0FB3A87E67A49179BEA0230A764167B58B112184E4695`
- Python tooling: 95/95 tests passed.
- C++ engine and GUI suites: 2/2 CTest targets passed, including all 15 EPD
  regressions, SEE/TT, board restoration and scalar/runtime NNUE checks.
- Starting-position perft depth 4: 197,281 nodes.
- Differential move generation: 32/32 Standard, 32/32 Chess960 and 32/32
  Horde positions passed; variant rows were mechanical tests only.
- Frozen-candidate identity: same move, score and completed depth on all 15
  regression positions.
- UCI: startup, readiness, infinite-search stop, 10,000-node search, best-move
  response and clean exit passed.
- Benchmark checksums matched frozen E2. Median time ratio was 0.9767 at depth
  5 and 1.0432 at depth 10, within the 15% investigation threshold.

This source promotion does not replace an active v2.5.0 installation and does
not claim that v2.7.5 Windows packages have been published. Package
reproducibility, extracted-package smoke checks and security scans remain
separate gates before binary publication.

Full lineage and limitations are in [DATA_SOURCES.md](DATA_SOURCES.md),
[E2_STANDARD_CAMPAIGN.md](E2_STANDARD_CAMPAIGN.md) and
[data/nnue_e2_standard_results.json](data/nnue_e2_standard_results.json).
