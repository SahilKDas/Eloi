# Eloi v3.1.1 hotfix

Status: stable hotfix. Live Lichess validation passed before publication.

## Defects found in v3.1.0

- The native WinHTTP client requested an 8192-byte read directly from an
  indefinite NDJSON event stream. A small `gameStart` event could remain
  buffered, leaving the bridge at its welcome message while a game timed out.
- Native Lichess play invoked Eloi's legacy `Searcher` directly instead of the
  production Standard routing used by UCI. Consequently, native Standard games
  did not use the crash-contained Caissa 1.25 brain advertised by v3.1.0.

## Fix

- Query WinHTTP for currently available bytes before each stream read and read
  only that bounded amount.
- Print an explicit connection line for the account and game streams.
- Route Standard positions through `IsolatedCaissaBrain`, using the adjacent
  hash-pinned `eval-71-v1.25.pnn` and production `Eloi.exe` worker.
- Retain Eloi E2 for Chess960, Horde, and safe fallback after a recorded Caissa
  failure.
- Route pondering through the same variant-aware production selector.
- Link the Exoskeleton `EloiLichess.exe` against the brain adapter library.

## Validation completed

- Split-runtime hotfix build succeeded.
- Full C++ suite passed: 3/3.
- Native configuration check passed.
- Five-position Standard Caissa UCI smoke completed with legal moves.
- Caissa network SHA-256 remained
  `615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`.

## Live validation

The candidate connected visibly to the Lichess account and event streams,
reacted to a real game, and submitted legal moves. This closed the final
functional gate that v3.1.0 had failed.