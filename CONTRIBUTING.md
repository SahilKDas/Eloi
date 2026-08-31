# Contributing to Eloi

Thank you for helping improve Eloi. Contributions should preserve its identity:
a deterministic, fixed-three-thread C++26 chess engine with a native Windows
GUI, UCI compatibility, and two golden Windows release packages.

## Before you begin

- Search existing issues and pull requests before starting overlapping work.
- Keep changes focused. Separate engine-strength, GUI, packaging, and
  documentation changes when practical.
- Never commit credentials, private game data, generated build trees, or
  dependency caches.
- By submitting a contribution, you agree that it may be distributed under
  Eloi's MIT license. Only submit code and assets you have the right to share.

For security-sensitive reports, contact the maintainer privately instead of
opening a public issue. Revoke any exposed Lichess token immediately.

## Development environment

Eloi requires:

- a C++26-capable MinGW UCRT64 compiler;
- CMake and Ninja;
- PowerShell; and
- the development dependencies installed by
  `scripts/bootstrap-windows.ps1`.

No Go toolchain is used. Python is allowed for development-only validation and
self-play scripts, but it must never become a production runtime dependency.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-windows.ps1
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release `
  -DELOI_BUILD_TESTS=ON
cmake --build build-release -j 2
ctest --test-dir build-release --output-on-failure
```

## Release invariants

Every change must preserve these requirements:

- GitHub releases contain exactly two downloadable archives: the canonical
  standalone ZIP and the Defender-friendly split-runtime ZIP.
- The standalone ZIP contains exactly `Eloi.exe` and `config.yml`.
- `Eloi.exe` is standalone and imports no non-system DLL.
- Piece PNGs, opening data, NNUE weights, and required attribution are embedded
  in the executable.
- `config.yml` is readable text and contains no real credential in Git or
  published artifacts.
- Eloi uses exactly three deterministic search threads, advertises a fixed UCI
  `Threads` value of 3, and does not advertise pondering.
- The engine warns above 40 plies, the GUI caps selection at 200 plies, and the
  absolute engine ceiling remains 17,697 plies.
- Standard chess, Chess960, UCI, and native Lichess operation remain compatible.
- Release builds use the exact toolchain and dependency hashes recorded in
  `reproducibility.lock.json`, contain a zero PE timestamp, and reproduce
  byte-for-byte from two independent clean build trees.

The split-runtime ZIP must isolate native networking in `EloiLichess.exe`, keep
WinHTTP out of its main `Eloi.exe`, and retain all required DLLs, PNG assets,
licenses, source revision, and per-file hashes. Both ZIP filenames include the
version and `windows-x64`; neither package replaces the other.

Local development uses `dist/current` as a rolling release-candidate area, not
an archive. After every build-affecting change, run
`scripts/stage-current-candidates.ps1`. It deletes only the previous rolling
candidate, rebuilds and tests both package forms, and leaves the newest
standalone and split-runtime ZIPs together. Extracted staging duplicates and
older local candidates do not remain under `dist`.

## Versioning

`CMakeLists.txt` is the single source of truth for Eloi's version. Its numeric
`project(... VERSION ...)` and `ELOI_PRERELEASE` values generate the C++
version header and Windows executable metadata. Do not hardcode a version in
another source file. Beta tags use `vMAJOR.MINOR.PATCH-beta.N`, release
candidate tags use `vMAJOR.MINOR.PATCH-rc.N`, and a stable release sets
`ELOI_PRERELEASE` to an empty string and uses `vMAJOR.MINOR.PATCH`.

## Code and engine changes

- Follow the surrounding C++ style: two-space indentation, braces on the same
  line, descriptive names, RAII ownership, and no avoidable heap allocation in
  hot search paths.
- Compile with warnings enabled and introduce no new warnings.
- Preserve deterministic behavior unless a change explicitly concerns
  randomness.
