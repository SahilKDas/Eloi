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
| E4-anchor-10 | 0 | 7W/7D/6L, 52.5% | Passed, not selected |
| E4-anchor-20 | 0 | 8W/8D/4L, 60.0% | Selected for extension |
| E4-anchor-35 | 1 | Not run | Rejected; repeated the online knight hang |

E4-anchor-20 then played 40 additional games on fresh mirrored reserve
openings, scoring 13W/15D/12L (51.25%). The combined 60-game result is
**21W/23D/16L, 32.5/60 (54.17%)**, with zero protocol failures. Independent
replay verified all 60 games, moves, final positions, results, and pairings.

E4-anchor-20 is therefore the preferred **unreleased Eloi-native research
brain**. Sixty games are preliminary evidence, not a reliable Elo estimate or
production qualification. Eloi v3.1.2 and its production E2 header remain
unchanged; no package or release was produced.
