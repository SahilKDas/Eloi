# Eloi

Eloi is a C++26 chess engine and native Windows chess application. The current
source version is **1.9.0-rc.1**. The production build creates one main
executable, `Eloi.exe`, with five primary runtime modes:

- no arguments or `--gui`: the Skia GUI
- `--uci`: UCI mode for chess tools and Lichess bot bridges
- `--lichess`: native Lichess bot mode using `config.yml`
- `--perft`: legal move-generator validation
- `--bench`: deterministic search benchmark

Additional flags launch Engine Lab/Version Match and render deterministic GUI
screenshots for validation. Official binaries and release packaging currently
target Windows x64 only; Linux, macOS, ARM64, and Windows ARM64 builds have not
been validated or published.

## Current project status

The latest tagged release baseline is `v1.5.0-beta.1`; `main` is preparing
`v1.9.0-rc.1`. The v1.9 source contains the cached-board/search overhaul,
exactly-three-lane engine, Engine Lab, hash-bound benchmark harness, expanded
move-generation differential tests, deterministic NNUE training pipeline, and
the two golden Windows package builders.

The embedded production NNUE has 64 hidden units selected from deterministic
64-versus-128 retraining. Both candidates passed clean builds and correctness
tests; in the user-shortened 110-game architecture playoff, 128 scored 43.64%,
so the frozen threshold selected 64. The sample-size changes and every evidence
hash are recorded in `data/nnue_architecture_playoff.json`. The separate
250-game final release gauntlet has not run, so the current candidate remains
an RC under validation rather than a completed strength-qualified release. See
[V1.9_VALIDATION_PLAN.md](V1.9_VALIDATION_PLAN.md).

## Repository map

- `include/eloi/chess.hpp` and `src/chess.cpp` contain board rules, evaluation,
  time management, and search. `src/nnue.cpp` contains NNUE runtime updates and
  dispatch.
- `src/gui.cpp` owns the Skia human-play UI and Engine Lab. `src/driver.cpp`
  owns UCI, perft, and benchmark modes. `src/lichess.cpp` owns the native Bot
  API client, chat, rematches, pondering, and Arena/Swiss pairing handling.
- `include/eloi/opening_data.hpp`, `include/eloi/nnue_weights.hpp`, and
  `include/eloi/nnue_architecture.hpp` are tracked generated inputs embedded in
  standalone builds; CMake does not regenerate them implicitly.
- `scripts/engine_lab.py` is the hash-bound speed/strength/deep harness,
  `scripts/differential_movegen.py` checks exact legal moves, and
  `scripts/train_nnue.py` is the bounded deterministic NNUE trainer.
- `REPRODUCING.md` and `reproducibility.lock.json` define the build provenance
  contract. `CONTRIBUTING.md` defines engineering/release invariants, and
  `V1.9_VALIDATION_PLAN.md` defines the remaining NNUE and final-gauntlet work.
- `data/games` and `data/tournaments` retain reference/historical PGNs. They
  are not runtime dependencies and are not embedded in either Windows package.
- `.deps`, `tmp`, `build-*`, `dist`, private `config.yml`, executables, and
  runtime DLLs are intentionally ignored. Do not treat ignored local artifacts
  as source or commit real Lichess credentials.

## Two golden release packages

Every Eloi release publishes exactly two Windows x64 archives:

- `Eloi-vVERSION-windows-x64-standalone.zip`, whose extracted contents are
  exactly the following two files; and
- `Eloi-vVERSION-windows-x64-exoskeleton.zip`, the Defender-friendly
  Exoskeleton ZIP with networking, runtime DLLs, and artwork deliberately
  separated.

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

