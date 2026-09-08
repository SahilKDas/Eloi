# Eloi

> A C++26 chess engine, native Windows chess application, reproducible
> engineering project, and home of a crash-contained Caissa 1.25 second brain.

Eloi is a UCI-compatible chess engine with a native Skia GUI, a native Lichess
Bot API client, Standard chess, Chess960, Horde, an embedded opening repertoire,
a compact incrementally updated NNUE, deterministic three-lane RootSplit
search, and reproducible Windows packaging.

The current stable source is **Eloi 3.0.0**.

The production evaluator is the 64-unit **E2-ranking** NNUE.

Production search uses exactly **three RootSplit lanes**.

Official packages currently target **Windows x64**.

Eloi is distributed under the **MIT License**.

Current main contains the pinned Caissa 1.25 backend and Eloi-owned hybrid.

Standard UCI play uses **Eloi 3.0.0 plus Caissa 1.25**.

Chess960 and Horde remain on Eloi E2 until separate parity qualification.

---

## Contents

1. Project status
2. Quick start
3. Downloads and verification
4. GUI and variants
5. UCI and command-line reference
6. Configuration and Lichess
7. Engine architecture
8. Evaluation, NNUE, and the complete E2 story
9. Search, RootSplit, hash, and time
10. Diagnostics and Engine Lab
11. Building, testing, and reproducibility
12. Releases and strength evidence
13. Repository, source, scripts, and data guide
14. Contributing, constraints, and security
15. Licenses and attribution
16. The Caissa 1.25 two-brain plan
17. The rejected hybrid and lessons learned
18. Integration, correctness, and qualification gates
19. Frequently asked questions
20. Glossary and acknowledgements

---

## Project status

| Item | Current status |
| --- | --- |
| Source version | 3.0.0 |
| Latest tag | v3.0.0 |
| Latest release | v3.0.0 |
| Release commit | 6ff04a8d5fa1fd87ec677c89ae52fdd61c8437aa |
| Language | C++26 |
| Build system | CMake |
| Primary toolchain | MSYS2 UCRT64 GCC |
| Primary platform | Windows x64 |
| GUI | Native Skia |
| Protocol | UCI |
| Online client | Native Lichess Bot API |
| Evaluator | E2-ranking, 64 units |
| Parallelism | Exactly three RootSplit lanes |
| Variants | Standard, Chess960, Horde |
| Source license | MIT |
| Caissa in current main | Yes, pinned v1.25 |
| Planned donor | Caissa 1.25 |
| Planned donor commit | 0c01e79ea36ae492585e88cca9d03abae9b7a3d5 |
| AGPL code accepted | No |

Source version, Git tag, and packaged release are related but distinct.

Stable releases should make all three identities agree.

Historical commits contain experiments absent from the current tree.

An old implementation is not automatically a current feature.

An old package proof is not automatically current qualification.

Current behavior comes from current source.

Published behavior comes from the commit named by the release.

Experimental history remains evidence.

---

## Quick start

To play locally:

1. Download the v3.0.0 standalone ZIP.
2. Verify its SHA-256.
3. Extract it.
4. Double-click Eloi.exe.

To use Eloi in another chess GUI:

1. Select Eloi.exe as a UCI engine.
2. Leave Threads at three.
3. Configure Hash and variant options as needed.

To develop:

1. Read CONTRIBUTING.md.
2. Read constraints_on_SahilKDas_device.md.
3. Use the locked toolchain.
4. Build with CMake and Ninja.
5. Run the complete tests.
6. Freeze a baseline before changing the brain.

Eloi values strength.

It also values knowing where strength came from.

A faster binary is not automatically a valid release.

A stronger short match is not automatically a valid release.

A correct package is not automatically a strong engine.

A strong engine is not automatically legally distributable.

A public file is not automatically licensed.

A failed experiment remains failed.

An incomplete match remains incomplete.

Correctness comes before strength.

Provenance comes before redistribution.

Resource accounting comes before heavy work.

Reproducibility comes before release claims.

---

## What ships today

Eloi 3.0.0 ships Eloi legal authority plus a Caissa 1.25 Standard brain containing:

- Eloi's authoritative board;
- Standard legality;
- Chess960 legality;
- Horde legality;
- iterative deepening;
- aspiration windows;
- principal-variation search;
- alpha-beta pruning;
- quiescence search;
- transposition tables;
- static-exchange evaluation;
- history move ordering;
- guarded pruning;
- late-move reductions;
- incremental NNUE accumulators;
- E2-ranking weights;
- three deterministic RootSplit lanes;
- adaptive time management;
- legal best-so-far fallback behavior.

The application adds:

- native Skia rendering;
- legal-move highlighting;
- animated moves and castling;
- four promotion choices;
- undo, side selection, and board flipping;
- material and evaluation displays;
- clocked play;
- Engine Lab;
- deterministic screenshots;
- UCI;
- native Lichess.

The repository includes tools for:

- perft;
- differential move generation;
- search diagnostics;
- deterministic benchmarking;
- mirrored-opening matches;
- NNUE training;
- provenance recording;
- release packaging;
- toolchain verification;
- reproducibility proof.

Eloi 3.0.0 does not ship Syzygy,
Lazy SMP, variable production thread counts, Linux packages, runtime model downloads,
Stockfish as a playing backend, Reckless source, or any AGPL component.

Some appear in old branches or plans.

That does not make them current.

---

## UCI handbook

Eloi implements the Universal Chess Interface expected by chess GUIs and
tournament controllers.

A minimal session is:

~~~text
uci
isready
ucinewgame
position startpos moves e2e4 e7e5
go depth 8
quit
~~~

### Core commands

**uci**

Begins negotiation.

Eloi prints its identity and supported options.

**isready**

Requests a readiness response.

**ucinewgame**

Clears game-specific search state.

**position startpos**

Loads the orthodox initial position.

**position startpos moves ...**

Loads the initial position and replays UCI moves.

**position fen ...**

Loads a FEN position.

**go depth N**

Searches toward a requested depth.

**go nodes N**

Searches under a node budget.

**go movetime N**

Searches under a millisecond budget.

**go wtime ... btime ...**

Uses game clocks and increments.

**stop**

Requests termination and a legal best-so-far move.

**quit**

Exits cleanly.

Search information can include depth, selective depth, score, mate distance,
nodes, time, nodes per second, and a principal variation.

Eloi 2.8.0 added selective-depth reporting.

Principal variations must be legal from the root.

Mate scores must preserve distance semantics through TT storage.

A forced single legal move returns immediately in 2.8.0.

That avoids wasting clock where no decision exists.

---

## UCI options

### Depth

~~~text
option name Depth type spin default 0 min 0 max 17697
~~~

Depth zero enables clock-oriented behavior where applicable.

Large values may be computationally impractical.

### Hash

~~~text
option name Hash type spin default 32 min 0 max 16384
~~~

The value is megabytes.

Current Eloi divides it among private RootSplit TT shards.

Future multi-brain work must treat it as one aggregate process budget.

### Threads

~~~text
option name Threads type spin default 3 min 3 max 3
~~~

Production search is fixed at three threads.

The option exists for compatibility and truthful discovery.

It is not a hidden variable-thread implementation.

### Move Overhead

~~~text
option name Move Overhead type spin default 100 min 0 max 5000
~~~

The value reserves milliseconds for protocol, scheduling, and network delay.

Losing on time is worse than preserving a small safety margin.

### Noise

~~~text
option name Noise type spin default 0 min 0 max 10000
~~~

Noise is measured in millipawns.

The default is deterministic evaluation.

### UCI_Chess960

~~~text
option name UCI_Chess960 type check default false
~~~

Enable it when the controller expects Chess960 notation.

### UCI_Variant

~~~text
option name UCI_Variant type combo default chess var chess var horde
~~~

Use chess for Standard.

Use horde for Horde.

Unsupported values are reported.

### OwnBook

~~~text
option name OwnBook type check default true
~~~

Disable it for controlled engine experiments.

---

## Command-line reference

### Version

~~~powershell
.\Eloi.exe --version
~~~

### GUI

~~~powershell
.\Eloi.exe --gui
~~~

### UCI

~~~powershell
.\Eloi.exe --uci
~~~

### Lichess

~~~powershell
.\Eloi.exe --lichess
~~~

### Perft

~~~powershell
.\Eloi.exe --perft --depth 4
~~~

Perft arguments include:

- --depth N;
- --fen FEN;
- --variant standard or horde;
- --divide.

### Benchmark

~~~powershell
.\Eloi.exe --bench --depth 8
~~~

### Search diagnostics

~~~powershell
.\Eloi.exe --diagnose-search --fen "FEN" --depth 8 --profile production --json diagnostic.json
~~~

Diagnostic controls include:

- --fen;
- --json;
- --profile production or full-width;
- --depth;
- --max-ms;
- --nodes;
- --hash-mb.

Full-width search is evidence, not proof of an optimal move.

### Screenshot modes

~~~powershell
.\Eloi.exe --screenshot frame.bmp
.\Eloi.exe --screenshot-setup setup.bmp
.\Eloi.exe --screenshot-engine-lab lab.bmp PREVIOUS.exe
~~~

### Version comparison

~~~powershell
.\Eloi.exe --version-match
.\Eloi.exe --version-match-smoke .\previous\Eloi.exe
~~~

The smoke path validates process and UCI interaction.

A watched match is not strength proof.

---

## Configuration reference

The public template is config.example.yml.

Release tooling copies it as config.yml.

The public token is empty.

~~~yaml
lichess:
  enabled: false
  token: ""
  url: "https://lichess.org"

challenge:
  min_base_seconds: 0
  max_base_seconds: 10800
  allow_bots: true
  variants:
    - standard
    - chess960
    - horde

engine:
  depth: 0
  hash_mb: 32
  move_overhead_ms: 100
  own_book: true
~~~

### Lichess enabled

Set lichess.enabled to true only in a private local configuration.

### Token

Store a Bot API token only in ignored config.yml.

Never add one to config.example.yml.

Never paste one into an issue.

Never commit a configured file.

### URL

The native client is restricted to:

~~~text
https://lichess.org
~~~

It is not a general bearer-token forwarding client.

