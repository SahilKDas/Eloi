# Handcrafted Teams revival — local validation

Validated on Windows x64, Rust 1.98.1/MSVC, 2026-10-18.

## Completed checks

- `cargo test --workspace --offline`: **93 passed**, zero failed. One existing
  official-donor integration test remains ignored because its explicit
  `ELOI_TEST_CAISSA20` fixture was not supplied.
- Historical pipeline/exporter Python unit tests: 5 passed. Full Kaggle runs
  and exporter entry points now refuse to start; dry runs remain historical tests.
- `cargo build --release -p eloi-rs --offline`: passed.
- Existing `scripts/rust_uci_smoke.py`: passed using the existing lichess-bot
  virtual environment (the global Python installation lacks `python-chess`).
  This exercised ordinary UCI handshake, legality, infinite/stop, ponderhit,
  reset, rejection and exit without starting a Lichess bridge.
- Dedicated Teams endpoint: 100 self-play plies at 250 ms requested per move,
  all replayed through the Rust rules core; every move completed an iteration;
  zero protocol failures. Transactional rejection, fixed Threads=3, unsupported
  command refusal, responsive isready, infinite/stop and clean quit passed.
- Native board renderer: embedded pieces visible, deterministic frame verified;
  selected squares/legal targets and moved positions change the frame.
- `git diff --check`: passed.

The workspace suite uses workspace-local TEMP/TMP because the first attempt
against Windows' default temporary directory received an ACL denial while
publishing an Operations Center snapshot. No test was removed or changed to
hide the failure; the same test passes with accessible scratch storage.

## Local evidence

| File | SHA-256 |
| --- | --- |
| `target/release/eloi-rs.exe` | `C8BDDB298ECF1B12AC9CB31732A2601984C923F1DF3080FB780B27426F23661E` |
| `tmp/four-player-teams-smoke100.json` | `329BEC1E737B6FC1789526550D16D8BB38536A97625A75EE33E2380B5DA7B8F8` |

Generated evidence and the executable remain ignored local artifacts. This is
a validation record, not a reproducibility or release qualification claim.
The 100-ply smoke is an interrupted self-play sequence, not 100 games, a
completed tournament, or evidence of beating Sahil. No human result is known.
The independent attack scan covers 32 seeded positions, not a completed
10,000-position differential legal-move campaign. Those broader strength and
rules campaigns can follow human playtesting.
