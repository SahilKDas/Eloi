# Caissa 2.0 donor provenance

Eloi's Standard-chess donor is the official `caissa-2.0-x64-avx2.exe`
release asset published by Michał Witanowski in the MIT-licensed Caissa
repository.

- Release: <https://github.com/Witek902/Caissa/releases/tag/2.0>
- Tag commit: `bb725799e9b19ebdaa0d584f5433fc1c3019e349`
- Asset SHA-256:
  `043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97`
- Upstream license at the frozen tag:
  <https://github.com/Witek902/Caissa/blob/2.0/LICENSE>

The official executable contains Caissa 2.0's matching multilayer evaluation
model. Eloi does not download, commit, or package a separate model from the
Caissa-Nets repository. Upstream does not publish a separate model-specific
license statement for those bytes. The Eloi maintainer accepts the official
tagged release asset, distributed from the MIT-licensed Caissa repository with
its matching evaluator embedded, as the redistribution basis for Eloi packages.
That project decision is intentionally explicit and must not be generalized to
loose Caissa-Nets artifacts.

The pinned binary is therefore packageable and eligible for production
promotion. It runs only as a crash-contained child process; Eloi remains
authoritative for protocol handling, variants, and final move legality.