### Challenge policy

min_base_seconds and max_base_seconds bound accepted initial clocks.

allow_bots controls bot-opponent acceptance.

variants lists accepted game variants.

### Engine policy

depth controls the default search mode.

hash_mb controls TT memory.

move_overhead_ms reserves clock safety.

own_book controls the embedded repertoire.

Configuration changes require parser tests.

---

## Native Lichess client

Eloi includes a native Lichess Bot API client.

It does not require a Python bridge.

For standalone builds, configure a private adjacent config.yml and run:

~~~powershell
.\Eloi.exe --lichess
~~~

For Exoskeleton builds, use EloiLichess.exe.

~~~powershell
.\EloiLichess.exe --configure
.\EloiLichess.exe --run
~~~

The native client supports:

- Standard;
- Chess960;
- Horde;
- eligible rematches;
- player chat commands;
- adaptive clocks;
- legal interruption fallback.

Player chat commands include:

- !help;
- !version;
- !eval;
- !depth;
- !rematch.

Arena and Swiss enrollment is performed by the user in a browser when bots are
eligible.

Eloi handles resulting Bot API pairings.

It does not bypass tournament eligibility.

Native pondering is limited to games with initial base time below four minutes.

No UCI Ponder option is advertised.

Do not overwrite an executable used by a running bridge.

Do not terminate all Eloi processes during an active game.

The device contract permits at most two concurrent bridge processes.

---

## Opening repertoire

Eloi embeds an ECO-derived weighted opening graph.

It contains:

- 5,480 positions;
- 8,092 weighted edges.

Eloi prefers the Italian Game as White when available.

Eloi prefers the Nimzo-Indian as Black when available.

Those are weighted preferences, not mandatory moves.

The book is disabled when:

- OwnBook is false;
- Chess960 is active;
- Horde is active;
- the position is outside the graph.

Compiled data lives in include/eloi/opening_data.hpp.

Source and attribution are in DATA_SOURCES.md.

---

## Engine architecture

The current path is intentionally compact.

~~~text
GUI / UCI / native Lichess
            |
            v
     Eloi public driver
            |
            v
    authoritative Board
            |
            +---- opening repertoire
            |
            +---- legal move generation
            |
            +---- RootSplit search
                     |
                     +---- private TT shard 0
                     +---- private TT shard 1
                     +---- private TT shard 2
                     |
                     +---- incremental E2 NNUE
~~~

The GUI does not implement a separate rules engine.

The Lichess bridge does not implement a separate chess brain.

UCI does not own a second board model.

All frontends converge on Eloi's authoritative chess implementation.

The future Caissa design changes internal shape, not public ownership.

Eloi remains the authority even when a donor proposes moves.

---

## Board and state

The board tracks:

- piece placement;
- side to move;
- castling rights;
- Chess960 rook origins;
- en-passant state;
- halfmove clock;
- fullmove number;
- repetition state;
- Zobrist state;
- NNUE accumulator state;
- variant identity.

Move application and restoration must be exact inverses.

Correct piece placement is insufficient if hash state is stale.

Correct hash state is insufficient if the NNUE accumulator is stale.

Castling is sensitive because squares may overlap in Chess960.

Horde is sensitive because White may legally have no king.

The Eloi board remains authoritative in the planned hybrid.

---

## Move generation

Legal move generation covers:

- quiet moves;
- captures;
- promotions;
- underpromotions;
- en passant;
- ordinary castling;
- Chess960 castling;
- check evasions;
- pins;
- double check;
- Horde pawn rules;
- Horde elimination;
- variant-specific king rules.

Perft verifies aggregate leaf counts.

Differential testing compares complete legal-move sets.

Those find different errors.

A matching total can conceal compensating mistakes.

A move-set comparison identifies missing and extra moves.

The Standard depth-four oracle is:

~~~text
197281
~~~

---

## Search

Eloi search contains:

- iterative deepening;
- aspiration windows;
- principal-variation search;
- alpha-beta pruning;
- quiescence;
- TT probing and storage;
- static-exchange evaluation;
- hash-move ordering;
- capture ordering;
- history ordering;
- guarded null-move behavior;
- late-move reductions;
- futility guards;
- extensions;
- mate-distance handling;
- repetition handling;
- stop propagation;
- node limits;
- time limits;
- PV reconstruction.

Search heuristics interact.

A pruning rule that gains Elo with one evaluator can lose with another.

A donor cannot be judged by counting famous techniques.

Every playing-code change needs:

1. focused correctness tests;
2. deterministic diagnostics;
3. bounded performance checks;
4. a frozen strength protocol;
5. an honest decision.

Eloi 2.8.0 corrected root recapture extension handling.

SEE is now evaluated on the correct pre-move board.

It also returns immediately for a forced single move.

Selective depth is reported through UCI and diagnostic JSON.

The E2 network and RootSplit architecture did not change in 2.8.0.

---

## RootSplit

RootSplit is the only current production parallel-search implementation.

Exactly three lanes are used.

Each lane owns a private share of configured TT memory.

The fixed count:

- matches the target laptop contract;
- narrows reproducibility variables;
- prevents silent overuse;
- keeps comparisons resource-comparable;
- simplifies package claims.

There is no public LazySMP switch.

There is no hidden six-thread production mode.

The future hybrid must preserve at most three active search threads.

One three-thread brain must stop before another becomes active.

---

## Evaluation and NNUE

NNUE means Efficiently Updatable Neural Network.

In a chess engine, the evaluator estimates a position after the tactical search
has decided which leaves need evaluation.

Efficiently updatable means most features are maintained incrementally as moves
are pushed and popped.

Eloi does not rebuild the entire input representation at every node.

The production implementation is split between:

- include/eloi/nnue_architecture.hpp;
- include/eloi/nnue_weights.hpp;
- src/nnue.cpp;
- board push and pop integration in the chess core.

The architecture header currently fixes the hidden width at 64.

The weight header contains the exact quantized E2-ranking parameters.

Production builds leave ELOI_NNUE_INCLUDE_DIR empty.

That selects the tracked header.

An explicit experimental include directory can replace it for controlled work.

CMake never trains the model.

CMake never downloads the model.

Runtime code never downloads the model.

### Incremental correctness

A valid NNUE implementation requires agreement between:

- a freshly reconstructed accumulator;
- the incrementally maintained accumulator;
- the scalar inference path;
- the runtime-dispatched optimized path.

Special moves are particularly sensitive:

- ordinary castling;
- overlapping Chess960 castling;
- promotion;
- capture promotion;
- en passant;
- undo after every special move.

BMI2 and AVX2 paths have scalar fallbacks.

They accelerate supported processors.

They are not hard requirements for every supported executable path.

---

## What E2 means

E2 is a project-local candidate name.

It is not a standard NNUE architecture name.

It is not a CPU instruction set.

It is not a search algorithm.

It is not a second engine.

It is not shorthand for Eloi 2.

It identifies the second major experimental network campaign after the earlier
E-series dormant-channel work.

The selected member is called **E2-ranking** because its recipe placed extra
emphasis on move-ranking pairs from difficult positions.

The full production identity is:

| Field | Value |
| --- | --- |
| Candidate | E2-ranking |
| Hidden units | 64 |
| Production release introduced | Eloi 2.7.5 |
| Still used by | Eloi 2.8.0 |
| Weight header SHA-256 | E3DFBE02F4DC765C45E243EFD4437E9EC3390D4F167531D6F54765CECB899C9F |
| Float checkpoint SHA-256 | E3E3D98C7CDF85E0D8AE82A7F07777E81C9C0FBE6F1BB31774F2DDA2118FCD29 |
| Frozen candidate executable SHA-256 | 966E4E87FB75664F96B2B50DA1603C179EFE380D1D341469B97BA6EAD94BEB66 |
| Parent network | C |
| Parent weight SHA-256 | 6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD |
| Training variant | FIDE Standard only |
| Chess960 training rows | 0 |
| Horde training rows | 0 |

When the README says E2, it means those exact production bytes and lineage.

It does not mean any newly trained 64-unit model.

It does not mean the generic training script's latest output.

It does not mean a network with similar offline error.

It does not mean a checkpoint that was never quantized and tested in-engine.

---

## The Eloi network family

Eloi's network names describe an experimental lineage.

They are not universal model names.

### A, B, and C

The A/B/C line predates E2.

C became the Eloi v2.5.0 production network.

C is the parent from which E1 and E2 were developed.

Its production weight identity is:

~~~text
6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD
~~~

C used 64 declared hidden units.

A later channel audit found that only 23 were functionally occupied in the
exact quantized production model.

The remaining channels had zero-input and zero-output behavior.

This was not merely a performance observation.

It shaped the E1 and E32 experiments.

### E1-selected

E1-selected retained the 64-unit architecture.

It began from C.

It deterministically revived 41 previously dormant channels.

It then performed one residual evaluation epoch on those channels.

Its recorded properties were:

| Property | Result |
| --- | --- |
| Hidden units | 64 |
| Occupied channels | 64 |
| Dormant channels | 0 |
| Nonzero output coefficients | 50 |
| Validation MAE | 179.2135 cp |
| Correctness | Passed |
| Perft depth four | 197,281 |
| Development screen | 7W / 6D / 7L |
| Chess score | 50% |

E1 demonstrated that dormant capacity could be activated.

Its twenty-game screen established competitive parity only.

It did not establish a production improvement.

### E1-full-schedule

A longer E1 schedule was also tried.

Its validation MAE worsened to 186.12325 cp.

It failed correctness through a repeated forbidden move on the retained
online-bIw09dp9-knight-hang regression.

It was rejected.

More training was not automatically better.

### E32-compact

E32-compact reduced the architecture to 32 declared units.

It retained every occupied C channel.

It omitted only channels that were zero-input and zero-output.

It performed no training.

Its predictions were identical to C for all inputs by construction.

Its properties were:

| Property | Result |
| --- | --- |
| Hidden units | 32 |
| Occupied channels | 23 |
| Dormant channels | 9 |
| Evaluation relation to C | Exact |
| Validation MAE | 181.22 cp |
| Correctness | Passed |
| Perft depth four | 197,281 |

A small three-sample speed check was mixed.

