# Caissa donor boundary

Eloi's experimental `caissa-merge` branch pins Caissa 1.26 at commit
`008b0b8f1fc6479890665a1a9c2ff6bbc2f1bc06`. The upstream project is
copyright (c) 2021 Michał Witanowski and distributed under the MIT license in
this directory.

This first import contains only audited board, move, score, material, hash,
time, tuning, bitboard, and waitable primitives. It deliberately excludes the
Caissa UCI frontend, trainer, self-play generator, automatic downloads, NUMA
and large-page support, tablebase implementation, packaging, search,
evaluation, endgame, repetition, and transposition-table implementations.
The allowlist is explicit in Eloi's CMake files; future integrations must not
replace it with source globbing.

## Network status

The Caissa 1.26 build requests `eval-82-383B.pnn`. The file inspected locally
has:

- Size: `50,367,040` bytes
- SHA-256: `22249DE582912F46F73F7CF7410D6D72ECCC77696B0B857E99B97A45F3F37116`

No redistribution license was visible in the separate Caissa-Nets repository
when this branch was created. The network therefore remains an ignored local
dependency under `.deps/caissa/`; it must not be committed, packaged, or
downloaded by CMake or at runtime. The Caissa brain must fail closed if the
file is absent or its hash differs.

## Reference identity

An untouched local reference build from the pinned source, configured with
only `-Wno-error=unknown-pragmas` for the MinGW toolchain, produced an
executable with SHA-256
`FB87B9D47452322E3759E19CC71F8EFA9F5FC03F0EE16B58EA930D221FC396C6`.
Its UCI smoke test used exactly three threads, 32 MB hash, and 10,000 nodes and
returned legal move `d2d4` from the initial position. This is a local adapter
parity reference, not a redistributable Eloi artifact.

## Provenance exclusions

The pinned donor contains implementations or comments that explicitly credit
Stockfish in endgame evaluation, upcoming-repetition detection,
transposition-table mate-score decoding, and an in-check ProbCut rule. Eloi's
project boundary forbids importing Stockfish source or derived runtime code.
Those implementations are excluded from this import. Any eventual equivalent
must be independently implemented from Eloi's requirements and tests, not
copied with comments removed.

Until both the source-provenance audit and network redistribution question are
resolved, the Caissa backend is local-experiment-only. Eloi v2.7.5/E2 remains
the production engine and the public UCI, GUI, clock, variants, and Lichess
bridge remain exclusively Eloi-owned.
