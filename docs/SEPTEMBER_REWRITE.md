# September rewrite

Status: active laboratory rewrite on the `september-rewrite` branch. The C++
v3.6.0 implementation remains the behavioral reference until Rust passes every
gate. No release or production replacement is implied by this branch.

The final accepted rewrite commit is reserved for the exact message
`Legacy-Free, most 3.9 now (I think)`, mirroring the historical v1 milestone. It is used
only after the shipped runtime has no legacy C++ dependency and all gates pass.

## Language and scope

- Rust 1.98.1, edition 2024.
- Rewrite the shipped engine, variants, UCI, GUI, native Lichess client,
  Operations Center, packaging, and native tests.
- Retain Python training, validation, gauntlet, and evidence tooling.
- Preserve the three-search-thread production contract and Windows x64 support.
- Design current 8×8 rules for speed without making 64 squares, two players,
  or one-piece-per-square assumptions part of the public engine interface.
- Keep every dependency permissively licensed; GPL, LGPL, MPL, EPL, AGPL, and
  other copyleft dependencies are prohibited.

## Standard donor: Caissa 2.0

| Identity | Frozen value |
| --- | --- |
| Tag | `2.0` |
| Source commit | `BB725799E9B19EBDAA0D584F5433FC1C3019E349` |
| Source license | MIT |
| Official AVX2 asset | `caissa-2.0-x64-avx2.exe` |
| Asset SHA-256 | `043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97` |
| Upstream LTC vs 1.26 | +40.41 ±4.85 Elo, 5,000 games |
| Upstream STC vs 1.26 | +29.15 ±4.59 Elo, 6,284 games |

The upstream strength gain is substantial and supported by thousands of games,
and is accepted by the maintainer for promotion without a redundant local
strength gauntlet. Eloi executes the official release asset as a
crash-contained child process and checks its hash and UCI identity before use.

## Donor model verification

Caissa 2.0's matching `(32×768 → 1536) × 2 → 16 → 32 → 1` multilayer model is
contained in the official executable asset published with the MIT-licensed
Caissa 2.0 release. Eloi does not fetch, commit, or package a separate `.pnn`
from the unlicensed Caissa-Nets repository.

## Rewrite architecture

- `eloi-core`: board state, legal moves, variants, repetition, FEN, clocks.
- `eloi-engine`: Eloi search/evaluation interface and isolated donor adapter.
- `eloi-protocol`: UCI, native Lichess state machine, journals, routing.
- `eloi-app`: Windows GUI, Operations Center, executable entry points.

Rust becomes authoritative one subsystem at a time. Each cutover requires
differential parity against the frozen C++ executable. Standard may use the
qualified donor; Chess960, Horde, KOTH, Atomic, and Antichess remain Eloi-owned
and cannot be silently routed through a Standard-only donor.

The long-term Eloi-owned rules layer includes Crazyhouse pockets/drops and a
separate four-player topology with four turn owners, team/free-for-all results,
and a 14×14 cross board. These future modes do not reuse Caissa and do not
distort the optimized two-player 8×8 representation. Their brains attach
through the same search boundary only after their own rules and evaluation
models exist.

The rewrite succeeds only if it produces a stronger qualified Standard brain
and cleaner ownership boundaries. Merely translating the current C++ behavior
into Rust is an intermediate parity milestone, not the final outcome.

## Gates

1. Dependency and artifact license audit passes with no copyleft or unknown
   license.
2. FEN, legal moves, make/undo, terminal results, and perft match C++.
3. Variant differential suites match all retained evidence.
4. UCI lifecycle and fixed-search behavior are reproducible.
5. Lichess routing, cancellation, fallback, and token redaction pass offline.
6. GUI and Operations Center pass native smoke tests outside the repository.
7. Rust packages build twice with byte-identical archives and verified hashes.
8. Caissa 2.0 retains its exact official asset identity and passes containment,
   legality, deadline, packaging, and runtime-route gates before promotion.
