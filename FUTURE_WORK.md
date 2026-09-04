# Work after Eloi v2.7.5

This is an index of unresolved work, not a running campaign or authorization
to train, benchmark, publish or replace a user's installation.
Follow [device constraints](constraints_on_SahilKDas_device.md) and freeze a
new protocol before expensive experiments.

## Current baseline

Use the exact E2-ranking network in
[data/nnue_provenance.json](data/nnue_provenance.json). C's v2.5.0 identity is
preserved in [data/nnue_provenance_v2_5_0.json](data/nnue_provenance_v2_5_0.json).
Do not silently reuse expired A/B/C or v1.9 gates.

The completed standard-only E2 campaign produced the v2.7.5 production network:
E2-ranking scored 31W/22D/7L in confirmation and 45W/56D/24L (58.4%) in its
fully disjoint 125-game final, then 93W/94D/63L (56.0%) in a separate
250-game confirmation against C. See
[E2_STANDARD_CAMPAIGN.md](E2_STANDARD_CAMPAIGN.md).

## Training experiments

The first dormant-channel and 32-unit experiments are implemented and recorded
in [data/nnue_e1_e32.json](data/nnue_e1_e32.json).

E2's completed standard-only experiment supersedes the old recommendation to
run another generic dormant-channel trial. Its candidate and evidence are
retained locally and summarized in
[data/nnue_e2_standard_results.json](data/nnue_e2_standard_results.json).
The next work is release packaging or new post-E2 research, not another E2
promotion match.

- **E1-selected:** deterministic residual initialization activated all 64
  channels, improved validation MAE from 181.22 to 179.21 cp and passed the
  complete engine correctness suite. Its first 20-game mirrored screen against
  C finished exactly 7W/6D/7L. This supports parity, not promotion; a fresh
  confirmation protocol is required before any production decision.
- **32 units:** exact C compaction into 32 units passes correctness and is
  evaluation-identical to C because all omitted channels were zero-input and
  zero-output. Training its nine spare channels improved offline MAE slightly
  but missed the required `lichess-001XA` defense, so that trained candidate is
  rejected. The short speed sample was mixed and does not establish a deep
  search speedup.
- **Dormant channels:** E1 proves explicit initialization can wake all 41
  channels. Later tactical/ranking epochs overtrained both architectures and
  reintroduced regressions, so future work should investigate validation-aware
  early stopping and tactical retention rather than blindly adding epochs.
- **Coverage:** accepted fresh labels intentionally exclude checks, captures,
  promotions, mates and large/disagreeing scores. Measure the resulting
  tactical/defensive/endgame gaps before increasing dataset size.
- **Quantization:** assess integer-network metrics and inside-engine decisions,
  not just float loss. Preserve exact scalar/AVX2 agreement.
- **Calibration:** puzzle ranking and evaluation calibration interact.
  C used A-to-B-to-C recalibration; future ablations should isolate one change.
- **Partition integrity:** retain game, board and NNUE-equivalence separation.
  Do not train on release regressions or select on sealed test positions.

Earlier D-series and the rejected trained E32 offline improvements did not
guarantee correct engine play.
Their original rejection evidence remains in Git history; it must not be
mistaken for a recommendation to train another numbered candidate blindly.

## Strength evidence

A future comparison needs a hash-verified C baseline, fresh mirrored openings,
an explicit chess-score threshold, fixed game count/budget and declared
uncertainty. Finish correctness, timing and identity checks first.
Do not pool tuning screens with confirmation or restart a losing match
because the laptop slept. Record interruptions and censor incomplete work.

## Search, ensembles and platforms

Lazy SMP and multi-network ensembles remain separate research ideas, not
features of v2.7.5. Prior Lazy SMP failures and the reverted search-recovery
patch are recoverable in Git history. Diagnose any new failure before choosing
a search or dataset remedy.

The active v3 experiment lives on the caissa-merge branch. It pins Caissa 1.26
at source commit 008b0b8f1fc6479890665a1a9c2ff6bbc2f1bc06 and keeps the
external network, whose redistribution license is not visible, in ignored
local storage. The imported backend,
E2 adapter and Eloi-owned hybrid arbiter compile as a separate laboratory;
the production executable, GUI, Lichess bridge and v2.7.5 packages do not link
it.

Current bounded v3 evidence covers exact network/executable identities,
Standard FEN and legal-move parity, clock fields, castling, en passant,
promotion, replayed threefold history, terminal positions, direct stop and
deadline propagation, legal fallbacks, normalized alternative reporting, and
depth-one agreement with the frozen official Caissa binary. Every active brain
uses three search threads sequentially, with 16 MB per brain in the 32 MB lab.

The v3 experiment is not release-qualified. Caissa's network redistribution
license is unresolved; deeper three-thread fixed-node parity is nondeterministic
at small budgets and remains open; the two score-to-WDL mappings are explicit
development constants rather than outcome-calibrated models. No adapter-sanity
games, screens, confirmation, gauntlet, production integration or package work
should begin until the user lifts the current no-gauntlet/no-long-test hold and
the applicable pre-game gates are frozen.

Linux/macOS/ARM ports need their own toolchain, GUI/dependency and correctness
validation. No emulation environment or extra bridge is implicitly authorized.

## Repository maintenance

Current build/runtime code, source licenses, provenance, release evidence and
reusable tooling stay in the tree. Obsolete campaign instructions belong in
Git history, not in the default contributor workflow.
The ABC100 frontend code is temporarily retained because that local session
is active; retire it only after confirming the user no longer needs it.
