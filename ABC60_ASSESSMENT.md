# A/B/C — One-Hour Strength Assessment

Generated: 2026-09-03T01:46:10.202222+00:00

## Outcome

**A won screening; confirmation was interrupted by host sleep. No formal checkpoint pass or release qualification.**

A had **10 wins, 3 draws, 3 losses: 11.5 points from 16 completed confirmation games (71.875%)**. Game 17 has no chess result; games 18–20 were not started. The frozen gate required all 20 games to finish cleanly, so banked points alone do not constitute a pass.

Windows logged lid-triggered Modern Standby at **18:06:42 PDT**, overlapping the interrupted move, further standby transitions around **18:17:37**, and lid-triggered exit at **18:45:54**. The 656.265-second timeout gap is consistent with host suspension, not evidence establishing an engine-only hang. The user subsequently confirmed the computer slept. See [power-event evidence](data/abc60_power_interruption.json).

The original assessment started at 17:36:06 PDT and stopped engine work at 18:17:43; report delivery was delayed until 18:46:10, beyond the requested wall-clock hour. The deadline was not extended and the result was not relabeled. The user's later request to keep experimenting authorizes a **separate** [20-minute follow-up](ABC60_FOLLOWUP.md); its results must not be pooled with this interrupted confirmation.

This is a small exploratory experiment, not a reliable Elo estimate. All original release-blocking regression failures remain in force. Production and ABC100 are unchanged.

## Screening

| Brain | Games / 8 | W / D / L | Points | Score |
|---|---:|---:|---:|---:|
| A | 8 | 5 / 1 / 2 | 5.5 | 68.8% |
| B | 8 | 3 / 2 / 3 | 4.0 | 50.0% |
| C | 8 | 5 / 0 / 3 | 5.0 | 62.5% |

## Independent confirmation

Selected: A. Completed **16 of 20 planned games**; W/D/L **10/3/3**, **11.5 points from those 16 games**. Required: 11 points, all 20 games completed, zero protocol failures. Unfinished games were not counted as losses or draws, and the gate denominator was not reduced.

Paired 95% descriptive score interval: [0.48379987231329286, 0.9537001276867072]. Normal approximation over mirrored pairs; small nonrandom sample, descriptive only; not an Elo guarantee.

## Correctness and interruptions

Exact test outputs and bounded search traces are retained in the evidence manifest. Depth-stability failures are not automatically blunders; full-width search is not an oracle.

- A: exit 1; censored=False; failures: FAIL: RootSplit: lichess-002mG: expected f8e8, got e5h2
- B: exit 1; censored=False; failures: FAIL: RootSplit: online-bIw09dp9-knight-hang: forbidden online blunder repeated: c6e5
- C: exit 1; censored=False; failures: FAIL: RootSplit: lichess-001XA: best move remains stable across quiescence depths; FAIL: RootSplit: poisoned-pawn-capture: best move remains stable across quiescence depths
- production: exit 0; censored=False; failures: none observed

Game incidents: 1. Campaign outcome: `{"ended_utc": "2026-09-03T01:17:43.187567+00:00", "message": "Stopped on game incident: {'type': 'move', 'stage': 'confirmation', 'game': 17, 'engine': 'A', 'fen': 'r1b1k2r/pp3ppp/2p2n2/2P1p3/3p2P1/PPP1BP2/3K4/RN1Q1BNq w kq - 0 13', 'move': None, 'elapsed_seconds': 656.2649999999994, 'protocol_failure': 'engine-response-error:TimeoutError'}", "started_utc": "2026-09-03T00:45:45.233070+00:00", "status": "stopped", "type": "ValueError"}`.

## Protocol and evidence

250 ms/move; three search threads; 32 MB hash; books/noise disabled; Windows Idle; fresh processes per game; mirrored openings; absolute-ply-200 adjudication. No result-based early stopping, replacement opponent, extra games, or pooled pass score.

Protocol SHA-256: `ADD52A8FA4EACCA9061CB04A079CB83CB6167960B61C435ED1D8DDC887C67132`.

[Protocol](data/abc60_protocol.json) · [Machine-readable results](data/abc60_results.json)

Final conservatively counted temporary bytes: 1,185,986,829; training: 677,404,725; ABC60 scratch: 2,964,184.

## Follow-up

**Diagnostic findings:** all 60 searches produced evidence; 54 reached their requested depth and six full-width searches were depth-censored. All 45 production-profile searches completed. The 21 runner tests and three diagnostic-interpretation tests passed. Original A/B/C failures were reproduced unchanged; the production control passed.

- A recovered the required `f8e8` defense at depth 6 with full-width search, keeping exactly the same network. Normal search chose `e5h2`. Full-width used 599,901 nodes versus 17,833 (about 33.6 times as many); its success does not identify one faulty pruning rule or justify a blanket full-width deployment. Normal search recorded the defensive move with an upper bound, not an exact score.
- B repeated the stored knight hang in normal depth-7 search. Full-width did not universally help: it introduced the forbidden bishop-hang move at depth 6.
- C changed its preferred move between the tested depths, but its normal deeper search found required `b1b7`; it avoided the poisoned-pawn capture in both profiles, with a 19 cp shallow/deep score swing. Move instability alone does not prove a blunder.

Bound-tagged root alternatives, PVs, static evaluations and pruning counters are retained in [the diagnostic assessment](data/abc60_diagnostics.json). Original assertions and release gates were not changed. No illegal moves were observed; all 40 completed PGNs were replayed and checked.

A is the provisional research favorite, C remains a close comparison, and B's weaker result is evidence rather than proof that it is useless. Four screening opening pairs cannot establish a robust ranking. An ensemble requires evaluator-isolated accumulators and TT semantics; it was not implemented. The 41 dormant training channels remain a separate training investigation.

No training, engine-source changes, Stockfish execution, deletion, installation, packaging, push or publication occurred. The optional full-campaign archival verifier was not run because the original campaign did not complete.