The Exoskeleton ZIP places piece PNGs and compiler runtime DLLs outside
the main executable, and native Lichess networking runs in a separate
`EloiLichess.exe`; the main `Eloi.exe` has no WinHTTP import. Build it with
`scripts/build-windows-exoskeleton-zip.ps1` and keep the extracted directory
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
TT-backed quiescence, compact four-way transposition tables with packed moves
and normalized mate scores, reversible in-place search moves, and
TT-reconstructed principal variations. Position state keeps a readable
mailbox synchronized with cached piece/color bitboards, occupancy, king
squares, Zobrist identity, and NNUE accumulators. Precomputed attacks and
passed-pawn masks avoid repeated board scans; sliding attacks use runtime BMI2
PEXT tables when available and a portable scalar fallback otherwise. NNUE
updates similarly dispatch to AVX2 when available without making AVX2 a hard
runtime requirement.

Move ordering combines killer, butterfly, capture, continuation, and
countermove history with static exchange evaluation. Guarded verified null
move, ProbCut, razoring, futility and late-move pruning, singular/selective
extensions, volatility-aware LMR, and the incrementally updated quantized NNUE
complete the search. Every calculated move uses exactly three persistent,
deterministic cooperative search lanes. Root work is split among them, each
lane has private TT storage within the single configured hash budget, and UCI,
GUI, and native Lichess sessions reuse their searcher instead of recreating its
threads and tables every move. Eloi exposes a fixed UCI `Threads` value of 3;
it cannot claim more processors or be configured to use fewer.

Eloi has a deliberate opening personality. As White it forces the Italian
Game with `1.e4 e5 2.Nf3 Nc6 3.Bc4` whenever Black permits it. As Black it
forces the Nimzo-Indian with `1.d4 Nf6 2.c4 e6 3.Nc3 Bb4` whenever White
permits it. An embedded position graph with 5,480 nodes and 8,092 weighted
edges across ECO A00-E99 supplies sound fallbacks and variations;
transpositions merge into shared nodes instead of duplicating branches. No
runtime database is needed.

## Search-depth limits

Eloi recommends at most **40 plies** for interactive play and warns when a
larger value is selected because even a three-thread search can take hours or
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

From that clean commit, build both golden archives and scan their executables
and ZIPs with the locally installed Microsoft Defender definitions:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\build-windows-release.ps1
```

On success, `dist/artifacts` contains exactly the standalone ZIP and the
Exoskeleton ZIP—no extracted staging duplicate.

Skia and development-only libraries are downloaded into `.deps/`, which is
intentionally ignored by git. Release builds statically link them and embed the
piece PNGs into `Eloi.exe`.

Double-click `build\Eloi.exe` to play. The GUI supports legal-move
highlighting, smooth animated moves (including the rook during castling), a
queen/rook/bishop/knight promotion picker, play as either color, undo, board
flipping, a chess.com-style captured-piece material counter with a live +N
advantage, a side-correct evaluation bar to the left of the board, a
0–200-ply control with a warning above 40, and live NNUE/search/LMR statistics.
Depth zero opens a friendly clocked-game setup instead of asking for terminal
commands: choose the base time and increment, play as White or Black, and pick
FIDE chess, a randomly numbered Chess960 start, or Horde. Eloi then uses the
same adaptive clock manager as native Lichess play. Hover states, dialogs,
promotion choices, piece movement, castling, and evaluation changes animate
smoothly. The bar is neutral before the first search, grows toward the side
Eloi evaluates as better, and follows the board when it is flipped. The board
and interface are drawn in code with Skia.

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

After making the change, rebuild and open `Eloi.exe`, then click **ENGINE
LAB**. Eloi automatically finds `Eloi.previous.exe`; if it is absent, a file
picker can select any historical Eloi executable. The current and previous
executables run as separate UCI child processes with equal settings: the GUI's
selected depth, a 32 MB hash table each, and both opening books disabled. The
board animates every move and identifies whose turn and last move it is. The
screen also shows both hashes, official-beta verification, PV, depth, nodes,
NPS, score, elapsed time, W/D/L, and raw-win rate. Use **RESTART ENGINE LAB**
to replay, **SWAP COLORS** to reverse the sides, **EXPORT ENGINE LAB REPORT**
to save Markdown and JSON under `%LOCALAPPDATA%\Eloi\Lab`, and **EXIT ENGINE
LAB** to return to human play. No terminal match loop is required.

To launch directly into autoplay from a terminal, use
`.\build-release\Eloi.exe --version-match`.

For a non-visual integration check, run:

```powershell
.\build-release\Eloi.exe --version-match-smoke `
  .\build-release\Eloi.previous.exe
```

