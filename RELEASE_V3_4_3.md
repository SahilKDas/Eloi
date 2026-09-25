# Eloi v3.4.3

Eloi v3.4.3 gives King of the Hill its qualified E4-KOTH neural evaluator and
adds native Lichess support for King of the Hill, Atomic, and Antichess.

## Brain routing

| Mode | Brain |
| --- | --- |
| Standard UCI/Lichess | Crash-contained Caissa 1.25 |
| Standard native GUI | User-selected Caissa 1.25 or Eloi E4-10 |
| King of the Hill | Eloi E4-KOTH plus the qualified 120 cp hill term |
| Chess960, Horde, Atomic, Antichess, fallback | Eloi E4-10 |

Only Standard may launch Caissa. Opening-book use remains Standard-only, and
native Lichess pondering is disabled for KOTH, Atomic, and Antichess.

## KOTH evidence

The original frozen campaign scored 80W/2D/18L. After production integration,
a fresh 60-game mirrored confirmation at 250 ms/move scored **45W/2D/13L,
46/60 (76.67%)** against the exact traditional E4 baseline. There were zero
protocol failures and all 60 PGNs passed independent replay verification.

The source KOTH header has SHA-256
`E06F0B3A71445933BF066E8FE6B03A9271B94DB522A15180C63DA4703E5FBF8E`.
The selected checkpoint has SHA-256
`D2DC34D6CA95AC280B6093E6EA2F6D6DA6148291152043DA2C2961B3B272361C`.

These results are variant-specific and are not a Standard-chess Elo claim.

## Lichess configuration

The default empty-token configuration accepts `standard`, `chess960`, `horde`,
`kingOfTheHill`, `atomic`, and `antichess`. Unsupported variants are declined;
an unsupported or disabled game stream is recorded and safely resigned.

No model is downloaded at build time or runtime, and no private token is
included in either Windows package.
