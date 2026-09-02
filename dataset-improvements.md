# Eloi NNUE Dataset Improvement Plan

Status: design and validation specification  
Repository baseline reviewed: `main` at `60edcec`  
Source version reviewed: `2.5.0-rc.1`  
Document created: 2026-09-01  
Scope: dataset acquisition, curation, splitting, training inputs, offline metrics,
engine validation, reproducibility, and resource safety

Implementation checkpoint: Stage 1 completed at
c4a9fd1e8face1e96335d464c8673851eb2db082. The analysis-only sampler,
fixture tests, exact retained-input report, and independent byte-for-byte
reproduction are recorded in scripts/analyze_nnue_dataset.py,
scripts/test_analyze_nnue_dataset.py, data/nnue_dataset_analysis.json, and
data/nnue_dataset_analysis_reproduction.json. Production NNUE files were not
changed.

## 1. Purpose

This document defines a practical, reproducible plan for improving the data used
to train Eloi's embedded NNUE evaluation network. It records the current
baseline, identifies the most likely data limitations, proposes a successor
dataset pipeline, and specifies the evidence required before a newly trained
network may replace the production network.

The central conclusion is:

> Eloi should improve the representativeness, label quality, split isolation,
> tactical negatives, and validation coverage of its dataset before increasing
> the production network beyond 64 hidden units.

This is a proposal, not a claim that a larger or better-curated dataset will
automatically increase playing strength. Offline metrics are diagnostic. Only a
correctness-gated, reproducible, paired engine comparison can establish that a
candidate is better for Eloi.

## 2. Executive summary

Eloi's current NNUE pipeline is unusually well documented for its size. It has
pinned upstream identities, bounded acquisition, deterministic splitting,
reproducible training, candidate hashes, compile-safe generated headers, and an
engine-level architecture playoff. Those are strong foundations and should be
preserved.

The present corpus is nevertheless a pilot corpus:

- it retains the first 20,000 complete records from the first 16 MiB of each
  upstream zstd archive;
- it trains on 12,000 Stockfish-evaluated positions and 12,000 puzzle pairs;
- its validation sets contain 1,958 evaluation positions and 1,963 puzzle
  pairs;
- each puzzle produces one correct move versus one randomly selected legal
  alternative;
- evaluation targets combine centipawn and mate labels by mapping mate to
  `+/-1500` centipawns and clipping centipawn labels to the same range;
- validation measures floating-point centipawn MAE and one-alternative tactical
  ranking accuracy;
- the training and validation records originate from the same two small archive
  prefixes.

The current 128-unit candidate did not exploit its additional capacity. It was
slightly worse than the 64-unit network on both recorded offline metrics and
scored only 43.64% in the shortened 110-game architecture playoff. That result
does not prove the 64-unit architecture is universally superior. It does show
that increasing width on the current data and objective did not help.

The recommended next experiment is therefore a **data-only 64-unit candidate**:

1. keep the production 64-unit architecture and runtime feature encoding;
2. replace prefix-only input selection with deterministic sampling across a
   much broader portion of the source population;
3. filter or weight evaluation records by label confidence;
4. stratify by position phase, material, score band, and tactical character;
5. use hard and multiple puzzle alternatives instead of one random negative;
6. isolate complete games or stable source identities across train, validation,
   and test partitions;
7. evaluate the quantized deployed network, not only the pre-quantized model;
8. pass Eloi's existing correctness, speed, reproducibility, and paired-match
   gates before installation.

Only after that experiment should 128- or 256-unit candidates be reconsidered.

## 3. Scope and non-goals

### 3.1 In scope

This plan covers:

- official source identity and licensing;
- bounded acquisition under the local device contract;
- canonical record formats;
- input validation and corruption handling;
- position and game deduplication;
- train, validation, and test isolation;
- deterministic sampling and stratification;
- evaluation-label quality controls;
- tactical-pair construction and hard-negative selection;
- quiet-position and endgame coverage;
- training-objective recommendations;
- quantization-aware validation;
- offline and engine-level acceptance gates;
- reproducibility manifests and retained evidence;
- storage, CPU, process, and active-Lichess protections.

### 3.2 Not in scope

This document does not authorize or implement:

- downloading a complete 21.7 GB archive onto the development laptop;
- relaxing `constraints_on_SahilKDas_device.md`;
- changing Eloi's production search-thread contract;
- replacing RootSplit with LazySMP;
- changing NNUE runtime features or hidden width in the first experiment;
- introducing GPU-only build or runtime dependencies;
- packaging training data with Eloi;
- committing upstream Lichess records to Git;
- treating an offline metric improvement as a release decision;
- deleting the current production network or its provenance;
- deleting historical validation evidence.

Architecture, feature, and optimizer changes are valid future experiments, but
they must be separated from the first dataset experiment so the result remains
interpretable.

## 4. Binding references

Any implementation of this plan must remain consistent with these tracked
sources:

- `constraints_on_SahilKDas_device.md`: binding local resource and process
  contract;
- `DATA_SOURCES.md`: current source, license, and embedded-data documentation;
- `scripts/acquire_nnue_samples.py`: current bounded prefix acquisition;
- `scripts/train_nnue.py`: current split, objective, validation, and
  quantization behavior;
- `data/nnue_input_manifest.json`: current exact input identities;
- `data/nnue_training_comparison.json`: current 64/128 offline comparison;
- `data/nnue_candidate_builds.json`: build and correctness evidence;
- `data/nnue_architecture_playoff.json`: engine-level architecture decision;
- `data/nnue_provenance.json`: selected production-network provenance;
- `V1.9_VALIDATION_PLAN.md`: completed architecture-selection process and
  recorded amendments;
- `README.md`: current release and validation summary.

If this plan conflicts with the binding device constraints, the device
constraints win. If source formats or upstream identities change, acquisition
must stop until the change is reviewed and recorded deliberately.

## 5. Current production baseline

### 5.1 Network and runtime

The production network uses:

- 64 hidden units;
- 8 king buckets;
- 12 piece-and-color planes;
- 64 squares per plane;
- 6,144 sparse input features;
- separate white and black accumulators;
- clipped activations;
- quantized generated weights embedded in the executable;
- no runtime download or training dependency.

The input representation is compact and fast, but intentionally limited. It
does not directly encode every chess-state property or search context. Dataset
quality cannot teach information that the feature representation never exposes.
For the first experiment, however, keeping features fixed is essential: it
isolates whether better supervision improves the existing evaluator.

### 5.2 Current source inputs

The recorded source archives are the official Lichess evaluation and puzzle
exports dated 2026-08-02, made available under CC0 1.0.

| Source | Upstream compressed size | Retained rows | Retained bytes |
| --- | ---: | ---: | ---: |
| Evaluations | 21,681,515,630 | 20,000 | 12,770,131 |
| Puzzles | 304,384,407 | 20,000 | 3,702,406 |

For each source, acquisition currently downloads bytes `0-16777215`, verifies
the upstream size and HTTP identity metadata, decompresses from the beginning
of the zstd stream, retains the first 20,000 complete records, hashes the
compressed prefix and retained sample, and removes the compressed prefix.

This method is bounded and reproducible. Its main statistical limitation is
that **reproducibility of a prefix is not representativeness of the archive**.

### 5.3 Current train and validation counts

| Partition content | Count |
| --- | ---: |
| Training evaluation positions | 12,000 |
| Training tactical pairs | 12,000 |
| Validation evaluation positions | 1,958 |
| Validation tactical pairs | 1,963 |

