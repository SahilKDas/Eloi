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

Eloi also adds a narrow packed-network memory loader. Windows builds may opt
in to an Eloi-owned `RCDATA` resource only when CMake has verified the exact
frozen size and SHA-256. The adapter verifies those bytes again at runtime
before handing them to the donor evaluator. The default build contains no
Caissa network, and no build mode discovers or downloads one.
The embedded backend also suppresses two donor attack-table size messages that
would otherwise be written to stdout before UCI negotiation. Assertions and
table construction remain unchanged.

## Network status

Eloi keeps Caissa 1.26 search but uses Caissa v1.25's `eval-71` CReLU
network, extracted byte-for-byte from its official AVX2/BMI2 release:

- Size: `50,367,040` bytes
- SHA-256: `615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`

The official asset SHA-256 is
`51929274A45CFC3057C35B07087EE9806E482DDCF64F0659EEDCDABF0FEA51FF`.
Its `EmbedData`, `EmbedEnd`, and `EmbedSize` symbols independently delimit the
network bytes. The v1.25 tag identifies the project as MIT and has the same
license retained here. Exact details are in `network-v1.25-provenance.json`.
The network remains an ignored local dependency and is embedded only by an
explicitly enabled, hash-gated build.

Any future v2.9.0 package must additionally pass
`scripts/caissa_license_gate.py` with
`caissa-network-license-v1.25.json`. The older
`caissa-license-gate-template.v1.json` records the blocked v1.26 Caissa-Nets
artifact and is not permission for that network. Replacing the network requires
technical compatibility, parity, correctness, and strength validation; editing
the frozen identity in this document is not sufficient.

## Reference identity

An untouched local reference build from the pinned source, configured with
only `-Wno-error=unknown-pragmas` for the MinGW toolchain, produced an
executable with SHA-256
`FB87B9D47452322E3759E19CC71F8EFA9F5FC03F0EE16B58EA930D221FC396C6`.
Its UCI smoke test used exactly three threads, 32 MB hash, and 10,000 nodes and
returned legal move `d2d4` from the initial position. This is a local adapter
parity reference, not a redistributable Eloi artifact.

The bounded adapter gate uses the official v1.25 AVX2/BMI2 release for
depth-one reference. It requires exact depth-one moves and validates deeper
three-thread searches for accepted legal output, score/mate sanity, timing,
and completion. Deeper exact best-move equality is retained as an observation,
not a mechanical gate, because the donor's thread scheduling is nondeterministic.

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

The future production controller is a separate opt-in build path:
`-DELOI_ENABLE_CAISSA_PRODUCTION=ON`. It affects Standard searches in the
GUI, UCI, native Lichess bridge, and Exoskeleton bridge, while Chess960 and
Horde stay E2-only. The controller accepts only an explicit
`--caissa-network PATH` or `ELOI_CAISSA_NETWORK_PATH`; unlike the lab, it
does not search the working directory. The option is off by default, and the
resulting ordinary executable remains byte-identical to published v2.7.5.
Enabling this development path does not authorize packaging the network.

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

The reproducible runner is scripts/caissa_adapter_parity.py. It hash-checks
the frozen official executable and local network, records its own hash and
the donor commit, applies Idle priority and process timeouts, refuses output
collisions, and writes only beneath a quota-checked dedicated scratch path.

The arbiter keeps Eloi and Caissa scores separate. Eloi retains its calibrated
1,300-centipawn scale; Caissa provisionally uses v1.25's native 400-centipawn
expected-score mapping until fresh disjoint calibration. The deterministic
`scripts/calibrate_hybrid_wdl.py` tool keeps entire games in one partition
and reports Brier score, log loss, and calibration error. The Eloi scale was
selected on 40 complete Standard games and improved log loss on a disjoint
40-game campaign. The former Caissa scale and exact evidence in
`data/v2_9_0_wdl_calibration.json` bind the replaced v1.26 network. Earlier
gauntlets remain historical rather than release-qualifying.
The pessimistic calibrated expectation selects moves and is retained as the
hybrid confidence value. Public UCI centipawns use Eloi's calibrated reporting
anchor, including the agreement route; this prevents Caissa worker-vote
nondeterminism from changing the meaning or scale of the public score.
