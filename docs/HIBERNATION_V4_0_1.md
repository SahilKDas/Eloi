# Eloi v4.0.1 — return to codebase hibernation

Recorded 2026-10-30. The anniversary maintenance exception is complete.
Development is paused; EloiBot, existing bridges, jobs, configuration and
keep-awake processes remain independent and were not stopped or upgraded.

## Immutable release identity

- [Eloi v4.0.1](https://github.com/SahilKDas/Eloi/releases/tag/v4.0.1), stable/latest.
- Final publication: **2026-10-30 05:26:41 UTC**, October 29 **10:26:41 PM UTC−7**.
- The maintainer authorized missing the original 05:00 UTC target to restore
  the real two-player GUI. No timestamp was backdated.
- Annotated tag object: `b7a5eadf9044f635b8e063a83715f2d9a89dd451`.
- Published source: `6c944a8b5ec2b07d90612c74ca3b18960ba40c75`.
- Later handoff-only commits are not the package source. Never move this tag
  or overwrite the published archives.

| Golden ZIP | SHA-256 |
| --- | --- |
| `Eloi-v4.0.1-windows-x64-standalone.zip` | `00E2C6868911E81FBEA137AB3C3CDBE689858BD96013F694A415CA35ECE49BA2` |
| `Eloi-v4.0.1-windows-x64-exoskeleton.zip` | `77EF9F68BFBCA542BD318E226AED1DEEB107206E4E85709F94915B8D6308BEBA` |

Exactly these two ZIPs are attached. Both draft and public downloads were
independently hashed and matched. The v4.0.0 tag/assets remain unchanged; its
[historical hibernation record](HIBERNATION_V4_0_0.md) retains their identities.

## What changed and passed

Watch Eloi Think reports completed Teams iterations through bounded latest-only
telemetry: depth, team-relative score, nodes, elapsed time, actual search PV,
and a legal suggestion arrow. Search does not wait for rendering. Generation
and root checks reject stale updates; cancellation clears arrows.

The classic two-player interface now has the original Maestro pieces, Segoe UI,
named controls, setup, clocks, legal targets, promotions, Crazyhouse pockets,
undo/flip/side controls and explicit local analysis. Two-way navigation preserves
both boards and suspends hidden play. Engine Lab is position analysis and
diagnostics; the old automatic previous-version tournament UI is not restored.

- 115 Rust workspace tests and two explicit real-donor integration tests passed.
- 199 Python tests passed; formatting and whitespace checks passed.
- [Windows CI](https://github.com/SahilKDas/Eloi/actions/runs/41007223975)
  passed on the exact published source.
- All 16 fixed-work Teams comparisons matched immutable v4.0.0. Nine paired
  250/500/1000 ms timing checks passed, with no median-depth regression or
  deadline failure. This is not strength qualification.
- Four independent builds matched within each form; independent ZIPs matched.
  Exact contents, zero Eloi PE timestamps, system-only imports, empty-token
  configuration, clean extraction, UCI lifecycle, Teams replay and Defender passed.
- The maintainer accepted the classic preview. After explicit computer-use
  authorization, both final extracted packages passed visual checks: classic
  artwork/controls, e2–e4 and legal verified Caissa reply, navigation, live Teams
  metrics/PV/arrow, pause clearing and normal close. Owned test processes exited.
- Strict Clippy is **not** claimed clean: existing lint failures were retained.

Standard remains pinned isolated Caissa 2.0 AVX2; native variants and three-lane
handcrafted Teams retain their playing logic. No training, donor upgrade,
strength claim or live-service handover was performed.

## Publication incident and retained evidence

An asset-free v4.0.1 release was externally published at 05:16:32 UTC against the
earlier rejected GUI source. It was returned to draft before golden assets were
attached. Its lightweight tag was conditionally replaced using the exact old
hash with the final annotated tag above. All final binaries, proof and source
identities were then checked again.

The one-shot Actions publisher failed its annotation preflight because
actions/checkout fetched the correct annotated tag, then overwrote its local
tag ref with the peeled commit. It did not publish or waive any gate. The
maintainer's explicit GitHub CLI authorization was used instead: local and
remote annotated-tag objects were verified, then the unchanged guarded
`publish_v401_anniversary.py --allow-late` rechecked the proof and downloaded
assets before publishing through `gh`. Do not claim that Actions run passed.

Ignored local evidence (not guaranteed in fresh clones):

- `dist/v4.0.1-golden-r7/validation.json` and the two golden ZIPs.
- `tmp/v401-package-build-r7.log`, `tmp/v401-package-audit-r7.log`.
- `tmp/v401-final-interaction-tests.log`, `tmp/v401-frozen-final-python.log`.
- `tmp/v401-final-donor.log`, `tmp/v401-final-gui-donor.log`.
- `tmp/v401-teams-comparison-r7.json`, `tmp/v401-cli-publication-r7.log`.
- `tmp/v401-draft-redownload-r7/`, `tmp/v401-public-redownload-r7/`.

Only disposable completed compilation caches were removed. Frozen release
archives, validation evidence, historical campaigns and private configuration
were preserved.

## Resume boundaries

Obtain a new scoped task before development resumes. Read the device limits,
inspect Git state and active services, and use the pinned Rust 1.98.1 MSVC
toolchain/Cargo.lock. Never infer a running bridge's version from repository
HEAD. Do not restart or replace live EloiBot services without a separate handover.
Do not rerun the already-consumed anniversary publisher against a public release.

Broader independent four-player rules coverage, human Teams playtests and any
strength campaign remain future work. FFA and Kaggle training remain retired
research, not newly authorized tasks. All honest v4.0.0 validation limitations
continue to apply.
