# Eloi v4.0.0 — codebase hibernation

Recorded 2026-10-18. Development is paused, not abandoned. **EloiBot may keep
playing on Lichess for a long time.** This status does not stop, restart,
reconfigure or upgrade any bridge, job, monitor or keep-awake process. It is
not a promise of unattended uptime; fatal errors still require human action.

## Frozen release

- Release: [Eloi v4.0.0](https://github.com/SahilKDas/Eloi/releases/tag/v4.0.0).
- Annotated tag: `refs/tags/v4.0.0`.
- Published source: `158aad3542bd1700a71833bc65d05054c64f0f02`.
- Maintenance after that commit changes documentation/tooling, not published
  package identity. Never move the tag or silently replace its ZIPs.
- Rust 1.98.1 MSVC, locked Cargo dependencies, Windows x64. Caissa requires AVX2.

| Golden ZIP | SHA-256 |
| --- | --- |
| `Eloi-v4.0.0-windows-x64-standalone.zip` | `F60B45C797D2763622EE07B3E5A4BA0AA0E35AFB7F04DC3BED9E0B5A892FFB97` |
| `Eloi-v4.0.0-windows-x64-exoskeleton.zip` | `31E5CADCFAD1D5B7A75457DC8C2235F0BA8D1ABF590BAA67EBDF9C4BA709065F` |

Both public assets were redownloaded and matched these hashes. Local retained
proof: `dist/v4.0.0/validation.json`; golden ZIPs: `dist/v4.0.0/`.
Ignored local proof is not guaranteed to exist in a fresh clone; keep the
public hashes and source identity above as the portable release record.

## What ships

| Surface | Brain/scope |
| --- | --- |
| Standard UCI / native Lichess | Hash-pinned isolated official Caissa 2.0 AVX2 |
| Eloi-native variants / fallback | Retained native search and variant evaluators |
| Local four-player Teams | HandcraftedTeams, three search lanes; Red+Yellow versus Blue+Green |
| Four-player FFA / Kaggle training | Historical research, not released playable/training promises |

Teams GUI is separate from Lichess. No Chess.com integration is provided.
See [Teams guide](FOUR_PLAYER_TEAMS.md), [release notes](../RELEASE_V4_0_0.md)
and [package quick start](../packaging/V4_QUICK_START.md).

The Caissa worker hash is
`043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97`.
Preserve [donor provenance](../third_party/caissa20/PROVENANCE.md), MIT notices,
artwork attribution and dependency licenses. Hibernation does not resolve or
remove the disclosed model-license interpretation caveat.

## Evidence and honest limits

Release validation passed 95 workspace Rust tests, one explicit pinned-donor
integration test and 191 Python tests. Four independent builds matched within
each package form; repeat ZIP bytes matched, Eloi PE timestamps were zero,
imports/content audits and clean extraction passed, and Defender found no
threats. Both package forms passed Teams/UCI lifecycle, offline configuration
and GUI startup/close smoke checks.

The earlier Teams self-play record is **100 plies, not 100 games**. Neither a
human victory nor numerical Elo gain nor exhaustive four-player certification
is established. Independent attack-scan coverage is not a completed
10,000-position legal-move differential campaign. See the historically dated
[revival evidence](FOUR_PLAYER_TEAMS_VALIDATION.md).

## Live-service boundaries

- Do not terminate jobs or bridges to implement codebase hibernation.
- Do not replace a live executable/config, start a duplicate bridge, or expose
  tokens. Tokens, HTTP headers and chat text never belong in diagnostics.
- Inspect token-free logs/status and current process identity before a future
  handover; source/package version is not proof of the currently running binary.
- No scheduled training, strength campaign, donor update or new release is
  authorized by this document. Existing jobs/monitor settings are unchanged.
- Preserve [device limits](../constraints_on_SahilKDas_device.md). No new
  keep-awake helper or Windows power-policy change is needed for this pause.

## Resume checklist

1. Obtain a new scoped task; read this record and inspect clean/dirty Git state.
2. Verify release tag/source and baseline ZIP hashes before using them as controls.
3. Identify active games/jobs and available disk/RAM without interrupting them.
4. Use the pinned toolchain/dependencies. Run focused tests, then workspace and
   relevant Python tests; use accessible TEMP/TMP on this laptop.
5. Freeze fresh rules/strength protocols before experiments; never pool old
   interrupted matches or treat smoke tests as strength qualification.
6. Prioritize Teams human playtest reports and broader independent rules checks.
   FFA, neural training and donor upgrades need separate scope and qualification.
7. Changes after this release need new review/validation. Rebuild packages only
   with explicit release authorization; never overwrite v4.0.0's evidence.