The split uses a stable source identity and a deterministic 10% hash decision.
Reservoir sampling then applies the configured per-split limits. This is better
than a simple random in-memory split, but its isolation is limited by the source
identifiers available in each archive.

### 5.4 Current target construction

For evaluation records, the trainer:

1. chooses the evaluation entry with greatest reported depth;
2. uses its first principal variation;
3. clips centipawn values to `[-1500, 1500]`;
4. maps mate labels to `-1500` or `+1500`;
5. converts the target to White's perspective;
6. trains for two evaluation epochs with error clipped to `[-200, 200]`.

For puzzle records, the trainer:

1. applies the puzzle setup move;
2. reads the expected best reply;
3. enumerates the other legal replies;
4. chooses one alternative with a deterministic pseudorandom generator;
5. creates one best-versus-alternative pair;
6. trains a ranking margin of 35 for three epochs.

The current validation metrics are:

- mean absolute centipawn error on evaluation records;
- fraction of puzzle pairs for which the best move's resulting position ranks
  above the one selected alternative.

### 5.5 Current recorded outcomes

| Hidden units | Evaluation MAE | Tactical pair accuracy |
| ---: | ---: | ---: |
| 64 | 470.8469 cp | 80.6419% |
| 128 | 473.9278 cp | 80.3872% |

The 128-unit candidate then scored:

- 31 wins;
- 34 draws;
- 45 losses;
- 43.64% score;
- an estimated `-44.46` Elo relative to the 64-unit baseline.

The experiment was originally planned for 250 games and was shortened after it
started, first to 100 and then to 110. The outcome is useful directional
evidence and correctly selected 64 under the recorded thresholds, but it should
not be presented as a high-precision Elo estimate.

## 6. Measured profile of the retained local samples

The following descriptive measurements were computed read-only from the exact
ignored local files whose SHA-256 hashes match `data/nnue_input_manifest.json`.
They are observations about the retained 20,000-row samples, not claims about
the complete upstream archives.

### 6.1 Evaluation sample

| Measurement | Value |
| --- | ---: |
| Rows | 20,000 |
| Unique full FENs | 20,000 |
| Duplicate full-FEN rows | 0 |
| Unique piece placements | 19,944 |
| White to move | 10,524 |
| Black to move | 9,476 |
| Mean piece count | 21.07 |
| Positions with 10 or fewer pieces | 4,430 |
| Positions with 11-20 pieces | 3,276 |
| Positions with 21 or more pieces | 12,294 |
| Minimum selected depth | 1 |
| Median selected depth | 33 |
| Mean selected depth | 56.10 |
| Maximum selected depth | 245 |
| Median reported knodes | 29,667 |
| Centipawn targets | 16,060 |
| Mate targets | 3,940 |
| Exact zero-centipawn targets | 2,189 |
| Centipawn targets outside `+/-1500` | 162 |
| Median absolute centipawn target | 46 |

The first 2,000 evaluation records have mean selected depth 62.87; the last
2,000 have mean depth 53.76. This alone does not prove archive-order bias, but it
demonstrates that record quality is not uniform even inside the small prefix.

The sample has useful properties: no exact-FEN duplicates, near-balanced side
to move, and meaningful endgame coverage. Its central concerns are the very
wide depth range and the large mate-label share. A depth-1 label and a
depth-245 label should not automatically have identical authority.

### 6.2 Puzzle sample

| Measurement | Value |
| --- | ---: |
| Rows | 20,000 |
| Unique full FENs | 20,000 |
| Duplicate full-FEN rows | 0 |
| Unique game identifiers | 20,000 |
| Duplicate game rows | 0 |
| White to move in source FEN | 9,682 |
| Black to move in source FEN | 10,318 |
| Mean piece count | 18.63 |
| Positions with 10 or fewer pieces | 2,167 |
| Positions with 11-20 pieces | 9,946 |
| Positions with 21 or more pieces | 7,887 |
| Minimum rating | 399 |
| Median rating | 1,408 |
| Mean rating | 1,466.70 |
| Maximum rating | 3,188 |

The first 2,000 puzzle ratings average 1,456.95; the last 2,000 average
1,449.74. The small difference is reassuring, but rating balance alone does not
establish tactical or positional representativeness.

The most frequent source themes include `short`, `endgame`, `middlegame`,
`crushing`, `mate`, `advantage`, `long`, `oneMove`, `mateIn1`, `master`,
`mateIn2`, and `fork`. The current trainer records themes but does not use them
to stratify sampling or weight training.

### 6.3 Interpretation boundaries

These measurements must not be over-interpreted:

- piece count is only a rough phase proxy;
- puzzle source FEN side-to-move precedes application of the setup move;
- reported depth is not directly comparable across every engine configuration;
- `knodes` can be absent or reflect different search circumstances;
- no exact duplicate does not rule out near-duplicates or multiple positions
  from the same game;
- puzzle rating is a human-solve statistic, not a direct engine-label confidence
  score;
- archive order may have undocumented structure.

## 7. Principal weaknesses to address

### 7.1 Prefix-only population coverage

The current retained sample comes from the beginning of each compressed stream.
It does not sample the complete archive population. Even if upstream rows were
originally shuffled, Eloi currently has no recorded proof that the prefix is
representative by date, rating, phase, opening, result, evaluation magnitude,
or tactical theme.

### 7.2 Unequal evaluation-label confidence

Evaluation depth spans 1 through 245. Treating all selected labels equally
allows shallow or unusual records to contribute the same nominal sample weight
as deeply evaluated positions.

Depth alone is not perfect, so the pipeline should combine available confidence
signals rather than blindly maximizing a single field. At minimum, depth,
knodes, principal-variation presence, score validity, and legal-PV validation
should be recorded.

### 7.3 Mate and clipping saturation

Mapping every mate target to exactly `+/-1500` discards mate distance and groups
many qualitatively different positions at the same endpoint. Clipping large
centipawn values introduces a second source of endpoint saturation.

This can be acceptable for a compact evaluator whose search handles mating
logic, but the saturated records should be measured, stratified, and possibly
weighted. They should not silently dominate a metric reported as centipawn MAE.

### 7.4 Weak tactical negatives

A uniformly random legal alternative is often obviously bad. Ranking the puzzle
move above that alternative can inflate validation accuracy without proving the
network distinguishes the best move from plausible competitors.

The alternatives that matter most are moves Eloi or a reference search would
actually consider: captures, checks, promotions, high-history quiet moves,
near-equal engine candidates, and known Eloi regression moves.

### 7.5 Narrow validation semantics

The current tactical metric asks one binary question per puzzle. The current
evaluation metric mixes ordinary centipawn labels and saturated mate labels in
one aggregate MAE. Neither metric is currently broken down by phase, score band,
depth, theme, or quantization state.

An aggregate can improve while a critical subgroup regresses. For example, a
candidate may lower middlegame MAE while worsening low-material endgames or
known tactical failures.

### 7.6 Potential partition leakage

The evaluation loader falls back to piece placement when no game/source/id
field exists. This keeps exact positions stable across partitions, but it does
not prevent neighboring positions from the same game—or transformed equivalents
of a position—from crossing partitions.

Puzzle IDs isolate puzzle rows, but they do not automatically isolate every
position from the underlying game if another source contains the same game.

### 7.7 Float-only candidate metrics

The recorded validation metrics are computed from the training arrays before
the generated representation is compiled into the engine. Quantization and
runtime arithmetic can change output ordering or error. Candidate selection
should include metrics from the exact quantized representation installed in a
test executable.