A watched game is useful for spotting crashes, illegal moves, obvious tactical
regressions, and style changes, but one game cannot establish strength. The
current overhaul gate uses 125 positions from the committed neutral Standard
suite twice with colors reversed: 250 games at equal 250 ms/move, three
threads, 32 MB hash, and books disabled. Acceptance requires at least 150
candidate wins (60% raw wins); draws do not count as wins. The official beta
executable must have SHA-256
`614CE6D601AFC749EA4EFD8FC94A8BAE79EF4537374B0984E292A92CA0A99B7F`.

Run the strict speed and strength gates with:

```powershell
& '.\.deps\lichess-bot\.venv\Scripts\python.exe' `
  '.\scripts\engine_lab.py' `
  --candidate '.\build-release\Eloi.exe' `
  --baseline '.\path\to\official-beta-1\Eloi.exe' speed

& '.\.deps\lichess-bot\.venv\Scripts\python.exe' `
  '.\scripts\engine_lab.py' `
  --candidate '.\build-release\Eloi.exe' `
  --baseline '.\path\to\official-beta-1\Eloi.exe' strength

& '.\.deps\lichess-bot\.venv\Scripts\python.exe' `
  '.\scripts\engine_lab.py' `
  --candidate '.\build-release\Eloi.exe' `
  --baseline '.\path\to\official-beta-1\Eloi.exe' ladder
```

Depths 1, 5, and 10 each require at least a 5.00x median wall-clock
improvement. Depths 15, 20, 30, and 40 are bounded report-only probes: when a
target does not complete within ten minutes per engine/position, the report
records reached depth, nodes, NPS, time, and the result as censored rather than
inventing a speedup.

Eloi implements legal castling (including attacked-square restrictions), en
passant, every underpromotion, checkmate, stalemate, threefold repetition, the
fifty-move rule, and dead-position draws from insufficient material. Repetition
identity includes side to move, castling rights, and an en-passant target only
when a legal en-passant capture exists.

Horde is available through `UCI_Variant` and native Lichess mode. Its canonical
36-pawn start, kingless White side, first-rank pawn double-step (without an
en-passant target), promoted Horde pieces, White checkmate victory, and Black
victory after eliminating every White piece are handled separately from
orthodox chess. Eloi disables standard NNUE/endgame shortcuts and the orthodox
opening book in Horde, using a dedicated Horde-safe evaluation.

Chess960 is supported through Shredder/X-FEN rook-file castling rights and the
standard `UCI_Chess960` option. Castling handles every legal overlap case and
uses UCI's king-to-rook notation when Chess960 is active. Eloi disables its
orthodox Italian/Nimzo opening book in Chess960 positions.

## UCI and Lichess

```text
uci
isready
setoption name Depth value 8
setoption name UCI_Variant value horde
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

Eloi then uses Windows HTTPS directly to accept eligible standard, Chess960, or
Horde challenges and play them with the same engine and time manager as UCI
mode. The native player-chat commands are `!help`, `!version`, `!eval`,
`!depth`, and `!rematch`. Eloi ignores spectator chat and its own messages. After a game it
auto-accepts an eligible rematch while idle; an earlier queued challenge event
takes precedence.

### Browser-joined bot tournaments

