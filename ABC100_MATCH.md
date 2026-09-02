# ABC100: user-requested exploratory match

## Current outcome: watchdog pause, not 100-game completion

At 23:43:56 UTC on 2026-09-02, the runner paused after **89 completed automated
games plus the completed human exhibition**. In game 90 (B's 30th game, B playing
Black), **the official v2.0.0 opponent** returned a legal move after **3.171 s**,
exceeding the frozen 2.5-second watchdog. The late move was not applied or scored.
Game 90 is saved after 76 played plies. There are no recorded illegal engine
moves; all 89 completed engine PGNs and the human PGN independently replay and
their results validate.

| Candidate | Completed games | W / D / L | Non-losses | Numerical threshold |
| --- | ---: | ---: | ---: | --- |
| A | 30 | 18 / 7 / 5 | 25 | Clinched |
| B | 29 | 15 / 4 / 10 | 19 | Clinched |
| C | 30 | 19 / 8 / 3 | 27 | Clinched |

All three have mathematically secured the user's at-least-17-non-loss criterion
and also banked more than 16.5 chess points. This does **not** mean the full
scheduled run finished or passed its timing protocol. No final outcome was
assigned to the interrupted game. The human game ended 0-1 by the user's
resignation after 28 plies, and is separate from candidate results.

Three bounded, single-position diagnostic searches in a fresh official-baseline
process returned legal `h7b7` at 250 ms each. They do not reproduce the earlier
search-cache state and do not establish the original delay's cause. Smaller
late-run timing spikes occurred in more than one engine; OS scheduling is a
possibility, not a demonstrated cause.

Evidence: `data/nnue_abc100_timing_interruption.json` and
`data/nnue_abc100_paused_results.json`. The latter retains all completed PGNs,
independent validations, original identities and per-game file hashes.
The OpenAI Docs-guided scheduled follow-up is paused pending user direction;
the local board server remains available. No limits have changed, no automatic
resume is authorized, and no completed game has been replayed.

The report-only checker is `scripts/report_abc100.py`; seven additional in-memory
tests in `scripts/test_report_abc100.py` cover wrong outcomes, changed pairings,
premature adjudication and the odd-game separation. Final `--retain` refuses to
run without all 100 results and the runner's final export. `--retain-paused`
explicitly labels this incomplete, error-paused snapshot and cannot overwrite a
different existing snapshot.

This is a new experiment, not a continuation or retroactive pass of the frozen
fresh-data campaign. Its candidates failed that campaign's deterministic
regression gate. The user explicitly requested playing A, B and C anyway.
No production replacement, training, installation, publication or release is
authorized by this match. No Stockfish code or playing backend is used.

## Frozen allocation and threshold

- A vs exact published v2.0.0: **33 games**.
- B vs exact published v2.0.0: **33 games**.
- C vs exact published v2.0.0: **33 games**.
- User vs exact published v2.0.0: **one local GUI exhibition**, recorded separately.
- Exactly **100 games total**. No development/confirmation pilots, blends, extra
  tiebreaks, or 300-game run are included.
- Per the user's explicit clarification, a candidate passes this **match's**
  criterion with **at least 17 wins-or-draws**, equivalently **at most 16 losses**.
  All 33 games must finish without protocol errors. A draw counts fully toward
  non-loss rate but contributes only half a point to ordinary chess score.
- Example: 0 wins / 17 draws / 16 losses passes the requested non-loss criterion
  despite scoring only 8.5/33 points. A pass is **not evidence of higher Elo**.

The runner freezes `data/nnue_abc100_protocol.json` before any games. This pins
executable, runner, frontend and opening-suite hashes, all 99 automated pairings,
settings and the exact threshold. Existing protocol/evidence files are unchanged.

## Fairness and bounds

All three candidates receive the same first 17 positions from the already-frozen
reserve partition. Each plays the first 16 positions with both colors and the
17th as White: **17 White / 16 Black**. An odd allocation cannot be fully
color-balanced. Candidate order rotates each round to spread temporal effects.
The old sealed-final openings remain unused. No post-result opening selection.

Both sides receive 250 ms per move, exactly three threads, 32 MB hash, books and
noise disabled, no move overhead, Windows Idle priority, standard chess draw
claims, and a draw adjudication at absolute ply 200 (including the opening's
existing ply counter). A 2.5-second watchdog and 5-second UCI timeout detect
protocol failures, which pause the run rather than silently count a win.
The automated worker is bounded to four hours per invocation. There is no early
stopping based on interim W/D/L. A single lock permits only one engine search at
a time, including the human opponent; human replies receive priority between
automated plies.

