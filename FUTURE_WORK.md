# Work after Eloi v2.5.0

This is an index of unresolved work, not a running campaign or authorization
to train, benchmark, publish or replace a user's installation.
Follow [device constraints](constraints_on_SahilKDas_device.md) and freeze a
new protocol before expensive experiments.

## Current baseline

Use the exact C network in [data/nnue_provenance.json](data/nnue_provenance.json)
and the stable package identities in [RELEASE_V2_5_0.md](RELEASE_V2_5_0.md).
Its 10W/3D/7L result against v2.0.0 is preliminary evidence, not a proven Elo
gain. Do not silently reuse expired A/B/C or v1.9 gates.

## Training limitations worth investigating

- **Dormant channels:** the warm start leaves 41 channels unable to learn
  under the observed training dynamics. Reproduce the retained channel audit,
  then test an explicit initialization/activation remedy in an isolated
  candidate. Do not alter production as part of an audit.
- **Coverage:** accepted fresh labels intentionally exclude checks, captures,
  promotions, mates and large/disagreeing scores. Measure the resulting
  tactical/defensive/endgame gaps before increasing dataset size.
- **Quantization:** assess integer-network metrics and inside-engine decisions,
  not just float loss. Preserve exact scalar/AVX2 agreement.
- **Calibration:** puzzle ranking and evaluation calibration interact.
  C used A-to-B-to-C recalibration; future ablations should isolate one change.
- **Partition integrity:** retain game, board and NNUE-equivalence separation.
  Do not train on release regressions or select on sealed test positions.

Earlier D-series offline improvements did not guarantee correct engine play.
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
features of v2.5.0. Prior Lazy SMP failures and the reverted search-recovery
patch are recoverable in Git history. Diagnose any new failure before choosing
a search or dataset remedy.

Linux/macOS/ARM ports need their own toolchain, GUI/dependency and correctness
validation. No emulation environment or extra bridge is implicitly authorized.

## Repository maintenance

Current build/runtime code, source licenses, provenance, release evidence and
reusable tooling stay in the tree. Obsolete campaign instructions belong in
Git history, not in the default contributor workflow.
The ABC100 frontend code is temporarily retained because that local session
is active; retire it only after confirming the user no longer needs it.
