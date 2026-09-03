# Eloi

Eloi is a C++26 chess engine and native Windows chess application. The current
stable version is **2.5.0**, with the 64-unit **C** NNUE and exactly three
deterministic RootSplit search threads. Official packages target Windows x64;
other platforms are not yet validated.

## Download and play

Use the two archives on the [release page](https://github.com/SahilKDas/Eloi/releases/tag/v2.5.0):

- **Standalone:** exactly `Eloi.exe` and an empty-token `config.yml`. The GUI,
  engine, UCI interface, native Lichess client, artwork, opening book and NNUE
  are embedded; no non-system DLL or Python installation is required.
- **Exoskeleton:** the engine plus separate `EloiLichess.exe`, runtime DLLs,
  external artwork, licenses and a file-hash manifest. Keep the entire
  extracted directory together. See [package instructions](packaging/WINDOWS-X64-EXOSKELETON.md).

Check the ZIP hashes in [release validation](RELEASE_V2_5_0.md). Do not mistake
an older `-rc.1` archive for the stable build, even if its release-page title
says v2.5.0. Published configs contain no token; credentials belong only in a
private local copy. Packages are unsigned: never disable antivirus protection
to run them, and assess each release hash separately.

Double-click `Eloi.exe` or run `Eloi.exe --gui`. The GUI supports legal-move
highlighting, animated moves and castling, all four promotion choices, undo,
side selection, board flip, material/evaluation displays and Engine Lab.
Depth zero opens clocked-game setup with standard chess, Chess960 or Horde.
The recommended interactive ceiling is 40 plies; the GUI permits 200 and the
absolute UCI/analysis ceiling is 17,697. Deep searches can take a long time.

## Current strength and acceptance

C scored **10 wins, 3 draws, 7 losses (57.5%)** in 20 games against the exact
published v2.0.0 executable. B's separate match ran concurrently. This is
preliminary evidence, not a statistically established Elo improvement.

The maintainer selected C under the reviewed v2.5.0 acceptance policy. Two
depth-equality assertions now allow legal move refinement, while required
defenses, forbidden moves, PV legality and score-swing limits remain enforced.
Other `stable` assertions still require the same move. Historical failed or
interrupted campaigns were not retroactively passed.

See [release validation](RELEASE_V2_5_0.md), [C's retained match evidence](data/abc60_parallel_audit.json),
[data provenance](DATA_SOURCES.md), and [future work](FUTURE_WORK.md).
Past campaign plans and unused legacy collections are available in Git
history, not presented here as current instructions.

## Build and validate

Use the locked MSYS2 UCRT64 compiler/dependencies, CMake, Ninja and PowerShell 7.
See [REPRODUCING.md](REPRODUCING.md) before rebuilding release artifacts.
Python is a development-only dependency.

```powershell
pwsh -NoProfile -File .\scripts\bootstrap-windows.ps1
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_BUILD_TESTS=ON
cmake --build build-release -j 2
ctest --test-dir build-release --output-on-failure --timeout 120
.\build-release\Eloi.exe --perft --depth 4
python -B scripts/differential_movegen.py --engine build-release/Eloi.exe --samples 32
```

Starting-position perft depth 4 must produce **197,281 nodes**. The differential
runner compares complete legal-move sets for 32 seeded standard, 32 Chess960
and 32 Horde positions. The C++ suite covers rules, FEN/board restoration,
SEE/TT semantics, scalar/runtime-dispatched NNUE agreement and all 15 EPD
regressions. GUI-handler tests cover castling, promotion, undo and setup.

Production builds leave `ELOI_NNUE_INCLUDE_DIR` empty and consume the tracked
headers; CMake never retrains the NNUE or downloads runtime data implicitly.
Release proof requires two independent clean builds per package form,
matching payload/ZIP bytes, package smoke checks, performance checks and
Defender scans. Use [the release workflow](REPRODUCING.md), not an old
campaign's game count, beta baseline or speed threshold.

## Engine and diagnostic tools

Runtime modes include `--gui`, `--uci`, `--lichess`, `--perft`, `--bench`,
`--version-match` and deterministic GUI screenshot modes.
`--diagnose-search --fen FEN --depth N --profile production|full-width --json PATH`
reports root alternatives, PVs, SEE/TT information and pruning activity.
Full-width search is diagnostic evidence, not proof of an optimal move.

The engine uses iterative deepening, aspiration/PVS search, quiescence,
private TT shards within the configured hash budget, SEE/history ordering,
guarded pruning and incremental NNUE accumulators. BMI2 and AVX2 dispatch have
scalar fallbacks; those CPU features are not hard requirements. RootSplit is
the only current search implementation; there is no public LazySMP switch.

The embedded ECO repertoire has 5,480 positions and 8,092 weighted edges.
Eloi prefers the Italian Game as White and the Nimzo-Indian as Black when
permitted. The orthodox book is disabled for Chess960 and Horde, and Horde
uses its variant-safe evaluation.

Engine Lab compares a selected previous executable with the current one.
Keep an identified baseline using `scripts/capture-brain-baseline.ps1`,
then use the GUI's **ENGINE LAB** control or `--version-match-smoke`.
A watched game is a regression check, not a strength estimate.
`scripts/engine_lab.py` supports score-based matches, mirrored openings,
fixed-node or movetime budgets, checkpoints and bounded benchmarks.
Freeze a new protocol before a future strength campaign; its compatibility
defaults for historical experiments are not today's acceptance policy.

## UCI and native Lichess

```text
uci
isready
position startpos moves e2e4 e7e5
go depth 8
quit
```

Use `Eloi.exe --uci` with chess tools; piped stdin also selects UCI
automatically. `Threads` is fixed at 3, `Hash` defaults to 32 MB, and
`OwnBook` can be disabled. Chess960 uses `UCI_Chess960`; Horde uses
`UCI_Variant`. Standard rules include legal castling, en passant,
underpromotion, repetition, fifty-move and insufficient-material draws.

For the standalone native client, privately set `lichess.enabled: true`
and a Bot API token in adjacent `config.yml`, then run:

```powershell
.\Eloi.exe --lichess
```

In Exoskeleton, double-click `EloiLichess.exe` for its configuration window,
or use `EloiLichess.exe --run` after configuration. Native networking is
restricted to the exact HTTPS origin `https://lichess.org`.

The native client supports standard/Chess960/Horde games, eligible rematches,
and player-chat commands `!help`, `!version`, `!eval`, `!depth`, `!rematch`.
Arena/Swiss enrollment is performed by the user in the browser when the
tournament permits bots; Eloi handles resulting Bot API pairings and never
bypasses eligibility restrictions. The adaptive clock protects a reserve and
uses a completed search or legal fallback when interrupted. Native pondering
is limited to games with initial base time below four minutes; no UCI Ponder
option is advertised.

## Repository guide

- `src/`, `include/eloi/`: current engine, GUI, UCI and native client.
- `tests/`: mechanical, tactical, variant and GUI regression checks.
- `scripts/`: build/package helpers, reusable validation and training/audit tools.
- [data/README.md](data/README.md): current provenance and retained evidence.
- [CONTRIBUTING.md](CONTRIBUTING.md): engineering and release invariants.
- [Device constraints](constraints_on_SahilKDas_device.md): binding local limits.
- [FUTURE_WORK.md](FUTURE_WORK.md): open work, not permission to launch experiments.

`.deps`, `tmp`, `build-*`, `dist`, binaries and private `config.yml` are
ignored. They are not source and must not be committed. The existing ABC100
frontend and its dependencies are retained while that local session is active;
they are not a release requirement or a new campaign recommendation.

## Artwork, licenses and thanks

Eloi's source is MIT-licensed; see [LICENSE](LICENSE). Skia uses BSD 3-Clause.
The twelve Maestro PNGs are CC BY 4.0 artwork from Kadagaden; preserve
[their attribution](assets/chess_maestro_bw/ATTRIBUTION.md).
Opening and training-source attribution is in [DATA_SOURCES.md](DATA_SOURCES.md).
Stockfish supplied historical offline labels only, never Eloi runtime code
or a playing backend.

Eloi began as a fork of [Morlock](https://github.com/herohde/morlock).
Thank you to [Henning Rohde](https://github.com/herohde) and
[Dr. Ryan Heuser](https://github.com/quadrismegistus) for its foundation.
Thanks also to [Resera](https://discord.gg/36JDXtjgCn) for supporting Eloi's
bot account.
