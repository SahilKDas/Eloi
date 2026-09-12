# Eloi Safe-Speed Campaign

## Outcome

No candidate qualified for promotion. Eloi v3.1.1 remains production.

The campaign evaluated three evaluator-preserving Caissa 1.26 backports, first
individually and then together, without changing search budgets, pruning,
Threads=3, Hash=32 MB, the Caissa 1.25 evaluator, or Eloi's legality and crash
containment. Every candidate missed the required short-time performance gate,
so the 60-game screen and 200-game confirmation were intentionally not run.

## Frozen reference

- Source revision at campaign start: `3892c8e`
- Eloi v3.1.1 executable SHA-256:
  `78242B1213A52FB00E6730AF5D3D0D23E71B03EB397978709E4376C6A3081EE6`
- Caissa 1.25 network SHA-256:
  `615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`
- Compiler: GCC 14.1.0; CMake 3.29.3; Ninja 1.12.1
- Search contract: three threads, 32 MB hash, Windows Idle priority

The default-off laboratory build reproduced the frozen executable byte for
byte before candidate testing.

## Candidate results

Ratios below are candidate median NPS divided by alternating-order baseline
median NPS. The acceptance gate required an overall median ratio of at least
1.05, no tier below 0.98, no median completed-depth reduction, and no deadline
overrun.

| Candidate | 250 ms | 500 ms | 1000 ms | Overall median | Result |
|---|---:|---:|---:|---:|---|
| Combined backports | 0.8993 | 1.0289 | 1.0242 | 1.0242 | Reject |
| Optimized capture detection | 0.9821 | 0.8370 | 1.0593 | 0.9821 | Reject |
| Generalized accumulator walk | 1.0088 | 1.0733 | 1.0001 | 1.0088 | Reject |
| Correction-history prefetch | 1.0130 | 0.9797 | 0.9108 | 0.9797 | Reject |

A separate 500,000-node screen made the combined build look 13.7% faster.
The target-time corpus disproved that apparent gain, including a 10.1%
regression at 250 ms. Fixed-node throughput alone is therefore not sufficient
evidence for this engine and workload.

All candidate C++ test suites passed. There were no recorded deadline
overruns. The current UCI/Caissa adapter reports depth as zero, so completed
depth could not be meaningfully compared; this telemetry limitation is
recorded rather than treated as affirmative evidence. It does not change the
rejection because the NPS requirements already failed.

## Safety corpus

`tests/epd/safe_speed_humiliation.epd` records diagnostic positions for the
observed five-queen terminal mate, a loose queen, a mutual promotion race, and
a forced mate net. These positions are diagnostic-only and are not exact-move
training targets. Existing regression suites remain authoritative.

## Preserved laboratory

The three changes remain behind default-off CMake switches so future compiler
or hardware investigations can reproduce them independently:

- `ELOI_CAISSA_LAB_FAST_CAPTURE`
- `ELOI_CAISSA_LAB_NSTAGE_ACCUM`
- `ELOI_CAISSA_LAB_CORR_PREFETCH`

The benchmark runner writes collision-safe JSON and alternates engine order.
Its ignored raw evidence is under `tmp/safe-speed/`; hashes are recorded in
`data/safe_speed_campaign.json`.

## Deferred work

Dense packed magic tables, portable AVX2 code-generation experiments, and
incremental worker position synchronization were not mixed into this rejected
batch. Incremental synchronization in particular changes state-management
semantics and deserves its own crash/resynchronization campaign. No guarded
early-stop logic was introduced.