### 7.8 Capacity experiments confound the question

The 64/128 comparison changed architecture width while holding the current data
pipeline constant. A future data experiment should first hold width constant.
Otherwise, a result cannot distinguish data quality from model capacity,
regularization, quantization pressure, or optimizer behavior.

## 8. Improvement hypotheses, in priority order

The following are hypotheses to test, not assumptions to encode as conclusions.

### H1: Representative coverage beats prefix-only coverage

A 64-unit candidate trained on a deterministic, archive-wide or broadly
distributed sample will generalize better than one trained on the initial
prefix, even at a similar retained row count.

### H2: Confidence-aware labels beat unweighted mixed-depth labels

Filtering the weakest labels and weighting the remaining labels by bounded
confidence will improve held-out error and engine strength.

### H3: Hard negatives beat random legal negatives

Puzzle ranking against several plausible alternatives will produce a more
useful tactical signal than ranking against one uniformly random legal move.

### H4: Independent game-level test data exposes overfitting

An untouched test partition grouped by game/source will provide a more honest
estimate than validation records drawn from the same retained prefixes.

### H5: Quantized metrics predict integration risk better than float metrics

Evaluating the exact generated integer network will catch ranking flips and
score distortion that pre-quantization metrics miss.

### H6: Better data may unlock wider models later

Once a stronger corpus and objective exist, 128 units may become useful. The
current loss by the 128-unit candidate should not permanently prohibit wider
models; it should prohibit assuming width alone is the solution.

## 9. Required invariants

Every successor pipeline must preserve these properties:

1. **Determinism:** identical pinned inputs, code, parameters, and environment
   produce byte-identical retained datasets and candidate headers where the
   existing platform guarantees this.
2. **Bounded storage:** the implementation refuses writes that could exceed the
   local nested 8 GB NNUE cap, the current stricter 7 GiB trainer cap, or the
   total 10 GB temporary-project cap.
3. **No runtime dependency:** Eloi continues to embed the selected network and
   never downloads training data while running.
4. **License clarity:** every source and derived artifact has recorded license
   and attribution information.
5. **Stable identity:** upstream URL, size, ETag, Last-Modified, hashes, sampler
   version, and parameters are recorded.
6. **Split isolation:** train, validation, and test membership is deterministic
   and grouped by the strongest available source identity.
7. **No silent corruption:** malformed records, illegal FENs, illegal PV moves,
   and invalid puzzle moves are counted and rejected with reason codes.
8. **Report-only default:** experiments do not overwrite production headers
   until selection and explicit installation stages.
9. **Correctness before strength:** candidates that fail deterministic engine
   gates do not enter a gauntlet.
10. **One major variable at a time:** the first experiment changes data and
    objective construction while preserving the 64-unit runtime architecture.
11. **Immutable evidence:** manifests and final reports bind hashes for every
    retained input, generated candidate, executable, suite, and match record.
12. **No post-result threshold changes:** match length and selection thresholds
    are frozen before the first game.

## 10. Proposed dataset pipeline

The proposed pipeline has eight explicit stages:

```text
pinned upstream archives
        |
        v
bounded stream acquisition
        |
        v
schema and legality validation
        |
        v
canonical records + stable group identities
        |
        v
deduplication and deterministic partitioning
        |
        v
stratified reservoir selection
        |
        v
training examples and hard negatives
        |
        v
float + quantized + engine validation
```

Each stage must emit counts and hashes. A rejected record must disappear for a
documented reason, not because of an unreported exception.

## 11. Acquisition strategy

### 11.1 Why arbitrary compressed byte ranges are unsafe

The current zstd archives are decompressed from byte zero. An arbitrary HTTP
range from the middle of a normal zstd stream is not generally independently
decompressible. Therefore, “download several random 16 MiB compressed ranges”
must not be implemented unless the upstream format is verified as seekable or
frame boundaries and dictionaries are handled correctly.

Range requests remain useful for bounded prefix acquisition and identity
verification, but they are not by themselves an archive-wide sampler.

### 11.2 Preferred method: one bounded sequential streaming pass

The preferred archive-wide method is:

1. verify the pinned HTTP identity before reading the body;
2. stream compressed bytes directly into a zstd decompressor;
3. parse records incrementally without retaining the compressed archive;
4. validate and summarize each record;
5. place eligible records into deterministic stratified reservoirs;
6. enforce strict reservoir and output byte caps;
7. stop at a predeclared compressed-byte, record-count, or time budget if a full
   pass is infeasible;
8. write only the selected canonical records and a manifest.

This avoids storing 21.7 GB locally, but a full pass still transfers and
decompresses the archive. On the development laptop, it must be treated as a
resource-heavy task with explicit permission, time bounds, storage preflight,
and no concurrent heavy Eloi workload.

### 11.3 Preferred operational location

If available, archive-wide sample generation should occur on a machine with
more free storage, sustained cooling, and no active Eloi bridge. The generated
sample can then be transferred to the development laptop together with:

- the exact sampler revision;
- upstream HTTP identities;
- a complete parameter file;
- selected-record hashes;
- per-stratum counts;
- rejection counts;
- a whole-sample SHA-256;
- an independent reproduction command.

The development laptop must verify all hashes before training.

### 11.4 Bounded fallback method

If only the development laptop is available, use a declared sequential budget,
for example a maximum compressed-byte count or maximum parsed-record count.
The run should still use reservoir sampling over the entire portion traversed,
not retain its first eligible records.

The fallback is broader than the current 16 MiB prefix but is not equivalent to
a complete archive-wide sample. Its manifest must describe the traversed prefix
and must not label the result “archive-wide.”

### 11.5 Acquisition must fail closed

The sampler must refuse to continue when:

- the upstream size, ETag, or Last-Modified differs from the pin;
- the server ignores an expected bounded response;
- decompression reports corruption;
- projected temporary usage exceeds a cap;
- the destination already contains an unrecognized file;
- output hashes cannot be computed;
- required schema fields disappear;
- a requested stratum cannot be represented without silently changing quotas.

## 12. Canonical record design

Raw upstream records should be converted into compact canonical JSONL or another
explicitly versioned format before training. Training code should not need to
reinterpret changing upstream schemas.

### 12.1 Canonical evaluation record

Recommended logical fields:

```json
{
  "schema": 2,
  "source": "lichess-evaluations-2026-08-02",
  "source_record_id": "stable-id-or-null",
  "group_id": "sha256-derived-game-or-source-group",
  "position_key": "normalized-position-hash",
  "fen": "canonical six-field FEN",
  "side_to_move": "w",
  "score_type": "cp",
  "score_white_cp": 34,
  "mate_distance": null,
  "depth": 33,
  "knodes": 29667,
  "pv": ["e2e4", "e7e5"],
  "piece_count": 30,
  "phase_bucket": "opening",
  "score_bucket": "near-equal",
  "confidence_bucket": "high",
  "partition": "train"
}
```

The physical format may use shorter field names or a binary representation for
size, but a schema document must define identical semantics.

### 12.2 Canonical puzzle record

Recommended logical fields:

```json
{
  "schema": 2,
  "source": "lichess-puzzles-2026-08-02",
  "puzzle_id": "00008",
  "game_id": "787zsVup",
  "group_id": "game:787zsVup",
  "source_fen": "...",
  "decision_fen": "...",
  "setup_move": "f2g3",
  "best_move": "e6e7",
  "continuation": ["b2b1", "b3c1", "b1c1", "h6c1"],
  "rating": 1939,
  "themes": ["crushing", "hangingPiece", "long", "middlegame"],
  "hard_alternatives": ["e6e8", "e6e5", "h6h3"],
  "piece_count": 23,
  "phase_bucket": "middlegame",
  "partition": "train"
}
```

