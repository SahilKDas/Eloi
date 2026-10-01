# Eloi v4.0.0 Handoff

Branch: `v4.0.0`

Current v4 theme: four-player chess only.

## Implemented

- Branch created from merged `main`.
- Workspace version is `4.0.0`.
- Four-player state is separate from two-player `Player` and FEN state.
- `FourSeat::{Red, Blue, Yellow, Green}` uses clockwise Red -> Blue -> Yellow -> Green order.
- 14x14 cross-board geometry has 160 playable squares.
- FFA and Teams modes exist as separate rules modes.
- Standard four-army initial setup exists.
- Directional pawns work for all four seats.
- FFA uses automatic queen promotion.
- Teams exposes selectable promotion choices.
- Teams prevents partner capture.
- FFA capture-point scoring is implemented.
- Deterministic state identity and local state serialization are implemented.
- `FourGame` owns reversible local history, move notation parsing, undo, resignation, and timeout outcomes.
- Handcrafted baseline search exists:
  - FFA: Max-N vector search.
  - Teams: team utility alpha-beta.
  - Root work respects Eloi's fixed three-thread contract.
- Protocol-neutral local snapshots exist for seats, clocks, scores, route, last move, result, and state.
- GUI presets exist in protocol types:
  - one-human FFA;
  - four-human pass-and-play;
  - two-human Teams;
  - all-engine demo.
- Local session wrapper exists with engine-seat stepping and undo.
- Native GUI has a `SurfaceKind::FourPlayer` and renders the 14x14 cross board.
- App CLI exposes:
  - `--four-player-gui`
  - `--four-player-smoke --mode ffa`
  - `--four-player-smoke --mode teams`
- Kaggle training scaffold exists at `scripts/four_player_kaggle_pipeline.py`.
- Kaggle local readiness checker exists at `scripts/kaggle_readiness_check.py`.
- Kaggle procrastination guide exists at `docs/KAGGLE_PROCRASTINATION_READINESS.md`.
- v4 scope doc exists at `docs/FOUR_PLAYER_V4.md`.

## Commits

- `08ebfc1` - `Start Eloi v4 four-player chess`
- `a1b5db4` - `Add four-player protocol snapshots`
- `c7a6a10` - `Add four-player local session flow`

## Validation Run

Passed:

```powershell
cargo test -p eloi-core -p eloi-engine -p eloi-protocol -p eloi-ui -p eloi-rs
python scripts\test_four_player_kaggle_pipeline.py
python scripts\test_kaggle_readiness_check.py
python scripts\kaggle_readiness_check.py --dry-run-only
cargo run -p eloi-rs -- --four-player-smoke --mode ffa
cargo run -p eloi-rs -- --four-player-smoke --mode teams
```

Observed smoke output:

```text
four-player-smoke mode=Ffa move=4052 turn=Blue state_hash=5C2713A61BFB07FC
four-player-smoke mode=Teams move=4052 turn=Blue state_hash=0067600E6B5EA995
```

The ignored donor-worker test still requires `ELOI_TEST_CAISSA20` and was not run.

## Not Finished

The branch is not a releasable v4.0.0 yet.

Remaining major gates:

- Complete all special four-player rules:
  - castling;
  - full checkmate/stalemate scoring;
  - multi-king check bonuses;
  - deterministic zombie-king movement;
  - valid 21-point FFA claim handling;
  - repetition/fifty-move adjudication;
  - clock decrement and time-control accounting.
- Build the slow independent four-player legal-move generator.
- Differentially validate at least 10,000 seeded FFA positions and 10,000 seeded Teams positions.
- Expand the native GUI from render-only surface into full local play:
  - seat selection;
  - mode selection;
  - legal target highlighting;
  - move input;
  - score/clocks;
  - pause/resign/undo;
  - move navigation;
  - copy/load four-player state.
- Build real self-play shard generation.
- Train `E4PC-FFA` and `E4PC-Teams` on Kaggle free compute.
- Export deterministic non-pickle artifacts and quantized Rust headers.
- Add Python/Rust inference parity.
- Run model qualification:
  - FFA: 400 seeded games against handcrafted baseline with rotated candidate seats;
  - Teams: 400 mirrored games against handcrafted baseline.
- Embed only qualified models.
- Run full existing Rust/Python, UCI, Lichess, GUI, Caissa-containment, package, and reproducibility gates.
- Build both Windows packages twice and prove deterministic ZIP hashes.
- Publish only after both FFA and Teams have complete rules and a correct Eloi computer opponent.

## Kaggle Instructions

Use Kaggle only for training, never for runtime.

Do not use free Colab for this chess training.

Create a private Kaggle notebook and private dataset. Run one mode at a time.

Local dry run:

```powershell
python scripts\four_player_kaggle_pipeline.py --mode ffa --dry-run
python scripts\four_player_kaggle_pipeline.py --mode teams --dry-run
python scripts\kaggle_readiness_check.py --dry-run-only
```

Full Kaggle target, inside Kaggle only:

```bash
python four_player_kaggle_pipeline.py --mode ffa
python four_player_kaggle_pipeline.py --mode teams
```

The current Kaggle script is still a manifest/split scaffold. It must be extended
with real self-play shard generation and PyTorch training before it can produce
candidate models.

## Safety Notes

- Four-player has no Chess.com login, scraping, browser automation, private endpoints, or affiliation claims.
- Lichess four-player is not supported.
- Standard remains Caissa 2.0.
- Existing two-player modes should remain unchanged.
- Training datasets, checkpoints, and raw Kaggle artifacts must stay ignored/private until deliberately exported, qualified, and hash-recorded.
