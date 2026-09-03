# Retained data and evidence

This directory is not a dataset dump. Runtime weights/book tables live in
`include/eloi/`; large inputs, checkpoints, binaries and build evidence are
ignored local artifacts.

## Current production lineage

- `nnue_provenance.json`: C's current header/checkpoint identities, counts,
  recipe, acceptance policy and match reference.
- `nnue_provenance_pre_v2_5_0.json`: the parent network C warm-started from.
- `nnue_input_manifest.json`, `nnue_broader_sample_manifest.json`: source
  and canonical puzzle identities required by that lineage.
- `nnue_fresh_data_*.json`: frozen acquisition, sampling, filtering, protocol,
  training/audit and outcome records for A-to-B-to-C. Earlier rejection fields
  remain historically true; see the later release acceptance policy.
- `abc60_parallel_*.json` and `abc60_parallel_games.pgn`: C's cited
  10W/3D/7L screen, B's concurrent control, pairings, timing and independent
  PGN audit. Raw evidence remains byte-identical.

## Future validation and live-session compatibility

- `strength_openings.json`: neutral opening suite.
- `search_recovery/{diagnostic,development,confirmation,final,reserve}.json`
  plus `search_recovery_protocol.json`: frozen partition identities. Preserve
  the sealed final partition and consult historical usage before selecting
  future openings. The old campaign's thresholds/deadline are not active.
- `nnue_abc100_*.json`: the paused historical campaign and still-running
  human frontend's protocol/amendment. Preserve these and their scripts until
  the user retires that session.

## Historical records and recovery

Obsolete plans, duplicate experiment reports, retired one-shot runners and
unused Morlock reference PGNs were removed from the current checkout.
Their original contents remain in commit
`24e8a4538fd1fcf164ad1747a62e91a01acdccec` and earlier Git history.
Hash manifests may refer to files at that historical revision; such references
are provenance, not a requirement that obsolete files stay in today's tree.

Read an archived file without changing the working tree:

```powershell
git show 24e8a4538fd1fcf164ad1747a62e91a01acdccec:V1.9_VALIDATION_PLAN.md
```

Cleanup does not reclassify any past failure as a pass or change release tags.
For current instructions use [DATA_SOURCES.md](../DATA_SOURCES.md),
[RELEASE_V2_5_0.md](../RELEASE_V2_5_0.md) and
[FUTURE_WORK.md](../FUTURE_WORK.md).