The decision FEN after the setup move must be stored or reproducibly verified so
that every candidate compares moves at the intended decision point.

### 12.3 Canonicalization rules

Canonicalization should include:

- expand four-field FENs to six fields with documented defaults;
- validate exactly one side to move;
- reject impossible king counts for standard-chess records;
- normalize castling-right ordering;
- normalize en-passant representation according to a declared rule;
- preserve halfmove/fullmove fields in the stored FEN;
- compute a separate position key with explicitly selected fields;
- verify every stored move is legal in sequence;
- convert scores to a single declared perspective;
- retain original score type and mate distance rather than immediately
  collapsing everything to centipawns;
- normalize text encoding and newlines before hashing.

## 13. Identity, deduplication, and leakage prevention

### 13.1 Three different identities are required

The pipeline should distinguish:

1. **Record identity:** the exact upstream row or logical source record.
2. **Position identity:** the canonical chess state used to detect exact or
   functionally equivalent positions.
3. **Group identity:** a game, analysis source, or other unit that must remain in
   one partition.

Using one hash for all three purposes is insufficient.

### 13.2 Position-key policy

At minimum, retain two position hashes:

- `full_state_key`: board, side, castling rights, legal en-passant state,
  halfmove clock, and other fields relevant to the evaluator or rules;
- `learning_state_key`: board, side, castling rights, and en-passant state,
  excluding move counters when they do not affect current NNUE features.

Exact duplicate training examples should be collapsed or explicitly weighted.
Near-duplicates from adjacent plies should be grouped by game, not treated as
independent evidence across partitions.

### 13.3 Group-first splitting

Partition assignment must happen before row-level reservoir sampling:

```text
group_id -> deterministic hash -> train / validation / test
```

Every row with the same group ID must receive the same partition. Preferred
group IDs are, in order:

1. verified game ID;
2. verified source-analysis ID;
3. puzzle game ID;
4. upstream record ID;
5. conservative derived cluster identity;
6. position identity only as a last resort.

If evaluation records lack game identity, this limitation must be recorded and
the test set should preferably come from a separately pinned source or date.

### 13.4 Cross-source overlap

The same decision position may occur in both evaluation and puzzle sources.
Before partitioning is finalized, cross-source position hashes should be
checked. If a position appears in multiple sources, all copies must share a
group or be assigned according to the strictest partition membership.

The test partition must never be allowed to leak into training through another
source.

## 14. Partition design

### 14.1 Recommended partitions

Use three partitions:

- **training:** optimizer updates only;
- **validation:** model and objective selection only;
- **test:** final offline report only, opened after the candidate recipe is
  frozen.

A reasonable initial target is 80% train, 10% validation, and 10% test by group,
subject to stratum minimums. Exact percentages should be parameters, not hidden
constants.

### 14.2 Independent test preference

The strongest test set comes from a separately pinned date or source not used
for training. If that is unavailable, use a game-grouped hash split and report
the weaker independence explicitly.

The test report should be generated once per frozen candidate family. Repeated
inspection of test results turns the test set into another validation set.

### 14.3 Split balance checks

Before training, emit per-partition counts for:

- source;
- side to move;
- phase bucket;
- piece-count bucket;
- score bucket;
- mate versus centipawn;
- confidence bucket;
- puzzle rating bucket;
- puzzle theme;
- legal move count;
- best-move tactical class;
- hard-negative count.

No partition should silently lose a rare but important stratum.

## 15. Stratified sampling

### 15.1 Why stratification is needed

A uniform reservoir reflects source frequency. That is useful for matching the
source distribution, but a chess evaluator also needs reliable coverage of
critical sparse regions: quiet equal positions, low-material endings, promotion
races, castling transitions, trapped pieces, and tactical near-misses.

The solution is not arbitrary balancing. The sampler should retain both:

- a population-like component representing natural frequency;
- a coverage component guaranteeing minimum counts for important strata.

### 15.2 Proposed evaluation strata

Evaluation records should be stratified by a compact cross-product of:

- phase: opening, middlegame, endgame, low-material ending;
- side to move: White or Black;
- score type: centipawn or mate;
- absolute score: `0-25`, `26-75`, `76-200`, `201-500`, `501-1500`, saturated;
- confidence: rejected, low, medium, high;
- tactical surface: in check, legal capture available, promotion available, or
  quiet;
- castling state: both, one side, none, or already castled when inferable;
- pawn count and major/minor material class.

The full cross-product would be too sparse. The implementation should use
separate marginal quotas or a deliberately reduced set of combined strata.

### 15.3 Proposed puzzle strata

Puzzle records should be stratified by:

- rating bands such as `<1000`, `1000-1499`, `1500-1999`, `2000-2499`, and
  `2500+`;
- phase;
- mate versus non-mate;
- short versus long continuation;
- tactical theme family;
- legal move count;
- number of generated hard alternatives;
- best-move class: capture, check, promotion, castle, or quiet;
- whether Eloi's baseline finds the move under the fixed tactical-search budget.

### 15.4 Deterministic reservoirs

Each reservoir must have:

- a stable name;
- a declared capacity;
- a deterministic seed derived from the global seed and reservoir name;
- seen, accepted, replaced, and rejected counters;
- a final canonical ordering before hashing;
- a minimum-fill warning;
- a byte-budget contribution.

Avoid relying on Python dictionary iteration or process-specific hash behavior
for reproducibility.

## 16. Evaluation-label quality

### 16.1 Minimum validity filters

Reject an evaluation record when:

- the FEN is invalid or incompatible with the declared variant;
- no evaluation entries exist;
- no principal variation exists;
- the first PV move is illegal;
- score type or numeric value is malformed;
- depth is missing or outside a deliberately accepted range;
- reported values overflow expected bounds;
- canonicalization changes the position ambiguously.

Every reason requires a separate counter.

### 16.2 Confidence policy

Do not use unbounded depth or knode values directly as sample weights. A robust
policy could assign confidence buckets from conservative thresholds, then use
small bounded weights such as 0.5, 1.0, and 1.5.

Candidate policies should be compared offline. Example dimensions:

- minimum depth;
- minimum knodes when present;
- agreement between multiple evaluation entries;
- stability of the top PV score across depth;
- whether the record is a mate label;
- whether the principal variation is legal for several plies.

The manifest must state the exact formula and thresholds.

### 16.3 Mate handling

At least three policies should be considered:

1. retain the current `+/-1500` mapping but report mate records separately;
2. map mate distance to a bounded monotonic scale while preserving sign;
3. exclude mate records from centipawn regression and use a separate ordering
   or classification term.

The first data-only pilot may preserve the production score convention while
changing only sampling and weights. More ambitious target changes should be a
separate experiment.

### 16.4 Score transformation

Raw centipawn regression overweights already-decided positions and does not map
linearly to game outcome. Candidate transformations include:

- current clipped centipawns;
- smoothly compressed centipawns, such as a bounded `tanh` transform;
- WDL expectation derived from centipawns and phase;
- mixed centipawn and pairwise ranking objectives.

Any transformation changes score calibration and must be validated against
Eloi's search behavior. The production evaluator's output scale affects pruning,
aspiration windows, and search decisions; calibration drift is not merely a UI
issue.

