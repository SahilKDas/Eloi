# Eloi v4.0.1 — Quick Start

Extract the entire ZIP before running anything.
Target: Windows 10/11 x64. Caissa 2.0 Standard search requires an AVX2-capable CPU.

## Four-player Teams

Double-click **Open-Teams.cmd**, or open **Eloi.exe** directly.
You control Red and Yellow; Eloi controls Blue and Green. All computer moves
use Eloi's own handcrafted Teams evaluator and three-thread search.

Use the top-right **TWO-PLAYER CHESS** / **FOUR-PLAYER TEAMS** button to
switch boards inside this application. Each board is preserved. Switching
pauses Teams and cancels its search; click Resume when returning. The
Operations Center remains separate and does not switch or restart a bridge.
An old v3.6.0 executable is unchanged; use this v4.0.1 application for navigation.

Select a piece, then a highlighted target. The sidebar offers a new Teams game,
pause, undo, team resignation, four-human play, an all-Eloi demo, 1/3-second
search budgets, and promotion selection. No Kaggle account or model is needed.

**Watch Eloi Think:** completed depth, team-relative evaluation, nodes, time
and up to six seat-labelled PV moves appear while Eloi searches. Positive
scores favor the explicitly named searching team, not always Red/Yellow.
Toggle **Show suggestion** for a board arrow; it never plays a move.
Suggestions appear on Eloi's turns, not as hints during your own turn.
Before any depth completes the panel says **Preparing search**. Final metrics
are labelled **previous search**; cancelled and emergency answers are explicit.

## Classic two-player play

Use **TWO-PLAYER CHESS** at the top right, or run `Eloi.exe --gui`.
The restored interface includes Maestro pieces, legal targets, check/last-move
highlights, clocks, material/evaluation, smooth moves, undo, flipping and side
selection. New Game configures base time, increment, variant and brain.
Caissa 2.0 is Standard-only; other variants use the corresponding Eloi evaluator.
Use the promotion picker; Crazyhouse pocket buttons select legal drops.
Engine Lab pauses local play and offers explicit position analysis plus
copy/export of diagnostics. It is not the old automatic version tournament UI.
Fast donor responses can omit telemetry: "depth not reported" is not an invented
depth or an Eloi fallback. Actual fallback identity is always displayed.

## Lichess Operations Center

Close any older bridge after its current game finishes. Edit the included
`config.yml`: add your own bot API token and set `lichess.enabled: true`.
Then double-click **Open-OperationsCenter.cmd**. Never share that edited file.
Standard uses verified Caissa 2.0. Lichess variants keep their existing Eloi
routes; four-player Teams is local and is not a Lichess variant.

To inspect the dashboard without connecting, run:
`Eloi.exe --operations-preview`.

## Package forms

- **Standalone:** the verified Caissa worker is embedded and materialized in
  the per-user Eloi worker cache when needed.
- **Exoskeleton:** keep `eloi-caissa-2.0.exe` beside `Eloi.exe`.

Both forms embed the piece artwork. Keep license/attribution files with either
package. Four-player Teams UCI is available through `Eloi.exe --four-player-uci`.
Its 14×14 coordinate extension is documented in the README and Teams guide.

## Strength and scope

This two-month-anniversary patch adds Teams search visibility without changing
budgets, rules or intentional search decisions. It does not claim a measured Elo increase or a proven win against
a particular human. FFA and Kaggle training are excluded from this release.
