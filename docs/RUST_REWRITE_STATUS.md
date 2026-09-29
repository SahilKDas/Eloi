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
  Independent Python lifecycle smoke passes, including clock-managed searches.
- Production integer clock reserves and panic/emergency/pressure allocation
  are ported. UCI clock fields select the actual side-to-move, retain the hard
  deadline, and stop at soft limits only after completed iterations. Explicit
  movetime takes precedence. Infinite/ponder compatibility remains unfinished.
- Horde retains its production material/advancement/king-pressure evaluation.
- Orthodox dead material and current-position draw adjudication are variant-aware;
  checkmate and hill wins precede fifty-move claims. Fairy material-draw rules
  still require their separate parity gates.
- Worker output is bounded before line allocation, rejects invalid UTF-8,
  and retains owned-process teardown. The explicit donor integration test was
  rerun successfully after this containment change.
- Rust Operations Center reducer now covers session states, active-game reconnects,
  HTTP retry/fatal classification, Retry-After, cancellation, one-time result
  accounting and bounded redacted events. This is an offline controller, not
  yet a live transport or dashboard.
- Native public configuration template is parsed with credential-safe Debug/errors,
  bounded input, exact HTTPS origin and the six production-supported variants.
  `--check-config --config PATH` works offline. Unknown settings and duplicate
  keys fail explicitly rather than being silently ignored; YAML escapes remain
  unsupported. Private settings have not been rewritten.
- Bounded UTF-8 stream framing and full/cumulative Lichess game reconstruction
  are tested offline across all six production variants. Account/variant gates,
  idempotent snapshots, legal incremental history, terminal-status consistency
  and transactional rejection are covered. Antichess now uses its own no-castling
  start position through the shared UCI/Lichess selector.
- JSON decoding pins cached `serde_json` 1.0.151; locked dependency metadata was
  audited as permissive MIT/Apache/Unlicense/Unicode. No copyleft dependency added.
- Injectable transport seam and offline supervisor authenticate bounded account
  replies, classify HTTP failures, gate challenges, reserve exactly one owned
  game, bind legal full histories and count explicit terminal results once.
  Fake-transport tests cover fatal authentication, retry reentry, duplicate games,
  cancellation, and aborted games without fabricated draws. The actual Windows
  network adapter and interruptible blocked-read tests remain to be implemented.

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
