# Eloi E3: controlled 64/128-unit campaign

E3 is an unreleased Standard-chess laboratory campaign. Production remains
Eloi v3.1.2 and is not modified by this work.

## Question

Does doubling Eloi E2's NNUE hidden width from 64 to 128 help when both models
receive the same larger dataset? The comparison trains E3-64 and E3-128 with
identical examples, ordering, epochs, and tactical-preservation pairs. E3-128
begins with E2 copied into its first 64 channels and neutral appended channels.

## Additional game sources

The ignored local research inputs are the freely downloadable player PGNs from
PGN Mentor for Viswanathan Anand and Anish Giri. Raw archives are not committed
or packaged. Their URLs, hashes, game counts, rejection counts, and selected
position counts are frozen in the generated campaign protocol. Positions are
FIDE Standard only, deduplicated by position, and partitioned by whole source
game so one game cannot cross training, validation, and sealed test partitions.

The player games identify useful positions; frozen Eloi v3.1.2/Caissa 1.25 is
used only as an offline numeric teacher at 10,000 nodes with three threads. It
is not a runtime dependency of either E3 candidate.

Numeric mate sentinels are clamped to the established scalar-NNUE range of
±1,500 cp. Revision 2 demonstrated that feeding EPV2's ±30,000 policy/value
mate sentinel directly into scalar regression dominated mean error and caused
multiple engine-level tactical regressions; those rejected artifacts remain
preserved in ignored campaign evidence.

## Gates

1. Freeze sources, hashes, partitions, resource limits, and teacher identity.
2. Generate append-only, resumable labels at Windows Idle priority.
3. Train E3-64 and E3-128 without opening the player-game test partition.
4. Compare offline validation and tactical retention, then build both engines.
5. Reject any mechanically or tactically failing candidate.
6. Run short mirrored screens against frozen native E2 before any larger match.

No offline metric promotes a network. A 128-unit network must beat the 64-unit
control and then beat E2 in engine games; being larger is not evidence of being
stronger.

## Result (revision 3)

The frozen corpus contained 39,704 globally deduplicated player-game positions:
31,636 train, 4,275 validation, and 3,793 sealed test. Training combined the
31,636 player positions with the retained 120,000-position EPV2 train partition.
The sealed player and EPV2 test partitions were not opened.

| Candidate | Broad quantized MAE | Player quantized MAE | Quantized pair accuracy | Correctness failures |
|---|---:|---:|---:|---:|
| E3-64 | 435.86 cp | 210.81 cp | 57.80% | 4 |
| E3-128 | 445.44 cp | 230.93 cp | 57.28% | 6 |

E3-64 still missed `lichess-009FP`, `lichess-002mG`, `lichess-001XA`, and one
mate-in-three expectation. E3-128 missed those three Lichess defenses, one mate
expectation, and repeated the forbidden poisoned-pawn blunder. Both candidates
were rejected before strength games. No 60-game screen or 200-game confirmation
was run, and the production E2 header remained byte-identical.

The experiment does **not** support the claim that 128 units are stronger. On
this recipe, 128 units were worse after quantization and in engine-level gates.
The useful outcome is the expanded, reproducible corpus and a concrete finding:
capacity is not the present bottleneck; target construction and preservation of
critical defensive behavior are.
