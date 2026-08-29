# Eloi

Eloi is a C++26 chess engine and native Windows chess application. The
production build creates one main executable, `Eloi.exe`, with four runtime
modes:

- no arguments or `--gui`: the Skia GUI
- `--uci`: UCI mode for chess tools and Lichess bot bridges
- `--perft`: legal move-generator validation
- `--bench`: deterministic search benchmark

The engine uses iterative deepening, aspiration-window PVS/alpha-beta,
quiescence search, a compact four-way transposition table, killer/history and
static-exchange move ordering, guarded null-move and futility pruning, late
move reductions (LMR), and an incrementally updated quantized NNUE evaluator.

Eloi has a deliberate opening personality. As White it forces the Italian
Game with `1.e4 e5 2.Nf3 Nc6 3.Bc4` whenever Black permits it. As Black it
forces the Nimzo-Indian with `1.d4 Nf6 2.c4 e6 3.Nc3 Bb4` whenever White
permits it. An embedded position graph with 8,000-plus weighted edges across
ECO A00-E99 supplies sound fallbacks and variations; transpositions merge into
shared nodes instead of duplicating branches. No runtime database is needed.

## Hard 40-ply limit

`maximum_search_depth` is a compile-time constant set to **40 plies**. Search
requests are clamped or rejected at that boundary throughout the GUI,
command-line parser, searcher, and UCI `Depth` option. A value of 41 or higher
cannot become the engine's configured search depth.

## Windows build

Requirements are CMake, Ninja, a MinGW UCRT C++ compiler with C++26
(`-std=c++2c`) support, and PowerShell. No Go source, module, toolchain, or
release configuration remains in the Eloi repository.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-windows.ps1
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --target Eloi -j
```

Skia and NanoSVG are downloaded into `.deps/`, which is intentionally ignored
by git. The compatible Skia raster library is linked into Eloi; required MinGW
and image-codec DLLs plus the piece assets are copied beside `Eloi.exe`.

Double-click `build\Eloi.exe` to play. The GUI supports legal-move
highlighting, smooth animated moves (including the rook during castling), a
queen/rook/bishop/knight promotion picker, play as either color, undo, board
flipping, a chess.com-style captured-piece material counter with a live +N
advantage, a 1–40-ply depth control, and live NNUE/search/LMR statistics. The
board and interface are drawn in code with Skia.

Eloi implements legal castling (including attacked-square restrictions), en
passant, every underpromotion, checkmate, stalemate, threefold repetition, the
fifty-move rule, and dead-position draws from insufficient material. Repetition
identity includes side to move, castling rights, and an en-passant target only
when a legal en-passant capture exists.

## UCI and Lichess

```text
uci
isready
setoption name Depth value 8
position startpos moves e2e4 e7e5
go depth 8
quit
```

Point a UCI-compatible Lichess bridge (for example, a bot-account runner) at
`Eloi.exe --uci`. When stdin is a pipe, Eloi also selects UCI mode
automatically, so wrappers that invoke the executable directly remain
compatible.

The UCI `Depth` option advertises `max 40`; attempts to assign 41 or above
are explicitly ignored. `go depth` is likewise capped at 40 plies. `OwnBook`
defaults to `true` and can be disabled for analysis. The compact fixed hash
table defaults to 32 MB and remains configurable through `Hash`.

## Validation

```powershell
cmake -S . -B build-tests -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_BUILD_TESTS=ON
cmake --build build-tests --target eloi_tests -j
ctest --test-dir build-tests --output-on-failure

.\build\Eloi.exe --perft --depth 4
.\build\Eloi.exe --bench --depth 6
.\build\Eloi.exe --screenshot .\build\eloi-gui.bmp

python .\scripts\selfplay_gauntlet.py --candidate .\build\Eloi.exe `
  --baseline C:\path\to\baseline\Eloi.exe --games 200 --nodes 2000
```

