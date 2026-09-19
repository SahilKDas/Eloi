# Eloi E4: E2-preserving target and tactical campaign

E4 is a 64-unit, unreleased native-Eloi experiment. It begins from exact E2
and treats E2 behavior as something to preserve, not merely an initialization
to overwrite.

Each scalar target is 80% E2 static evaluation and 20% corrected, ±1,500 cp
teacher evaluation. Training replays the frozen broad tactical rankings and
adds high-weight child-position rankings for every best-move regression EPD.
One learned delta is exported at 10%, 20%, and 35% strength. This isolates how
far Eloi can move from E2 before defensive behavior breaks.

Every candidate must pass the complete engine correctness suite before games.
Passing candidates then face native E2 in mirrored screening. Production Eloi
v3.1.2 remains unchanged unless a later campaign explicitly qualifies E4.

## Result

| Candidate | Correctness failures | Initial 20-game score | Decision |
|---|---:|---:|---|
| E4-anchor-10 | 0 | 7W/7D/6L, 52.5% | Selected native mode after direct qualification |
| E4-anchor-20 | 0 | 8W/8D/4L, 60.0% | Extended, then rejected in favor of E4-anchor-10 |
| E4-anchor-35 | 1 | Not run | Rejected; repeated the online knight hang |

E4-anchor-20 then played 40 additional games on fresh mirrored reserve
openings, scoring 13W/15D/12L (51.25%). The combined 60-game result is
**21W/23D/16L, 32.5/60 (54.17%)**, with zero protocol failures. Independent
replay verified all 60 games, moves, final positions, results, and pairings.

That initial result selected E4-anchor-20 for further comparison, not for
release. The later direct comparison against E4-anchor-10 used 400 disjoint
games over 200 fresh mirrored openings:

| Stage | E4-anchor-20 W/D/L | E4-anchor-20 score |
|---|---:|---:|
| Initial comparison | 18/14/18 | 25/50 (50.00%) |
| First confirmation | 41/56/53 | 69/150 (46.00%) |
| Fresh rematch | 59/83/58 | 100.5/200 (50.25%) |
| **Combined** | **118/153/129** | **194.5/400 (48.63%)** |

Every game completed without a protocol failure and every PGN passed
independent legal replay. E4-anchor-20 did not establish superiority and lost
the combined direct comparison. Eloi therefore selects the more conservative
**E4-anchor-10** network for its native mode. Its exact quantized header SHA-256
is `4C705496950E27204C976F0D027CAA9C73B209961584F7998742AA481B524E88`.

Caissa remains the default Standard brain. The GUI exposes Caissa 1.25 and
Eloi E4-10 for Standard games; Chess960 and Horde force Eloi E4-10. Explicit
native-brain selection and emergency fallback also use E4-10. This decision
does not by itself create a release or make an Elo claim against Caissa-backed
production.
