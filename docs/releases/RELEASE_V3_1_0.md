# Eloi v3.1.0

Eloi v3.1.0 is a speed-focused stable release. Standard chess still uses the
hash-pinned Caissa 1.25 brain under Eloi's authoritative legality, protocol,
variant routing, and crash-containment layers. The neural network and chess
search logic are unchanged.

## What changed

- Removed an unnecessary thread creation and join from every isolated Caissa
  search while preserving parent-owned cancellation and worker containment.
- Replaced byte-at-a-time worker output reads with bounded buffered reads.
- Let the isolated worker inherit Eloi's selected Windows priority instead of
  silently forcing every production search to Idle priority.
- Added a repeatable fixed-node speed benchmark and corpus test.

## Measured speed

On the maintainer's Windows laptop, using three search threads and five fixed
Standard positions:

| Benchmark | v3.0.0 baseline | v3.1.0 | Change |
| --- | ---: | ---: | ---: |
| 500,000 nodes, median of 25 searches | 2.344M NPS | 2.697M NPS | **+15.1%** |
| Median wall time | 213.6 ms | 185.6 ms | **-13.1%** |
| 100,000 nodes, median of 15 searches | 1.616M NPS | 2.193M NPS | **+35.8%** |

Three-thread parallel search is scheduling-sensitive, so these figures are
local benchmark measurements rather than a universal hardware guarantee or an
Elo claim. The longer 500,000-node result is the more conservative headline.

## Compatibility and safety

- Standard chess: Caissa 1.25 search with Eloi legality and containment.
- Chess960 and Horde: Eloi E2 search.
- Exactly three production search threads.
- No Stockfish runtime component or playing backend.
- No network or weight change.
- Windows x64 packages only.

The complete C++ suite and benchmark-tool tests passed before release
preparation. Both release ZIPs are built from the tagged source and must pass
the repository's reproducibility and package-content checks before upload.