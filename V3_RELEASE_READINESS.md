# Eloi v3.0.0 release readiness

Eloi v3 is not currently releasable. The experimental hybrid has strong local
match evidence, but a future production binary must clear every gate below.
No historical result is silently promoted into a release qualification result.

## Current evidence

- The reviewed donor source is Caissa 1.26 at commit
  `008b0b8f1fc6479890665a1a9c2ff6bbc2f1bc06`.
- The frozen local network is `eval-82-383B.pnn`, 50,367,040 bytes, SHA-256
  `22249DE582912F46F73F7CF7410D6D72ECCC77696B0B857E99B97A45F3F37116`.
- The hybrid lab scored 95/32/23 (74.0%) at 10,000 nodes per move and
  139/10/1 (96.0%) at 250 ms per move against the exact v2.7.5 binary.
- Both 150-game PGNs replayed successfully, with zero protocol failures.
  Exact identities are preserved in `data/v3_strength_evidence.json`.

## Blocking gates

1. **Network redistribution permission — blocked externally.** Caissa source
   is MIT-licensed, but no license for the separate Caissa-Nets artifact was
   visible during the audit. `scripts/caissa_license_gate.py` requires exact
   artifact and evidence hashes plus explicit rights for both package forms.
   The checked-in template intentionally fails. Local diagnostics remain
   permitted; packaging does not.
2. **WDL calibration — open.** The arbiter's 400/360 expected-score scales are
   development constants. A whole-game-separated calibration and held-out
   validation report must support any replacement. Until then, playing behavior
   stays frozen at the values that produced the recorded match evidence.
3. **Production routing — open.** Standard chess must use the hybrid through an
   Eloi-owned controller; Chess960 and Horde must remain E2-only. UCI, GUI,
   Lichess, clocks, repetition, and final legality remain Eloi-owned.
4. **Resource and failure semantics — open.** The integrated executable must
   prove exactly three active search threads, sequential brain slices, one
   shared Hash budget, one move-overhead deduction, hard-deadline propagation,
   and legal E2 fallback for unavailable, late, crashed, or invalid Caissa work.
5. **Adapter validation — open.** Depth-one and board/legal parity are
   mechanical gates. Deeper three-thread runs are validated for legality,
   mate/score sanity, timing, and distributions rather than falsely requiring
   deterministic best-move equality.
6. **End-to-end correctness and packaging — open.** All existing regressions,
   perft, differential move generation, stop handling, GUI/bridge smoke tests,
   reproducible builds, clean extraction, and package-content checks must pass.
   No build or runtime network download is allowed.
7. **Post-integration strength — not started.** Only after behavior is frozen:
   screen configurations, run 100-game confirmation, then 250 games against
   v2.7.5 and 100 games against equal-budget Caissa-only. Historical lab matches
   inform the decision but do not qualify a different binary.

The current production and recoverable champion remains Eloi v2.7.5. No tag,
release, package, or production installation should call the hybrid “v3.0.0”
until every gate above is closed with retained evidence.
