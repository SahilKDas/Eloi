# Eloi v3.9.0 — Legacy-Free, Most 3.9 Now

Eloi 3.9.0 replaces the shipped C++ runtime with a Rust 2024 engine,
protocol stack, native Win32/`tiny-skia` interface, Lichess client, Operations
Center, and reproducible Windows packaging. Python remains only for retained
validation, training, and evidence tooling.

## Chess architecture

- Standard uses the exact official Caissa 2.0 AVX2 release asset behind Eloi's
  SHA-256/UCI identity check, three-thread contract, deadline containment,
  legal-move validation, and fresh-budget fallback.
- Chess960, Horde, King of the Hill, Atomic, Antichess, and Crazyhouse remain
  Eloi-owned routes. Caissa is never asked to play a non-Standard variant.
- Crazyhouse now has complete pocket/drop legality and a qualified pocket-aware
  Eloi evaluator. Its frozen 100-game gate scored 40W/43D/17L (61.5%).
- The public rules boundary includes a separate 14×14 four-player topology and
  four-owner action types for future work; v3.9.0 does not claim a playable
  four-player engine.

## Caissa 2.0 provenance

- Upstream tag: `2.0`
- Tag commit: `bb725799e9b19ebdaa0d584f5433fc1c3019e349`
- Official AVX2 asset SHA-256:
  `043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97`
- Upstream evidence versus 1.26: +40.41 ±4.85 Elo at LTC over 5,000 games and
  +29.15 ±4.59 Elo at STC over 6,284 games.

The official executable contains its matching evaluator. Eloi does not fetch
or package loose Caissa-Nets artifacts. The maintainer accepts the official
tagged asset from the MIT-licensed Caissa repository as packageable and
promotable; the absence of a separate model-specific statement remains
disclosed in `third_party/caissa20/PROVENANCE.md`.

## Protocol and operations

- Complete UCI lifecycle includes clock, movetime, nodes, depth, infinite,
  ponder/ponderhit, stop, new-game reset, fixed three threads, hash, book, and
  all seven supported variants.
- Native Lichess has exact variant routing, bounded parsing, transient retry,
  fatal authentication handling, cancellable WinHTTP streams, and no token
  logging.
- A real read-only smoke authenticated `eloibot` and cancelled a blocked
  control-stream read in 5 ms without accepting a challenge or sending a
  mutating request.
- The visible Operations Center enforces one instance and provides challenge
  acceptance, reconnect, configuration, diagnostics, log-folder, and controlled
  exit actions.
- Token-free rotating logs and an atomic status snapshot live under
  `%LOCALAPPDATA%\Eloi`.

## Validation

- 60 active Rust tests pass, plus the explicit real-Caissa integration test.
- Strict workspace Clippy passes with warnings denied.
- 178 retained Python tests pass.
- Standard perft depth 4: exactly 197,281 nodes.
- 384 Standard/Chess960/Horde differential positions: zero mismatches.
- 384 Atomic/Antichess/Crazyhouse differential positions: zero mismatches.
- Independent Python/Rust NNUE parity: 224/224 exact.
- Real donor search/reset/stop/infinite-stop/variant-refusal checks pass.
- Native GUI and Operations Center release-mode smoke tests remain responsive;
  duplicate Operations Center launch exits cleanly.

The release publishes exactly two Windows x64 ZIPs: standalone and
Exoskeleton. Both are built twice from one frozen commit with static CRT
linkage, zero Eloi PE timestamps, deterministic archives, exact package-content
checks, internal file manifests, fresh-extraction smokes, and Defender scans.
The release body records the final source commit and archive SHA-256 values.

This is a major runtime rewrite, not a claim that Eloi-native search now beats
Caissa. Standard strength comes from the accepted Caissa 2.0 donor; variants
remain independently evidence-bound.
