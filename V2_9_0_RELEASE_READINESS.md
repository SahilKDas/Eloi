# Eloi v2.9.0 release readiness

Eloi v2.9.0 is not currently releasable. The experimental hybrid has strong local
match evidence, but a future production binary must clear every gate below.
No historical result is silently promoted into a release qualification result.

## Current evidence

- The reviewed donor source is Caissa 1.26 at commit
  `008b0b8f1fc6479890665a1a9c2ff6bbc2f1bc06`.
- The release candidate combines Caissa 1.26 code with the v1.25 `eval-71`
  CReLU network extracted from the official v1.25 MIT release: 50,367,040
  bytes, SHA-256
  `615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`.
- The former v1.26-network hybrid scored 95/32/23 (74.0%) at 10,000 nodes per move and
  139/10/1 (96.0%) at 250 ms per move against the exact v2.7.5 binary.
- Both historical 150-game PGNs replayed successfully, with zero protocol
  failures. Their exact, now-replaced network identity remains in
  `data/v2_9_0_strength_evidence.json`.

## Blocking gates

1. **Network provenance — passed for v1.25; packaging remains closed.** The
   official v1.25 release executable embeds `eval-71` and comes from the tag
   whose project and matching retained license are MIT. Exact asset, PE
   extraction, model, tag, and license hashes are frozen in
   `third_party/caissa/network-v1.25-provenance.json`. The unrelated v1.26
   Caissa-Nets artifact remains blocked and unused.
2. **WDL calibration evidence — partially reset; requalification open.** A bounded
   collector replayed 40 complete Standard games and sampled four positions per
   game from the preserved 250-ms campaign, then queried each isolated brain in
   a fresh three-thread, 2,000-node process. A second, separately hash-namespaced
   40-game/160-position sample from the fixed-node campaign served only as
   external validation; game overlap was zero. Eloi's selected 1,300 cp scale
   improved external log loss from 0.88 to 0.60 and remains applicable.
   Caissa's former 360 cp scale belonged to the replaced v1.26 network; v1.25's
   native 400 cp expected-score mapping is provisional pending fresh disjoint
   calibration. Mate reports remain discrete and excluded. The exact
   report is `data/v2_9_0_wdl_calibration.json`, SHA-256
   `FE6B667A2BF0087E2A422BD35D8EB7F52C1B8BEE8A865642794F254A34950D20`.
   This changes arbitration, so all older strength results are informative but
   cannot qualify the calibrated binary.
3. **Production routing — implemented behind an opt-in flag; final validation
   open.** `ELOI_ENABLE_CAISSA_PRODUCTION=ON` routes Standard searches from
   GUI, UCI, native Lichess, and the Exoskeleton bridge through one shared
   `ProductionBrain`. Chess960 and Horde route directly to E2. The ordinary
   flag-off build remains byte-identical to published v2.7.5. The network path
   is accepted only through `--caissa-network` or
   `ELOI_CAISSA_NETWORK_PATH`; there is no discovery or download.
4. **Resource and failure semantics — implemented; stress evidence open.**
   Both brains use exactly three search threads and run sequentially. Standard
   divides the configured Hash without duplication; Caissa's table is lazy and
   released before a full-Hash variant or fallback E2 search. Move overhead is
   converted into the shared hard deadline once. Missing, wrong, exceptional,
   failed, or Eloi-illegal hybrid results fall back safely when time remains.
   An operating-system-level in-process donor crash cannot be caught in C++ and
   remains a release-blocking watchdog test rather than a claimed fallback.
5. **Adapter validation — v1.25-network depth-one parity passed; corpus
   revalidation open.** The official v1.25 executable and v1.26-code adapter
   matched all three depth-one moves; initial-position evaluation also matched
   exactly at +29 cp. Deeper
   three-thread move distributions are retained as observations rather than
   falsely requiring deterministic best-move equality. Evidence is preserved
   at `tmp/caissa-parity/parity-v290-corrected-v2.json`, SHA-256
   `CEE70064FE80B3E800452131AC32BF28126B1CBDCD19CFC252AA7C96B2CBD3CC`,
   from source `c31c004130d5261f6eff69ec25f6022cf3e99c01`. The embedded hybrid
   suite also passed exact FEN round trips and legal-move equality across 256
   seeded Standard positions, plus dedicated castling, en-passant, promotion,
   clock, history, and repetition seams.
6. **Former bounded correctness — historical; new network checks in progress.**
   The preservation-safe preflight refuses existing destinations, enforces all
   storage limits, retains deterministic archive inputs, and creates nothing
   when blocked. Both local app forms now embed and runtime-hash-verify the
   exact network, run without an external network file, and preserve the
   byte-identical flag-off v2.7.5 control. The hash-bound implementation report
   is `data/v2_9_0_embedded_network_validation.json`. At source
   `a7ec2ff2a414f8500a55c112e23f469b476b7e50`, both Windows forms passed all
   three CTest targets; the production hybrid route passed all 15 regressions
   with zero protocol failures; perft reached 197,281 nodes; and seeded
   differential generation passed 96/96 Standard, Chess960, and Horde
   positions. UCI readiness, three bounded timed moves, stop, clean exit,
   pre-UCI stdout, and offline Exoskeleton configuration also passed. Exact
   binary and evidence hashes are in
   `data/v2_9_0_calibrated_correctness_validation.json`, but it binds the old
   network. The new combination has passed a clean standalone build, all three
   CTest targets, perft 197,281, and UCI timed/stop smoke. Its 15-position gate,
   differential move generation, and two independent
   reproducible builds, deterministic archives, fresh extraction, full
   package-content/dependency checks, and security validation remain open.
   No build or runtime network download is allowed.
7. **Post-integration strength — not started.** Only after behavior is frozen:
   screen configurations, run 100-game confirmation, then 250 games against
   v2.7.5 and 100 games against equal-budget Caissa-only. Historical lab matches
   inform the decision but do not qualify a different binary.

The current production and recoverable champion remains Eloi v2.7.5. The new
v1.25-network controller has passed its first build, unit/GUI tests, perft, UCI
smoke, and depth-one donor comparison. Broader correctness and all strength
qualification are deliberately reset. No tag,
release, package, or production installation should call the hybrid “v2.9.0”
until every gate above is closed with retained evidence.
