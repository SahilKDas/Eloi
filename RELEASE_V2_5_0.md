# Eloi v2.5.0 release decision and validation

## Verified local release artifacts

These artifacts passed all local release gates from source commit
`24e8a4538fd1fcf164ad1747a62e91a01acdccec`. Later repository cleanup does not
change that tested source identity. Rebuild that exact commit to reproduce
these ZIPs; do not substitute an older RC archive or merely rename it.

- `Eloi-v2.5.0-windows-x64-standalone.zip`, SHA-256:
  `6FD9F1FB17178D8C1B5BF7795663ADE251C1EF3555A18A3B706401728980B4F4`.
- `Eloi-v2.5.0-windows-x64-exoskeleton.zip`, SHA-256:
  `F3BBBBFEC437F5D264F37C832DA1424179B58F4CC73D7FCF4BC78B478D0AB18B`.

Both package forms reproduced byte-for-byte across independent builds.
All four builds passed C++ and GUI-handler tests; extracted packages passed
perft, differential move generation, UCI/offline-config checks and all 15
frozen-C comparisons. Benchmark gates passed. Defender reported no threats
in either complete extracted package or ZIP. This records local validation,
not an assertion that an arbitrary uploaded file matches those artifacts.

See [compact release evidence](data/release_v2_5_0.json) and
[reproduction instructions](REPRODUCING.md). Verify downloaded asset hashes
before relying on a release-page title. Historical campaign files removed
from today's tree remain recoverable from the tested source commit.

## Selection and immutable identity

The maintainer explicitly selected C for stable v2.5.0 after a completed
20-game screen against the exact published v2.0.0 executable: 10 wins,
3 draws, 7 losses, 11.5/20 chess points (57.5%). B's independent match ran
concurrently. This is preliminary evidence, not a reliable Elo estimate or
proof of superiority. No new strength gauntlet is part of this release.

Production's 64-unit NNUE header is copied byte-for-byte from C, SHA-256
`6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD`.
Its float checkpoint SHA-256 is
`48A40465E1E7A0AB7B408501FBEF78319D62612F6928891AD2B33B58D51AACE9`;
quantizing it reproduces every exported integer array. Search, evaluation
runtime code, opening logic, and the three-thread contract are unchanged.
The stable executable's hash differs from the experimental C executable
because version/build metadata changes; the network hash does not.

The earlier production header was
`CD3226903D48E0ADFE1DBD337E9CEC7BFB0A22C85185F9B6E0895D873A73394E`.
Its provenance is retained in `data/nnue_provenance_pre_v2_5_0.json` and its
source remains recoverable from Git. Current C checkpoints and successful
release proof remain protected locally; retired tracked experiments remain
recoverable from Git history. Private configuration is unchanged.

## Reviewed depth-comparison requirements

C's original C++ suite was rerun before changing assertions: it failed
exactly the two recorded best-move-equality checks. The production control
passed. The sole harness change for those reruns retained its own isolated
configuration fixture instead of deleting it.

Different fixed-depth moves alone do not establish a tactical error: deeper
search can refine a legal choice. The new test-only EPD `compare` operation
therefore permits move refinement, while `stable` still requires equality.
Only two EPD cases use `compare`:

| Case | Fresh shallow/deep searches | Preserved or strengthened requirements |
|---|---|---|
| lichess-001XA | d5 `f1d1` (+2 cp), d7 `b1b7` (+77 cp) | Require `b1b7` at d7; legal complete PVs; swing <=250 cp |
| poisoned-pawn-capture | d1 `d4g7` (+388 cp), d3 `d4e5` (+369 cp) | Forbid `d4d5` at both depths; legal complete PVs; swing <=250 cp |

These are fresh independent searches, not just points on one iterative trace.
The free-queen case still uses `stable`; the other 13 EPD cases and all
mechanical assertions are retained. Synthetic helper cases reject illegal
roots/PVs, missing PVs, missing required defenses, forbidden shallow/deep
moves, excess score swings, and unequal moves under `stable`.
The revised full C++ suite passes locally. This decision does not certify
every shallow move as optimal or erase C's original rejection.

Historical D-series, fresh-data, ABC100, ABC60, and recovery protocols/results
remain frozen in Git history at the tested release commit. Their failures,
interruptions, and old thresholds remain recoverable exactly as recorded.
The maintainer's new acceptance policy requires the reviewed
correctness suite and all release-engineering checks below, not a relabeled
pass under an earlier strength campaign.

## Stable release gates

Before publication, `scripts/release_v250.py` must validate one clean source
commit using the locked toolchain and four fresh builds: two standalone and
two Exoskeleton. Every build runs the complete C++ suite and the isolated
real-GUI-handler tests. GUI tests cover rook/king castling animation, all four
promotion choices, undo, side selection, clock setup/cancel, flip, piece
loading, and Engine Lab rendering. Production GUI source is not modified.

Final extracted packages additionally require perft d4=197281, 32 seeded
move-generation comparisons per variant (standard/Chess960/Horde), UCI
handshake/new-game/timed-move/stop/quit checks, offline config and empty-token
guards, version-match smoke, and board/setup/Engine Lab render inspection.
Screenshot-mode Engine Lab numbers are rendering fixtures, not match results.
Fixed-depth results on all 15 regressions must match frozen C exactly.
Three benchmark repetitions at d1/5/10 compare equal-load results to frozen C;
unexplained median slowdowns above 15% at d5/10 block publication.

Within each package form, both payloads and deterministic ZIP bytes must
match. ZIP entries are sorted, use the locked epoch and fixed attributes,
and use pinned Python/zlib compression. PE timestamps must be zero. The
standalone contains exactly Eloi.exe/config.yml; Exoskeleton retains its
runtime DLLs, twelve PNGs, licenses, source commit and per-file hash manifest.
No dataset, private token, previous engine, or development artifact is shipped.
Fresh Defender scans without remediation/exclusions and post-upload download
hash verification remain mandatory. No passing claim is inferred from a
missing, failed or censored check.

Final machine-readable proof and logs are retained under the unique release
scratch directory. GitHub release notes bind the tested source commit,
network hash, package hashes and actual completed checks. The release tag
points to that tested source commit; no untested source edits follow it.

## Preservation and publication

Use the preservation workflow, never the legacy deleting staging commands:

```powershell
.\scripts\build-windows-release.ps1 -PreserveExisting -PythonExecutable python
```

It leaves only the two new stable ZIPs under `dist/v2.5.0`, preserves
`dist/current`, refuses output collisions, retains scratch/test fixtures,
and does not install or publish automatically. Each attempt is bounded to
two hours and 2 GB new scratch; global limits remain 10 GB total temporary
data, the stricter nested training cap, and at least 5 GB free disk. All
heavy work is sequential at Idle priority. Existing bridges/frontend remain.

After every gate passes, normal non-force pushes publish the reviewed commit
and annotated `v2.5.0` tag. A draft receives exactly the two ZIP assets;
downloaded hashes must match before marking it stable/latest. Conflicting
remote history, tags, assets, or any failed gate stop publication. No live
local installation or account session is changed by this release workflow.

Dormant NNUE channels, ensembles, search changes, and training stronger than
C are follow-up research, not hidden work in this release.
