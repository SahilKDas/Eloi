# B/C Parallel Screen

Same openings and per-engine settings as A, but B/C share CPU. Concurrent fixed-movetime results are not a clean strength comparison with A's solo run; actual overlap can vary as games finish.

| Brain | Conditions | Games | W/D/L | Points | Provisional checkpoint |
|---|---|---:|---:|---:|---|
| A | Prior solo run, context only | 20 | 8/5/7 | 10.5/20 | Missed |
| B | Concurrent B/C | 20/20 | 8/3/9 | 9.5 | Not passed |
| C | Concurrent B/C | 20/20 | 10/3/7 | 11.5 | Passed |

## Protocol and limitations

User explicitly authorized B/C concurrency: two simultaneous searches, exactly three search threads per engine, six active search threads total; fresh private engine pair per game; 250 ms/move, 32 MB hash, books/noise off, Idle priority, absolute-ply-200 adjudication. Same ten mirrored openings as A's solo follow-up. New twenty-minute budget, minute-18 search cutoff, no result-based early stop or extra games.

Eleven points and all 20 cleanly completed games are required for each provisional checkpoint. This is not release qualification. All original tactical/depth-stability failures remain in force. Results must not be used to declare B or C stronger than solo A without equal-load confirmation.

## Evidence

[Protocol](data/abc60_parallel_protocol.json) · [Results, game records, color splits and paired uncertainty](data/abc60_parallel_results.json) · [PGNs](data/abc60_parallel_games.pgn) · [A follow-up and combined context](ABC60_FOLLOWUP.md)

Protocol SHA-256: `CBAA24CD3517686A31AF1E12F613AD67B0DE6DB0D54B5B033212EA172435592C`. Final temporary bytes: 1,187,860,592; parallel scratch: 1,249,456.

Production, earlier evidence and the existing frontend were preserved. No training, Stockfish execution, engine changes, deletion, release package or publication.

## Final independent audit

All 40 completed PGNs were independently replayed against their frozen pairings and starting positions. Results and final positions matched; every response's engine identity, position, legal move and elapsed time reconciled with the per-game records. The aggregate PGN and protected prior evidence also verified. There were no illegal moves, crashes, watchdog incidents or incomplete games. All owned experiment workers exited; the original human-game frontend and its idle opponent remained untouched.

| Brain | Verified moves | Worker elapsed | Longest response | White W/D/L | Black W/D/L |
|---|---:|---:|---:|---|---|
| B | 2,075 | 9m 55s | 0.594 s | 3/3/4 | 5/0/5 |
| C | 2,252 | 10m 48s | 0.734 s | 6/1/3 | 4/2/4 |

Both workers completed within the new twenty-minute budget. Their response intervals overlapped for approximately 411.3 seconds, estimated from logged UTC response ends and elapsed durations, not from CPU profiling. C finished 52.5 seconds after B, leaving a final stretch without the competing match. Neither B/C nor their comparison with solo A had perfectly uniform CPU contention.

Descriptive paired-opening normal 95% intervals for chess score are B: 25.0–70.0%, C: 35.5–79.5%. These wide intervals include 50%; this small screen is not a reliable Elo estimate or a demonstrated strength improvement. Screening and confirmation results have not been pooled to manufacture a pass.

Recommendation: C is the provisional preferred brain for further investigation from this parallel screen, not a replacement for production or a newly established champion. C's existing depth-stability failures still block release; A's required-defense failure and B's knight-hang failure also remain documented. Any future equal-load confirmation or targeted diagnostic work needs its own bounded protocol. No additional run was started.

Final measured training artifacts were 677,404,725 bytes and free disk space was 34,018,291,712 bytes; total temporary usage remained 1,187,860,592 bytes, including 1,249,456 bytes of parallel scratch. The measurement preceded this small retained audit addition. All limits were respected and no files were deleted.

[Machine-readable audit](data/abc60_parallel_audit.json) retains timings, validation scope and evidence hashes. Results SHA-256: `1F3145FF6FF5B12C3A2708FDD13080457F96A579EE497BC7148B71C4B0CC4B9C`. Aggregate PGN SHA-256: `0C90E0BEBBD1A38BD9DF511A37A86F2A0C5BA90942B55D577713FDAB55DE5FAE`.