It looked faster at shallow depth and slightly slower at depth ten.

That evidence did not establish a deep-search speedup.

### E32-selected

E32-selected used the exact 23-channel compaction and revived nine spare
channels.

It trained those channels for one residual epoch.

Its validation MAE improved slightly to 180.57775 cp.

It nevertheless failed the lichess-001XA defensive regression.

It chose c3a1 instead of the required depth-seven defense b1b7.

It was rejected.

This is an important Eloi lesson:

**better offline error does not guarantee better engine decisions.**

### E32-full-schedule

The longer trained 32-unit schedule worsened validation MAE to 198.18275 cp.

It failed lichess-000o3 by choosing d3e2 instead of d3d4.

It was rejected.

### E2-conservative

E2-conservative was the least aggressive E2 candidate.

Its recipe used:

- teacher fraction 0.25;
- retained delta fraction 0.30;
- hard-ranking weight 0.75;
- two hard-data epochs.

Its validation MAE was 181.5805 cp.

Its mean absolute drift from C was 5.1815 cp.

Its twenty-game screen scored:

~~~text
4 wins
7 draws
9 losses
7.5 / 20 points
37.5%
~~~

It was not selected.

### E2-balanced

E2-balanced used:

- teacher fraction 0.50;
- retained delta fraction 0.50;
- hard-ranking weight 1.00;
- two hard-data epochs.

Its validation MAE was 180.0005 cp.

Its mean absolute drift from C was 19.0175 cp.

Its twenty-game screen scored:

~~~text
6 wins
5 draws
9 losses
8.5 / 20 points
42.5%
~~~

It was not selected.

### E2-ranking

E2-ranking used:

- teacher fraction 0.50;
- retained delta fraction 0.70;
- hard-ranking weight 1.50;
- three hard-data epochs.

Its validation MAE was 178.10225 cp.

Its mean absolute drift from C was 43.10625 cp.

Its twenty-game screen scored:

~~~text
7 wins
8 draws
5 losses
11 / 20 points
55%
~~~

It was selected for confirmation.

The selection metric was engine-in-loop play.

Offline metrics alone did not select the winner.

---

## E2 training and selection

E2 began from the exact quantized C parameters converted to float32.

It did not begin from random weights.

Its recipe combined evaluation targets and ranking constraints.

### Base data

The retained production provenance records:

| Input | Count |
| --- | ---: |
| Base training evaluations | 32,015 |
| Base training pairs | 12,000 |
| Base validation evaluations | 4,000 |
| Accepted base test evaluations | 3,985 |
| Hard source positions | 3,197 |
| Hard diagnosed positions | 384 |
| Hard retained positions | 166 |
| Hard training positions | 130 |
| Hard validation positions | 36 |
| Hard ranking pairs | 365 |

The base source was a filtered Lichess Elite database archive.

The underlying Lichess database exports are released under CC0 1.0.

Exact URLs and hashes are recorded in DATA_SOURCES.md and provenance JSON.

### Teacher

Stockfish 17.1 generated offline numeric and move-ranking labels.

Its role was limited to offline labeling.

Stockfish code is not linked into Eloi.

Stockfish is not started by the Eloi runtime.

Stockfish is not a packaged dependency.

Stockfish is not the playing backend.

Hard positions used 100,000 teacher nodes per position.

Restricted extra root moves used 25,000 nodes.

### Hard-position mining

The hard-data source began with 28 mirrored E1 pairs that scored no more than
0.5 out of 2 against C.

The pipeline extracted 3,197 raw Standard positions.

It diagnosed 384 positions.

It retained 166 C-or-E1 disagreements.

It split those into:

- 130 training positions;
- 36 validation positions;
- 365 ranking pairs.

The first immutable scratch attempt had a partitioning defect.

It reused a sorted identifier prefix.

All 166 retained rows landed in validation.

No weights were trained in that failed attempt.

The failed attempt remains recorded.

The completed run used an independently salted deterministic partition.

### Objective

E2 blended C and Stockfish evaluation targets.

The selected candidate used teacher fraction 0.50.

It retained 70% of the trained delta away from C.

It emphasized difficult ranking pairs at weight 1.50.

It used three hard-data epochs.

The delta anchor limited how far the model moved from C.

The ranking component tried to improve move ordering among alternatives rather
than only minimizing absolute centipawn error.

### Quantization

Input weights were:

1. rounded with numpy.rint;
2. clipped to the interval from -127 through 127;
3. stored as signed eight-bit integers.

Bias and output values were rounded to signed sixteen-bit integers.

The checkpoint arrays were verified equal to the exported representation.

The promoted header was copied byte-for-byte.

It was not regenerated or reformatted during promotion.

### Candidate screen

All three E2 candidates passed mechanical correctness before play.

The twenty-game screens chose E2-ranking.

Screening was not the final qualification.

### Sixty-game confirmation

E2-ranking then scored:

~~~text
31 wins
22 draws
7 losses
42 / 60 points
70%
required score: 52%
~~~

It passed.

### First 125-game final

An initial final scored:

~~~text
50 wins
49 draws
26 losses
74.5 / 125 points
59.6%
~~~

A later learning-key audit found overlap with prior match stages:

- two screening overlaps;
- seven confirmation overlaps;
- zero training overlap.

The run remained a valid played match.

It was superseded as independent final evidence.

Its files remain preserved.

It was not used for the production decision.

### Disjoint 125-game final

A corrected disjoint final used a new suite.

It scored:

~~~text
45 wins
56 draws
24 losses
73 / 125 points
58.4%
~~~

The games contained 62 mirrored pairs plus one additional game.

Candidate results by color were:

| Color | Wins | Draws | Losses |
| --- | ---: | ---: | ---: |
| White | 24 | 26 | 13 |
| Black | 21 | 30 | 11 |

Learning-key overlap was zero with training, screen, and confirmation data.

All games replayed legally.

The candidate passed its frozen gate.

### Two-hundred-fifty-game promotion confirmation

A separate confirmation used 125 mirrored openings.

It scored:

~~~text
93 wins
94 draws
63 losses
140 / 250 points
56.0%
estimated raw-score Elo difference: +41.894
descriptive paired interval: 51.36% to 60.64%
protocol failures: 0
~~~

Every PGN replayed legally.

This supported promotion to Eloi 2.7.5.

Eloi 2.8.0 retained the exact same E2 network.

### Why the name includes ranking

The selected candidate did not merely have the best validation MAE.

It also had the largest retained delta and strongest hard-ranking emphasis.

Its selection path required engine play.

The name distinguishes that recipe from conservative and balanced siblings.

---

## E2 limitations

E2 was trained and selected on FIDE Standard chess only.

It had:

- zero Chess960 training rows;
- zero Horde training rows.

Chess960 and Horde still passed mechanical engine checks.

Those checks prove integration and legality.

They do not prove that E2 is well calibrated for those variants.

The 250-game confirmation used 10,000 nodes per move.

It does not establish superiority at:

- 250 milliseconds;
- online blitz;
- long classical controls;
- arbitrary hash sizes;
- arbitrary thread counts;
- Chess960;
- Horde.

Held-out hard-pair accuracy was 30.303% for every quantized E2 candidate.

That weak metric remains documented.

The Elo transform and score interval are descriptive.

They are not an official rating certification.

The accepted fresh-label filters excluded categories such as checks, captures,
promotions, mates, and large or highly disagreeing scores.

This created deliberate coverage boundaries.

Future work should measure tactical, defensive, and endgame gaps rather than
assuming more generic epochs will solve them.

The E1 and E32 failures show that:

- activating capacity can help offline metrics;
- longer training can overfit;
- narrower networks can be evaluation-identical yet not faster at depth;
- small offline improvements can break a critical move;
- engine-in-loop validation remains essential.

The authoritative E2 records are:

- RELEASE_V2_7_5.md;
- E2_STANDARD_CAMPAIGN.md;
- DATA_SOURCES.md;
- data/nnue_provenance.json;
- data/nnue_e2_standard_results.json.

A fresh generic training run is not E2.

Only the frozen identity is E2-ranking.

---

## Transposition tables

Eloi caches search information for positions reached through multiple paths.

Entries include position identity, depth, score, bound, move, and normalized
mate-distance information.

RootSplit uses private shards.

The public Hash option is a total budget.

It must not be multiplied by lane count.

It must not be multiplied by future brain count.

In the planned hybrid:

- Eloi retains an Eloi-format TT;
- Caissa retains a Caissa-format TT;
- configured memory is partitioned;
- neither engine decodes the other's entries.

They share a budget, not an entry format.

---

## Time management

Eloi supports fixed depth, fixed nodes, movetime, game clocks, increments,
moves-to-go information, stop requests, and move overhead.

Time management distinguishes:

- a soft target;
- a hard deadline;
- protocol overhead;
- network overhead;
- fallback time.

The native Lichess path protects a reserve.

Eloi 2.8.0 skips search at a forced one-move root.

The future hybrid must derive one aggregate deadline.

It must subtract overhead once.

It must not grant each brain the full clock.

---

## Diagnostics

Search diagnostics explain behavior.

~~~powershell
.\build-release\Eloi.exe --diagnose-search --fen "FEN" --depth 10 --profile production --json tmp\diagnostic.json
~~~

Reports can include:

- root candidates;
- PVs;
- depth;
- selective depth;
- score;
- SEE;
- TT observations;
- pruning activity;
- nodes;
- time.

The full-width profile reduces selected shortcuts.

It is still bounded search.

It does not mathematically prove the best move.

Use unique output paths.

Do not overwrite retained evidence.

---

## Engine Lab

Engine Lab compares current Eloi with an identified previous executable.

Capture a baseline before a brain change:

~~~powershell
pwsh -NoProfile -File .\scripts\capture-brain-baseline.ps1
~~~

Then use:

- the GUI ENGINE LAB control;
- --version-match;
- --version-match-smoke;
- scripts/engine_lab.py.

The runner supports:

- score-based matches;
- mirrored openings;
- fixed nodes;
- movetime;
- checkpoints;
- bounded benchmarks.

A watched game can reveal spectacular failure.

It is not a strength estimate.

A valid campaign identifies:

