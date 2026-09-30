# Eloi v4.0.0 Four-Player Chess

v4.0.0 is scoped to local four-player chess. It does not add Chess.com login,
scraping, browser automation, private endpoints, or Chess.com affiliation.

## Runtime Scope

- Standard remains routed through qualified Caissa 2.0.
- Existing two-player Eloi variants remain on their existing paths.
- Four-player chess uses a separate 14x14 cross-board state and separate seats:
  Red, Blue, Yellow, and Green.
- Turn order is clockwise: Red, Blue, Yellow, Green.
- FFA and Teams are separate modes.
- The initial computer opponent is a handcrafted baseline:
  - FFA uses Max-N vector search.
  - Teams uses team utility alpha-beta.
  - The whole engine keeps the fixed three-thread contract.

## Rules Implemented First

The Rust core now owns:

- 160 playable cross-board squares.
- Standard four-army initial setup.
- Directional pawns for all four seats.
- FFA automatic queen promotion.
- Teams selectable promotion.
- Partner capture prevention in Teams.
- FFA capture-point accounting.
- Deterministic identity keys for repetition and replay tests.
- Token-free local state serialization for protocol readiness.

The four-player state intentionally does not reuse the two-player `Player` or
FEN types. Four-player state has different seats, scores, active armies, team
membership, and terminal rules.

## Training Plan

Training is free-quota Kaggle only. The repo provides a versioned pipeline
scaffold, but no Kaggle, Python, downloaded model, or private dataset is needed
at runtime.

Targets:

- `E4PC-FFA`: complete-move policy plus four-seat placement/score value.
- `E4PC-Teams`: complete-move policy plus team W/D/L value.
- 500,000 unique positions per mode.
- 80% train, 10% validation, 10% sealed test split by source game.

The pipeline must preserve:

- deterministic seeds;
- shard manifests and hashes;
- package versions;
- checkpoint hashes;
- validation-aware early stopping;
- sealed-test isolation until checkpoint selection freezes;
- non-pickle float32 exports and quantized Rust headers.

Unqualified models are not embedded. If one mode fails model qualification, that
mode remains on the handcrafted evaluator without blocking the other mode.

## Release Gate

v4.0.0 cannot publish until both FFA and Teams are complete and playable with a
correct Eloi computer opponent. Neural strength is allowed to differ by mode,
but rules correctness is not optional.