### 16.5 Label disagreement diagnostics

Where a record has multiple evaluation entries, record:

- deepest score;
- second-deepest score;
- score delta;
- best-move agreement;
- mate/centipawn disagreement;
- PV legality.

High disagreement can be rejected, down-weighted, or placed in a diagnostic
slice. It should not be silently treated as high-confidence truth.

## 17. Puzzle and hard-negative construction

### 17.1 Decision-point correctness

The setup move must be legal and applied before selecting the best reply.
Training features must represent the resulting decision position. Validation
should independently replay the complete stored move sequence.

### 17.2 Negative tiers

Generate alternatives in tiers:

1. **Reference hard negatives:** legal alternatives close to the best move under
   a fixed reference search.
2. **Eloi hard negatives:** moves Eloi's production baseline ranks highly or
   actually chooses under a fixed budget.
3. **Forcing negatives:** other checks, captures, and promotions.
4. **Structured quiet negatives:** legal quiet moves with strong move-ordering
   signals.
5. **Random negatives:** deterministic fallback only.

The first available tier should not suppress all others. A mix of two to four
alternatives per puzzle is a reasonable starting point, bounded by storage and
training cost.

### 17.3 Avoid trivial inflation

Report accuracy by negative tier. A candidate that scores 95% against random
moves but 55% against reference hard negatives has not achieved 95% tactical
accuracy in a meaningful sense.

Recommended metrics include:

- top-1 best-move ranking across all stored alternatives;
- pairwise accuracy by tier;
- mean best-move margin;
- fraction satisfying the training margin;
- accuracy by puzzle theme and rating;
- baseline-found versus baseline-missed slices.

### 17.4 Avoid tactical-only distortion

Puzzle records are selected because a tactic exists. Overweighting them can make
the static evaluator volatile or sacrifice quiet positional judgment. Keep the
evaluation corpus as the primary calibration signal and treat puzzles as a
bounded ranking component.

The evaluation-to-ranking update ratio must be a recorded parameter and tested,
not inferred from loop order alone.

## 18. Quiet positions and endgames

### 18.1 Quiet-position coverage

The successor corpus should guarantee coverage of positions where:

- no side is in check;
- no immediate capture or promotion dominates;
- the score is near equal;
- several legal quiet moves are plausible;
- positional factors, not a short tactic, distinguish choices.

Quiet positions help prevent an evaluator trained heavily on puzzles from
learning only tactical aftermath.

### 18.2 Endgame coverage

The current sample includes substantial low-material content, which should be
preserved. Report at least:

- piece count;
- pawn count;
- queen presence;
- rook-only, minor-only, and mixed endings;
- opposite-colored and same-colored bishop endings;
- promotion availability;
- bare-king or Horde-specific conditions only when the variant is explicitly
  supported by the dataset.

Tablebase labels can be valuable for eligible positions, but they introduce a
new source and objective. If used, tablebase identity, probe semantics, DTZ/WDL
mapping, and rule-50 treatment require their own provenance and experiment.

## 19. Variant policy

Eloi supports Standard, Chess960, and Horde, while the current training sources
and feature assumptions are primarily standard-chess oriented.

The first improved dataset should remain explicitly **Standard-only** unless a
source record has trustworthy variant identity and the trainer has variant-
correct legality and target semantics.

Do not mix variant records into one corpus merely because their FEN parses.
Chess960 castling states and Horde king rules require variant-aware validation.
Future variant-specific datasets should have separate strata, metrics, and
engine matches. Production installation must consider whether one shared
network or separate variant networks are appropriate.

## 20. Training objective recommendations

### 20.1 First experiment: conservative objective

For the first data-focused candidate:

- keep 64 hidden units;
- keep the current feature encoding;
- keep the runtime output scale;
- keep the same quantized data types;
- preserve the broad evaluation-plus-ranking structure;
- introduce better sampling, confidence handling, hard negatives, and split
  isolation;
- avoid optimizer changes unless required for numerical stability.

This provides the cleanest comparison with production.

### 20.2 Loss reporting

Even if training remains hand-coded online SGD, report separate losses for:

- ordinary centipawn records;
- saturated centipawn records;
- mate records;
- each confidence bucket;
- each phase bucket;
- random versus hard tactical negatives;
- float versus quantized inference.

### 20.3 Epoch and order control

Record:

- evaluation epochs;
- ranking epochs;
- learning rates and schedules;
- gradient/error clipping;
- shuffle seeds;
- exact training-order algorithm;
- sample weights;
- update counts;
- skipped numerical updates;
- elapsed time and peak temporary usage.

Candidate data lists should not be mutated in place across architecture runs.

### 20.4 Calibration checks

Before an engine match, compare baseline and candidate score distributions over
a fixed calibration suite:

- mean and standard deviation;
- percentiles;
- sign agreement;
- mean absolute score delta;
- phase-specific score delta;
- saturation frequency;
- side-to-move symmetry;
- color-swap or board-mirror consistency where the feature semantics permit it.

Large scale drift should trigger review even when MAE improves.

## 21. Quantization-aware validation

### 21.1 Required inference modes

Every candidate report should contain metrics for:

1. floating-point training parameters;
2. quantized arrays interpreted by a reference implementation;
3. the exact generated header compiled into Eloi;
4. scalar and AVX2 runtime paths where both are supported.

### 21.2 Required comparisons

Report:

- float-to-quantized MAE;
- maximum absolute output difference;
- tactical ranking flips caused by quantization;
- accumulator overflow checks;
- scalar-versus-AVX2 exact or bounded agreement;
- candidate-header SHA-256;
- executable SHA-256;
- architecture constant and generated-array dimensions.

A candidate with improved float metrics but degraded quantized metrics should not
advance until the discrepancy is understood.

## 22. Offline metrics

### 22.1 Aggregate metrics

At minimum, record:

- centipawn MAE;
- centipawn median absolute error;
- RMSE, reported cautiously because of saturation sensitivity;
- sign accuracy excluding a declared near-zero band;
- WDL or outcome-calibration loss if such targets are introduced;
- tactical top-1 accuracy;
- tactical pairwise accuracy;
- mean tactical margin;
- quantization deltas.

### 22.2 Slice metrics

Every aggregate should be broken down by relevant slices:

- train, validation, and untouched test;
- phase;
- side to move;
- score magnitude;
- mate versus centipawn;
- depth/confidence;
- piece count;
- quiet versus forcing;
- puzzle rating;
- puzzle theme family;
- hard-negative tier;
- baseline-found versus baseline-missed tactics.

### 22.3 Confidence intervals

Use deterministic bootstrap or another declared method to provide uncertainty on
major test metrics. The seed and resampling count must be recorded. Confidence
intervals do not replace engine matches, but they discourage overreaction to
tiny metric differences.

### 22.4 Selection policy

Freeze a candidate selection rule before test evaluation. A reasonable policy
for the first experiment is:

1. reject any candidate with a critical-slice regression beyond a declared
   tolerance;
2. require quantized metrics to preserve the float improvement direction;
3. prioritize hard-negative tactical accuracy;
4. use ordinary-centipawn MAE as a calibration guardrail;
5. break near-ties in favor of the simpler or more reproducible candidate;
6. advance at most one data candidate to the first engine playoff.

## 23. Engine-level validation

Offline success is necessary but not sufficient. Search amplifies some static
evaluation errors and corrects others.

### 23.1 Gate order

Every candidate must pass, in order:

