# Caissa donor boundary

Eloi's experimental `caissa-merge` branch pins Caissa 1.26 at commit
`008b0b8f1fc6479890665a1a9c2ff6bbc2f1bc06`. The upstream project is
copyright (c) 2021 Michał Witanowski and distributed under the MIT license in
this directory.

The first import contains only audited board, move, score, material, hash,
time, tuning, bitboard, and waitable primitives. Eloi-owned compatibility
layers provide ordinary allocation and fail-closed NUMA, tablebase, and
specialized-endgame behavior. It deliberately excludes the Caissa UCI
frontend, trainer, self-play generator, automatic downloads, NUMA and
large-page implementations, tablebase implementation, packaging, search,
repetition, and transposition-table implementations. The admitted evaluator
and position layer has been modified to prohibit embedded networks and all
implicit executable-directory or working-directory network discovery.
Eloi-owned time and repetition compatibility layers avoid the donor's
LeelaChessZero-attributed clock formula and Stockfish-attributed upcoming-cycle
implementation. Upcoming-cycle pruning is conservatively disabled.

The admitted Caissa search file differs from pinned 1.26 by removing two
historically Stockfish-attributed rules: in-check ProbCut and the PV TT-move
quiescence bypass. Its time manager include targets Eloi's compatibility
implementation. These changes intentionally sacrifice unknown playing strength
to preserve the repository's no-Stockfish-code boundary.
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

Developers may opt into the separate `EloiHybridLab` UCI executable with
`-DELOI_BUILD_CAISSA_LAB=ON`. It resolves the network from
`--caissa-network`, then `ELOI_CAISSA_NETWORK_PATH`, then the repository's
ignored `.deps/caissa` path. It fixes each active engine search at three
threads and shares 32 MB of hash as 16 MB per brain. It is not a release
target and must not be packaged. The command-line-only modes --brain caissa
and --brain eloi isolate either adapter for parity diagnostics; hybrid is the
default.

Caissa's node counter is flushed in batches across its search lanes, so a
fixed-node request can overshoot modestly. Fixed-node hybrid results are not
equal-resource qualification evidence until that accounting is bounded and
measured. Early strength comparisons should use equal movetime instead.

The embedded search polls Eloi's shared stop flag directly, without a helper
polling thread. Every Caissa worker is allowed to complete depth one so an
interrupted UCI search can still return a legal best-so-far move; cancellation
is checked recursively below the root from depth two onward.

## Bounded parity checkpoint

On 2026-09-04, fresh three-thread, 16 MB, MultiPV-2 processes matched the
official pinned binary at depth one on the initial position,
lichess-001XA, and poisoned-pawn-capture (3/3 best moves). A 10,000-node
probe is not a deterministic parity oracle at three threads: five fresh
official runs on poisoned-pawn-capture selected four different moves, and
five embedded runs also selected four, with d4a4 appearing in both sets.
The deeper fixed-node parity gate therefore remains open; this checkpoint
does not waive it or establish playing-strength equivalence.

The arbiter currently keeps Eloi and Caissa scores separate and maps them
through development scales of 400 and 360 centipawns per expected-score
decade. These constants have not yet been independently calibrated against
held-out game outcomes. They are suitable for exercising control flow, not
for release qualification; WDL calibration remains an open pre-gauntlet gate.
