# Eloi v2.8.0 local promotion

## Decision

The maintainer explicitly accepted the search candidate as Eloi v2.8.0. This
is a local source promotion only. No GitHub push, tag, release, package, or
running installation was changed by this decision.

## Changes

- Evaluate root recapture SEE on the correct pre-move board before deciding
  whether to extend the root move.
- Return immediately when exactly one legal move exists, avoiding needless
  clock expenditure.
- Report selective depth through UCI and diagnostic JSON.
- Add focused regression coverage for selective depth and forced replies.

The 64-unit E2-ranking NNUE and three-thread RootSplit architecture are
unchanged.

## Evidence and acceptance override

The clean fixed-node match against the exact v2.7.5 executable completed
250 games at 25,000 nodes per move:

- 80 wins, 104 draws, 66 losses
- 132/250 points
- 52.80% chess score
- approximately +19.5 Elo by the raw-score transform
- zero protocol failures
- all 250 PGNs independently replayed legally

A separate 100-game match at 250 ms per move stopped after a candidate engine
failure in game 38:

- 16 wins, 12 draws, 10 losses
- 22/38 points
- 57.89% partial score
- one protocol failure
- incomplete denominator

The timed partial result is not a completed 55% match and cannot independently
qualify a release. The maintainer knowingly overrode the original +50-Elo and
protocol-completion requirements. The unresolved timed failure remains a
release risk and must not be erased from future documentation.

Candidate executable SHA-256:

`6C7FEBA0C6DAA7636FB936A3B726BE3BC1553B393790AE0D1E265E15B14A7E1D`

Exact v2.7.5 baseline SHA-256:

`80002F4AC83AD3D87DA0FB3A87E67A49179BEA0230A764167B58B112184E4695`

Full evidence and paths are recorded in
[V275_PLUS50_RESULTS.md](V275_PLUS50_RESULTS.md).

## Remaining publication work

Before distributing binaries, produce reproducible standalone and Exoskeleton
packages from the accepted commit, test both extracted forms, and retain the
timed engine-failure warning in release notes. Publication is intentionally
left to the maintainer.