1. generated-header schema and dimension checks;
2. clean compile of the relevant configurations;
3. unit tests;
4. perft and move-generation checks;
5. scalar/AVX2 evaluator consistency;
6. deterministic tactical regression corpus;
7. benchmark completion and basic speed gate;
8. reproducible candidate rebuild;
9. bounded pilot match;
10. frozen larger paired match if the pilot is eligible.

Failure at an earlier gate prevents later strength testing.

### 23.2 Fixed engine conditions

The candidate and baseline must use:

- identical source except for the NNUE data/header under test;
- identical compiler and flags;
- RootSplit production mode unless the experiment explicitly concerns search;
- exactly three threads per engine;
- identical hash size;
- identical opening suite and colors;
- books disabled when required by the established protocol;
- identical move-time or node conditions;
- fixed maximum plies and adjudication rules;
- Windows Idle priority when required to protect foreground use;
- no concurrent heavy task.

### 23.3 Match stages

Use a staged design to protect the laptop:

**Stage A: smoke sample**

- very small, bounded, mirrored set;
- detects crashes, hangs, gross regressions, and packaging mistakes;
- not used for Elo claims.

**Stage B: pilot comparison**

- frozen paired openings and game count;
- catches a clearly harmful candidate cheaply;
- thresholds and continuation rule frozen before game one.

**Stage C: selection comparison**

- larger mirrored sample when the pilot is eligible;
- exact game count fixed in advance;
- no shortening or extension based on interim score;
- retain PGN, settings, hashes, and interruption history.

The exact game count should be chosen after measuring runtime and checking the
device schedule. This document deliberately does not authorize an unbounded
gauntlet.

### 23.4 Result interpretation

Report score, wins/draws/losses, paired-opening breakdown, color balance,
estimated Elo, and uncertainty. Small samples should be described as bounded
evidence, not definitive strength measurement.

A candidate that improves offline metrics but fails tactical correctness is
rejected. A candidate that passes correctness but produces an inconclusive
match remains experimental; it does not replace production by default.

## 24. Proposed experiment matrix

Experiments should be sequential, not all-at-once.

| ID | Width | Dataset | Negatives | Target policy | Purpose |
| --- | ---: | --- | --- | --- | --- |
| B0 | 64 | Current prefix | One random | Current | Reproduce baseline |
| D1 | 64 | Broader representative | One random | Current | Isolate sampling |
| D2 | 64 | D1 | Multiple hard | Current | Isolate negatives |
| D3 | 64 | D2 | Multiple hard | Confidence-weighted | Test label quality |
| D4 | 64 | D3 | Multiple hard | Revised mate/score | Test target mapping |
| A1 | 128 | Selected D-series | Selected | Selected | Revisit capacity |
| A2 | 256 | Selected D-series | Selected | Selected | Capacity only if justified |

Only B0 and the next single candidate need to be trained initially. Later rows
are contingent on earlier evidence.

### 24.1 Required baseline reproduction

Before attributing a gain to new data, reproduce B0 from the currently pinned
inputs and verify:

- input hashes;
- split counts;
- environment versions;
- validation metrics within exact or declared tolerance;
- generated-header hash;
- clean engine build and benchmark identity.

If B0 cannot be reproduced, stop and diagnose the environment or code change.

### 24.2 Ablation discipline

Each experiment report must list every difference from its baseline. If two
dimensions change, the report must say the result is confounded. Do not assign
credit to “better data” when width, optimizer, feature encoding, and target scale
also changed.

## 25. Proposed manifest and report contents

### 25.1 Input manifest schema 2

The successor input manifest should include:

- schema version;
- acquisition script path and Git commit;
- canonicalization script path and Git commit;
- source name and license;
- source URL;
- upstream size, ETag, and Last-Modified;
- acquisition start and completion UTC;
- whether acquisition was full-stream or bounded-prefix;
- compressed bytes transferred;
- decompressed records seen;
- validation and rejection counts by reason;
- partition seed and algorithm;
- stratum definitions and capacities;
- records selected by source, partition, and stratum;
- canonical sample byte size and SHA-256;
- software versions;
- peak measured temporary bytes;
- configured hard limits;
- completion status and interruption history.

### 25.2 Training report schema 2

The training report should include:

- every input hash;
- architecture and feature schema;
- seed hierarchy;
- objective parameters;
- epochs and learning rates;
- sample weights;
- exact update counts;
- float metrics and slice metrics;
- quantized metrics and slice metrics;
- candidate header hashes;
- elapsed time;
- environment versions;
- peak temporary bytes;
- warnings and rejected candidates;
- frozen selection rule;
- selected candidate and reason.

### 25.3 Engine evidence report

The engine report should bind:

- source commit;
- baseline and candidate header hashes;
- executable hashes;
- compiler identity and flags;
- test executable hash;
- opening suite hash;
- EPD/tactical suite hash;
- command/settings document;
- thread, hash, mode, time, and priority settings;
- test outputs;
- benchmark outputs;
- PGN and transcript hashes;
- planned and completed game count;
- every interruption or protocol amendment;
- result and selection decision.

## 26. Resource plan for the development laptop

### 26.1 Binding limits

The implementation must obey:

- at most 10,000,000,000 bytes of all temporary project data;
- at most 8,000,000,000 bytes of temporary NNUE data and artifacts within that
  total;
- the trainer's stricter current ceiling of 7 GiB;
- exactly three search threads per engine;
- at most two bridge processes;
- at most two Eloi GUI processes;
- no concurrent heavy gauntlets or training jobs without explicit permission.

### 26.2 Peak-space accounting

Before any acquisition or training run, calculate a conservative peak:

```text
retained canonical inputs
+ partition/index metadata
+ temporary decompressor buffers
+ training arrays
+ candidate arrays and headers
+ build-tree growth
+ match evidence
+ safety reserve
```

The sampler and trainer should check actual destination usage before each major
write. A projected overrun must stop the task before the write occurs.

### 26.3 Suggested retained-size targets

The first improved corpus should be sized by measured canonical bytes per row,
not by an aspirational row count. A likely exploratory range is 100,000 to
500,000 total canonical positions/pairs, but the final count must be selected
only after:

- measuring bytes per record;
- measuring Python/NumPy in-memory expansion;
- reserving build and match space;
- confirming training time;
- confirming the 7 GiB hard ceiling.

A smaller well-stratified corpus is preferable to a larger corpus that violates
the device contract or cannot be reproduced.

### 26.4 CPU and responsiveness

Acquisition, canonicalization, training, building, and matches should not run as
overlapping heavy tasks. Long work should expose progress, elapsed time, records
processed, selected counts, current bytes, and projected completion.

An active Lichess bridge must not be stopped or overwritten for the experiment.
Candidate binaries should use separate paths until installation is explicitly
approved.

## 27. Reproducibility requirements

### 27.1 Seed hierarchy

Use one recorded root seed and derive child seeds by a stable cryptographic hash
of names such as:

```text
root/acquisition/evaluation/opening/high-confidence
root/acquisition/puzzle/endgame/2000-2499
root/split/train
root/training/64/shuffle/epoch-1
root/bootstrap/test/centipawn
```

Do not rely on process-randomized language hashes.

### 27.2 Canonical output ordering

Reservoir sampling order is not necessarily canonical output order. Before
writing the final retained sample, sort by a stable key such as partition,
source, stratum, group ID, and position key. Record the sorting rule.

### 27.3 Environment capture

Record:

