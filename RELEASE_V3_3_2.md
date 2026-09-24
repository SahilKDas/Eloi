# Eloi v3.3.2

Eloi v3.3.2 adds three Eloi-owned fairy-chess modes while preserving the existing Standard-chess production route.

## Highlights

- Adds King of the Hill, Atomic, and Antichess legality, terminal conditions, UCI/perft support, native GUI selection, and Caissa bypass.
- Promotes the qualified Atomic 140 cp blast-pressure term and Antichess 100 cp material-shedding term.
- Keeps Standard UCI and native Lichess on crash-contained Caissa 1.25.
- Keeps Standard GUI, Chess960, Horde, fairy variants, and emergency fallback on Eloi's three-thread E4-10 route.
- Fixes a generic root safety defect where an empty reconstructed PV could replace a known-legal root result with `bestmove 0000`.

## Strength evidence

Atomic first scored 52W/12D/36L (58%) in its 100-game 250 ms screen. It then passed both confirmations:

- 500 ms, 100 games: 51W/13D/36L, 57.5%, zero failures, 100/100 replayed.
- 250 ms, 200 games: 115W/14D/71L, 61%, zero failures, 200/200 replayed.

Antichess scored 97W/0D/3L (97%) in its clean 100-game 250 ms rerun, with zero failures and 100/100 replayed. Legal-move parity matched python-chess on 64 randomized Atomic and 64 randomized Antichess positions.

The E4-KOTH laboratory candidate scored 80W/2D/18L, but it used a separate network in addition to its 120 cp term. That model is not shipped: embedding it globally would alter Standard and fallback evaluation without qualification. KOTH is playable using E4-10 and correct KOTH rules.

These matches compare variant candidates against frozen Eloi controls; they are not cross-engine Elo estimates.

## Packages

The release contains exactly two reproducibly built Windows x64 ZIPs: standalone and Exoskeleton. Both retain the pinned Caissa 1.25 network and license, use no runtime downloads, and exclude private configuration.