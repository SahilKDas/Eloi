# Eloi

Eloi is a C++26 chess engine and native Windows chess application. The
production build creates one main executable, `Eloi.exe`, with three runtime
modes:

- no arguments or `--gui`: the Skia GUI
- `--uci`: UCI mode for chess tools and Lichess bot bridges
- `--perft`: legal move-generator validation

The engine uses iterative deepening, alpha-beta negamax, quiescence search,
transposition-table ordering, late move reductions (LMR), and an incrementally
updated quantized NNUE evaluator.

## Hard 40-ply limit

`maximum_search_depth` is a compile-time constant set to **40 plies**. Search
requests are clamped or rejected at that boundary throughout the GUI,
command-line parser, searcher, and UCI `Depth` option. A value of 41 or higher
cannot become the engine's configured search depth.

## Windows build

Requirements are CMake, Ninja, a MinGW UCRT C++ compiler with C++26
(`-std=c++2c`) support, and PowerShell. Go is not used.

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
flipping, a 1–40-ply depth control, and live NNUE/search/LMR statistics. The
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
are explicitly ignored. `go depth` is likewise capped at 40 plies.

## Validation

```powershell
cmake -S . -B build-tests -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_BUILD_TESTS=ON
cmake --build build-tests --target eloi_tests -j
ctest --test-dir build-tests --output-on-failure

.\build\Eloi.exe --perft --depth 4
.\build\Eloi.exe --screenshot .\build\eloi-gui.bmp
```

Tests cover standard perft positions, en passant, both castling sides, every
promotion choice, checkmate, stalemate, threefold repetition and undo, the
fifty-move rule, FEN round trips, search, incremental NNUE state, and LMR
activity.

## Artwork and licenses

Eloi's source is MIT-licensed; see `LICENSE`. The twelve files under
`assets/chess_maestro_bw` are separate, unmodified CC BY 4.0 artwork from
[Kadagaden/chess-pieces](https://github.com/Kadagaden/chess-pieces/tree/master/chess_maestro_bw).
See [the asset attribution](assets/chess_maestro_bw/ATTRIBUTION.md).

NanoSVG is used under its zlib license in the ignored dependency cache. Skia is
used under its BSD 3-Clause license.
