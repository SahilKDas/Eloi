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
| F2: policy/value network | Trainer and first model implemented; not search-integrated | 800 train, 95 validation, 105 sealed test; candidate under `tmp/eloi-native-f2-candidate2` |
| F3: conservative selectivity | Mechanism isolation implemented; no new pruning | `--selectivity none|all|reverse-futility,razoring,internal-reduction,null-move,probcut,futility,lmp,lmr` |
| F4: restore three-thread Eloi | Structural mode exists and is tested | production Searcher owns exactly three lanes with private TT shards |
| F5: challenge Caissa-era Eloi | Blocked by design | requires an F2 model integrated into F1, per-mechanism F3 selection, and tactical qualification |

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

The model must not steer production or enter a package until native C++
inference parity, root-order integration, tactical gates, and strength gates
all pass.

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

## Required next gates

1. Implement a strict C++ `EPV1` loader and prove Python/C++ inference parity.
2. Integrate policy only as a root/move-order prior in the one-thread lab;
   retain alpha-beta as the authority over the final score and move.
3. Expand F0 with game-balanced positions and tactical refutations while
   staying under device quotas; keep the existing 105 test roots sealed.
4. Run the complete EPD and humiliation suites on full-width F1+F2.
5. Screen each F3 mechanism independently at equal nodes, then validate the
   retained combination.
6. Restore F4 three-thread search and re-run determinism-distribution, deadline,
   legality, and tactical gates.
7. Only then run F5 mirrored games against frozen v3.1.1/Caissa-era Eloi.

Until step 7 succeeds, Caissa-era Eloi remains the champion and production is
unchanged.
