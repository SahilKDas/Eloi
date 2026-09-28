# Eloi-native search challenger laboratory

Status: implemented, default-off, not production-qualified.

## Purpose

This laboratory turns completed Standard Lichess games into reproducible search
diagnostics and tests whether Eloi's own E4-10 search can close the gap to the
frozen Caissa 1.25 production brain. Eloi v3.6.0 remains unchanged.

## Analysis Studio

Launch from a source checkout:

```powershell
.\build\Eloi.exe --analysis-studio
```

The native Win32 shell reads token-free journals under
`%LOCALAPPDATA%\Eloi\autopsy`, starts the headless analyzer at Windows Idle
priority, and owns its process tree through a Windows job object. Analysis is
manual, cancellable, and refused while `active-game.lock` identifies a live
game. E4-10 and Caissa are queried sequentially, never as a hidden six-thread
search.

Reports preserve the playing binary and network identities, move telemetry,
first 150 cp loss, E4/Caissa disagreement positions, and quarantined regression
proposals. Proposals are evidence only; they never enter tests or training
automatically.

## First search candidate

The first challenger is enabled only with:

```powershell
.\Eloi.exe --uci --brain eloi --search-safety tactical
```

It changes two search decisions without changing E4-10 weights:

- verify null-move cutoffs from depth five instead of only depth eight;
- cap aggressive late-move reductions in shallow or tactically volatile nodes.

The default safety mask is zero. Production UCI, GUI, Lichess, variants, and
packages therefore retain v3.6.0 behavior.

## Frozen comparison

`scripts/run_caissa_challenger_gate.py` freezes 200 reserve openings, mirrors
colors, starts fresh processes per game, gives each engine three threads and
32 MiB hash, and uses 250 ms per move. Games are capped after 200 newly played
plies, not absolute FEN ply. Protocol and results are written incrementally and
every completed PGN is replayed.

Run the E4-10 baseline first, then run the challenger on the identical schedule.
The challenger qualifies only if all 400 games complete without a protocol
failure and it scores strictly more points against Caissa than E4-10 did. A
claim that Eloi beat Caissa requires a separate, stricter result: more than
200/400 points against Caissa itself. Neither draws nor an equal baseline score
are rounded into a pass.

No candidate is promoted, packaged, or routed into production automatically.
