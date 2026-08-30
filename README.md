# Eloi

Eloi is a C++26 chess engine and native Windows chess application. The
production build creates one main executable, `Eloi.exe`, with five runtime
modes:

- no arguments or `--gui`: the Skia GUI
- `--uci`: UCI mode for chess tools and Lichess bot bridges
- `--lichess`: native Lichess bot mode using `config.yml`
- `--perft`: legal move-generator validation
- `--bench`: deterministic search benchmark

## Two golden release packages

Every Eloi release publishes exactly two Windows x64 archives:

- `Eloi-vVERSION-windows-x64-standalone.zip`, whose extracted contents are
  exactly the following two files; and
- `Eloi-vVERSION-windows-x64-split-runtime.zip`, the Defender-friendly package
  with networking, runtime DLLs, and artwork deliberately separated.

The canonical standalone archive contains:

- `Eloi.exe`, a standalone statically linked Windows application containing the
  GUI, engine, UCI interface, native Lichess client, NNUE, opening data, piece
  PNGs, and artwork attribution; and
- `config.yml`, a human-readable configuration file for the user's Lichess
  token, challenge filters, and engine settings.

Published `config.yml` files always contain an empty token. Real credentials
belong only in a user's ignored local copy. Release builds must not require
Python, Go, external assets, downloaded data, or non-system DLLs.
The native client accepts only the exact HTTPS origin `https://lichess.org`, so
a changed configuration cannot redirect its bearer token to another host.

The second golden package places piece PNGs and compiler runtime DLLs outside
the main executable, and native Lichess networking runs in a separate
`EloiLichess.exe`; the main `Eloi.exe` has no WinHTTP import. Build it with
`scripts/build-windows-split-zip.ps1` and keep the extracted directory
together. Double-clicking `EloiLichess.exe` opens a native configuration window
that reads and writes the adjacent `config.yml`; no text or development editor
is required.

### Microsoft Defender false-positive resolution

Microsoft analyzed the RC-2 standalone executable submitted as suspected false
positive `f6ee03e9-1ec6-4f33-bd8e-f831c8502d27`. Its analyst determined that
the submitted file did not meet Microsoft's criteria for malware or a
potentially unwanted application and removed the
`Trojan:Win32/Wacatac.B!ml` detection. This determination applies to the exact
submitted RC-2 binary; a new release hash is scanned and assessed separately.
Never disable antivirus protection to run Eloi. If Defender retains the old
cached verdict, update its security intelligence and rescan the file.

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

Requirements are the hash-locked MSYS2 UCRT64 GCC 14.1.0-3 toolchain, CMake
3.29.3-2, Ninja 1.12.1-1, and PowerShell. No Go source, module, toolchain, or
release configuration remains in the Eloi repository. See
[REPRODUCING.md](REPRODUCING.md) for the complete package names, verified
dependency hashes, and byte-for-byte release procedure.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-windows.ps1
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --target Eloi -j
cmake --build build --target release -j
```

Every release must additionally pass two independent clean builds:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-reproducible.ps1 `
  -StageRelease
```

Release compilation uses fixed single-partition LTO, remapped build paths, a
fixed build epoch and a zero PE timestamp. The verifier refuses a dirty
worktree and stages the two-file package only after both builds and test runs
produce byte-identical files.

Skia and development-only libraries are downloaded into `.deps/`, which is
intentionally ignored by git. Release builds statically link them and embed the
piece PNGs into `Eloi.exe`.

Double-click `build\Eloi.exe` to play. The GUI supports legal-move
highlighting, smooth animated moves (including the rook during castling), a
queen/rook/bishop/knight promotion picker, play as either color, undo, board
flipping, a chess.com-style captured-piece material counter with a live +N
advantage, a 1–200-ply depth control with a warning above 40, and live
NNUE/search/LMR statistics. The board and interface are drawn in code with
Skia.

### Watch the new brain play the previous brain

Eloi's **Version Match** mode is a friendly, real-time regression tool for
engine-logic changes. Before changing search, evaluation, time management, the
opening book, or another part of the chess brain, retain the current executable
with one command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\capture-brain-baseline.ps1
```

The script keeps exactly one sibling baseline named `Eloi.previous.exe` and a
small commit-label file. Capturing again deliberately replaces that baseline,
so old builds do not accumulate. These build-local files are ignored by Git
and never enter either release package.

After making the change, rebuild and open `Eloi.exe`, then click **VERSION
MATCH**. Eloi automatically finds `Eloi.previous.exe`; if it is absent, a file
picker can select any historical Eloi executable. The current and previous
executables run as separate UCI child processes with equal settings: the GUI's
selected depth, a 32 MB hash table each, and both opening books disabled. The
board animates every move and identifies whose turn and last move it is. Use
**RESTART VERSION MATCH** to replay, **SWAP COLORS** to reverse the sides, and
**EXIT VERSION MATCH** to return to human play. No terminal match loop is
required.

To launch directly into autoplay from a terminal, use
`.\build-release\Eloi.exe --version-match`.

For a non-visual integration check, run:

```powershell
.\build-release\Eloi.exe --version-match-smoke `
  .\build-release\Eloi.previous.exe
```

A watched game is useful for spotting crashes, illegal moves, obvious tactical
regressions, and style changes, but one game cannot establish strength. Brain
changes still require paired, color-reversed fixed-node self-play; major
strength claims retain the documented 200-game, above-55% gauntlet gate.

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

The two-file standalone package does not need that Python bridge. Set `lichess.enabled`
to `true`, paste a Bot API token into the adjacent `config.yml`, and run:

```powershell
.\Eloi.exe --lichess
```

Eloi then uses Windows HTTPS directly to accept eligible standard or Chess960
challenges and play them with the same engine and time manager as UCI mode.

### Browser-joined bot tournaments

Eloi can play Arena tournament pairings without joining tournaments through
the API. While signed in as the bot account, join an Arena whose page
explicitly says BOT accounts are allowed, then keep that tournament page open
and keep either the native client or the `lichess-bot` bridge running. Lichess
delivers each pairing as a `gameStart` event; Eloi recognizes the current
`gameId`, records the `tournamentId`, plays the game, and returns to the control
stream for the next pairing.

Browser enrollment needs no `tournament:write` token permission because the
browser performs the join. The bot process still needs `bot:play` to receive
and play its games. Challenge minimum/maximum clock filters do not reject an
Arena pairing: joining the Arena is the explicit authorization to play its
clock and variant. To change Eloi's rating, the Arena itself must be marked
**Rated**; Casual Arena games change tournament standings but not rating.

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

The native Lichess client accepts clocked challenges below four minutes as well
as longer games (subject to the configurable minimum and maximum base times).
Only games whose initial base clock is below four minutes use pondering. Eloi
announces that once in player chat, searches the predicted reply while the
opponent's clock runs, cancels immediately on a different reply, and never
ponders in four-minute-or-longer games. Increment is deliberately ignored when
deciding whether pondering is enabled. Standard chess and Chess960 are both
supported.

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

Eloi's source is MIT-licensed; see `LICENSE`. The twelve PNG files under
`assets/chess_maestro_bw` are separate CC BY 4.0 artwork, rasterized without
visual alteration from
[Kadagaden/chess-pieces](https://github.com/Kadagaden/chess-pieces/tree/master/chess_maestro_bw).
See [the asset attribution](assets/chess_maestro_bw/ATTRIBUTION.md).

Skia is used under its BSD 3-Clause license.

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
