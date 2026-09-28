# Eloi v3.6.0 — One Month Old, Atomic Goes Flagship

Eloi v3.6.0 arrives exactly one month after the GitHub repository was created
on August 27, 2026. The anniversary feature is Eloi's first independently
trained, qualified variant-native evaluator: **E4-Atomic**.

## Atomic flagship brain

E4-Atomic was trained from 100,000 unique Atomic positions: 80,000 training,
10,000 validation, and 10,000 sealed test positions. Fairy-Stockfish 14 was a
pinned offline teacher only; it is not committed, packaged, downloaded, or
used at runtime.

The frozen 60-game screen finished 33W/4D/23L, scoring 35/60 (58.3%). The
sealed 200-game confirmation finished:

- **96 wins, 16 draws, 88 losses**;
- **104/200 points (52.0%)**;
- exactly the frozen 52% qualification threshold;
- zero illegal moves, crashes, watchdog failures, or protocol failures;
- 200/200 games independently replay-verified.

Atomic is the flagship brain because it alone completed and passed the full
variant-native qualification pipeline. The result stands directly on the
requirement line; it is not presented as a large or statistically conclusive
Elo gain. The approximate unpaired 95% score interval is 45.1%–58.9%.

The embedded E4-Atomic header SHA-256 is
`9B47E6EAEFBB3DCAE0B5861AE90C8A647FDD3A6A31FFF93543D8DAC336D5B179`.
Its selected checkpoint SHA-256 is
`F2109B2622DDAC57E23E0EFB9C54B85369EC57B7CC21613B0993988448EB215E`.

## Honest rejections

- Chess960: 14W/30D/16L, 29/60 (48.3%); rejected at screening.
- Antichess: 31W/0D/29L in screening, then 96W/6D/98L and 99/200
  (49.5%) in confirmation; rejected.

Those models remain ignored laboratory artifacts. Eloi does not package them
or turn a failed experiment into a release claim.

## Routing in v3.6.0

| Mode | Brain |
| --- | --- |
| Standard UCI and Lichess | Crash-contained Caissa 1.25 |
| GUI Standard choice | Caissa 1.25 or Eloi E4-10 |
| Atomic | E4-Atomic, the flagship variant-native brain |
| King of the Hill | E4-KOTH |
| Chess960, Horde, Antichess, fallback | E4-10 |

The Atomic model participates in accumulator rebuilding and transposition-key
separation, preventing evaluator state from crossing variant boundaries.

## One month of Eloi

In its first month on GitHub, Eloi grew into a C++26 engine ecosystem with a
native Skia GUI, native Lichess Operations Center, reproducible Windows
packages, six playable variants, crash-contained Caissa Standard search, and
multiple Eloi-trained neural evaluators. v3.6.0 celebrates that pace without
hiding the boundary result or the candidates that did not qualify.

This release makes no new Standard-chess strength claim.