- executable hashes;
- opening suite;
- mirroring;
- node or time budget;
- hash;
- threads;
- adjudication;
- game count;
- stopping rules;
- score metric;
- failure policy.

---

## Build requirements

The verified environment uses Windows, PowerShell, MSYS2 UCRT64, CMake, Ninja,
and hash-locked dependencies.

| Component | Locked version |
| --- | --- |
| GCC/runtime | 14.1.0-3 |
| GNU binutils | 2.42-2 |
| MinGW headers, CRT, winpthreads | 11.0.0.r750.g05598db99-1 |
| CMake | 3.29.3-2 |
| Ninja | 1.12.1-1 |
| PowerShell | 7.6.4 |
| Reproducible ZIP Python | 3.12.13 |
| Reproducible ZIP zlib | 1.3.2 |

Machine-readable identities live in reproducibility.lock.json.

Never change a hash merely because a newer dependency exists.

CMake 3.29 predates standardized CXX26 labeling.

Eloi requests -std=c++2c on GCC-like compilers.

It requests /std:c++latest on MSVC.

Windows application builds expect Skia and static codecs beneath ignored
dependency storage.

Bootstrap populates development dependencies.

Those are not runtime downloads.

Python is development-only.

---

## Build instructions

Bootstrap:

~~~powershell
pwsh -NoProfile -File .\scripts\bootstrap-windows.ps1
~~~

Configure:

~~~powershell
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_BUILD_TESTS=ON
~~~

Build:

~~~powershell
cmake --build build-release -j 2
~~~

Core and tests without the GUI:

~~~powershell
cmake -S . -B build-core -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_BUILD_APP=OFF -DELOI_BUILD_TESTS=ON
cmake --build build-core -j 2
~~~

Exoskeleton:

~~~powershell
cmake -S . -B build-exoskeleton -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_BUILD_TESTS=ON -DELOI_SPLIT_PACKAGE=ON
cmake --build build-exoskeleton -j 2
~~~

The split package is Windows-only.

Experimental network include:

~~~powershell
cmake -S . -B build-experimental -G Ninja -DCMAKE_BUILD_TYPE=Release -DELOI_NNUE_INCLUDE_DIR=C:\candidate\include
~~~

The directory must contain eloi/nnue_weights.hpp.

An experimental header needs new provenance and qualification before release.

---

## Testing

Run CTest:

~~~powershell
ctest --test-dir build-release --output-on-failure --timeout 120
~~~

The core suite covers:

- FEN parsing;
- board restoration;
- push and pop;
- Standard rules;
- Chess960 generation;
- Chess960 castling;
- Horde rules;
- Zobrist restoration;
- NNUE restoration;
- scalar and SIMD agreement;
- SEE;
- TT semantics;
- search behavior;
- selective depth;
- forced replies;
- fifteen retained EPD regressions.

The GUI suite covers:

- setup;
- variant selection;
- castling interaction;
- promotion interaction;
- undo;
- screen state.

Python tools have scripts/test_*.py tests.

Run those relevant to a changed tool.

A timeout is a failure.

A skipped test is not evidence of a pass.

---

## Move-generation validation

Perft:

~~~powershell
.\build-release\Eloi.exe --perft --depth 4
~~~

Expected:

~~~text
197281
~~~

Divide:

~~~powershell
.\build-release\Eloi.exe --perft --depth 4 --divide
~~~

Differential validation:

~~~powershell
python -B scripts/differential_movegen.py --engine build-release/Eloi.exe --samples 32
~~~

The release procedure compares:

- 32 Standard positions;
- 32 Chess960 positions;
- 32 Horde positions.

That is 96 complete legal-move-set comparisons.

The future Caissa seam adds:

- Eloi Standard move set;
- Caissa Standard move set;
- canonical translated moves;
- round-trip state.

Any disagreement blocks strength testing.

---

## Reproducible builds

Eloi controls:

- source commit;
- dependency hashes;
- tool hashes;
- compiler;
- linker;
- CMake;
- Ninja;
- static libraries;
- source epoch;
- path remapping;
- compiler seed;
- LTO partitioning;
- PE timestamps;
- ZIP ordering;
- ZIP timestamps;
- ZIP attributes;
- compression level.

The fixed source epoch is:

~~~text
1787961600
2026-08-29 00:00:00 UTC
~~~

Release builds use one LTO partition.

Source and build paths are remapped.

Compiler randomness is seeded from the Eloi version.

PE timestamps are zeroed.

Verify the toolchain:

~~~powershell
pwsh -NoProfile -File .\scripts\verify-toolchain.ps1 -RequirePackageArchives
~~~

Read REPRODUCING.md before release work.

Established proof builds each package form twice.

It requires byte-identical payloads and archives.

It runs tests in every build.

It validates clean extraction.

It refuses output collisions.

Reproduction does not prove strength.

It does not replace security validation.

---

## Release packages

### Standalone contract

The ZIP contains exactly:

~~~text
Eloi.exe
config.yml
~~~

The token is empty.

No non-system DLL is required beside Eloi.exe.

### Exoskeleton contract

The split ZIP contains the application, separate bridge, runtime libraries,
artwork, notices, source identity, and hashes.

Its main Eloi.exe has no WinHTTP import.

Networking belongs to EloiLichess.exe.

### Release proof

A candidate should pass:

1. clean source export;
2. standalone build A;
3. standalone build B;
4. standalone byte comparison;
5. Exoskeleton build A;
6. Exoskeleton build B;
7. Exoskeleton byte comparison;
8. tests in every build;
9. content checks;
10. manifest verification;
11. clean extraction;
12. UCI readiness;
13. timed search;
14. stop handling;
15. clean exit;
16. GUI checks;
17. offline Lichess checks;
18. Defender scans;
19. final hash review.

Do not overwrite a running installation.

Do not publish without maintainer authorization.

---

## Release history

### v2.8.0

Published September 7, 2026.

Source:

~~~text
6ff04a8d5fa1fd87ec677c89ae52fdd61c8437aa
~~~

Changes:

- correct root recapture SEE context;
- return immediately for one legal move;
- report selective depth;
- add focused regression coverage;
- build GUI tests during reproducibility proof.

E2 did not change.

RootSplit did not change.

### v2.7.5

Published September 4, 2026.

Source:

~~~text
8362cfa88e60b04b7d1dc1e5ee880fd5cedbe3b9
~~~

It promoted E2-ranking.

### v2.5.0

Published September 3, 2026.

Source:

~~~text
24e8a4538fd1fcf164ad1747a62e91a01acdccec
~~~

It is the primary historical C-network reproducibility anchor.

### v2.0.0

Published September 1, 2026.

Its title records the old v1.9.6 candidate naming.

### v1.5.0-beta.1

Published August 31, 2026.

It is a prerelease.

### v1.0.0

Published August 29, 2026.

### Historical rule

Tags are immutable identities.

Do not move an old tag.

Do not rename an old binary and claim reproduction.

Do not erase an inconvenient failed experiment.

---

## Strength evidence

### E2 versus C

Disjoint final:

~~~text
45 wins
56 draws
24 losses
73 / 125 points
58.4%
~~~

Promotion confirmation:

~~~text
93 wins
94 draws
63 losses
140 / 250 points
56.0%
0 protocol failures
~~~

Both used 10,000 nodes per move.

They support E2 over C under that protocol.

### v2.8.0 versus v2.7.5

Fixed-node match:

~~~text
250 games
25,000 nodes per move
80 wins
104 draws
66 losses
132 / 250 points
52.80%
approximately +19.5 Elo by raw-score transform
0 protocol failures
~~~

Timed match before failure:

~~~text
38 completed games
250 ms per move
16 wins
12 draws
10 losses
22 / 38 points
57.89%
1 candidate failure
incomplete run
~~~

The maintainer accepted v2.8.0 despite that timed failure.

The release does not claim a completed 55% timed result.

It does not claim a statistically established +50 Elo gain.

Read RELEASE_V2_8_0.md and V275_PLUS50_RESULTS.md.

---

## Interpreting results

Always ask:

- How many games?
- Were openings mirrored?
- Were colors balanced?
- Were binaries hashed?
- Were resources equal?
- Were failures scored?
- Were PGNs replayed?
- Was the stopping rule frozen?
- Was confirmation disjoint?
- Was the run complete?

Chess score is:

~~~text
wins + 0.5 times draws
~~~

Raw wins and chess score are different metrics.

Twenty games can expose catastrophe.

Twenty games rarely measure small Elo differences.

Two hundred fifty games provide evidence.

They may still be inadequate for a narrow effect.

Paired openings and SPRT are preferred for future hybrid selection.

A strong score cannot waive an illegal move, crash, deadlock, timing violation,
wrong binary, or corrupted PGN.

---

## Repository map

~~~text
Eloi/
|-- CMakeLists.txt
|-- README.md
|-- LICENSE
|-- CONTRIBUTING.md
|-- REPRODUCING.md
|-- DATA_SOURCES.md
|-- FUTURE_WORK.md
|-- RELEASE_V2_5_0.md
|-- RELEASE_V2_7_5.md
|-- RELEASE_V2_8_0.md
|-- E2_STANDARD_CAMPAIGN.md
|-- V275_PLUS50_RESULTS.md
|-- constraints_on_SahilKDas_device.md
|-- reproducibility.lock.json
|-- config.example.yml
|-- include/eloi/
|-- src/
|-- tests/epd/
|-- scripts/
|-- data/
|-- assets/chess_maestro_bw/
|-- packaging/
|-- pkg/engine/uci/
~~~

Ignored development and private locations include .deps, tmp, build trees,
dist staging, local binaries, private config.yml, large datasets, and
checkpoints.

Ignored does not mean safe to delete blindly.

An ignored dependency may be active.

An ignored configuration may contain credentials.

An ignored executable may be serving a live game.

---

## Source-file guide

### CMakeLists.txt

Defines version 2.8.0, build options, generated version resources, core and app
targets, reproducible flags, GUI dependencies, package staging, and tests.

### include/eloi/chess.hpp

Declares chess types and public engine structures.

It carries state needed by Standard, Chess960, Horde, GUI, and search.

### include/eloi/config.hpp

Declares runtime configuration.

