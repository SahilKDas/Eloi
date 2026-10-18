# Eloi v4.0.0 — Quick Start

Extract the entire ZIP before running anything.
Target: Windows 10/11 x64. Caissa 2.0 Standard search requires an AVX2-capable CPU.

## Four-player Teams

Double-click **Open-Teams.cmd**, or open **Eloi.exe** directly.
You control Red and Yellow; Eloi controls Blue and Green. All computer moves
use Eloi's own handcrafted Teams evaluator and three-thread search.

Select a piece, then a highlighted target. The sidebar offers a new Teams game,
pause, undo, team resignation, four-human play, an all-Eloi demo, 1/3-second
search budgets, and promotion selection. No Kaggle account or model is needed.

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

This release adds playable handcrafted Teams and restores the retained dashboard
composition. It does not claim a measured Elo increase or a proven win against
a particular human. FFA and Kaggle training are excluded from this release.
