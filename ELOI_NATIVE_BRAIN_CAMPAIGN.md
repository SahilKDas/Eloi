# Eloi-native brain recovery: F0–F5

This campaign exists to make Eloi's own chess brain strong enough to challenge
the Caissa-era releases. It does **not** redefine the current production
architecture: Eloi v3.1.1 continues to use isolated Caissa 1.25 for Standard
UCI/Lichess, while E2 remains the legal fallback and the Chess960/Horde brain.

## Frozen principles

- Standard FIDE chess is the training and selection domain.
- Caissa 1.25 is an offline teacher, never silently relabelled as Eloi.
- The Caissa network is hash-gated at
  `615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`.
- Test positions are sealed during training and model selection.
- Production keeps exactly three search threads. The one-thread E2 path is a
  named laboratory mode, not a public UCI option.
- A later gauntlet cannot waive legality, tactical, deadline, or regression
  failures.

## Phase status

| Phase | State | Evidence / remaining gate |
|---|---|---|
| F0: instrument E2 and teacher data | Implemented; 1,000-row campaign complete | `tmp/eloi-native-f0-teacher-1000`; dataset SHA-256 `CCFCF806055EE18AF5B38A2B95D17608EF30E3658F3E59E815E4F2A96CD175A8` |
| F1: modern single-thread E2 | Laboratory path implemented; mechanical suites pass | `--brain eloi-single`; no helper lanes; full configured TT belongs to the single lane |
| F2: policy/value network | Implemented and root-order integrated in the lab | Python/C++ parity max error `5.94e-08`; model remains unqualified |
| F3: conservative selectivity | Mechanisms screened independently | no-null combination passes; full stack repeats the knight-hang regression |
| F4: restore three-thread Eloi | Implemented and tactically green | three-lane policy candidate passes core and humiliation EPDs |
| F5: challenge Caissa-era Eloi | Completed and rejected | 0W/0D/20L at 20,000 nodes per move against frozen v3.1.1 |

## F0 dataset semantics

`scripts/build_eloi_teacher_dataset.py` deterministically selects nonterminal
Standard positions from the canonical evaluation corpus. Source group and
partition identities are preserved. If a source lacks a partition, its group
is assigned deterministically to 80% train, 10% validation, or 10% test.

For every root the collector records:

- canonical FEN, source/group identity, and sealed partition;
- E2's one-thread best move and Caissa's three-thread best move;
- a bounded candidate set that always contains both choices;
- independent Caissa child scores for each candidate;
- a normalized candidate-policy target and W/D/L value target;
- a tactical weight when E2 disagrees and trails the best rescored move by at
  least 150 centipawns;
- executable, source, network, runner, and dataset hashes.

The collector is append-only, collision-refusing, quota-checked, incremental,
and resumable only when its frozen protocol is byte-for-byte identical.
Teacher and E2 searches are sequential and run at Windows Idle priority.

## F1 and F4 concurrency contract

`SearchConcurrency::single_thread_lab` creates no root helpers and gives its
single coherent search the full configured transposition table. The default
constructor remains `production_three_threads`: one principal lane plus two
helpers with private TT shards sharing the configured Hash budget as 1/2,
1/4, and 1/4. Production callers were not changed.

This separation lets search correctness be repaired without SMP noise, then
restores parallelism as its own measured F4 change.

## F2 model

`scripts/train_eloi_policy_value.py` trains a compact dual-head network:

- 781 side-to-move-oriented Standard-chess inputs;
- one shared 64-unit hidden layer;
- W/D/L value head;
- legal-candidate policy head factorized by source square, destination square,
  promotion, and moving piece;
- tactical disagreement weighting;
- deterministic initialization and shuffling;
- best-validation checkpoint selection;
- custom `EPV1` artifact with no pickle or executable payload.

The first substantive model selected epoch 17. Its validation policy top-1 was
`0.2105263158`; policy cross-entropy was `1.9271882080`; value cross-entropy
was `1.0251705226`. Model SHA-256 is
`EC9A8423F7BAB5689235E5926BF4249AADC9ED7BF5040A3ED88F9A62848B55F9`.
Those numbers are preliminary: 1,000 roots are enough to prove the pipeline,
not enough to establish a strong chess model. The test partition was not
opened.

The model must not steer production or enter a package: although inference
parity, root-order integration, and tactical gates passed, its F5 strength gate
failed decisively.

## F3 isolation

Existing selective-search mechanisms are individually maskable in the lab:
reverse futility, razoring, internal reduction, null move, ProbCut, frontier
futility, late-move pruning, and late-move reduction. `full_width` still
disables all selectivity. The production default mask enables the exact
pre-campaign set, so adding the laboratory switch does not alter production
decisions.

Selection must start with full-width F1, add one mechanism at a time, and keep
only changes that improve work without adding a tactical or stability failure.
No pruning threshold should be tuned against the sealed test set.

## Gate disposition

1. C++ `EPV1` loader and Python parity: passed.
2. One-thread root-policy integration with alpha-beta authority: passed.
3. Core plus humiliation tactical suites: passed for F1/F2.
4. Per-mechanism F3 screen: completed; combined full stack rejected.
5. Conservative no-null F3 combination: passed tactical gates.
6. Three-thread F4 restoration: passed tactical gates.
7. F5 mirrored screen: failed 0W/0D/20L; candidate rejected.

## F2–F5 qualification result

The strict C++ loader fails closed on malformed artifacts. Python/C++ inference
parity passed across opening, middlegame, and endgame positions with maximum
absolute difference `5.94e-08` at tolerance `2e-06`. The model was attached
only as a root-order prior; alpha-beta remained authoritative.

Every selectivity mechanism passed alone, but the full combination repeated
`online-bIw09dp9-knight-hang` by playing forbidden `c6e5`. Removing null-move
pruning produced the fastest conservative passing ablation and passed both the
15-position core suite and the humiliation suite after restoring three lanes.

That F4 candidate then played a 20-game mirrored F5 screen at 20,000 nodes per
move against frozen v3.1.1 and scored **0W/0D/20L (0.0%)** with no reported
protocol failures. It is rejected. Production remains unchanged.

The next model must use far more teacher positions and a policy head capable of
move interactions. No further gauntlet is justified for candidate 1.

Until step 7 succeeds, Caissa-era Eloi remains the champion and production is
unchanged.
