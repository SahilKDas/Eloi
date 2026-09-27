# Tracking upstream Caissa

Eloi treats Caissa as its long-term Standard-chess search foundation, but it
does not auto-update donor code or models. Production remains the coherent,
qualified Caissa 1.25 source and `eval-71` CReLU network first used by Eloi
v3.1.1. The native GUI offers Caissa 1.25 or Eloi E4-10. Chess960, Horde,
Atomic, Antichess, and emergency fallback use E4-10; King of the Hill uses
KOTH E4.

## Caissa 1.25 network redistribution record

The production record cites concrete upstream artifacts rather than Eloi's own
prior release as its basis:

- the pinned upstream tag `1.25` at commit
  `0c01e79ea36ae492585e88cca9d03abae9b7a3d5` contains Caissa's MIT
  `LICENSE`;
- the official [Caissa v1.25 release](https://github.com/Witek902/Caissa/releases/tag/1.25)
  describes the expanded trained network and distributes it inside the official
  release executables; Eloi's source artifact was
  `caissa-1.25-x64-avx2.exe`, whose GitHub asset digest is
  `SHA-256:DEF18F5941C7D2D21B89C1D7A646BA9B354E533537A9CEFDDA24301F4DBEDAA8`;
- Eloi extracted `eval-71-v1.25.pnn` from that official distribution and pins
  SHA-256
  `615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`.

Upstream does not provide a separate model-specific license statement. The
maintainer interprets the tag-level MIT license as covering the official v1.25
distribution and preserves the notice in Eloi packages. This is an explicit
project interpretation, not a claim that a distinct upstream weights license
was found.

## Source-only laboratory

New donor releases are inspected under ignored
`.deps/caissa-upstream/<release>-source`. Pinned identities and evaluator
requirements live in `data/caissa_upstream_releases.json`. The audit tool is
read-only with respect to the donor and refuses to overwrite evidence:

```powershell
python scripts/caissa_upstream_lab.py `
  --release 1.26 `
  --source .deps/caissa-upstream/1.26-source `
  --source-archive .deps/caissa-upstream/Caissa-1.26.tar.gz `
  --output tmp/caissa-upstream-126/audit.json
```

Caissa 1.26 requires `eval-82-383B.pnn` and SCReLU semantics. The separate
Caissa-Nets repository has no affirmative model license recorded by Eloi.
Consequently the manifest marks 1.26 `source-only-lab`, its model identity is
unapproved, and the candidate cannot become runnable or promotable. Never use
the 1.25 `eval-71` network with 1.26 code.

If permission and an authoritative hash are later obtained, update the pinned
manifest in a reviewed commit before supplying the model. Keep it outside the
repository or under ignored `.deps`; never enable upstream's automatic model
download in an Eloi build.

## Qualification order

After provenance and matching-model approval, complete the existing adapter
parity, crash/deadline, official fixed-node, regression, protocol, mirrored
screening, sealed 250 ms confirmation, and reproducible-package gates. Every
engine uses exactly three search threads. Production promotion requires a
completed score strictly above 50% against v3.1.1 and no protocol failure.

Search-only backports may be evaluated separately when they preserve the 1.25
evaluator's formats and semantics. Attribute each donor change, test it alone,
and retain production 1.25 whenever evidence is incomplete or inconclusive.
