# Eloi-Native Policy/Value v2 Campaign

## Outcome

EPV2 is a completed but rejected Eloi-native laboratory experiment. The selected
network passed every correctness and tactical gate, but scored only **13 wins,
20 draws, and 27 losses** against frozen native E2 in the required 60-game
mirrored screen: **23/60 points, or 38.33%**. The conditional 200-game
confirmation was therefore not started.

Production remains Eloi v3.1.2. No packaged model, public default, or production
routing changed.

## Dataset and sealed-test discipline

- Dataset: 150,000 unique Standard-chess positions.
- Training: 120,000 positions.
- Validation: 15,000 positions.
- Sealed test: 15,000 positions.
- Dataset SHA-256:
  `FD851DE4D66AC9E4987A4D6B6364202CCD1F6CC8D7159C8B4C9434E9DAC40DC8`.
- Pretraining audit: exact partition counts, legal and normalized policy targets,
  zero train/validation canonical-key overlap, zero train/validation source-group
  overlap, and zero malformed train/validation records.

The trainer initially parsed sealed-test rows even though it did not evaluate
them. That violated the stronger campaign rule. Training did not begin until the
loader was changed to recognize test rows solely by their partition marker and
skip them before JSON parsing. The test partition was opened exactly once, after
checkpoint selection was frozen and after the strength screen could no longer
influence selection.

## Training and checkpoint selection

EPV2 retains 781 board inputs and a 64-unit hidden layer. Its policy head scores
complete oriented `(from, to, promotion)` moves across 20,480 outputs; legal
moves are masked before softmax. Its value head predicts win/draw/loss.

Training used deterministic category-balanced ordering, seed `20260916`, batch
size 256, learning rate 0.002, validation-aware early stopping with patience 3,
and the frozen 15-position tactical suite for every improving checkpoint.

Epoch 3 was selected. Epochs 4–6 improved the offline selection metric but each
failed the tactical gate by playing the forbidden `c6e5` knight hang in
`online-bIw09dp9-knight-hang`. Early stopping then ended training.

Selected model SHA-256:
`DD9FC147C10D4FB63096099897D6901B266C84EC2BF2307E8B4557792D19A67B`.

| Metric | Untrained | Selected validation | Sealed test |
| --- | ---: | ---: | ---: |
| Policy cross-entropy | 2.324422 | 2.323666 | 2.321293 |
| Policy top-1 | 12.15% | 13.83% | 13.50% |
| Value cross-entropy | 1.097296 | 0.958566 | 0.960048 |

The sealed-test result had no effect on training, checkpoint selection, or
promotion.

## Correctness and integration

- Python/C++ inference parity passed on deterministic positions.
- Maximum absolute parity difference: `5.92e-8` under a `2e-6` tolerance.
- Invalid-header, truncated, non-finite, trailing-byte, and missing artifacts
  fail closed.
- EPV2 is connected only as a root-move ordering prior. Alpha-beta scores and
  legal-move selection remain authoritative.
- Core, hybrid, and GUI C++ suites passed: 3/3.
- All 15 retained regressions passed with the selected model.
- The humiliation diagnostics completed without a new tactical failure.
- No production UCI default or packaged artifact references EPV2.

## Strength screen

The screen used 30 mirrored reserve openings, indices 240–269, at 10,000 nodes
per move, three threads per engine, 32 MB hash, and a 200-ply draw cap. Candidate
and baseline used the same executable and search profile; only the EPV2
root-order prior differed. The future confirmation indices were frozen in the
protocol before game one and remained unused.

- W/D/L: **13/20/27**.
- Score: **23/60 (38.33%)**.
- Protocol failures: **0**.
- PGN replay: **60/60 games verified**, with matching results, reserve indices,
  legal move sequences, and final FENs.
- Screen protocol SHA-256:
  `B0EAE9ABCA1E3F779469C4800138977343AE7151498D3C3D769CD355592C8145`.
- Results SHA-256:
  `EBE2ED5BB037F84C671F49CC0D4A3B98EFB689B5A2ADD8480DDC588CAA483DDF`.
- PGN SHA-256:
  `D34DD82A9397D95F1DAABD08BAE43DDA84DC94870F050F7F237DBFCDD5F00C21`.
- Replay evidence SHA-256:
  `F45CE37208C4A1B2EF805C93640D497D2714D16D42AD94FB8A81C9B1FEB47C62`.

## Decision

EPV2 does not become the preferred Eloi-native brain. The complete-move policy
head and larger teacher dataset improved offline value prediction and modestly
improved move classification, but the root prior materially weakened E2 in
actual search. Running 200 more games would violate the predeclared gate and
would not turn this failed candidate into a qualified one.

Generated datasets, checkpoints, models, PGNs, and detailed machine-readable
evidence remain ignored local artifacts under `tmp/`. Only reproducible tooling,
tests, and this compact report belong in Git.
