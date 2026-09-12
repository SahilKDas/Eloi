# Tracking upstream Caissa

Eloi treats Caissa as its long-term Standard-chess search foundation, but it
does not auto-update donor code or models. Production remains the coherent,
qualified Caissa 1.25 source and `eval-71` CReLU network used by Eloi v3.1.1.
Chess960 and Horde continue through Eloi E2.

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
