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
- Independent Atomic/Antichess/Crazyhouse differential validator:
  **96/96** freshly generated positions, zero mismatches in the current pass.
- Atomic position replacement, reversible game history, repetition and undo.
- Pinned official Caissa 2.0 AVX2 donor from the MIT-licensed upstream release.
  Its matching multilayer model is embedded in that executable; Eloi does not
  fetch or package a loose model from Caissa-Nets. The maintainer explicitly
  accepts the official tagged release asset as packageable and promotable; the
  absence of a separate model-specific license statement remains disclosed in
  `third_party/caissa20/PROVENANCE.md`.
- Runtime SHA-256 and UCI identity checks, exactly three search threads, 32 MB
  hash, real-budget stop, containment margin, and owned-process teardown.
- Explicit donor integration test passed: bounded legal Standard search,
  new-game reset, external stop, variant refusal and no remaining owned worker.
- Eloi E4-10/KOTH/Atomic models exported without changing quantized values.
  KOTH's production namespace rename is recorded separately from the frozen
  original campaign header hash.
- Rust scalar NNUE, incremental updates, reverse updates and model switching.
- Runtime-dispatched AVX2 NNUE output dot product with an exact scalar fallback.
  The sole intrinsic exception lives in the audited `eloi-simd` leaf crate;
  every runtime/engine/protocol crate still forbids unsafe code. Randomized
  scalar/AVX2 parity passed 4,096 vectors.
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
  movetime takes precedence. Infinite, ponder, ponderhit, stop and option
  compatibility are implemented and covered by lifecycle smoke tests.
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
  bounded input, exact HTTPS origin and seven Lichess variants, including Crazyhouse.
  `--check-config --config PATH` works offline. Unknown settings and duplicate
  keys fail explicitly rather than being silently ignored; YAML escapes remain
  unsupported. Private settings have not been rewritten.
- Bounded UTF-8 stream framing and full/cumulative Lichess game reconstruction
  are tested offline across all seven supported Lichess variants. Account/variant gates,
  idempotent snapshots, legal incremental history, terminal-status consistency
  and transactional rejection are covered. Antichess now uses its own no-castling
  start position through the shared UCI/Lichess selector.
- JSON decoding pins cached `serde_json` 1.0.151; locked dependency metadata was
  audited as permissive MIT/Apache/Unlicense/Unicode. No copyleft dependency added.
- Injectable transport seam and offline supervisor authenticate bounded account
  replies, classify HTTP failures, gate challenges, reserve exactly one owned
  game, bind legal full histories and count explicit terminal results once.
  Fake-transport tests cover fatal authentication, retry reentry, duplicate games,
  cancellation, and aborted games without fabricated draws.
- Native Windows Runtime HTTP adapter compiles with the workspace unsafe-code ban
  intact. It fixes the HTTPS origin, disables redirects/UI/cookies, bounds bodies
  and chunks, and polls cancellable OS asynchronous operations. Offline tests
  cover path/header injection, pre-request cancellation and cancellation of a
  pending async fixture. Actual blocked-network cancellation and live stream
  smoke are still unverified; no real token or connection was used.
- The live supervisor now consumes control/game streams, performs challenge
  actions, reconstructs legal histories, submits only validated legal moves,
  honors clock increments, and routes Standard through the contained donor.
  Donor failure reserves a fresh native fallback budget instead of reusing an
  expired deadline. The complete loop has deterministic fake-transport coverage;
  a real account smoke remains intentionally outstanding.
- Native Win32 chess and Operations Center windows render through `tiny-skia`.
  The chessboard accepts legal click-to-move input, pieces render from Eloi state,
  hover animation is timer-driven, and the Operations Center acquires its named
  mutex before starting the supervised bridge thread.
- The Operations Center now exposes working Start/Stop accepting, Reconnect now,
  Configure, Copy diagnostics and Open log folder controls. Manual reconnect
  cancels a blocked `WinHTTP` operation, clears transient backoff, and preserves
  an attached game's identity. Dashboard diagnostics contain only the explicit
  token-free snapshot fields. The full Rust suite and strict Clippy pass, and a
  release-mode native-window smoke remained responsive.
