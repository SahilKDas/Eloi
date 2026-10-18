# Eloi revive — handcrafted four-player Teams

Eloi supplies all computer seats locally. No Kaggle, trained model, teacher,
website account or network connection is required. The work is collected in
one local commit on `v4.0.0`; publishing is a separate action.

## Play

Double-click `Open-Eloi-Teams.cmd` in the repository root. The separate
`Open-Eloi-OperationsCenter.cmd` opens the current Rust bridge with a
hash-verified Caissa 2.0 worker; it refuses while another Eloi bridge is open.
An old `Eloi-v3.6.0-live/EloiLichess.exe` remains an old installation and does
not acquire Teams support from new source commits. Leave an active old bridge
alone until its game finishes, close it manually, then use the new launcher.
Lichess does not support four-player Teams; the Teams GUI is a separate local game.

The bridge launcher reuses the valid native config under
`.deps/lichess-bot/engines/Eloi-v3.6.0-live/config.yml` without modifying it.
You may supply another native config with
`powershell -File scripts/start-eloi.ps1 -Mode Operations -Config <path>`.
The Python lichess-bot configuration has a different schema. Offline validation:
`powershell -File scripts/start-eloi.ps1 -Mode Operations -Check`.

```powershell
cargo build --release -p eloi-rs --offline
& .\target\release\eloi-rs.exe --four-player-gui
```

Red moves first, followed by Blue, Yellow, Green. Red/Yellow form one team;
Blue/Green form the other. Default: you control Red and Eloi controls all other
seats, including your Yellow teammate. Distinctly colored, embedded Maestro
piece artwork needs no external asset directory. Click your piece and a
highlighted destination. Castling uses the king's destination.

Controls offer a fresh human/Eloi game, pause/resume, undo to Red's turn,
Red resignation, four-human pass-and-play, all-engine demonstration, 1/3-second
thinking time, and Queen/Rook/Bishop/Knight promotion selection. Sessions start
with ten minutes per seat and no increment. Pausing suspends clocks and cancels
search; closing joins the search worker.

## Rules and evaluation

The geometry has 160 playable squares in a 14×14 cross. Pawns move in their
seat's direction, may double-step from their starting rank, and promote on
their eleventh rank with underpromotion. En passant survives the intervening
seats until the double-pushing seat's next turn. Castling tracks each original
rook independently and rejects check, occupied paths and attacked transit or
destination squares. Partner pieces block movement and cannot be captured;
they do not attack the allied king.

Checkmate/stalemate is resolved only for the seat whose turn has arrived.
Mating one enemy wins for the entire team; stalemate draws. Resignation or
timeout loses for the team. Threefold repetition uses local game history;
loading an isolated state starts fresh history. A 200-ply reversible-move
counter represents fifty complete four-seat rounds. Bare kings draw.
These Teams objectives and promotion/turn rules follow
[Chess.com's published Teams rules](https://www.chess.com/terms/4-player-chess).
Eloi is an independent local implementation.

Search uses team alpha-beta, iterative deepening, capture/promotion ordering,
and bounded tactical continuation with check evasions. Every iteration splits
the root over exactly three search lanes. Search reuses core-generated legal
children and commits only completed iterations. An interrupted first iteration
is explicitly reported as an emergency legal move. The GUI discards cancelled
searches. Evaluation includes team material, directional pawn progress, piece
centrality, king shelter and checks to either teammate. No trained weights are
loaded. FFA's old implementation is retained as historical code, not exposed
by these Teams interfaces.

## Four-player UCI extension

```powershell
& .\target\release\eloi-rs.exe --four-player-uci
```

Use `uci`, `isready`, `ucinewgame`, `position startpos [moves ...]`,
`position state <complete Eloi state> [moves ...]`, `go`, `stop`, `d`, `quit`.
`d` prints the current serialized state. Invalid positions are rejected
transactionally. `position ... moves` preserves repetition history.

Moves contain four hexadecimal digits: source file/rank then destination
file/rank, each `0..d`. Optional `q/r/b/n` specifies promotion. For example,
`6163` moves Red's pawn from file 6/rank 1 to file 6/rank 3. This is deliberately
distinct from 8×8 algebraic UCI. `bestmove 0000` indicates no move in a terminal
position.

Supported search bounds: `go movetime 500`, `go nodes 10000`, `go depth 3`,
or combinations. Depth is bounded to 1–12. Four clocks are `rtime`, `btime`,
`ytime`, `gtime` with `rinc`, `binc`, `yinc`, `ginc`, all milliseconds.
Clock allocation uses the active seat and a configurable reserve.
`go infinite` searches up to the depth cap and waits for `stop` before publishing.
Ponder and searchmoves are rejected rather than misinterpreted.
Supported options: fixed `Threads=3`, `UCI_Variant=fourplayerteams`,
`Move Overhead=0..5000` (default 20 ms). The Teams engine currently has no TT or
configurable Hash option. Scores are in centipawns from the active team's
perspective, including ±30000 for a team win/loss.

## Validation and limits

See [the validation record](FOUR_PLAYER_TEAMS_VALIDATION.md) for completed
checks, executable/evidence hashes and their limits.

```powershell
# Workspace-local test scratch avoids Windows temp-directory ACL failures.
$env:TEMP = "$PWD\tmp"
$env:TMP = $env:TEMP
cargo test --workspace --offline
python scripts\four_player_teams_smoke.py --engine target\release\eloi-rs.exe
```

Tests cover special moves in all orientations, attack detection against an
independent piece scan, turn-based mate, pins, state round trips, partner
capture refusal, underpromotion, clocks, cancellation, basic tactical search,
GUI state changes and protocol lifecycle. They do not establish a numerical
Elo rating or that Eloi already beats a particular human. Human Teams playtests
are the next strength evidence. No Chess.com integration, FFA completion,
neural model, release package or public publication is part of this commit.