Tests cover standard perft positions, en passant, both castling sides, every
promotion choice, checkmate, stalemate, threefold repetition and undo, the
fifty-move rule, FEN round trips, incremental Zobrist and NNUE state, Italian
and Nimzo personality/transpositions, an 8,000-entry minimum repertoire,
mate-in-two tactics, search, and LMR activity.

The development-only gauntlet runner uses eight neutral opening seeds, plays
every seed with colours exchanged, disables both opening books, and returns a
failure status unless the candidate's score exceeds 55% by default.

The pinned pre-upgrade comparison (`7c1ee72`, Windows Release, books off)
needed 35,708 nodes and 222 ms to complete depth six from the initial position.
This build completed the same search in 7,161 nodes and 55 ms. In the mirrored
200-game, 1,000-node gauntlet it scored 84.75% (151 wins, 37 draws, 12 losses),
passing the required 55% gate. The default transposition-table allocation also
fell from 128 MB to 32 MB.

## Emergency restart handoff (2026-08-28)

The repository was reduced from about 1.66 GiB to about **155 MiB** before an
emergency restart. The cleanup removed only ignored, reproducible caches: the
private compiler toolchain, duplicate Skia trees, downloaded NNUE/training
datasets, package archives, and `build-tests`. It retained the configured
`.deps/lichess-bot` bridge, `.deps/skia108`, `.deps/nanosvg`, Git history,
source, artwork, and the working `build-release/Eloi.exe` package.

The last verified feature is the GUI's chess.com-style captured-piece material
counter. It renders the actual piece SVGs, reports `EVEN` or `WHITE/BLACK +N`,
values promoted material correctly, follows en-passant captures, and rewinds
with undo. The Release build and complete test suite passed before cache
cleanup.

An engine-strength pass was interrupted after source edits began and **has not
been built or tested**. Its work-in-progress is in `src/chess.cpp`,
`src/driver.cpp`, and `include/eloi/chess.hpp`; inspect the diff first and
either complete those edits or surgically remove only those hunks. Do not
regenerate datasets yet. The next pass should proceed in this order:

1. Restore only the compiler/runtime files required for a C++26 build, without
   restoring duplicate SDKs or the training corpora. Update CMake so packaged
   runtime DLLs come from one compact dependency root.
2. Finish adaptive clock allocation using best-move stability, evaluation
   swings, root-score gaps, credible alternatives, game phase, increment, and
   configurable network/move overhead.
3. Finish and validate lightweight endgame knowledge: exact KPK, opposition
   and corresponding squares, wrong-bishop rook-pawn draws, Lucena/Philidor,
   fortresses, insufficient winning material, opposite-bishop scaling, and the
   rule of the square.
4. Add carefully filtered quiet checks for double attacks, king restriction,
   undefended major pieces, and continuing mating nets.
5. Finish the volatility classifier (hanging pieces, exposed kings, forcing
   moves, advanced passers, evaluation swings, and singular replies), then use
   it to tune LMR, aspiration windows, pruning, and selective extensions.
6. Rebuild Release and tests, run tactical/perft/clock regressions and a
   benchmark, refresh the executable staged in lichess-bot, then delete the
   temporary build/toolchain cache again.

The existing Release executable remains runnable after restart. A new build
will require rehydrating the removed compiler and Skia runtime/import-library
cache; those files are intentionally not part of Git.

## Artwork and licenses

Eloi's source is MIT-licensed; see `LICENSE`. The twelve files under
`assets/chess_maestro_bw` are separate, unmodified CC BY 4.0 artwork from
[Kadagaden/chess-pieces](https://github.com/Kadagaden/chess-pieces/tree/master/chess_maestro_bw).
See [the asset attribution](assets/chess_maestro_bw/ATTRIBUTION.md).

NanoSVG is used under its zlib license in the ignored dependency cache. Skia is
used under its BSD 3-Clause license.

The embedded opening and NNUE tables were generated from CC0 Lichess data.
See [DATA_SOURCES.md](DATA_SOURCES.md) for pinned provenance and reproduction
details.