### include/eloi/nnue_architecture.hpp

Fixes the production hidden width at 64.

### include/eloi/nnue_weights.hpp

Contains exact E2-ranking quantized parameters.

It is evidence and should not be casually reformatted.

### include/eloi/opening_data.hpp

Contains the compiled weighted opening graph.

### include/eloi/version_match.hpp

Declares current-versus-previous comparison integration.

### include/eloi/version.hpp.in

Templates the generated source version header.

### src/chess.cpp

Contains the primary board, legality, move generation, search, TT, time, and
related engine implementation.

It is the largest hand-maintained C++ engine source.

Changes deserve narrow tests and careful benchmarks.

### src/nnue.cpp

Implements neural evaluation, accumulators, and optimized dispatch.

### src/book.cpp

Implements the embedded opening repertoire.

### src/config.cpp

Parses and validates runtime configuration.

### src/config_writer.cpp

Writes safe configuration for applicable package flows.

### src/main.cpp

Selects top-level runtime modes.

### src/driver.cpp

Implements UCI, perft, benchmark, and engine-driver behavior.

### src/search_diagnostic.cpp

Implements structured search diagnostics.

### src/gui.cpp

Implements the native Skia application.

### src/version_match.cpp

Implements the executable comparison arena.

### src/lichess.cpp

Implements native Lichess API and game flow.

### src/lichess_main.cpp

Provides the split bridge entry point.

### src/lichess_config_gui.cpp

Implements Exoskeleton bridge configuration.

### src/resources.rc

Defines embedded Windows resources.

### src/version.rc.in

Templates main executable metadata.

### src/version-lichess.rc.in

Templates bridge executable metadata.

---

## Test-file guide

### tests/tests.cpp

The principal C++ regression suite.

It covers rules, variants, restoration, evaluation, search, and regressions.

### tests/gui_smoke.cpp

The native GUI interaction suite.

### tests/tactical_data.hpp

Retained tactical fixtures.

### tests/live_feed.txt

Small feed-integration input.

### tests/epd/v2_5_regressions.epd

Fifteen retained release regressions.

They are correctness tests.

They are not training data.

They must not become a candidate selection set.

---

## Script guide

Read a script and its evidence before running it.

An old filename does not make an old campaign current policy.

### bootstrap-windows.ps1

Bootstraps locked Windows development dependencies.

It writes into ignored dependency storage.

It is not a runtime step.

### bootstrap-static-codecs.ps1

Prepares hash-pinned static GUI codec libraries.

### verify-toolchain.ps1

Verifies installed tools and retained archives.

### build-windows-release.ps1

Wraps standalone release staging.

### build-windows-split-zip.ps1

Builds the split Exoskeleton archive.

### build-windows-exoskeleton-zip.ps1

Provides the retained Exoskeleton package path.

### stage-current-candidates.ps1

Stages bounded candidate artifacts.

It must not overwrite protected releases.

### verify-reproducible.ps1

Checks controlled build reproducibility.

### release_v250.py

Implements the preservation-oriented v2.5.0 reproduction workflow.

Its historical thresholds are not universal future policy.

### test_release_v250.py

Tests release tool safety.

### engine_lab.py

Runs bounded current-versus-previous comparisons.

### test_engine_lab.py

Tests Engine Lab orchestration.

### selfplay_gauntlet.py

Runs bounded engine gauntlets.

Do not start it without declared resource limits.

### generate_openings.py

Generates controlled opening suites.

### generate_strength_suite.py

Generates retained strength inputs.

### capture-brain-baseline.ps1

Captures and identifies the preceding executable.

### differential_movegen.py

Compares complete legal-move sets.

### generate_tactics.py

Generates bounded tactical fixtures.

### validation_support.py

Provides shared EPD parsing and resource preflight.

### test_validation_support.py

Tests shared validation helpers.

### train_nnue.py

Implements generic bounded NNUE training.

Running it does not reproduce E2 without exact E2 inputs and protocol.

### test_train_nnue.py

Tests training machinery with synthetic artifacts.

It is not permission for a large campaign.

### analyze_nnue_dataset.py

Analyzes partitions and dataset properties.

### test_analyze_nnue_dataset.py

Tests dataset analysis.

### sample_nnue_sources.py

Samples accepted source channels.

### test_sample_nnue_sources.py

Tests sampling rules.

### acquire_nnue_samples.py

Acquires bounded permitted samples.

### fresh_nnue_data.py

Implements retained fresh-data preparation.

### test_fresh_nnue_data.py

Tests fresh-data processing.

### audit_fresh_nnue_training.py

Audits training outputs and procedure.

### audit_fresh_nnue_channels.py

Audits occupied and dormant channels.

### report_fresh_nnue_coverage.py

Reports coverage boundaries.

### test_fresh_nnue_coverage.py

Tests coverage reporting.

### test_fresh_nnue_channels.py

Tests channel auditing.

### run_fresh_nnue_campaign.py

Runs the retained campaign workflow.

It is historical unless a new protocol adopts it.

### continue_fresh_nnue_campaign.py

Continues a retained checkpoint under original rules.

### retain_fresh_nnue_evidence.py

Normalizes retained evidence.

### test_fresh_nnue_campaign.py

Tests campaign orchestration.

### nnue_e1_e32.py

Implements E1 dormant-channel and 32-unit experiments.

### test_nnue_e1_e32.py

Tests E1 and E32 tooling.

### nnue_e2.py

Implements the retained E2 campaign.

### test_nnue_e2.py

Tests E2 tooling.

### abc100_match.py

Implements the retained ABC100 frontend.

### test_abc100_match.py

Tests ABC100 match behavior.

### report_abc100.py

Reports ABC100 evidence.

### test_report_abc100.py

Tests ABC100 reporting.

### abc100_gui_fix.py

Records the retained GUI amendment path.

### abc100_board.html

Provides the local browser board for that historical frontend.

### freeze_e1_gauntlet.py

Freezes associated historical identities.

### Script safety rules

- Read before running.
- Use unique scratch.
- Refuse collisions.
- Respect the 10 GB cap.
- Respect the nested 8 GB training cap.
- Run one heavy workload.
- Use Idle priority.
- Protect active bridges.
- Preserve interrupted checkpoints.
- Never call partial output complete.

---

## Data and evidence guide

### DATA_SOURCES.md

Human-readable source, license, sampling, and provenance documentation.

### data/README.md

Index of current retained evidence.

### data/nnue_provenance.json

Machine-readable E2 identity.

### data/nnue_provenance_v2_5_0.json

Machine-readable C identity.

### data/nnue_provenance_pre_v2_5_0.json

Earlier provenance context.

### data/nnue_input_manifest.json

Accepted input identities.

### data/nnue_e2_standard_results.json

Complete E2 experiment record.

### data/nnue_e1_e32.json

E1 and E32 experiment record.

### Fresh-data records

Retained records cover acquisition, sampling, protocols, continuation, results,
audits, and coverage.

They document what happened.

They do not authorize restarting a campaign.

### ABC records

ABC60 and ABC100 records preserve protocols, results, audits, PGNs, timing
interruptions, and GUI amendments.

### Search recovery

data/search_recovery preserves diagnostic, development, confirmation, reserve,
and final evidence.

Rejected or reverted search work remains useful evidence.

It is not production behavior.

### strength_openings.json

Contains controlled opening inputs.

Partitions must remain separate from training and sealed confirmation.

### Data principles

- Record hashes.
- Record licenses.
- Record filters.
- Record rejected samples.
- Split by complete game.
- Prevent position leakage.
- Do not train on regressions.
- Do not select on sealed tests.
- Label incomplete evidence.
- Preserve production identity.

---

## Contributing

Read CONTRIBUTING.md first.

Read the device constraints before heavy work.

Read REPRODUCING.md before release work.

Before editing:

1. Check Git status.
2. Identify concurrent changes.
3. Protect private configuration.
4. Protect running processes.
5. Reproduce the problem.
6. Freeze a baseline for brain changes.
7. Define the smallest responsible scope.

C++ style:

- two-space indentation;
- descriptive names;
- RAII;
- limited hot-path allocation;
- clean warnings;
- scalar fallbacks;
- explicit variant logic;
- focused tests;
- honest limitations.

A change description should explain problem, cause, solution, tests, commands,
performance, strength evidence, remaining risk, packaging, and licensing.

Documentation does not create Elo.

Correctness work does not create Elo without measurement.

A match does not create release readiness without other gates.

---

## Engineering invariants

### Playing

- Exactly three production search threads.
- Standard remains legal.
- Chess960 remains legal.
- Horde remains legal.
- Push and pop restore state.
- PVs remain legal.
- Mate scores remain normalized.
- Stop returns safely.
- Hash stays within budget.
- Scalar and SIMD NNUE agree.
- Fifteen EPD regressions pass.

### Runtime

- No required Python runtime.
- No runtime network download.
- No implicit NNUE regeneration.
- No external playing backend.
- No configurable token origin.
- No published token.
- No unsolicited pre-UCI output.

### Release

- Source is committed.
- Version comes from CMake.
- Two Windows package forms exist.
- Independent builds agree.
- Fresh extractions pass.
- Contents match policy.
- Hashes are reviewed.
- Defender scans are fresh.
- Historical tags do not move.

### Experiment

- Baselines are hashed.
- Protocols freeze before play.
- Resources are equal.
- Openings are controlled.
- Interruptions are recorded.
- Failures remain failures.
- Tuning and confirmation differ.
- Post-hoc changes are disclosed.

---

## Device limits

The binding contract is constraints_on_SahilKDas_device.md.

Recorded laptop:

- HP Pavilion 15-eg2xxx;
- Intel Core i7-1255U;
- 10 physical cores;
- 12 logical processors;
- about 15.68 GiB visible RAM;
- NVIDIA MX550 with 2 GiB VRAM;
- Intel Iris Xe;
- Windows 11 Home x64.

Hard limits:

| Resource | Limit |
| --- | --- |
| Search threads per process | Exactly 3 |
| All temporary Eloi data | 10,000,000,000 bytes |
| Temporary NNUE subset | 8,000,000,000 bytes inside the total |
| Concurrent bridges | At most 2 |
| Concurrent GUIs | At most 2 |
| Heavy Linux or ARM environments | New permission required |