Eloi can play Arena tournament pairings without joining tournaments through
the API. While signed in as the bot account, join an Arena whose page
explicitly says BOT accounts are allowed, then keep that tournament page open
and keep either the native client or the `lichess-bot` bridge running. Lichess
delivers each pairing as a `gameStart` event; Eloi recognizes the current
`gameId`, records the `tournamentId`, plays the game, and returns to the control
stream for the next pairing.

Swiss pairings use the same Bot API game stream rather than a second gameplay
endpoint. If Lichess admits the bot to a Swiss event, Eloi recognizes the
`gameStart` source as Swiss (and records a `swissId` when Lichess supplies one),
labels the game as a Swiss pairing, plays it normally, and waits for the next
pairing. Browser enrollment remains the user's job. Lichess may refuse BOT
accounts on a particular Arena or Swiss page; Eloi cannot and does not bypass
that server-side eligibility rule.

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
deciding whether pondering is enabled. Standard chess, Chess960, and Horde are
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
.\build\Eloi.exe --screenshot-engine-lab `
  .\build\engine-lab.bmp C:\path\to\official-beta-1\Eloi.exe

& '.\.deps\lichess-bot\.venv\Scripts\python.exe' `
  '.\scripts\engine_lab.py' --candidate '.\build\Eloi.exe' `
  --baseline C:\path\to\official-beta-1\Eloi.exe speed

& '.\.deps\lichess-bot\.venv\Scripts\python.exe' `
  '.\scripts\differential_movegen.py' `
  --engine '.\build\Eloi.exe' --samples 32
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
Horde tests cover the canonical 36-pawn position and reference perft, kingless
White play, the special first-rank double-step without en passant, Horde
elimination, and checkmating Black.
The differential runner compares complete legal-move sets—not only counts—
against python-chess for deterministic random Standard, Chess960, and Horde
positions.
Clock tests cover five-minute allocation, protected reserve, increment and
overhead bounds, phase scaling, every pressure mode, hard ceilings, and legal
fallback under a near-expired deadline.

The older `selfplay_gauntlet.py` runner remains available for quick historical
diagnostics, but its old result is not a current acceptance gate. Current
claims use the hash-bound `engine_lab.py` protocol above.

### v1.9.0-rc.1 evidence and open gates

The reproducible standalone candidate executable used by the final shallow
speed report has SHA-256
`C86A883AB5E3CAF2FDB1037468E1652EB7318730E86C6E77A1F6C47611D20FCA`.
Against the hash-verified official beta baseline, its measured medians were:

| Depth | Baseline | v1.9 candidate | Speedup | 5.00x gate |
|---:|---:|---:|---:|:---:|
| 1 | 5,529.253 ms | 585.934 ms | 9.437x | PASS |
| 5 | 3,967.747 ms | 950.923 ms | 4.173x | **FAIL** |
| 10 | 26,899.311 ms | 4,295.656 ms | 6.262x | PASS |

Depth 5 remains below the declared hard speed gate; it is not rounded into a
pass. A five-second development deep ladder generally reached farther depths
than beta.1 and measured one completed depth-15 pair at 9.677x, but the other
depth-15/20/30/40 rows were correctly recorded as censored. The release-grade
ten-minute deep report has not been run.

A 40-game development precursor scored 25 wins, 14 draws, and 1 loss at the
final 250 ms/move settings. That binary did **not** have the final candidate
hash, and 40 games are not the 250-game gate, so this is encouraging diagnostic
evidence only. The exact final candidate has not passed the required 250-game,
150-raw-win gauntlet.

The completed correctness evidence includes the C++ test suite, reproducible
two-build proof, packaged UCI/config/GUI smoke tests, and a 96-position exact
legal-move differential run: 32 Standard, 32 Chess960, and 32 Horde positions
against python-chess. Packaging checks also prove that the Exoskeleton main
engine does not import WinHTTP while `EloiLichess.exe` does. See
[V1.9_VALIDATION_PLAN.md](V1.9_VALIDATION_PLAN.md) for the selected-NNUE
reproducibility gate and remaining final release decision.

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
