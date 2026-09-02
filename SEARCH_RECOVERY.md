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
unrecognized files are never overwritten. The final experiment state and
measured results will be recorded alongside the protocol, not inferred from this
plan.
