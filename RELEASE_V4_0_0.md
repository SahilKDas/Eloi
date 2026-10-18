# Eloi v4.0.0 — Four-Player Teams

Four-player **Teams** is the focus of v4.0.0. You control **Red + Yellow**;
Eloi controls **Blue + Green** on the 160-square cross board.

## Handcrafted Eloi brain

- Eloi-owned team alpha-beta with iterative deepening, tactical continuation,
  legal move ordering, and exactly three search lanes.
- Handcrafted team material, pawn progress, piece activity and king-safety evaluation.
- Directional pawns, double moves, en passant, castling, underpromotion,
  turn-based checkmate/stalemate, local repetition, resignation and clocks.
- A dedicated four-player Teams UCI extension through `--four-player-uci`.
- No Kaggle account, neural training campaign, downloaded model, or donor engine
  is needed for four-player play. FFA is outside this release's playable scope.

## Native play and retained styling

- Red/Yellow human control, Blue/Green Eloi control; all-human and all-engine presets.
- Pause, undo, resignation, promotion selection and adjustable thinking time.
- Smoothly filtered four-color Maestro pieces, Segoe UI typography, rounded
  charcoal panels, purple accents and gentle hover effects.
- The board geometry and seat positions are preserved.
- Operations Center restores the retained status banner, game/search cards,
  session strip, event timeline and six bottom actions. `--operations-preview`
  shows it offline without starting a bridge or locking its live instance.

Standard UCI/Lichess retains verified **Caissa 2.0**. Existing two-player variant
routes remain separate from the handcrafted Teams brain.

## Downloads

Download either Windows x64 ZIP and **extract it completely**. Start with
`Open-Teams.cmd`. Both forms contain the artwork and notices:

Use Windows 10/11 x64; the bundled Caissa 2.0 Standard worker requires AVX2.

- `Eloi-v4.0.0-windows-x64-standalone.zip`
- `Eloi-v4.0.0-windows-x64-exoskeleton.zip`

Lichess configuration ships **disabled with an empty token**. Finish any game
on an old bridge before closing it and starting the new Operations Center.

## Evidence and limits

The local revival passed its Rust correctness suites, tactical fixtures, UCI
lifecycle checks, and a 100-ply Teams self-play sequence with full legal replay
and zero protocol failures. That sequence was **100 plies, not 100 games**.
Final release preparation passed 95 workspace Rust tests, the additional
pinned-donor containment integration test, and 191 Python tests.

No numerical Elo gain, win against Sahil, completed strength tournament, or
exhaustive four-player rules certification is claimed. The handcrafted brain
is the selected Teams release route; playing strength remains a playtest target.
Release package reproducibility and published-asset SHA-256 verification are
recorded with the uploaded artifacts.