The 8 GB allowance is not additional.

The trainer's 7 GiB limit remains stricter where applicable.

Run one heavy workload at a time.

Declare time, game, and storage bounds.

Measure before writing.

Use Idle priority for long background work.

Protect active play.

Stop before a quota is exceeded.

---

## Security and privacy

A Lichess token is a credential.

Keep it only in private ignored config.yml.

Do not place it in commits, screenshots, logs, issues, releases, fixtures, or
examples.

The native client accepts only the intended HTTPS origin.

Development dependencies are hash-pinned.

Never weaken a hash to accept an unexpected file.

Scan ZIPs and complete extracted packages.

Do not use antivirus exclusions during proof.

A permissive donor license does not prove secure behavior.

Imported code needs:

- a bounded allowlist;
- dependency review;
- provenance review;
- protocol containment;
- crash containment;
- network-I/O review;
- package review.

---

## Licenses

Eloi source is MIT-licensed.

See LICENSE.

Skia uses BSD 3-Clause.

The twelve Maestro PNGs are CC BY 4.0 artwork from Kadagaden.

Preserve assets/chess_maestro_bw/ATTRIBUTION.md.

Opening and training attribution is in DATA_SOURCES.md.

Stockfish supplied historical offline labels only.

It is not a runtime backend.

Eloi began as a fork of Morlock.

Future Caissa files retain Caissa's copyright and MIT notice.

Eloi does not accept AGPL source.

Reckless may be an external opponent.

Its source is not a donor.

Translating licensed code does not erase its license.

Ideas may be independently implemented from permitted sources.

Copied implementation remains governed by its license.

---

## Known limitations

Official packages are Windows x64 only.

Binaries are unsigned.

Production threads are fixed at three.

Very deep searches can take impractical time.

The v2.8.0 timed match failed during game 38.

The maintainer accepted that risk explicitly.

Fresh-label coverage intentionally omitted several tactical categories.

E2 was trained only on Standard chess.

Tablebases are not shipped.

Caissa is not in current main.

The previous hybrid was rejected.

The next Caissa plan starts from different donor assumptions.

It inherits no strength credit.

---

## The Caissa 1.25 plan

The next large experiment is planned as:

~~~text
Eloi 2.8.0
    +
Caissa 1.25 code
    +
Caissa 1.25 evaluator and network generation
    +
an Eloi-owned hybrid arbiter
~~~