- Add focused tests for every rule, parser, search heuristic, or regression
  changed.
- Guard selective-search optimizations against checks, zugzwang-prone endings,
  promotions, forced replies, and tactical positions as appropriate.
- Do not claim an Elo gain from a few games. Three-lane strength changes should
  use paired equal-wall-time or equal-depth self-play; a fixed total-node gate
  unfairly fragments one budget across three independent trees. Major strength
  claims still require an SPRT or the documented 200-game mirrored gauntlet.

### Brain-change regression protocol

Before editing search, evaluation, time management, opening selection, or other
playing logic, capture the executable that immediately precedes the change:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\capture-brain-baseline.ps1
```

This intentionally retains only `Eloi.previous.exe` beside the current build;
running it again replaces the prior baseline. After rebuilding, open the GUI
and run **VERSION MATCH** in both color assignments at the same depth. Both
engines must start successfully, return legal moves, and finish or reach a
stable test stopping point without hanging. Also run the command-line smoke:

```powershell
.\build-release\Eloi.exe --version-match-smoke `
  .\build-release\Eloi.previous.exe
```

Record noteworthy visual behavior in the pull request, but use a mirrored
equal-wall-time gauntlet—not a single watched game—as the strength gate. Do not
commit the retained executable or package it in a release. On a shared Windows
machine, add `--idle-priority` so foreground applications and live bot games
preempt the test engines.

```powershell
& '.\.deps\lichess-bot\.venv\Scripts\python.exe' `
  '.\scripts\selfplay_gauntlet.py' `
  --candidate '.\build-release\Eloi.exe' `
  --baseline '.\build-release\Eloi.previous.exe' `
  --games 200 --movetime-ms 250 --required-score 55 --idle-priority
```

Run at minimum:

```powershell
ctest --test-dir build-release --output-on-failure
.\build-release\Eloi.exe --perft --depth 4
.\build-release\Eloi.exe --bench --depth 6
.\build-release\Eloi.exe --screenshot .\build-release\smoke.bmp
.\build-release\Eloi.exe --screenshot-setup .\build-release\setup-smoke.bmp
.\build-release\Eloi.exe --version-match-smoke `
  .\build-release\Eloi.previous.exe
```

## Artwork and data

The canonical chess-piece assets are the twelve transparent PNG files under
`assets/chess_maestro_bw`. Do not reintroduce SVG runtime assets. Preserve
`ATTRIBUTION.md` and the embedded GUI attribution when modifying packaging.

Document the provenance, license, version, and hash of any new book, NNUE,
training, or validation data in `DATA_SOURCES.md`. Runtime downloads are not
allowed.

## Configuration and secrets

`config.example.yml` is the tracked template. The release target copies it to
`config.yml`; local users may then add their Lichess token. Root `config.yml`
is ignored deliberately.

- Never paste a token into source, tests, documentation, logs, screenshots, or
  a pull request.
- Keep defaults safe: native Lichess mode disabled, token empty, pondering off,
  and challenge filters explicit.
- Keep the native endpoint restricted to exactly `https://lichess.org`; never
  send the bearer token over plaintext or to a configurable third-party host.
- New configuration keys require parser tests and README documentation.

## Pull requests

A good pull request includes:

1. A concise description of the problem and solution.
2. Tests that fail before the change and pass afterward.
3. Benchmark or gauntlet evidence for performance/strength claims.
4. Screenshots for visible GUI changes.
5. Confirmation that `git diff --check`, CTest, UCI startup, GUI rendering, and
   both golden release-package validations pass.

Keep commits understandable and avoid committing generated binaries. Maintainers
may ask for a change to be split, retested, or retuned before merging.

Before tagging a release, follow [REPRODUCING.md](REPRODUCING.md)
and run `scripts/verify-reproducible.ps1 -StageRelease` from a clean worktree.
Do not describe an artifact as reproducible unless that command completes and
the published asset hashes match its output.
