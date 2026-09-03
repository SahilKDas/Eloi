# Contributing to Eloi

Keep Eloi a fixed-three-thread C++26 engine with a native Windows GUI, UCI
compatibility and two reproducible Windows packages. Keep search, training,
GUI and packaging changes independently reviewable.

## Before changing anything

- Read [device constraints](constraints_on_SahilKDas_device.md).
- Preserve running bridges/frontends, private configuration and user changes.
- Never commit credentials, datasets, checkpoints, binaries or dependency caches.
- Preserve source and artwork licenses. Report security-sensitive issues privately.
- Reproduce the issue and add focused regression tests before changing behavior.

## Build and test

Use the locked dependencies and PowerShell 7 described in
[REPRODUCING.md](REPRODUCING.md).

```powershell
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_BUILD_TESTS=ON
cmake --build build-release -j 2
ctest --test-dir build-release --output-on-failure --timeout 120
.\build-release\Eloi.exe --perft --depth 4
python -B scripts/differential_movegen.py --engine build-release/Eloi.exe --samples 32
```

Run the relevant `scripts/test_*.py` tests for tooling changes. Training tests
may create tiny synthetic models; that is not permission for a real training
campaign. Bound all tests and keep heavyweight work sequential at Idle
priority. Never treat a timeout as a pass.

## Playing-code invariants

- Exactly three deterministic RootSplit lanes; no public ParallelMode or
  UCI Ponder option. Every lane uses its private share of the configured TT.
- Standard chess, Chess960, Horde, UCI and native Lichess remain compatible.
- Preserve complete board/NNUE/Zobrist restoration, legal PVs, SEE/TT semantics,
  mate-score normalization and scalar/runtime-dispatched agreement.
- Keep the 40-ply warning, 200-ply GUI maximum and 17,697-ply absolute ceiling.
- No runtime database downloads, Python dependency or external engine backend.
- CMake consumes the tracked NNUE/opening headers without regenerating them.

Use two-space C++ indentation, descriptive names and RAII. Avoid unnecessary
hot-path allocations and new compiler warnings. Add tests for changed rules,
search guards, parsers or GUI behavior.

Before a brain change, retain and hash the preceding executable. Engine Lab
and `--version-match-smoke` are useful integration checks, not Elo proofs.
New strength experiments need an explicitly frozen opponent, partitions,
game count, score metric, time/node budget, resource cap and stopping rules.
Use chess score (wins + half draws) when that is the declared metric.
Do not inherit obsolete beta/raw-win thresholds or change gates after play.
A strong match result cannot waive a correctness failure.

The current C acceptance decision and reviewed `compare` versus `stable`
semantics are in [RELEASE_V2_5_0.md](RELEASE_V2_5_0.md).
Historical failures remain failures in their archived evidence.

## Release requirements

- Publish exactly two Windows x64 ZIPs: standalone and Exoskeleton.
- Standalone contains exactly `Eloi.exe` and empty-token `config.yml`,
  with embedded artwork and no non-system DLL requirement.
- Exoskeleton contains both executables, required runtime DLLs, twelve PNGs,
  licenses, source revision and file hashes. Its main executable has no
  WinHTTP import; networking belongs to `EloiLichess.exe`.
- Set the version only through CMake's project version and
  `ELOI_PRERELEASE`. Stable releases use an empty prerelease string.
- Build from committed source with the hash-locked toolchain, normalized
  timestamps and zero PE timestamps.
- Require two independent builds of each form and matching payload/ZIP bytes.
- Validate extracted packages outside the repository, GUI interactions,
  UCI/time/stop behavior, offline configuration and fresh Defender scans.
- Review exact artifact hashes before upload and verify downloaded assets
  afterward. An old RC ZIP does not become stable by renaming it.
- Do not replace an active installation, overwrite existing artifacts or
  publish externally without the maintainer's authorization.

Use the preservation workflow in [REPRODUCING.md](REPRODUCING.md).
Generic legacy packaging helpers remain for compatibility, but their cleanup
options are not permission to delete unrelated files. Never change historical
tags to make a new build appear to reproduce a published artifact.

## Data and configuration

Document each new source's license, version, sampling rules and hashes in
[DATA_SOURCES.md](DATA_SOURCES.md). Keep production's exact header identity
and checkpoint correspondence in `data/nnue_provenance.json`.
The dormant-channel limitation is open research, not a silently fixed issue.

`config.example.yml` is the public empty-token template. Real tokens belong
only in ignored local configuration. Keep the native endpoint restricted to
exactly `https://lichess.org`; do not add configurable bearer-token destinations.
Configuration changes require parser tests and user documentation.
Preserve the twelve PNG assets and their attribution.

## Review checklist

A contribution should explain the problem, focused fix, before/after tests,
relevant benchmark evidence and any changed limitations. Include screenshots
for visual changes. Run `git diff --check`, relevant unit tests and appropriate
integration checks. Do not claim a new release or strength gain from documentation
cleanup alone.

Superseded plans, runners and unused Morlock game collections are recoverable
from Git history before the cleanup. They are not current engineering policy.
Keep current evidence discoverable via [data/README.md](data/README.md).
