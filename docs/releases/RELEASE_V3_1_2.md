# Eloi v3.1.2

Eloi v3.1.2 is a contributor-experience and documentation patch release. It
does not claim greater playing strength than v3.1.1 and does not promote any
default-off laboratory candidate.

## Highlights

- Adds a code of conduct, security policy, structured issue forms, and pull
  request checklist.
- Adds bounded, least-privilege Windows CI for source-only C++ and Python tests.
- Clarifies the production routing boundary: Standard UCI and native Lichess
  use crash-contained Caissa 1.25; native GUI Standard, Chess960, Horde, and
  emergency fallback use Eloi E2.
- Adds focused first-contribution guidance for documentation, regressions,
  diagnostics, and platform research.

## CI and production validation

Public CI does not download or redistribute the Caissa network. It builds the
source-only core and Caissa laboratory with the production application disabled.
The two Windows release packages are built and validated locally from the exact
tagged commit with the hash-pinned Caissa 1.25 network and locked toolchain.

## Strength statement

No strength gauntlet is claimed or required for this patch. Packaged playing
behavior must match v3.1.1 on the frozen regression comparison before release.
