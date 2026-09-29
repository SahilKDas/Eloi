# September rewrite

Status: active laboratory rewrite on the `september-rewrite` branch. The C++
v3.6.0 implementation remains the behavioral reference until Rust passes every
gate. No release or production replacement is implied by this branch.

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

## Proposed Standard donor: Viridithas 19.0.1

| Identity | Frozen value |
| --- | --- |
| Tag | `v19.0.1` |
| Source commit | `77F4731EA4C319A68FC4BB3317459A3115073820` |
| Source license | MIT |
| Source `LICENSE` SHA-256 | `7EE7D175D4D12AED856DF5E2DB1569C7877C577D31A724BECD72FB02141C6DF3` |
| Network repository license | CC0-1.0; repository states all networks are CC0 |
| CCRL 40/2 FRC | 4040 ±9, 4,170 games |
| Caissa 1.26 comparison | 4037 ±11, 2,780 games |

The rating edge is narrow but supported by more games and tighter reported
uncertainty. Strength still must be reproduced locally under Eloi's resources.
No donor source or network enters release artifacts merely because of the
external rating.

The tag source is audited in ignored scratch before import. Optional features,
tablebases, datagen, tuning tools, and dependencies not needed by Eloi are
excluded. A matching CC0 network is hash-pinned separately before any strength
test or package build.

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
and a 14×14 cross board. These future modes do not reuse Viridithas and do not
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
8. Standard donor passes a fresh equal-resource strength gate before replacing
   Caissa; otherwise the Rust runtime ships with no donor promotion.