Only existing binaries are executed. The verified official opponent SHA-256 is
`5F13AB2FEB05DE4171DB39E637FD1322409211872DEBB72AD7BEF88858B5AACF`.
The network and executable hashes are pinned in the protocol. Current production
weights remain untouched. Existing correctness rejection evidence remains valid.

## Human game

The localhost-only browser board uses the repository's existing PNG pieces and
an independently running official v2.0.0 UCI subprocess. Choose a color before
starting; White is the default. Human thinking time is unlimited; the engine has
250 ms per move. Assistance is explicitly permitted for this casual exhibition,
which is labeled potentially assisted and never affects candidate scores.
The assistant does not submit moves, resign, or play the human game on the user's
behalf. Closing the page does not forfeit the game. Reopening restores its state.
Promotion choice, castling, legal-move checks, move log, engine PV/score/depth,
and an explicitly confirmed resignation are available. No takebacks or new-game
button: this is exactly one exhibition.

The HTTP server binds only `127.0.0.1`, checks the Host and Origin, and requires
a per-session anti-CSRF token for moves. It does not read private configuration,
authenticate to Lichess, transmit moves externally or expose a filesystem browser.

## Evidence and recovery

`tmp/abc100/` retains an append-only event log, rolling active/human checkpoints,
one immutable JSON record with complete PGN for each finished game, live summary,
and final automated aggregate/PGN. Every completed record binds to the protocol
hash. Resume validates binaries, scripts, schedule and saved moves; it cannot
change thresholds or silently replay completed games. An interrupted active game
resumes from its moves with a fresh engine state, explicitly logged as a resume.
Search-cache continuity across interruption is not claimed.

The GUI backend prints engine move, score, PV, node and timing output to its
terminal log. It must remain running while the user plays. The match reserves
100 MB new scratch; checks the nested training quota, total repository temporary
usage and free space at each automated game. No files are deleted. Deliberately
retained pinned dependencies are not counted as disposable copies.

## Local commands

Use the existing Python runtime with `python-chess` available through the repo's
dependency path. First run `scripts/test_abc100_match.py` (in-memory tests only).
Then `scripts/abc100_match.py --prepare` once to freeze the protocol, and
`scripts/abc100_gui_fix.py --serve --run-automated` to run the local board and match.
Run long-lived Python at Windows Idle priority with a hidden helper window and
redirected terminal output, while opening the board visibly at
`http://127.0.0.1:8765/`. Do not launch a duplicate worker. The GUI does not run any
game until the user presses its start button; automated games begin only with
the explicit `--run-automated` argument.

## Status

The match started on 2026-09-02 at approximately 23:03 UTC. At the launch
checkpoint it had completed 14 automated games and the human game was actively
being played. These are a historical snapshot, not current standings. Read
`tmp/abc100/summary.json` or the live board for current results. No final result
or strength claim is implied by this launch checkpoint.

Twelve in-memory tests pass. Initial live HTTP validation caught a GUI-only
property-access error (`board.legal_moves()` instead of `board.legal_moves`).
The additive `abc100_gui_fix.py` adapter overrides only state serialization;
the original frozen runner, protocol, binaries and match settings were not
changed. Eight completed games were retained and game 9 resumed after 27 saved
moves, with fresh engine caches. This interruption must accompany final results.
The precise identities and restart are recorded in
`data/nnue_abc100_gui_amendment.json`. No completed game was replayed.

The initial output remains in `tmp/abc100/terminal.log` and `.err`; the running
continuation uses `terminal-2.log` and `terminal-2.err`. The local board, piece
images, state API and legal opening moves returned successfully after the fix;
subsequent human/engine moves confirm the interactive path is being used.
Automated browser visual inspection could not run because its sandbox helper
failed twice. No visual-inspection pass is claimed.

The `eloi-abc100-match-follow-up` heartbeat checks every five minutes, remains
quiet during normal progress, and reports completion or errors. It may not add
games, change the frozen rule, make the user's moves, or stop their GUI. After
reporting the 99 automated results and human status it pauses itself. Keep the
computer and desktop app running for local scheduled checks. The GUI worker
continues independently until its process is stopped; closing the page does not
stop it or forfeit the human game.
