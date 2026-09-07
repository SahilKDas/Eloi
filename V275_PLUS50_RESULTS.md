# v2.7.5 +50 Elo experiment

## Decision

The candidate is **not qualified to replace Eloi v2.7.5**.

The fixed-node gauntlet showed a positive result, but not the requested +50 Elo margin. The timed gauntlet was interrupted by a candidate engine failure after 38 games and therefore failed its protocol regardless of its favorable partial score.

## Candidate

Source branch: `codex/v275-plus50`

Source commit: `12df974ed63030604e84f6ca6231026063b45655`

Candidate executable SHA-256:

`6C7FEBA0C6DAA7636FB936A3B726BE3BC1553B393790AE0D1E265E15B14A7E1D`

Frozen v2.7.5 baseline SHA-256:

`80002F4AC83AD3D87DA0FB3A87E67A49179BEA0230A764167B58B112184E4695`

Implemented changes:

- Correct root recapture SEE timing: RootSplit now evaluates a prospective root capture on the pre-move board before deciding whether to extend it.
- Return the sole legal move immediately instead of spending clock on a decision that cannot change.
- Track and report selective depth in UCI and diagnostic JSON.
- Add regression coverage for selective depth and the forced-reply fast path.

The full C++ correctness suite and GUI smoke suite passed before either match.

## 250-game fixed-node gauntlet

Protocol:

- 25,000 nodes per move
- Three threads per engine
- 32 MB hash per engine
- 200-ply maximum
- Books and noise disabled
- Windows Idle priority
- 124 mirrored opening pairs plus one predeclared candidate-White game
- Required score: 57.15%, used as the predeclared +50 Elo proxy

Result:

- 80 wins
- 104 draws
- 66 losses
- 132/250 points
- 52.80% score
- Approximately +19.5 Elo descriptively
- Zero protocol failures
- Gate failed

Independent replay verified all 250 games, every move was legal, checkpoint results matched PGN results, and no protocol failure was present.

Evidence:

- `tmp/v275-plus50-gauntlet250-nodes/protocol.json`
- `tmp/v275-plus50-gauntlet250-nodes/checkpoint.json`
- `tmp/v275-plus50-gauntlet250-nodes/games.pgn`
- `tmp/v275-plus50-gauntlet250-nodes/replay-verification.json`
- PGN SHA-256: `2CDCECD73C9CAE6EA259E973563E3910906F98D768169F86290ED76C3DB6E209`

## 100-game 250-ms gauntlet

Protocol:

- 250 ms per move
- Three threads per engine
- 32 MB hash per engine
- 200-ply maximum
- Books and noise disabled
- Windows Idle priority
- 50 mirrored opening pairs planned
- Required score: 57.15%

At the user's explicit request, this campaign began concurrently with the closing portion of the fixed-node campaign. That produced exactly two simultaneous games: four isolated engine processes and twelve search threads total. Each process had private memory, TT, histories, and UCI pipes; campaign files were disjoint.

Observed before termination:

- 38/100 games completed
- 16 wins
- 12 draws
- 10 losses
- 22/38 points
- 57.89% partial score
- One candidate engine failure in game 38
- Gate failed because the denominator was incomplete and a protocol failure occurred

The game-38 partial PGN is retained with `Termination "candidate engine failure"` and `ProtocolFailure "engine failure"`. Windows Event Viewer contained no Eloi application-crash record at the failure time, so the exact cause is unresolved. The run was not resumed or replaced.

Independent replay verified all recorded moves as legal and all 38 checkpoint results against the PGN, including the explicitly recorded protocol failure.

Evidence:

- `tmp/v275-plus50-gauntlet100-250ms/protocol.json`
- `tmp/v275-plus50-gauntlet100-250ms/checkpoint.json`
- `tmp/v275-plus50-gauntlet100-250ms/games.pgn`
- `tmp/v275-plus50-gauntlet100-250ms/replay-verification.json`
- PGN SHA-256: `B486928891CA8C68E96291680C209C25AC3573C8E3CD5DD71F03F0D51DEADAB8`

## Separate bridge finding

The previously reported Glimbus queen hang was not reproduced as a search-choice failure. The bridge submitted a stale result calculated before a manual move was made on Eloi's side. A fresh search of the post-capture position preserved the queen. That bridge state-race requires its own guard and must not be used as evidence for relaxing or widening engine search.

## Follow-up

Keep v2.7.5 as production champion. Before another strength candidate:

1. Reproduce the timed game-38 engine failure under a short crash-containment harness.
2. Preserve stderr and identify the offending process and last UCI command.
3. Add a bridge position/version guard so a stale search result cannot be submitted after external board state changes.
4. Use selective-depth telemetry to compare tactical regressions and only make another pruning or extension change when a concrete divergence supports it.
5. Screen any next candidate before committing another full gauntlet.
