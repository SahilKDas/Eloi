# Search-first strength recovery

This campaign freezes production NNUE at
`CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E`.
No D-series training or production-network replacement is authorized by this
campaign. Its authoritative protocol is `data/search_recovery_protocol.json`.

## Baseline and scope

The exact official v2.0.0 opponent is
`5F13AB2FEB05DE4171DB39E637FD1322409211872DEBB72AD7BEF88858B5AACF`.
Its release ZIP retains the historical v1.9.6-rc.1 filename; the release tag and
executable hash, not that filename, define the opponent. The preparation script
verifies both the official ZIP hash and the extracted executable hash.

The previous 250-game result was 80 wins, 90 draws, and 80 losses. This campaign
does not interpret it as a strength improvement. D1 was rejected at the engine
gate: the tracked rejection lists `lichess-002mG`, `lichess-001XA`, and two
depth-stability failures. The handoff's claim that it repeated both online
catastrophes is not supported by that rejection JSON; both catastrophe tests
remain mandatory regardless.

## Frozen partitions and selection

Sort the existing 500 unique FENs by the byte digest
`SHA256("eloi-search-recovery-v1\0" + FEN)` and partition into 20 diagnostic,
30 development, 30 confirmation, 150 final, and 270 reserve openings. The files
under `data/search_recovery/` are disjoint and hash-bound by the protocol.
"Sealed" means unused for tuning in this recovery campaign; these positions
come from an existing suite and are not newly independent of historical matches.

- Development: 60 mirrored games, 10,000 nodes per move, tuning only.
- Confirmation: one untouched 60-game fixed-node run for the selected candidate,
  at least 52% score.
- Final: exactly 300 games from 150 sealed mirrored openings, 250 ms per move,
  200-ply adjudication, three threads, 32 MB hash, books and noise off, Windows
  Idle priority; at least 165/300 points (55% score).
- Never change game count or thresholds after game one. Identical-protocol
  checkpoints may resume after interruption; mismatched PGN/checkpoint hashes
  require investigation, not silent repair.

## Implementation order

1. Resource and process preflight, exact baseline acquisition, immutable protocol.
2. Restore v2.0 RootSplit and private TT shards; preserve later terminal fixes,
   regression tests, GUI/Lichess features, and scalar/AVX2 checks.
3. Add production/full-width diagnostics and compare regression traces.
4. Make at most one evidence-selected TT, selectivity, or budget/ordering repair.
   If evidence fits none, stop rather than invent another patch.
5. Full correctness, two clean reproducible builds, depth 1/5/10 performance
   medians (no unexplained >15% regression at depths 5/10), then match stages.
6. Only a passing candidate may become v2.5.0-rc.2 and receive standalone and
   Exoskeleton ZIPs. Failure retains v2.0 as strength champion and produces no
   package. Checkpoint commits are local; no push or publication.

## Resource contract

All work follows `constraints_on_SahilKDas_device.md`. Recovery scratch is capped
at 2 GB within the 10 GB total temporary limit. Preparation conservatively counts
all `.deps` bytes even though some pinned dependencies are not temporary. Only
one heavy build, training job, or match runs at a time. Never interrupt a live
bridge or replace its executable. Keep all source and compact historical
evidence; remove only verified, no-longer-needed recovery build directories.

## Commands

```powershell
.\.deps\lichess-bot\.venv\Scripts\python.exe scripts/search_recovery.py prepare --acquire-baseline
.\.deps\lichess-bot\.venv\Scripts\python.exe scripts/test_search_recovery.py
```

Preparation is idempotent only for byte-identical frozen artifacts. Existing
unrecognized files are never overwritten. The measured state is recorded below
and in the hash-bound JSON evidence, not inferred from this plan.

## Campaign result: stopped at correctness

The initial restoration passed the complete C++ suite. Production and official
v2.0.0 traces agreed on the regression moves at completed depths. UCI mate scores
are rounded to moves, so decoded mate centipawns are not an exact internal-score
comparison. Full-width retained the same NNUE but selected forbidden `c6a7` in
the bishop catastrophe and `c6e5` at its last completed depth in the knight
catastrophe. It is not a safer production setting.

The diagnostic pass found 63 cases where a top-five prior root score was moved
to tenth or later in the next iteration. Many scores were upper bounds, not
exact rankings. This justified a bounded ordering experiment, not confidence
that it would improve strength. The experiment preserved the full previous-
iteration order and disabled helper diversification at the root. It immediately
failed `online-Lc65wiSv-bishop-hang`: depth 6 selected `c6a7`.

The repair was rejected and reverted. Its exact patch, source-state digest,
candidate and test hashes, log, and selected move trace are retained under
`data/search_recovery/` and in `data/search_recovery_rejection.json`. The passing
RootSplit restoration was rebuilt and passed unit/EPD/SEE/TT/quiescence/SIMD,
perft depth 4, and all 96 differential positions after the revert.

No development/confirmation/final match ran; no final opening was used for
tuning. No NNUE training, installation, version bump, ZIP creation, or external
publication occurred. The one-repair allowance is exhausted. A new search
experiment requires a new explicit scope, not silently moving to another idea.

## Diagnostic and harness limitations

- Full-width still uses normal quiescence, TT bounds, extensions, and alpha-beta;
  it is not exhaustive game-theoretic truth.
- Internal TT/root diagnostics are from the instrumented current build, not the
  unmodified official executable. Official comparisons use UCI observations.
- Private-lane node limits are inherited from v2.0 and are not a strict global
  counter: a 10,000-node start-position diagnostic consumed 12,260 aggregate
  nodes. Any future fixed-node strength claim must account for this. No node
  budget repair was added after the one ordering experiment failed.
- Engine Lab starts both Eloi versions with `--move-overhead 0`, in addition to
  configuring UCI. The CLI is necessary because the historical UCI parser does
  not correctly join multiword option names. Neither engine gets a special time
  allowance.
- Match score confidence intervals are descriptive normal approximations over
  mirrored opening-pair scores, not a sequential significance test.
- Staged match guards are unit-tested. The two-build verifier extension passed
  PowerShell syntax validation but was not executed in this failed campaign;
  no two-build/strength qualification is claimed for the rejected candidate.

## Staged runner

`scripts/run_search_recovery.py` accepts `correctness`, `reproducibility`,
`performance`, `development`, `confirmation`, and `final`. Each later stage
requires hash-matching successful earlier evidence; development is tuning-only.
Confirmation and final selection seals prevent switching candidates after
viewing their outcomes. Run artifacts are grouped by executable hash under
`tmp/search-recovery/runs/`. The runner never installs or packages a network or
engine.
