# Fresh-data NNUE campaign — 2026-09-02

## Authority and non-negotiable boundaries

The user authorized a new training campaign while away for approximately eight
hours, with at most 8,000,000,000 training bytes inside 10,000,000,000 total
temporary bytes. Retain the existing trainer's stricter 7 GiB limit. No deletion
of existing files, production-network replacement, installation, packaging,
push, or publication is authorized here. Search and the 64-unit architecture
remain fixed. This is a new dataset campaign, not a reopening or alteration of
the rejected search-recovery protocol.

The user subsequently prohibited Stockfish code and a Stockfish backend. Eloi
must remain an independent engine. The user then explicitly clarified:
"Stockfish acceptable solely for offline training labels". Stockfish 17.1 may
therefore be used in an isolated offline labeling process only; no Stockfish
source, library, or playing dependency enters Eloi.

Initial HEAD: c22535b; clean worktree, six local commits ahead of origin/main.
Production weights: CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E.
Initial conservative temporary usage: 725,956,363 bytes. No active Eloi,
Stockfish, or Python engine jobs were found. Stop launching new heavy jobs after
2026-09-02 22:35 UTC; preserve resumable state and report any unfinished work.

## Replacement source

Use the complete January 2025 Lichess Elite PGN archive from
https://database.nikonoel.fr/lichess_elite_2025-01.zip, not another prefix of the
old Lichess evaluation/puzzle files. The publisher describes post-December-2021
selection as 2500+ against 2300+, excluding bullet:
https://database.nikonoel.fr/ . Original game source:
https://database.lichess.org/ . Preserve source attribution and hash the fetched
bytes; do not imply that a locally computed hash is an upstream signature.

Traverse the complete compressed PGN member and select games by deterministic
hash priority. Parse only the selected games into positions, retaining several
phases per game. Group train/validation/test by game, discard cross-partition
duplicate board states, and exclude existing regression and match-opening FENs.
Never infer that a strong player's actual move is automatically the best move.
Game results alone are not equivalent to accurate position evaluations.

The data is *intended* to improve coverage and label consistency; whether it is
better must be measured. High player ratings alone do not establish label
quality or NNUE strength.

## Experimental direction

Before scaling, inspect score perspective, tactical stability, mate treatment,
ordinary-position calibration, and the effect of the trainer's evaluation-then-
puzzle sequence. Retain before/after-puzzle checkpoints when training is run.
Do not label test positions by their known regression answer, tune against the
sealed final openings, or claim statistical improvement from puzzle success.

The immutable training and selection protocol is now frozen in
`data/nnue_fresh_data_protocol.json`, before candidate training.
Use independent candidate build directories and never swap production headers
in place. Run deterministic engine gates early. Only eligible candidates may
advance to bounded mirrored development, independent confirmation, and a fixed
300-game final against the exact published v2.0 binary. Keep 55%/165 points as
the final release threshold and report uncertainty. No release is implied by
this campaign.

## Continuation

### Pre-training resource amendment

After measuring approximately 20 labeled positions/second, the retained target
was reduced from 100,000 to 40,000 accepted positions to leave time for training
and engine validation during the remaining campaign window. This was decided
before training any candidate or playing any match, based solely on runtime.
The original protocol is preserved in
`data/nnue_fresh_data_protocol_before_budget_adjustment.json`. Label confidence,
partitioning, recipes, selection rules, and all game counts/thresholds are
unchanged. Previously completed labels remain in the resumable checkpoint.
Only the campaign's verified offline Stockfish child was stopped to reload this
configuration; no Eloi or bridge process was stopped.

### Verified acquisition and initial audit

The complete archive contained 289,776 games. Hash sampling retained 32,000
games and 150,690 positions: 120,630 train, 15,133 validation, 14,927 test. The
sampler removed 414 cross-partition duplicate board states. Phase counts are
61,557 opening, 61,819 middlegame, and 27,314 endgame. These are unlabeled
candidate counts, not claims about accepted training data.

The source ZIP is 82,724,777 bytes with SHA-256
F2FA14565BCDABA7AD6DE6A4F8F2348D0F9F8F262935C46E61925C5ACCE6F7B7.
The offline teacher executable SHA-256 is
5F95EAEA0D4EB697381989187CE6EB4D6AD59283C34421765ECC73CDB09BA766.
Of 512 training-only audit positions, 361 passed the proposed filters. Their
median absolute 25k-to-100k-node score change was 11 cp, with 0.831% exceeding
150 cp. The frozen audit rule passed. This establishes budget stability on that
sample, not perfect labels or improved Eloi strength.

### Runtime and continuation commands

Use `C:/Users/suhas/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`
(Python 3.12.13, NumPy 2.3.5, python-chess from the existing project venv).
This differs from the historical trainer runtime; the experiment warm-starts
from frozen production weights rather than claiming old float reproduction.

Run `scripts/test_fresh_nnue_data.py` for integrity tests. Run
`scripts/run_fresh_nnue_campaign.py run` to resume acquisition, sampling,
labeling, training, correctness, and eligible match stages in order. The runner
holds a Windows OS file lock; do not launch it while another worker is active.
Use a new log filename on each restart to preserve earlier evidence. Background
workers must use Windows Idle priority and hidden windows.

The resumed worker was launched with PID 31568 and logs to
`tmp/nnue-fresh-data/campaign-2.log` and `campaign-2.err`. Verify the executable
and command line before treating a stored PID as current. The original
`campaign.log`/`campaign.err` retain the intentional offline-teacher interruption
used to reload the resource amendment; it was not an engine-correctness failure.

Fourteen lightweight tests currently pass (eight data tests and six campaign
tests). Candidate compilation, full engine correctness, training outcomes, and
matches have **not yet completed** at this checkpoint. Do not report the runner
as fully end-to-end validated merely because its unit tests passed.

Subsequent active checks increased this to 17 tests, including identical header
serialization, exact array round-trip, a C++ syntax-only compile of the exported
header, incomplete-match rejection, and the exact 165/300-point boundary. These
do not substitute for compiling and testing each trained engine.

A separate read-only audit on the first 2,000 accepted TRAIN positions from
1,906 game groups found production-NNUE MAE 209.817 cp, median error 175 cp,
and sign accuracy 60.16% outside +/-25 cp. These labels exclude mates and have
passed the teacher stability filters. Thus substantial static-network error is
present without the historical mate-target artifact. This is not a causal proof
that data alone is responsible, not a full-engine evaluation comparison, and
not a strength result. The audit did not change the frozen training recipes.
Reproduce with `scripts/audit_fresh_nnue_training.py --limit 2000`; compact
evidence is in `data/nnue_fresh_data_training_audit.json`.

New-corpus game/board isolation is enforced. Unknown overlap with the historical
production network's original training data cannot be ruled out; the new test
partition is not claimed to be independent of all historical Eloi training.
Stockfish is not linked or copied into Eloi packages; it is an offline research
tool in ignored scratch only. No package is authorized by this campaign.

All candidate networks and build directories remain under
`tmp/nnue-fresh-data/candidates/`. CMake's optional experimental include root
avoids swapping the production header. The default build remains unchanged.
No candidate may be installed or used by the live bot in this campaign.

The task heartbeat checks progress every 15 minutes during the campaign window.
Read this file, the immutable protocol (once created), and the latest ignored
run logs before acting. Reuse existing work; never launch overlapping heavy
jobs. The official scheduling guidance was consulted to arrange continuation:
https://learn.chatgpt.com/docs/automations?surface=app .
