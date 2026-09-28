# Eloi v3.4.4

Eloi v3.4.4 is a native-Lichess reliability hotfix. It does not change the
Caissa 1.25 network, Eloi neural evaluators, search heuristics, variant rules,
or public UCI options, and it makes no chess-strength claim.

## Fixed

- Clock-managed Standard searches no longer inherit a fixed 2.5-second parent
  watchdog. The isolated Caissa worker now receives the real hard search budget
  selected from the live clock.
- The parent watchdog uses that same budget plus a 150 ms containment margin
  for IPC completion and crash containment.
- If Caissa fails, Eloi E4-10 receives a new budget calculated from the clock
  time remaining after the failed primary search.
- A depth-zero Eloi fallback cannot cross the native-Lichess submission
  boundary unless it contains a move from Eloi's authoritative legal list and
  is explicitly recorded as `emergency_legal_move`.

## Validation

- A clock-managed Caissa regression search ran for 12.05 seconds and returned
  `e2e4` without a watchdog failure or fallback. The former implementation
  would terminate this search after 2.5 seconds.
- Forced isolated-worker failure recovered through E4-10 at completed depth 13
  with a legal move.
- All C++ core, hybrid, and GUI suites passed.
- All 165 Python tests passed.
- Standard starting-position perft depth 4 returned 197,281 nodes.
- Native-Lichess configuration validation passed.

Standard Lichess still uses crash-contained Caissa 1.25. All v3.4.3 variant
routing, networks, and strength evidence remain unchanged.
