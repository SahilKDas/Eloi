# Variant-native NNUE campaign

## Result

The September 2026 campaign trained independent 64-unit evaluators for
Chess960, Atomic, and Antichess from 100,000 unique variant positions apiece.
Only **E4-Atomic** qualified for production routing. Chess960 and Antichess
remain ignored laboratory artifacts and are not embedded or packaged.

This is a variant-specific result. It does not claim improved Standard, KOTH,
Horde, or Antichess strength.

| Variant | 60-game screen | 200-game confirmation | Decision |
| --- | ---: | ---: | --- |
| Chess960 | 14W/30D/16L, 29/60 (48.3%) | Not run | Rejected at screen |
| Atomic | 33W/4D/23L, 35/60 (58.3%) | 96W/16D/88L, 104/200 (52.0%) | Qualified exactly at the gate |
| Antichess | 31W/0D/29L, 31/60 (51.7%) | 96W/6D/98L, 99/200 (49.5%) | Rejected at confirmation |

Every completed match had zero protocol failures and complete legal replay.
Atomic's approximate unpaired 95% score interval is 45.1%–58.9%, so the
result satisfies the frozen promotion rule but is not a precise Elo estimate.
Its confirmation color split was 63/100 as White and 41/100 as Black.

## Frozen data and models

Each variant has 80,000 training, 10,000 validation, and 10,000 sealed-test
positions. Checkpoint selection used training and validation only. The sealed
partitions were opened afterward exactly once for final measurement.

| Variant | Selected checkpoint SHA-256 | Header SHA-256 | Sealed-test MAE |
| --- | --- | --- | ---: |
| Chess960 | `6705497210E52A04B64693699B67B2C8B92A188379A6F1224183AE6CB523F7C3` | `ECBF9469C0022A0E1625DECC49789D72C66A19AC38AFD27B648A70C7C548172F` | 479.61 cp |
| Atomic | `F2109B2622DDAC57E23E0EFB9C54B85369EC57B7CC21613B0993988448EB215E` | `9B47E6EAEFBB3DCAE0B5861AE90C8A647FDD3A6A31FFF93543D8DAC336D5B179` | 694.04 cp |
| Antichess | `FEBD87597006ED5F6C4F887715890DC1F46506D09CC04923D799D47DA49CA1E8` | `4E08270A16F517B728E06912CC553FFB0F6AE51D7C7EFD944891A0C46468E135` | 735.61 cp |

Fairy-Stockfish 14 was an ignored offline teacher only. Its executable identity
was `9ADEFF67FF3AD8A80D9706AD4416FD2D8A34AE681A14BF424B6E176C7DE916F1`.
It is neither committed, packaged, downloaded at runtime, nor used to play.

## Confirmation evidence

Atomic used deterministic mirrored opening pairs 31–130, disjoint from the
screen's pairs 1–30, at 250 ms per move, three threads per engine, 32 MB hash,
and 200 plies maximum.

- Protocol: `DADAD5F48075514C881A814D14C33EB5F62A039625DED138A21D64D66C13BC85`
- Results: `60EA94DDA6F6B4DF6521A90EDEA6035811AC4B52276050BF986002A456D9813A`
- PGN: `D156E6E9B4E53A4AC41DB431D52EB3140EE57091E3C19767E11BD5625BFBE7A9`
- Replayed: 200/200

The embedded header is byte-identical to the qualified artifact. Ten sampled
fixed-depth searches matched the frozen candidate in both move and score.
Model identity participates in accumulator rebuilding and transposition-key
separation. All other variant routes retain their previous evaluator.
