# Faloi - Fairy Eloi

Faloi is Eloi's fairy-chess layer. King of the Hill, Atomic, and Antichess are included in Eloi v3.3.2.

## Qualified laboratory variants

| Variant | Candidate | Control | Result | Score |
| --- | --- | --- | ---: | ---: |
| King of the Hill | E4-KOTH | E4-traditional | 80W/2D/18L | 81.0% |
| Atomic | Atomic-140 | untuned Faloi | 52W/12D/36L | 58.0% |
| Antichess | Antichess-100 | untuned Faloi | 97W/0D/3L | 97.0% |

These are frozen variant comparisons, not Elo claims. Atomic-140 and Antichess-100 are promoted in v3.3.2; the separately trained E4-KOTH network remains laboratory-only.

## Rules and routing

- **KOTH:** orthodox legality plus an immediate center-square king win.
- **Atomic:** captures explode the capturing square and adjacent non-pawns; adjacent pawns survive, and exploding the opposing king wins.
- **Antichess:** captures are compulsory, kings are non-royal, castling is disabled, king promotion is supported, and losing every piece or having no legal move wins.
- All three bypass Standard-only Caissa 1.25 and use Eloi''s three-thread search.

Atomic-140 adds a 140 cp blast-pressure heuristic; Antichess-100 adds a 100 cp material-shedding heuristic. These are compile-time variant terms, not neural-network training.

## Interfaces

- Native GUI: choose **KOTH**, **Atomic**, or **Anti**. Each forces Eloi.
- UCI: set `UCI_Variant` to `kingofthehill`, `atomic`, or `antichess`.

## Validation

All core, hybrid, and GUI suites pass. Legal-move parity with python-chess passed 64/64 Atomic and 64/64 Antichess positions. Each campaign used 50 mirrored openings, 250 ms/move, three threads/engine, 32 MB hash, fresh processes/game, and Idle priority; all 200 completed games replayed successfully.

The first Antichess attempt stopped in game one after `bestmove 0000` despite legal moves. Its evidence remains preserved. The legal root fallback was fixed, the exact position retested, and a fresh R2 completed 100 games without protocol failure.

See [FALOI_FAIRY_CAMPAIGNS.md](FALOI_FAIRY_CAMPAIGNS.md) and [the result manifest](data/faloi_atomic_antichess_results.json).

## Boundary

Native Lichess support is not enabled for these variants. Standard UCI/Lichess remains on Caissa 1.25; Standard GUI, Chess960, Horde, fairy variants, and fallback remain Eloi-owned.