- Live/headless bridge state is durably mirrored to token-free, parseable JSON
  under `%LOCALAPPDATA%\Eloi\status\lichess.json` using same-directory atomic
  replacement. Session event logs are capped at 1 MiB, startup rotation retains
  at most ten files and reserves the 10 MiB aggregate ceiling, and tests prove
  credentials are redacted before either output is written.
- Crazyhouse has a pocket-aware board/pocket/drop-pressure evaluator instead of
  applying the Standard NNUE to invisible pocket material. Its frozen 100-game,
  250 ms qualification against the pre-change generic evaluator passed at
  **40W/43D/17L (61.5/100)** with zero protocol failures and **100/100** replay
  verification. Evidence lives under `tmp/rust-crazyhouse100-250ms`.

## Strength evidence

The first local Viridithas 19.0.1 versus Caissa 1.26 gate stopped at game 28,
as frozen, when Viridithas returned `0000` at ply 43. Completed results were
**4W/14D/9L (11.0/27, 40.7%)** with one protocol failure. This is a failed,
incomplete qualification: Viridithas is not promoted and the evidence is not
resumed, replaced, or pooled.

Later Viridithas retries remained separate. The final r5 run was explicitly
cancelled at the user's request after 44 games (13W/17D/14L, 21.5/44) with zero
recorded protocol failures. Viridithas is rejected as the rewrite donor.

The replacement candidate is official Caissa 2.0 AVX2, SHA-256
`043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97`.
Upstream reports +40.41 ±4.85 Elo at LTC over 5,000 games and +29.15 ±4.59
Elo at STC over 6,284 games against 1.26. The maintainer waived a redundant
local strength gate and accepts this upstream evidence for donor promotion.
The subsequently cancelled local smoke stopped after five games at 2W/1D/2L;
it is preserved separately and is not presented as strength evidence.

The conservative selective-search candidate was compared with exact pre-change
commit `5e463b2` in a bounded 20-game, 250 ms mirrored preliminary screen. It
scored **10W/7D/3L (67.5%)**. This supports retaining the selective mechanisms,
but the screen reused persistent engine processes and is not a sealed release
qualification; a fresh-process confirmation is still required.

## Package evidence

The current r4 package pass performed four clean MSVC `/Brepro` builds and
produced identical executable bytes within each package form. PE timestamps
were normalized to zero before deterministic archive construction. The A/B
archives match byte-for-byte:

- standalone ZIP A/B: `06B31CB9C4F5FE12505CFC366D4687C659873F6D6E42764EB8EFC8B888E59DB9`;
- Exoskeleton ZIP A/B: `72F1F14A9942991E4EE41D38477ED76FD931EC62D0FE29CB604C64343684037A`.

Both staged executables validate the seven-variant config. The standalone
materializes its embedded, hash-named donor with the exact published SHA-256;
the Exoskeleton uses the adjacent exact donor plus its MIT notice. Both fresh
extractions selected `d2d4` with the same +91 cp score in a non-book Standard
smoke. Native GUI and Operations Center windows stayed responsive, and a second
Operations Center instance exited cleanly after activating the existing one.
Evidence is preserved under `dist/rust-rewrite-validation-r4` and
`tmp/rust-package-validation-r4`.

## Still required

Further native-search optimization, exhaustive board/variant parity, donor
fixed-node parity, real Lichess smoke, and richer game/search telemetry in the
dashboard. The promised Operations Center command controls are implemented.
Reproducible package construction now passes; final release naming, package
content audit, security scan, and release-source freeze remain outstanding.
Crazyhouse is qualified against the frozen generic-Eloi baseline; broader
external-strength claims still require a separate opponent gate.
Four-player currently has topology/action types; complete rules and its brain
remain future work.

The final accepted rewrite commit is reserved for
`Legacy-Free, most 3.9 now (I think)` after the actual completion gates pass.
