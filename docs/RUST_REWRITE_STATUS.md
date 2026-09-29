# Rust rewrite implementation evidence

Branch: `september-rewrite`. The persistent objective includes complete runtime
migration, stronger Standard search, existing variants, Windows UI/Lichess,
and package qualification. This file records completed implementation slices;
it does not declare the rewrite or a release qualified.

## Implemented and checked

- Strict six-field FEN, Chess960 rook origins, Crazyhouse pockets and promoted
  provenance, legal movement and state transitions for the two-player variants.
- Standard perft depth four: **197,281**.
- Existing independent Standard/Chess960/Horde differential validator:
  **96/96** positions, zero mismatches.
- Existing independent Atomic/Antichess differential validator:
  **128/128** positions, zero mismatches.
- Atomic position replacement, reversible game history, repetition and undo.
- Pinned Viridithas 19.0.1 MIT donor and matching CC0 `noumena` model identity;
  official release inspected as data, without execution.
- Source-built Windows worker with three search threads, local-only model
  hash verification, 32 MB default hash, deadline, stop and process containment.
- Explicit donor integration test passed: bounded legal Standard search,
  new-game reset, external stop, variant refusal and no remaining owned worker.
- Eloi E4-10/KOTH/Atomic models exported without changing quantized values.
  KOTH's production namespace rename is recorded separately from the frozen
  original campaign header hash.
- Rust scalar NNUE, incremental updates, reverse updates and model switching.
- Independent Python/production-header arithmetic versus Rust:
  **224/224** exact scores over Standard, Chess960, Horde, KOTH, Atomic,
  Antichess and Crazyhouse sample positions.
- Workspace tests and strict Clippy checks pass at each committed slice.
- Conservative three-lane native alpha-beta with bounded nodes/time, cancellation,
  legal iteration PVs and explicitly marked emergency answers.
- Laboratory UCI runtime replaces the shell: transactional position history,
  iteration telemetry, readiness during search, external stop and clean exit.
  Independent Python lifecycle smoke passes. Clock-managed/infinite searches
  remain explicitly rejected pending the time-manager migration.

## Still required

Native search migration and optimization, exhaustive board/variant parity,
SIMD evaluator parity, complete public UCI/time-manager compatibility, donor fixed-node parity and
equal-resource strength qualification, Windows GUI/Operations Center, native
Lichess transport and simulations, and reproducible packages. Crazyhouse has
rules scaffolding and validation examples but no qualified pocket-aware brain.
Four-player currently has topology/action types; complete rules and its brain
remain future work.

The final accepted rewrite commit is reserved for
`Legacy-Free, most 3.9 now` after the actual completion gates pass.
