# Eloi-Native Policy/Value v2 Campaign

## Status and boundary

This is a laboratory campaign. Production remains Eloi v3.1.2, where Standard
UCI and native Lichess use crash-contained Caissa 1.25. EPV2 is never packaged
or described as the playing model unless its exact artifact actually played.

The first qualification opponent is native Eloi E2, not production Caissa.
Passing the E2 gate makes EPV2 the preferred unreleased Eloi-native research
brain only. A separate future gate against v3.1.2 is required for production.

## Frozen data protocol

The collector targets exactly 150,000 unique, nonterminal Standard positions
from the canonical public evaluation and puzzle corpora. It excludes regression
EPDs, Chess960, Horde, source-game duplicates, exact canonical duplicates, and
color-mirrored equivalents.

Source groups retain their sealed partition. Selection enforces 120,000 train,
15,000 validation, and 15,000 sealed-test positions.

The requested mixture is 50% broad, 15% Eloi/Caissa disagreements, 10% forced
or low-mobility positions, 10% promotions, 10% mate threats, and 5% quiet
defenses. Rare-category shortages are backfilled from broad coverage and
reported. Positions are never copied to fake a quota.

Every eligible root receives sequential 1,000-node screening probes. Selected
roots receive frozen 10,000-node Caissa 1.25 labels, three teacher threads, and
at most twelve complete-move candidate rescoring probes. The collector verifies
the laboratory route from UCI output, verifies the pinned network hash, records
all executable/source/runner hashes, checkpoints every 100 rows, and resumes
only under the identical protocol.

All output stays under `tmp/eloi-native-v2-teacher-150000`. Resource checks
enforce the repository's 8 GB training and 10 GB total temporary-byte caps.

## EPV2 format and training

EPV1 remains readable for historical evidence. EPV2 uses 781 oriented board
inputs, a 64-unit shared ReLU hidden layer, a three-output W/D/L value head, and
a 20,480-entry complete-move interaction policy: 64 sources by 64 destinations
by five promotion states.

Illegal moves are masked before softmax. Castling and every underpromotion have
distinct move indices. Artifacts are deterministic little-endian float32 files
with the `EPV2` magic; pickle and executable payloads are forbidden.

Training uses category-balanced ordering without duplicated rare records,
tactical weights capped at 3.0, deterministic seeds, validation-aware early
stopping, patience 3, and minimum improvement 0.0001. The sealed test partition
is not opened during selection. Every improving checkpoint must pass the
three-lane no-null F4 tactical profile; a new tactical failure rejects that
checkpoint regardless of validation loss.

## Search and qualification

EPV2 is a root-order prior only. Alpha-beta is authoritative. Production
routing, public defaults, Caissa, pruning thresholds, and packaged models do
not change.

Qualification proceeds through dataset audit, Python/C++ parity, correctness
and tactical suites, fixed-node E2 comparison, a 60-game mirrored E2 screen,
and—only after a clean score of at least 50%—a sealed 200-game E2 confirmation.
The confirmation must exceed 50% chess score with no correctness, protocol, or
added tactical failure. Screening and confirmation are never pooled.

## Legacy Lichess autopsy

The native bridge appends token-free completed-game journals below
`%LOCALAPPDATA%\Eloi\autopsy\queue`. It records game identity, moves, clocks,
search telemetry, brain route, executable/version/network identity, and the
explicit role `production_or_legacy`. Tokens, private configuration, chat, and
HTTP headers are excluded.

Run the separate headless worker manually:

```powershell
python -B scripts\lichess_autopsy.py `
  --engine tmp\eloi-native-v2-build\EloiHybridLab.exe `
  --network .deps\caissa\eval-71-v1.25.pnn `
  --watch
```

The worker runs at Idle priority, pauses while the recorded bridge PID is
active, analyzes only completed Standard games, and emits JSON/Markdown reports
plus an aggregate index. Regression suggestions remain quarantined proposals;
they never enter training or tests automatically.