- operating system and architecture;
- Python implementation and version;
- NumPy version;
- python-chess version;
- zstd executable identity and version;
- compiler and linker versions;
- CPU feature path used for evaluator tests;
- relevant locale and newline policy.

### 27.4 Independent reproduction

A candidate should not become production until at least one clean report-only
rerun reproduces the selected generated header byte-for-byte or explains a
documented platform-dependent difference with equivalent array hashes.

## 28. Testing the dataset tools

Dataset code requires its own automated tests.

### 28.1 Acquisition tests

- rejects HTTP 200 when a bounded range is required;
- rejects mismatched size, ETag, or Last-Modified;
- rejects truncated and oversized responses;
- rejects corrupt zstd data;
- enforces byte caps before writes;
- produces deterministic reservoirs from fixture streams;
- cleans only its own explicitly named temporary files;
- leaves existing unrecognized files untouched.

### 28.2 Canonicalization tests

- validates four-field and six-field FEN handling;
- validates castling and en-passant normalization;
- rejects illegal puzzle setup and best moves;
- rejects illegal evaluation PVs;
- preserves score perspective correctly;
- handles mate signs and distances;
- produces stable position and group keys;
- normalizes encoding and newlines.

### 28.3 Split tests

- one group never crosses partitions;
- results are invariant to input order;
- cross-source duplicate positions cannot leak into test;
- partition ratios are measured by groups and rows;
- rare strata emit warnings rather than silently disappearing.

### 28.4 Training tests

- hard alternatives are legal and exclude the best move;
- every negative tier is deterministic;
- candidate runs do not mutate shared dataset ordering;
- report-only mode cannot overwrite production headers;
- quantized reference inference matches compiled inference;
- disk-limit failure occurs before exceeding the cap;
- manifests remain valid on interrupted runs.

## 29. Failure modes and mitigations

| Failure mode | Risk | Required mitigation |
| --- | --- | --- |
| Prefix bias | Misleading generalization | Stream broadly and stratify |
| Shallow labels | Noisy targets | Filter or bounded confidence weights |
| Mate saturation | Distorted MAE and calibration | Separate reporting and policy experiment |
| Random easy negatives | Inflated tactical metric | Hard and multiple alternatives |
| Game leakage | Optimistic validation | Group-first split and independent test |
| Cross-source overlap | Hidden test contamination | Shared position/group registry |
| Quantization flips | Float metrics do not deploy | Quantized and compiled validation |
| Score-scale drift | Search regression | Calibration suite and engine gates |
| Dataset too large | Device impact or failed run | Preflight, quotas, staged sizes |
| Archive identity change | Irreproducible source | Fail closed and repin deliberately |
| Interrupted generation | Ambiguous partial data | Atomic finalization and incomplete marker |
| Post-start match changes | Biased evidence | Freeze protocol before game one |
| Concurrent workload | Noisy timing and laptop impact | Serialize heavy work |
| Variant mixing | Illegal or misleading labels | Explicit variant policy |
| Overfitting to regressions | Narrow strength gain | Keep regression cases out of training test |

## 30. Rollout stages

### Stage 0: freeze the baseline

- reproduce the current 64-unit report;
- verify existing input and header hashes;
- capture current compiled evaluator metrics;
- preserve current production artifacts and evidence.

Exit criterion: current baseline is reproducible and fully identified.

**Completed 2026-09-01.** B0 reproduced the production 64-unit weights and
architecture byte-for-byte from the pinned 12,000/12,000 inputs. Counts,
environment versions, historical float metrics, exact hashes, and newly
measured quantized metrics are tracked in data/nnue_b0_reproduction.json.
The integer reference revealed a 30.01 cp MAE increase and 453 tactical ranking
flips versus the float parameters; this is now the guardrail D1 must beat.

### Stage 1: build analysis-only sampler

- add canonical schemas;
- add validation/rejection counters;
- add group and position identities;
- add deterministic stratified reservoirs;
- run only on tiny fixtures and the existing retained samples.

Exit criterion: output is deterministic, tested, and stays within tiny fixture
bounds.

### Stage 2: profile broader source data

- run a bounded sequential source pass;
- emit distributions without training;
- compare retained-prefix and broader-stream distributions;
- choose quotas based on evidence.

Exit criterion: the proposed corpus composition is documented before candidate
training.

**Completed 2026-09-01.** A bounded 128 MiB sequential prefix of each pinned
Lichess source produced 200,000 complete source records per source. After
legality filtering, the deterministic sampler retained 100,000 evaluations and
100,000 puzzles. Compared with the retained 20,000-row prefixes, phase, score,
tactical, rating, and theme proportions remain broadly similar; the most
material label shift is evaluation confidence (high 47.6% to 40.1%, medium
43.2% to 49.2%, low 9.3% to 10.7%). There is no evidence-based reason to invent
additional class rebalancing before testing the coverage-only D1 hypothesis.

### Stage 3: generate dataset candidate D1

- retain the current objective and random-negative behavior;
- change only representative sampling and split isolation;
- generate a manifest and immutable sample hashes.

Exit criterion: D1 is reproducible and passes integrity checks.

**Completed 2026-09-01.** D1 is frozen at 100,000 canonical evaluations and
100,000 canonical puzzles with group-first 80/10/10 assignment. Two clean runs
produced byte-identical canonical files and manifests. The exact source
metadata, distributions, rejection counts, quotas, sample ID, and output hashes
are tracked in `data/nnue_broader_sample_manifest.json`; independent-run proof
is tracked in `data/nnue_broader_sample_reproduction.json`. D1 remains
report-only and has not changed a production NNUE artifact.

### Stage 4: train 64-unit D1

- reproduce baseline B0 in the same environment;
- train D1 report-only;
- compare float, quantized, aggregate, and slice metrics;
- do not inspect the final test until the recipe is frozen.

Exit criterion: D1 passes the frozen offline rule.

**Completed 2026-09-01.** D1 was trained twice, report-only, and reproduced the
same 64-unit header hash. Production and D1 were evaluated on identical frozen
validation rows. D1 improved quantized MAE by 23.33 cp and tactical pairwise
accuracy by 8.65 percentage points. It passes the rule frozen in
data/nnue_offline_selection_rule.json. Compact evidence is tracked in
data/nnue_d1_report.json. The test partition remains sealed.

### Stage 5: add hard negatives if needed

- generate D2 from the selected broader corpus;
- keep width and score policy fixed;
- evaluate hard-negative slices and calibration.

Exit criterion: one data candidate is selected for engine validation.

**D2 result (2026-09-01): rejected.** Multiple stored hard alternatives
improved quantized hard-negative pairwise accuracy by 9.46 percentage points
and top-1 by 5.83 points versus production on identical rows. Quantized MAE
improved by only 2.54 cp, below the frozen 5 cp calibration gate, while median
error regressed by 6 cp. Evidence is tracked in data/nnue_d2_report.json. D1
remains the provisional winner while D3 tests bounded confidence weights.

**D3 result (2026-09-01): rejected.** Adding bounded 0.5/1.0/1.5 confidence
weights to D2 improved hard-negative pairwise accuracy by 9.40 percentage
points versus production, but improved quantized MAE by only 1.79 cp and
regressed median error by 11 cp. Evidence is tracked in
data/nnue_d3_report.json. D1 is the frozen validation winner; D2 and D3 do not
advance. The test partition has not yet been opened.

### Stage 6: engine correctness and speed gates

- compile candidate separately;
- run all deterministic correctness tests;
- verify scalar/AVX2 behavior;
- verify benchmark and packaging safety.

