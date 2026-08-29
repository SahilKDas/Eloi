# Eloi

Eloi is a C++26 chess engine and native Windows chess application. The
production build creates one main executable, `Eloi.exe`, with four runtime
modes:

- no arguments or `--gui`: the Skia GUI
- `--uci`: UCI mode for chess tools and Lichess bot bridges
- `--perft`: legal move-generator validation
- `--bench`: deterministic search benchmark

The engine uses iterative deepening, aspiration-window PVS/alpha-beta,
TT-backed quiescence, a compact four-way table with packed moves and normalized
mate scores, reversible in-place search moves, and TT-reconstructed principal
variations. Move ordering combines killer, butterfly, capture, continuation,
and countermove history with static exchange evaluation. Guarded verified null
move, ProbCut, razoring, futility and late-move pruning, singular/selective
extensions, volatility-aware LMR, and an incrementally updated quantized NNUE
complete the single-threaded search.

Eloi has a deliberate opening personality. As White it forces the Italian
Game with `1.e4 e5 2.Nf3 Nc6 3.Bc4` whenever Black permits it. As Black it
forces the Nimzo-Indian with `1.d4 Nf6 2.c4 e6 3.Nc3 Bb4` whenever White
permits it. An embedded position graph with 8,000-plus weighted edges across
ECO A00-E99 supplies sound fallbacks and variations; transpositions merge into
shared nodes instead of duplicating branches. No runtime database is needed.

## Search-depth limits

Eloi recommends at most **40 plies** for interactive play and warns when a
larger value is selected because a single-threaded search can take hours or
days. The GUI permits up to **200 plies**. UCI and command-line analysis have
an absolute maximum of **17,697 plies**, the proven maximum length of a legal
game under the automatic FIDE draw rules ([Yim, 2026](https://arxiv.org/abs/2608.14762)).

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
advantage, a 1–200-ply depth control with a warning above 40, and live
NNUE/search/LMR statistics. The board and interface are drawn in code with
Skia.

Eloi implements legal castling (including attacked-square restrictions), en
passant, every underpromotion, checkmate, stalemate, threefold repetition, the
fifty-move rule, and dead-position draws from insufficient material. Repetition
identity includes side to move, castling rights, and an en-passant target only
when a legal en-passant capture exists.

Chess960 is supported through Shredder/X-FEN rook-file castling rights and the
standard `UCI_Chess960` option. Castling handles every legal overlap case and
uses UCI's king-to-rook notation when Chess960 is active. Eloi disables its
orthodox Italian/Nimzo opening book in Chess960 positions. Pondering is
deliberately not advertised or enabled yet.

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

The UCI `Depth` option advertises `max 17697`; requests above 40 emit a clear
performance warning, while requests above 17,697 are rejected. `OwnBook`
defaults to `true` and can be disabled for analysis. The compact fixed hash
table defaults to 32 MB and remains configurable through `Hash`.

With `Depth` set to zero, Eloi uses a fail-safe adaptive clock policy. It
protects a reserve before searching, budgets conservatively across the
expected remaining game phase, credits only a bounded share of increment, and
adjusts the soft stop using best-move stability, evaluation swings, root score
gaps, credible alternatives, and tactical volatility. Pressure, emergency,
and panic modes impose progressively smaller hard deadlines below 120, 60,
and 20 seconds. If a deadline interrupts an iteration, Eloi plays the last
fully completed result (or a guaranteed legal fallback) rather than trusting
partial work.

The staged Lichess bridge is configured to accept only challenges whose base
clock is at least four minutes. Increment is deliberately ignored for this
eligibility check, so `3+30` is rejected while `4+0` is accepted. It accepts
both standard chess and Chess960 while keeping `ponder: false`.

## Validation

```powershell
cmake -S . -B build-tests -G Ninja -DCMAKE_BUILD_TYPE=Release `
  -DELOI_BUILD_TESTS=ON -DELOI_BUILD_APP=OFF
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
mate-in-one/two/three tactics, packed TT moves and mate scores, exact search
make/unmake and null-move restoration, search pruning exemptions, and activity
from null move, ProbCut, singular extensions, LMR, LMP, and history ordering.
Chess960 tests cover rook-file FEN rights, UCI notation, attacked transit
squares, non-corner rights loss, and king/rook origin/destination overlaps.
Clock tests cover five-minute allocation, protected reserve, increment and
overhead bounds, phase scaling, every pressure mode, hard ceilings, and legal
fallback under a near-expired deadline.

The development-only gauntlet runner uses eight neutral opening seeds, plays
every seed with colours exchanged, disables both opening books, and returns a
failure status unless the candidate's score exceeds 55% by default.

Against the pinned `dad44d4` Windows Release baseline, five deterministic
depth-six benchmark runs reduced the median from 2,181 ms and 194,320 nodes to
803 ms and 103,560 nodes. The candidate checksum was identical on every run.
In the mirrored 200-game, 2,000-node gauntlet it scored 66.00% (100 wins,
64 draws, 36 losses), passing the required 55% strength gate. The default
transposition-table allocation remains 32 MB.

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

## A very big thank-you to Morlock

Eloi began as a fork of
[Morlock](https://github.com/herohde/morlock), and its largest thank-you goes
to all the upstream code inherited from commits dated July 29, 2026 and
earlier. The collaborators on that version were
[**herohde** — Henning Rohde](https://github.com/herohde) and
[**quadrismegistus** — Dr. Ryan Heuser](https://github.com/quadrismegistus).
Their work provided the foundation from which Eloi grew.

### A smaller thank-you to Resera

Thank you to [Resera](https://discord.gg/36JDXtjgCn), a global research
collective that pairs students with research opportunities. Resera's owner
kindly allowed Eloi to use one of their email addresses for its Lichess bot
account.
