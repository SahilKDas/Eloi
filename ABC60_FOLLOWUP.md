# A — Independent Confirmation After Host Sleep

**No provisional checkpoint pass; no release qualification.**

Completed 20/20 games against the exact published v2.0.0: **8 wins, 5 draws, 7 losses; 10.5 points (52.5%).**

This is a new user-authorized experiment following a documented laptop-sleep interruption. It neither resumes nor repairs the previous experiment. Previous 11.5/16 confirmation points are excluded from this score.

## Frozen protocol

Ten new mirrored reserve openings; 250 ms/move; three search threads; 32 MB hash; books/noise off; Idle priority; fresh engine processes per game; absolute-ply-200 draw adjudication. Twenty-minute total budget, minute-18 search cutoff. The threshold is 11/20 points, all games completed, no protocol incidents. No extra games or result-based stopping.

Protocol SHA-256: `B46915B98A7579A624199D038F8B29BC75543BF5916B573B6A95AD1DCB519C7A`.

## Interpretation

Paired 95% descriptive score interval: [0.2888717391849177, 0.7611282608150823]. Normal approximation over mirrored pairs; small nonrandom sample, descriptive only; not an Elo guarantee.

Color split: `{"white": {"loss": 4, "win": 3, "draw": 3}, "black": {"draw": 2, "loss": 3, "win": 5}}`. Mirrored pair points: `[0.5, 0, 0.5, 2, 1.5, 1, 2, 2, 0.5, 0.5]`.

A remains blocked from release by its original required-defense regression. Better match results do not waive that failure or prove superiority over C. No training, engine changes, Stockfish use, installation, deletion or publication occurred.

Protocol incidents: 0. Outcome: `{"started_utc": "2026-09-03T03:16:28.883845+00:00", "status": "completed", "ended_utc": "2026-09-03T03:25:48.053020+00:00"}`.

## Evidence

The separate post-run audit reconciled all **2,148 moves** against each response's FEN, engine identity, elapsed time and PGN. No illegal moves or protocol incidents were found; the maximum response was 0.610 seconds. Engine play took **9 minutes 19 seconds**. Protected prior evidence and production weights were verified unchanged.

## Requested combined summary — descriptive only

Combining the previous **16 completed** confirmation games with these 20 gives A **18 wins, 8 draws, 10 losses: 22/36 points (61.1%)**. The interrupted game, unstarted games and screening results are excluded. Both sets used the same engine settings and non-overlapping opening pairs.

The paired 95% descriptive interval is **44.2%–78.0%** across 18 mirrored pairs. This does not establish a reliable Elo gain and does not turn either original outcome into a pass: the first set was incomplete; this fresh set missed 11/20 by half a point. See [combined evidence](data/abc60_combined_summary.json).

[Protocol](data/abc60_followup_protocol.json) · [Results and all game records](data/abc60_followup_results.json) · [PGNs](data/abc60_followup_games.pgn) · [Original assessment](ABC60_ASSESSMENT.md)

Final temporary bytes: 1,186,611,136; training: 677,404,725; follow-up scratch: 624,307.