Exit criterion: no correctness failure and no disqualifying speed regression.

### Stage 7: frozen paired engine comparison

- record protocol and thresholds before game one;
- run bounded smoke, pilot, and eligible selection stages;
- retain complete hashed evidence;
- do not modify game count based on interim score.

Exit criterion: candidate satisfies the frozen installation rule.

### Stage 8: installation and release evidence

- explicitly copy only the selected generated network into production;
- rebuild and reproduce hashes;
- update provenance, data-source documentation, README, and release evidence;
- preserve the superseded production network in Git history.

Exit criterion: clean tree contains only deliberate tracked changes and the
release candidate passes final smoke tests.

## 31. Acceptance criteria for a production replacement

A new dataset-trained network may replace production only when all of the
following are true:

- upstream and retained inputs are fully hash-pinned;
- dataset generation is deterministic and bounded;
- source licenses and attribution are documented;
- train/validation/test groups do not overlap under the declared identity
  policy;
- malformed and rejected records are counted by reason;
- partition and stratum distributions are recorded;
- baseline reproduction succeeds;
- candidate training is reproducible;
- exact generated and executable hashes are recorded;
- float and quantized offline reports are complete;
- no critical slice exceeds its frozen regression tolerance;
- compiled scalar and AVX2 evaluator behavior is valid;
- all deterministic engine correctness gates pass;
- benchmark and runtime behavior remain acceptable;
- the frozen paired match rule selects the candidate;
- installation is explicit and followed by a clean rebuild;
- `DATA_SOURCES.md`, provenance JSON, README, and validation evidence are
  updated consistently;
- no ignored upstream dataset is packaged or committed;
- the development laptop remained inside every binding resource limit.

## 32. Rejection and rollback policy

Reject a candidate immediately when it:

- fails a legality, perft, move-generation, or tactical correctness gate;
- cannot be reproduced;
- relies on an unpinned or ambiguously licensed source;
- leaks test groups into training;
- exceeds a resource cap;
- causes substantial unexplained score-scale drift;
- improves only float metrics while quantized metrics regress materially;
- violates the frozen engine selection rule.

Rejection must not delete historical evidence. Record the candidate identity,
failure stage, and reason. Production remains the last accepted generated
network. Candidate binaries and ignored temporary data may be removed later
under the binding cleanup policy, but tracked manifests and intentionally
retained evidence must remain available.

## 33. Questions to resolve before implementation

These decisions should be made from a profile run, not guessed:

1. What sequential compressed-byte or record budget is safe on the development
   laptop?
2. Can archive-wide sampling be generated on a more suitable machine?
3. Which evaluation fields provide stable confidence signals across the source?
4. What minimum depth and knode policy yields sufficient coverage without
   preserving obvious noise?
5. Does a separate-date evaluation source exist for a stronger test set?
6. How often do evaluation and puzzle positions overlap after canonicalization?
7. How many hard negatives per puzzle fit the training-time budget?
8. Should hard negatives be generated by the production Eloi baseline, a pinned
   reference engine, source multipv data, or a controlled mixture?
9. Which mate policy best preserves Eloi's runtime score calibration?
10. What critical-slice regression tolerances should be frozen?
11. What pilot and selection game counts are feasible without changing them
    after the match begins?
12. When, if ever, should 128 units be retested on the improved corpus?

## 34. Implementation checklist

### Planning

- [x] Confirm this design against current source and device constraints.
- [x] Freeze the Stage 1 analysis ID, root seed, and analysis-only scope.
- [x] Estimate peak bytes and output counts for the retained-input prototype.
- [x] Confirm no conflicting heavy task or active executable replacement.
- [x] Freeze the offline selection rule before opening test.

### Acquisition

- [x] Pin source URL, size, ETag, Last-Modified, date, and license.
- [x] Choose explicitly bounded sequential mode for D1.
- [x] Enforce byte and row caps before writes.
- [x] Validate decompression and source schema.
- [x] Record records seen, accepted, rejected, and retained.
- [x] Hash canonical outputs.

### Curation

- [x] Canonicalize FENs and score perspective for the retained-input prototype.
- [x] Validate legal PV and puzzle moves.
- [x] Compute record, position, and group identities.
- [x] Detect cross-source overlap.
- [x] Assign partitions by group before deterministic selection.
- [x] Fill deterministic population and coverage selections.
- [x] Emit distribution and rejection reports.

### Tactical examples

- [ ] Apply setup moves and store decision FENs.
- [ ] Generate deterministic hard alternatives.
- [ ] Classify negative tiers.
- [ ] Verify every alternative is legal and not the best move.
- [ ] Record baseline-found and baseline-missed slices.

### Training

- [x] Reproduce B0 first, including exact production header hashes.
- [x] Train 64-unit D1 candidate report-only and reproduce its header.
- [x] Record every D1 parameter and environment version.
- [x] Measure peak temporary storage.
- [x] Produce float and quantized validation reports.
- [x] Keep production headers untouched.

### Validation

- [x] Apply frozen offline selection rule to D1 validation.
- [ ] Open untouched test only after recipe freeze.
- [ ] Run generated-header and dimension checks.
- [ ] Build candidate separately.
- [ ] Run unit, perft, move-generation, tactical, and SIMD checks.
- [ ] Run bounded benchmark and calibration suite.
- [ ] Run frozen paired comparison only if eligible.
- [ ] Hash every retained evidence artifact.

### Installation

- [ ] Select candidate only under the frozen rule.
- [ ] Install generated header explicitly.
- [ ] Rebuild and reproduce candidate identity.
- [ ] Update provenance and public documentation.
- [ ] Confirm packaging excludes all datasets and secrets.
- [ ] Verify final Git status and release smoke tests.

## 35. Recommended immediate next action

**Stage 1 result (2026-09-01): completed.** The exact retained samples produced
19,876 valid Standard evaluation records and 20,000 valid puzzle records. The
sampler rejected 124 evaluation positions: 118 for invalid castling rights and
6 for impossible Standard material counts. No exact learning-state overlap was
found between the retained evaluation and puzzle samples. A second clean
analysis produced byte-identical canonical evaluation, canonical puzzle, and
report hashes. The two canonical files total 41,829,872 bytes before the small
report, far below the device limits.

**Stages 2 and 3 result (2026-09-01): completed.** The bounded broader-source
sampler retained a five-times-larger, 200,000-row D1 corpus in 210,081,790 bytes
of canonical data. Two clean acquisitions and canonicalization runs produced
the same sample ID, output hashes, and manifest hash. Compressed prefixes were
deleted after each source. The corpus has only two exact cross-source learning
state overlaps, and connected groups keep them in one partition.

Do not begin with a 256-unit network or a full upstream download. The next
concrete change is Stage 4: extend the existing 64-unit report-only trainer to
consume D1's frozen group partitions, reproduce B0 in the same environment,
and report both float and exact quantized validation metrics. Production NNUE
headers remain immutable until every later gate passes.

## 36. Final decision principle

The dataset project succeeds only if it improves **Eloi as a complete engine**.
A larger corpus, lower float MAE, higher easy-puzzle accuracy, or wider network
is not independently sufficient.

The preferred candidate is the smallest, safest, reproducible network that:

- learns from more representative and trustworthy evidence;
- preserves calibration across important position classes;
- survives quantization and compiled runtime arithmetic;
- passes every correctness gate;
- and wins under a frozen, hash-bound engine protocol.

Until that evidence exists, the current 64-unit network remains the correct
production baseline.