The official upstream release is
[Caissa 1.25](https://github.com/Witek902/Caissa/releases/tag/1.25).

The official tag is:

~~~text
1.25
~~~

The pinned upstream commit is:

~~~text
0c01e79ea36ae492585e88cca9d03abae9b7a3d5
~~~

Planning notes may informally write 1.2.5.

The upstream identity is 1.25.

Automation and manifests must use the real tag.

### Current status

- Planning is active.
- Implementation on main has not started.
- Current donor code is absent.
- Current donor network is absent.
- No hybrid package exists.
- No hybrid release exists.
- No hybrid strength claim exists.

### Intended result

The goal is a genuine two-brain Eloi.

It is not intended to rename Caissa.

It is not intended to delete E2.

It is not intended to replace Eloi's GUI.

It is not intended to replace Eloi's UCI layer.

It is not intended to replace Eloi's Lichess client.

It is not intended to copy every donor file.

The intended ownership is:

- Eloi owns the game;
- E2 remains a complete brain;
- Caissa 1.25 becomes a complete second brain;
- an Eloi arbiter selects candidates;
- Eloi validates every public move.

---

## Why Caissa 1.25

Caissa 1.25 is a coherent donor generation.

It provides:

- C++ source;
- an MIT project license;
- a 32-king-bucket evaluator generation;
- matching search and evaluation semantics;
- multithreaded search;
- shared correction histories;
- singular extensions;
- continuation-history refinements;
- optimized move generation;
- NNUE accumulators;
- an official Windows reference executable.

The tag points to:

~~~text
0c01e79ea36ae492585e88cca9d03abae9b7a3d5
~~~

The official AVX2/BMI2 release asset SHA-256 is:

~~~text
51929274A45CFC3057C35B07087EE9806E482DDCF64F0659EEDCDABF0FEA51FF
~~~

The official executable historically exposed an embedded eval-71 network.

The previously extracted identity was:

~~~text
Name: eval-71.pnn
Size: 50,367,040 bytes
SHA-256: 615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B
~~~

Those identities must be independently revalidated.

They do not waive a new provenance record.

### Why not Caissa 1.26

Caissa 1.26 moved models into the separate
[Caissa-Nets](https://github.com/Witek902/Caissa-Nets) repository.

The files are visible and downloadable.

The repository currently declares no license.

Visible does not mean licensed.

Public does not mean redistributable.

Eloi will not package the Caissa 1.26 network without explicit permission.

The new plan also avoids mixing 1.26 search with a 1.25 evaluator.

Instead it pins the full donor brain to the coherent 1.25 era.

### Legal caution

Caissa source is MIT-licensed.

Substantial copied portions retain the copyright and permission notice.

The exact basis for redistributing extracted network bytes must be recorded
explicitly and conservatively.

This README is engineering documentation, not legal advice.

For v3.0.0, the maintainer accepts that official v1.25 distribution as the
redistribution basis; the Caissa MIT notice remains bundled.

---

## The rejected hybrid

Eloi already attempted a different hybrid.

It remains in Git history but is absent from current main.

It used:

~~~text
Caissa 1.26 search code
Caissa 1.25 eval-71 network
Eloi E2
an isolated worker
hybrid arbitration
~~~

It was not the planned full Caissa 1.25 brain.

### What succeeded

The experiment achieved:

- donor containment;
- explicit import allowlisting;
- network hash validation;
- qualification-package embedding;
- no automatic download;
- FEN round trips;
- legal-move equality over 256 seeded Standard positions;
- castling tests;
- en-passant tests;
- promotion tests;
- clock tests;
- history and repetition tests;
- all fifteen Eloi regressions;
- perft 197,281;
- 96 of 96 variant differential positions;
- UCI readiness;
- timed moves;
- stop handling;
- clean exit;
- worker crash containment;
- two builds of each package form;
- byte-identical qualification archives.

Those successes prove the engineering was real.

They do not rescue the playing result.

### What failed

The frozen strength gate used:

~~~text
20 games
250 ms per move
3 threads per engine
32 MB hash per engine
200-ply maximum
exact v2.7.5 baseline
~~~

The result was:

~~~text
1 win
3 draws
16 losses
2.5 / 20 chess points
5% raw win rate
12.5% chess score
0 protocol failures
~~~

The frozen gate required at least ten wins.

The candidate failed decisively.

It was rejected.

No release should call it v2.9.0.

### Earlier unlicensed-network results

An earlier 1.26-network hybrid scored much better in two historical 150-game
runs.

That network came from the unlicensed Caissa-Nets path.

Those results cannot authorize redistribution.

They also cannot qualify another network.

Changing a network changes the engine.

Changing activation semantics changes the engine.

Changing calibration changes arbitration.

Every materially changed binary must requalify.

### Lessons

The attempt demonstrated:

- correctness can pass while strength collapses;
- mixed search and evaluator generations can fail badly;
- process isolation can contain crashes;
- three-thread scheduling complicates exact parity;
- donor node counting can overshoot;
- calibration changes decisions;
- reproducibility does not imply strength.

The full-1.25 plan carries those lessons forward.

---

## Future two-brain architecture

~~~text
                    Public frontends
               GUI / UCI / native Lichess
                           |
                           v
                 Eloi authoritative game
                 board / history / clocks
                           |
                           v
                    ProductionBrain
                           |
                 Standard chess only?
                    /              \
                  no                yes
                  |                  |
                  v                  v
             Eloi E2 brain      Hybrid arbiter
                                  /       \
                                 v         v
                          Eloi E2 brain  Caissa 1.25
                                 \         /
                                  v       v
                              candidate set
                                   |
                                   v
                         Eloi legal validation
                                   |
                                   v
                              public bestmove
~~~

### Eloi core owns

- public FEN parsing;
- complete move history;
- repetition history;
- legal moves;
- variants;
- clocks;
- UCI;
- GUI;
- Lichess;
- public score policy;
- final validation;
- fallback.

### Eloi brain owns

- E2 evaluation;
- current Eloi search;
- RootSplit;
- Eloi TT;
- variants;
- emergency fallback.

### Caissa brain owns

- internal position;
- move encoding;
- move generation;
- search;
- TT;
- histories;
- evaluator;
- workers;
- model validation;
- neutral result translation.

### Arbiter owns

- total budget division;
- agreement detection;
- candidate union;
- verification;
- WDL normalization;
- mate vetoes;
- pessimistic combination;
- failure policy;
- final selection;
- diagnostics.

### Public boundary

Caissa never prints public bestmove directly.

Caissa never controls the GUI.

Caissa never owns the Lichess clock.

Caissa never sends HTTP.

Caissa never receives Horde initially.

Every proposal crosses Eloi's legal parser.

---

## Integration gates

### Gate zero: freeze Eloi

Record:

- Eloi 2.8.0 commit;
- executable hash;
- package hashes;
- E2 header hash;
- benchmark;
- tests;
- UCI transcript;
- known failures.

### Gate one: freeze Caissa 1.25

Record:

- tag 1.25;
- commit 0c01e79ea36ae492585e88cca9d03abae9b7a3d5;
- source archive hash;
- per-file manifest;
- MIT license;
- import allowlist;
- official binary hashes;
- model identity;
- evaluator semantics;
- compiler flags.

### Gate two: define the interface

Wrap Eloi before importing donor behavior.

Wrapped Eloi must match direct Eloi.

Brain inputs include:

- authoritative position;
- complete relevant history;
- variant;
- root filter;
- node limit;
- soft deadline;
- hard deadline;
- thread allowance;
- hash allowance;
- stop token;
- verbosity.

Brain results contain candidates.

Each candidate contains:

- move;
- PV;
- score;
- score kind;
- score bound;
- root-side perspective;
- depth;
- selective depth;
- nodes;
- elapsed time;
- mate information;
- defined confidence information.

### Gate three: bounded donor closure

Vendor only required files.

Never use recursive source globbing.

Retain every imported path in a manifest.

Initially exclude:

- Caissa UCI frontend;
- trainer;
- self-play;
- downloader;
- packaging;
- unused platforms;
- tablebases unless separately approved;
- unrelated tools.

NUMA may need a single-node compatibility layer.

Caissa search types reference NUMA allocation abstractions.

Do not rip them out blindly.

Retain backend MultiPV.

The arbiter needs alternatives.

Only remove its public UCI presentation.

### Gate four: position synchronization

FEN alone is insufficient.

FEN does not encode repetition history.

The first adapter replays:

- initial position or FEN;
- every authoritative move;
- the reversible history window;
- clocks;
- fifty-move state.

Incremental synchronization comes later.

### Gate five: move translation

For every Caissa move:

1. Convert to canonical UCI.
2. Parse against Eloi's board.
3. Require exactly one legal match.
4. Reject missing translation.
5. Reject ambiguous translation.
6. Record the failure.
7. Fall back safely.

Promotion identity survives translation.

Castling identity survives translation.

En passant identity survives translation.

### Gate six: model loading

The development path is explicit.

The loader:

- verifies size;
- verifies SHA-256;
- rejects mismatch;
- rejects absence cleanly;
- avoids directory discovery;
- avoids build downloads;
- avoids runtime downloads;
- never accepts a newer model silently.

Embedding waits for license and package gates.

### Gate seven: isolated parity

Compare embedded Caissa 1.25 with official 1.25.

Use one thread for deterministic parity.

Use three threads for legal behavior, timing, resources, and distributions.

Do not demand impossible deterministic equality from scheduling noise.

### Gate eight: crash containment

A donor crash must not silently kill public Eloi.

The previous worker process contained forced termination.

That architecture deserves reuse consideration even though its chess candidate
was rejected.

### Gate nine: packaging

No donor material ships until:

- source licensing passes;
- model licensing passes;
- attribution passes;
- reproducibility passes;
- runtime hashes pass;
- extraction passes;
- security passes.

---

## Hybrid arbitration

Raw Eloi and Caissa centipawns are not comparable.

The same number means different expected outcomes.

Each brain needs independent WDL calibration.

### Candidate collection

Each brain returns:

- best move;
- second move when available;
- PV per move;
- score per move;
- completion status.

### Agreement

If both choose the same legal move, accept agreement without spending the full
disagreement budget.

Unused time still obeys the hard deadline.

### Disagreement

1. Union both top-two lists.
2. Deduplicate by Eloi move identity.
3. Reject illegal candidates.
4. Allocate bounded verification.
5. Inspect candidates with both brains or root filters.
6. Normalize to the original root side.
7. preserve mate results discretely.
8. veto convincingly forced losses.
9. combine calibrated outcomes pessimistically.
10. choose the best survivor.
11. validate again.

### Perspective

Every score declares perspective.

A child position changes the side to move.

Misreading perspective can invert the decision.

Normalize to the original root player.

### Bounds

Exact, lower, and upper bounds differ.

Do not average them as exact values.

### Mate

Mate remains discrete.

Do not feed mate through ordinary cp calibration.

Conflicting mate claims trigger verification.

### Calibration

Each brain gets its own mapping.

Calibration data is:

- separate from tuning;
- split by game;
- tied to binaries;
- tied to models;
- tied to budget;
- evaluated out of sample.

Report log loss, Brier score, calibration error, and reliability.

Changing the model invalidates Caissa calibration.

---

## Hybrid resource accounting

The machine permits exactly three search threads per engine process.

The hybrid must not become a hidden six-core engine.

### Sequential schedule

1. Caissa uses three active threads.
2. Caissa reaches a stop barrier.
3. Eloi uses three active threads.
4. Eloi reaches a stop barrier.
5. The arbiter spends bounded verification.

Sleeping workers and active workers must be distinguished.

If the invariant means three total OS search threads, dual persistent pools are
not acceptable.

If it means three active workers, a shared gate can work.

The protocol must say which.

### Candidate allocations

The original planning candidate was:

~~~text
70% Caissa
20% Eloi
10% verification
~~~

It is not sacred.

Other frozen candidates may include:

~~~text
75 / 25 / 0
80 / 10 / 10
65 / 25 / 10
confidence-triggered verification
Caissa-first cascade
~~~

Every candidate receives equal aggregate resources.

### Candidate explosion

Two moves from each brain create at most four unique moves.

Two brains inspecting four moves can mean eight tiny searches.

Short controls may spend most time on setup.

Define:

- maximum candidates;
- minimum verification budget;
- TT reuse;
- root filtering;
- early stopping;
- duplicate handling.

### Hash

The engines need private TT formats.

Hash is partitioned.

Example only:

~~~text
Public Hash: 64 MB
Caissa TT: 44 MB
Eloi TT: 20 MB
Total: 64 MB
~~~

Alignment and minimum sizes affect the final split.

Never give 64 MB to both.

### Deadline

Subtract overhead once.

The arbiter owns the hard deadline.

Initialization, IPC, translation, and final validation consume real time.

They belong inside the budget.

---

## Hybrid correctness

Strength starts only after correctness closes.

### Board tests

- start-position parity;
- arbitrary FEN parity;
- castling rights;
- en passant;
- promotion;
- halfmove clock;
- fullmove number;
- repetition history;
- legal move sets;
- translation round trips;
- push and pop;
- mate;
- stalemate.

### Corpus coverage

Include:

- quiet middlegames;
- tactical positions;
- checks;
- double checks;
- pins;
- castling;
- en passant;
- promotions;
- underpromotions;
- repetitions;
- fifty-move boundaries;
- mate in one;
- mated roots;
- stalemate;
- insufficient material;
- long histories.

### Protocol tests

- clean startup;
- no pre-UCI noise;
- isready;
- ucinewgame;
- depth;
- nodes;
- movetime;
- clocks;
- stop;
- quit;
- forced move;
- no move;
- malformed donor output;
- timeout;
- crash;
- wrong network;
- missing network.

### Resource tests

- three active threads maximum;
- aggregate hash compliance;
- no worker growth;
- no zombie process;
- hard deadline;
- bounded node overshoot;
- bounded scratch;
- bounded logs.

### Existing Eloi tests

- all C++ tests;
- all GUI tests;
- perft 197,281;
- fifteen EPD regressions;
- 96 differential positions;
- Standard GUI;
- Chess960 bypass;
- Horde bypass;
- offline Lichess configuration;
- standalone extraction;
- Exoskeleton extraction.

### Determinism

One-thread donor parity may be exact.

Three-thread Caissa is not assumed deterministic.

Separate:

- exact requirements;
- legal-output requirements;
- distribution observations;
- performance tolerances;
- strength statistics.

Do not write an impossible gate and waive it later.

---

## Hybrid qualification

The new experiment inherits no strength credit.

The rejected games remain history.

The unlicensed-network games remain history.

Neither qualifies a new binary.

### Phase A: donor sanity

Compare embedded 1.25 with official 1.25.

Prefer evaluation parity, depth-one parity, legal PVs, deterministic
single-thread tests, and bounded three-thread observations.

### Phase B: arbiter screens

Screen a small predeclared set.

Use mirrored openings.

Separate screening from confirmation.

Reject catastrophes early.

Do not move thresholds after seeing results.

### Phase C: confirmation

The baseline is Eloi 2.8.0.

Freeze and hash it.

Equalize:

- total time or nodes;
- active threads;
- aggregate hash;
- opening pairs;
- adjudication;
- failure scoring.

### Phase D: Caissa-only comparison

The hybrid must justify what it does to Caissa.

If Caissa-only dominates under equal resources, the arbiter may simply waste
time on a weaker opinion.

That negative result is valid.

### Statistics

Use paired openings and pentanomial statistics.

Prefer SPRT with frozen hypotheses.

Example hypotheses for review:

~~~text
Hybrid versus Eloi 2.8.0
H0: 0 Elo
H1: +20 Elo

Hybrid versus Caissa-only
H0: -15 Elo
H1: 0 Elo
~~~

Short matches are screening tools.

They are not precise estimates.

### Failures

Predefine treatment of:

- crash;
- timeout;
- illegal move;
- missing move;
- malformed UCI;
- worker death;
- watchdog termination;
- unfinished game;
- laptop sleep;
- controller failure.

Do not remove failed games because they look bad.

### Release decision

A release requires:

- correctness;
- provenance;
- licensing;
- resource compliance;
- crash containment;
- reproducibility;
- security;
- frozen strength success;
- honest non-inferiority interpretation.

If Caissa-only wins, retain the experiment in a lab branch.

Do not ship a weaker Frankenstein just because it is interesting.

---

## Hybrid licensing

The donor is selected partly because MIT aligns with Eloi.

Accepted:

- Eloi MIT source;
- Caissa 1.25 MIT source with notice;
- Eloi-owned adapters;
- Eloi-owned arbitration;
- reviewed compatible dependencies;
- explicitly licensed models.

Not accepted:

- AGPL source;
- mechanically translated AGPL source;
- copied code with notices removed;
- unlicensed weights;
- downloads used to evade review;
- conflicting provenance;
- uncontrolled source globs.

Future THIRD_PARTY_NOTICES.md records:

- upstream project;
- author;
- release;
- commit;
- imported files;
- modifications;
- license;
- model identity;
- model license basis.

Visibility is not enough.

Downloadability is not enough.

Public is not enough.

The model needs explicit redistribution permission.

---

## Frequently asked questions

### Is Eloi 2.8.0 available now?

Yes.

Use the v2.8.0 release page.

Verify the archive hash.

### Is Caissa already inside Eloi?

No.

Current main contains E2 only.

### Was there a Caissa experiment?

Yes.

It survives in Git history.

It was rejected and removed from production main.

### Why start again with Caissa 1.25?

The rejected candidate mixed 1.26 search with a 1.25 network.

The new plan uses a coherent 1.25 generation.

### Why not use Caissa 1.26?

Its separately distributed network repository has no declared license.

Eloi will not redistribute that model without permission.

### Is the version 1.2.5 or 1.25?

The official upstream tag is 1.25.

Use 1.25 in manifests, code, scripts, and documentation.

### What exactly is E2?

E2-ranking is Eloi's selected 64-unit neural evaluator.

It descended from C.

It mixed C and Stockfish offline targets.

It emphasized difficult move-ranking pairs.

It passed a disjoint 125-game final and a separate 250-game confirmation.

Its exact hashes are documented above and in provenance JSON.

### Is E2 a search engine?

No.

E2 evaluates positions inside Eloi's search.

### Is E2 the same as Eloi 2.8.0?

No.

E2 is the evaluator.

Eloi 2.8.0 combines E2 with board logic, search, GUI, UCI, Lichess, and fixes.

### Was E2 trained on Horde?

No.

### Was E2 trained on Chess960?

No.

### Why does it still run those variants?

The network is integrated into variant-aware Eloi code.

Mechanical tests protect legality and state.

Playing quality in untrained variants remains a limitation.

### Does Eloi use Stockfish at runtime?

No.

Stockfish supplied historical offline labels only.

### Does Eloi require Python?

Not to play.

Python is a development dependency.

### Does Eloi download its network?

No.

Production weights are compiled in.

### Why keep two board representations in the hybrid?

A complete Caissa brain depends on its own internal types and semantics.

Keeping it coherent reduces accidental search rewrites.

The adapter cost is accepted and tested.

### Why is FEN not enough?

FEN lacks repetition history.

The adapter must replay moves or supply equivalent history.

### Why not share a TT?

The engines have different keys, moves, entries, scores, and replacement rules.

They share a memory budget, not entries.

### Why run brains sequentially?

Parallel three-thread brains would be a hidden six-thread engine.

The device contract permits three active search threads.

### Why not average centipawns?

Evaluator scales differ.

Raw averages are meaningless.

Each brain needs independent outcome calibration.

### What happens if Caissa crashes?

The intended controller records failure and returns legal Eloi fallback when
the remaining deadline allows it.

Process isolation is under consideration.

### Why retain the rejected worker architecture?

Its playing result failed.

Its containment behavior succeeded.

Good infrastructure can survive a bad candidate.

### Will Chess960 use Caissa?

Not initially.

### Will Horde use Caissa?

Not initially.

Horde remains E2-only.

### Can Threads be increased to twelve?

Not under the production contract.

### Can Hash be set to zero?

The UCI parser permits zero.

Practical behavior should be validated for the intended mode.

### Can I request depth 17,697?

The parser ceiling permits it.

The search is unlikely to complete in ordinary time.

### Is Eloi signed?

No.

Verify hashes and scan packages.

### Where does a Lichess token belong?

Only in private ignored config.yml.

### Should config.yml be committed?

No.

Commit the empty-token example only.

### Can AGPL code enter Eloi if translated to C++?

No.

Translation does not erase licensing.

### Can Reckless play against Eloi?

Yes, as an external process under an appropriate tournament setup.

Its source is not merged.

### Is Apache code accepted?

A future decision can consider permissive Apache-2.0 components with notices.

The planned donor here is MIT Caissa 1.25.

### Does MIT mean attribution can be removed?

No.

The copyright and permission notice must remain with substantial copies.

### Does a successful build qualify a hybrid?

No.

The rejected hybrid built and packaged successfully.

It still failed strength.

### Does a winning match qualify a release?

No.

Correctness, licensing, reproducibility, and security still matter.

### Why keep failure records?

They prevent repeated mistakes.

They also prevent accidental overclaiming.

### Where is current future work?

FUTURE_WORK.md.

It is an index, not permission for unbounded work.

### Where is release procedure?

REPRODUCING.md and the release-specific decision files.

### Where is E2 provenance?

DATA_SOURCES.md, data/nnue_provenance.json, and E2_STANDARD_CAMPAIGN.md.

### Where is v2.8 evidence?

RELEASE_V2_8_0.md and V275_PLUS50_RESULTS.md.

---

## Glossary

### Alpha-beta

A search method that skips branches unable to affect the minimax decision.

### Arbiter

The planned Eloi-owned component that compares E2 and Caissa candidates.

### Aspiration window

A narrow search score interval centered on an expected result.

### Baseline

The exact frozen executable against which a candidate is compared.

### Best move

The legal root move selected after search and validation.

### Bound

A score classified as exact, lower, or upper.

### Brain

A complete search and evaluation stack capable of proposing moves.

### C

The Eloi v2.5.0 production neural network and parent of E-series work.

### Caissa

The MIT chess engine by Michał Witanowski selected as planned donor.

### Candidate

A move, model, binary, strategy, or release under evaluation.

### Centipawn

A conventional score unit nominally equal to one hundredth of a pawn.

Different evaluators use different practical scales.

### Chess score

Wins plus half of draws.

### Chess960

A chess variant with 960 starting arrays and generalized castling.

### Clean build

A build from fresh source export and controlled dependencies.

### Confirmation

A frozen evaluation after screening or tuning.

### Correction history

A search table that adjusts evaluation from prior search outcomes.

### CReLU

Clipped rectified linear activation used by the Caissa 1.25 evaluator era.

### Depth

Nominal search horizon in plies.

### Differential move generation

Complete legal-move-set comparison across implementations.

### E1

The first dormant-channel revival experiment descended from C.

### E2

The second major E-series campaign.

E2-ranking is the selected production member.

### E32

Experiments that represented or trained Eloi networks at 32 units.

### En passant

A pawn capture whose availability depends on the immediately preceding move.

### EPD

Extended Position Description used for retained regression positions.

### Exoskeleton

The split Windows package with separate bridge and external resources.

### FEN

Forsyth-Edwards Notation for position state and clocks.

It does not carry complete repetition history.

### Fixed-node search

Search limited by visited nodes rather than wall-clock time.

### Hard deadline

A limit after which search must stop promptly.

### Horde

A variant with a kingless White pawn horde and asymmetric win conditions.

### Hash

Common UCI shorthand for TT memory.

### History heuristic

A table that learns which moves historically caused useful cutoffs.

### Incremental accumulator

NNUE state updated from moves instead of rebuilt at every node.

### Iterative deepening

Repeated searches at increasing depth.

### Legal move

A move valid under the complete current state and variant.

### LMR

Late-move reductions.

Later low-priority moves initially receive reduced depth.

### Mate score

A discrete score representing forced mate and usually its distance.

### Mirrored openings

Opening pairs played with colors reversed.

### Move overhead

Time reserved for non-search work.

### MultiPV

Search that returns multiple principal variations.

### Neural provenance

Model origin, license, training lineage, hashes, and transformations.

### NNUE

Efficiently Updatable Neural Network.

### Node

A search position.

### Null move

A guarded search technique that temporarily passes a turn.

### Perft

A legal leaf-node count at fixed depth.

### Pessimistic combination

An arbiter rule emphasizing the weakest calibrated assessment.

### Pinned dependency

A dependency identified by exact immutable revision and hashes.

### Ply

One half-move.

### Principal variation

The line search currently considers best.

### PVS

Principal-variation search.

### ProbCut

Selective pruning using a shallow result and margin to predict a cutoff.

### Promotion

Replacing a final-rank pawn with queen, rook, bishop, or knight.

### Provenance

Documented origin and transformation history.

### Quiescence

Tactical continuation beyond nominal depth to reduce horizon effects.

### Repetition history

Prior position sequence needed for repeated-position draws.

### Reproducible build

Independent controlled builds producing byte-identical artifacts.

### RootSplit

Eloi's deterministic three-lane root-parallel search.

### SCReLU

Squared clipped rectified activation used by Caissa 1.26.

### SEE

Static-exchange evaluation.

### Selective depth

Deepest reached ply after selective search effects.

### Shredder-FEN

A Chess960-aware FEN convention identifying castling rooks by file.

### SIMD

CPU instructions applying one operation across multiple values.

### Singular extension

An extension for a move that appears uniquely stronger.

### Soft deadline

A target deciding whether another iteration is worthwhile.

### SPRT

Sequential Probability Ratio Test used for engine comparisons.

### Standalone

The two-file Eloi Windows package.

### Static library

A library linked into the executable at build time.

### TT

Transposition table.

### UCI

Universal Chess Interface.

### WDL

Win, draw, and loss expectation.

### Zobrist hash

An incrementally maintained position key.

---

## Acknowledgements

Eloi began as a fork of
[Morlock](https://github.com/herohde/morlock).

Thank you to
[Henning Rohde](https://github.com/herohde)
and
[Dr. Ryan Heuser](https://github.com/quadrismegistus)
for the foundation.

Thank you to
[Michał Witanowski](https://github.com/Witek902)
for creating and open-sourcing
[Caissa](https://github.com/Witek902/Caissa).

Caissa 1.25 is the Standard-search donor in Eloi 3.0.0.

Its MIT notice and network identity remain prominent in both package forms.

Thank you to Kadagaden for Maestro chess-piece artwork under CC BY 4.0.

Thank you to
[Resera](https://discord.gg/36JDXtjgCn)
for supporting Eloi's bot account.

Thank you to everyone who reports illegal moves, crashes, timing failures,
packaging problems, reproducibility mismatches, and weak positions.

The spectacular games are fun.

Precise bug reports are how the engine survives.

---

## Final note

Eloi 3.0.0 combines Eloi's authoritative board, legal-move validation, variants,
GUI, UCI, and bridge ownership with a crash-contained Caissa 1.25 Standard
search brain. Standard UCI play uses the mate-safe hybrid policy; Chess960 and
Horde remain on Eloi's E2 search until separate donor adapters qualify.

The bundled `eval-71-v1.25.pnn` is byte-identical to the network extracted from
the official Caissa v1.25 release executable. Its SHA-256 is
`615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`.
Caissa's MIT notice ships with the network and imported source.

At 10,000 nodes per move, the selected policy scored 20W/0D/0L against v2.7.5
and 19W/1D/0L against v2.8.0 in separate bounded 20-game screens. These are
strong preliminary results, not a statistically reliable Elo estimate. The
rejected calibration and veto policies remain documented as failures.

Production packages contain no runtime model downloader. A missing or
hash-mismatched donor network fails closed rather than silently changing the
engine identity.
