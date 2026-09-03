# Reproducing Eloi releases

## Source identity comes first

The verified v2.5.0 artifacts were built from commit
`24e8a4538fd1fcf164ad1747a62e91a01acdccec`.
Use that exact commit in a separate clean checkout when reproducing those
published bytes. A later documentation/tooling cleanup commit is not the same
source identity, even when playing code and weights are unchanged.

See [RELEASE_V2_5_0.md](RELEASE_V2_5_0.md) for the network, package hashes and
acceptance decision. Production builds leave `ELOI_NNUE_INCLUDE_DIR` empty;
they use the tracked C header. Build tooling never retrains it implicitly.

## Locked inputs

[reproducibility.lock.json](reproducibility.lock.json) pins the MSYS2 packages,
tool executable hashes, Skia/codec archives and linked static libraries.
The Windows x64 environment uses PowerShell 7.6.4 and:

| Component | Locked package |
|---|---|
| GCC/runtime | 14.1.0-3 |
| GNU binutils | 2.42-2 |
| MinGW headers/CRT/winpthreads | 11.0.0.r750.g05598db99-1 |
| CMake | 3.29.3-2 |
| Ninja | 1.12.1-1 |

Archive generation used **Python 3.12.13 / zlib 1.3.2**.
Python executable SHA-256:
`D8E3F0ADF246DB00358C0C4ED349CF714898178F9558FB0E944F79F5C07F8EAA`.

The fixed source epoch is `1787961600` (2026-08-29 00:00:00 UTC).
C++26 compilation uses `-std=c++2c`, fixed LTO partitioning, remapped paths
and a fixed compiler seed. The linker writes zero PE timestamps. ZIPs use
sorted entries, the fixed epoch, normalized attributes and compression level 9.

Retain the exact signed MSYS2 archives in the package cache and verify both
installed tools and cached archives. Never change a hash to accept an
unfamiliar substitute.

```powershell
pwsh -NoProfile -File .\scripts\bootstrap-windows.ps1
pwsh -NoProfile -File .\scripts\verify-toolchain.ps1 -RequirePackageArchives
```

Bootstrap downloads hash-pinned development dependencies into ignored
`.deps`. It is not a production runtime step.

## Four-build package proof

Commit intended source changes first; release tooling refuses a dirty tree.
For an independent proof without a local frozen experimental executable:

```powershell
python -B scripts/release_v250.py build --reproduce-only --work-dir tmp/reproduce-v2.5.0-1
```

Choose a fresh output directory. The script refuses collisions and retains
scratch. It exports the selected commit, builds standalone twice and Exoskeleton
twice, runs CTest in every build, checks package contents/imports/PE timestamps,
and requires byte-identical payloads and archives within each form.

This proves the artifacts produced by that source and environment agree.
To reproduce the original v2.5.0 ZIP hashes, run from the original commit and
use the recorded Python/zlib environment as well. Exoskeleton records its
source commit inside the package, so a newer source revision changes its bytes.

Reproduction-only does not qualify a new release: it skips the ignored frozen-C
reference, performance comparison, security and publication gates.
The full local validation path is `build` without `--reproduce-only`;
it also requires the frozen C executable and retained campaign inputs.
It must not overwrite an existing `dist/v2.5.0` directory.

The `build-windows-release.ps1 -PreserveExisting` wrapper selects that
preservation path. Other generic package helpers remain available, but the
old v1.9/search-recovery campaign instructions are not release prerequisites.

## Validation and safety

Before publication, require complete mechanical/tactical/GUI suites,
perft d4=197281, 32 seeded move-generation comparisons per variant, UCI
startup/readiness/new-game/timed/stop/exit checks, and offline Lichess config
and empty-token guards. Never start a live account just to validate packaging.

Compare fixed-depth behavior with the identified brain and record bounded
benchmark repetitions under equal settings. The v2.5.0 policy rejects
unexplained median slowdowns above 15% at depths 5/10. Future releases need
their own explicit policy; old beta speed gates and abandoned campaign game
counts are not universal requirements.

Inspect board/setup/Engine Lab renders and exercise castling, promotion,
undo and side selection. Engine Lab screenshot-mode statistics are fixtures,
not strength evidence. Scan both complete extracted packages and both ZIPs
with Defender without remediation or exclusions.

Follow [device constraints](constraints_on_SahilKDas_device.md): exactly
three search threads, sequential heavy work at Idle priority, at most 10 GB
total temporary data, the stricter nested training limit, 2 GB new release
scratch and at least 5 GB free disk. Preserve active bridges/frontends.
`scripts/validation_support.py` provides shared EPD parsing and a resource
preflight without depending on a retired campaign or an old NNUE identity.

## Verify downloads

Compare each ZIP's SHA-256 with the release notes before extracting:

```powershell
Get-FileHash .\Eloi-v2.5.0-windows-x64-standalone.zip -Algorithm SHA256
Get-FileHash .\Eloi-v2.5.0-windows-x64-exoskeleton.zip -Algorithm SHA256
```

Standalone contains exactly `Eloi.exe` and empty-token `config.yml`.
Exoskeleton also includes `SOURCE_COMMIT.txt` and `SHA256SUMS.txt`; verify
every listed file. Hash agreement proves byte identity, not that source is
harmless. Source review and antivirus checks remain separate.
These release binaries are unsigned.

## Training provenance, not implicit retraining

C's exact A-to-B-to-C recipe and source/checkpoint/header identities are in
[DATA_SOURCES.md](DATA_SOURCES.md) and
[data/nnue_provenance.json](data/nnue_provenance.json).
C warm-started from the earlier production network; a fresh run of the generic
trainer is not a claim to reproduce C.

The bounded trainer, sampler, learning-equivalence checks and dormant-channel
audit remain development tools. Their frozen fresh-data campaign parameters
document C's lineage; old deadlines must not be treated as a new campaign
authorization. Use a new reviewed protocol and output directory for future
training, and qualify any candidate inside the actual engine before promotion.

Archived campaign plans and retired runners remain available at the original
source commit. Current source, data lineage, evidence and future work are indexed
by [README.md](README.md), [data/README.md](data/README.md) and
[FUTURE_WORK.md](FUTURE_WORK.md).
