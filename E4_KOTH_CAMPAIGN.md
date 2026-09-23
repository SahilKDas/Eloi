# E4-KOTH Campaign

## Outcome

E4-KOTH defeated the unchanged E4-10 (“E4-traditional”) baseline by **80 wins, 2 draws, and 18 losses**, scoring **81.0/100 (81.0%)** in the frozen 100-game King of the Hill gauntlet. All games completed, no protocol failure occurred, and an independent legal replay verified all 100 PGNs.

This is variant-specific laboratory evidence. It does not promote E4-KOTH into Standard chess, replace a production model, or establish strength against unrelated engines.

## Candidate construction

- Starting point: the preserved E4-10 floating-point checkpoint.
- Training corpus: 20,000 deterministic, unique, nonterminal King of the Hill positions.
- Partition: 17,953 training positions and 2,047 validation positions.
- Position mix: equal broad-random and king-to-hill-biased generation.
- Target: the exact E4-10 quantized evaluation plus a 120 cp target adjustment per relative Manhattan-distance step to the four hill squares.
- Training: one deterministic epoch, with the learned delta anchored to 25% to preserve E4 behavior.
- Candidate-only search evaluation: the same 120 cp king-distance term, compiled behind the default-off `ELOI_KOTH_HILL_BONUS_CP` setting.
- No Stockfish, Caissa, network download, live game, Standard regression fixture, Chess960 position, or Horde position was used.

Validation MAE improved from **74.774 cp** to **69.949 cp**; validation p95 absolute error improved from **219.361 cp** to **184.164 cp**.

## Correctness and match protocol

Both E4-traditional and E4-KOTH passed the complete local core, hybrid, and GUI CTest suites before game one. Each also returned a legal move in a 250 ms KOTH smoke search.

The gauntlet used:

- 50 deterministically generated four-ply KOTH openings, each mirrored for 100 games;
- 250 ms per move;
- three threads and 32 MB hash per engine;
- fresh engine processes per game;
- Windows Idle priority;
- a 200-ply adjudication ceiling after the opening;
- Eloi’s native brain for both competitors;
- no book and no noise.

Color split:

| E4-KOTH color | W | D | L | Points |
|---|---:|---:|---:|---:|
| White | 40 | 2 | 8 | 41.0/50 |
| Black | 40 | 0 | 10 | 40.0/50 |

Paired-opening totals were 32 sweeps (2.0 points), 2 pairs at 1.5, 14 split pairs (1.0), and 2 baseline sweeps (0.0).

## Identities and evidence

- Parent E4-10 checkpoint: `D613B853FE534B6AD3604080E559DB26D9CCC55E124005FE60B9ABBCD508EE99`
- Parent production header: `4C705496950E27204C976F0D027CAA9C73B209961584F7998742AA481B524E88`
- E4-KOTH checkpoint: `D2DC34D6CA95AC280B6093E6EA2F6D6DA6148291152043DA2C2961B3B272361C`
- E4-KOTH header: `E06F0B3A71445933BF066E8FE6B03A9271B94DB522A15180C63DA4703E5FBF8E`
- Traditional executable: `DD7091429913FA6797C9991879C34CB4B6375ABD758FB9E8442D1BE3EA5C311E`
- Candidate executable: `C4DC9BD1C8B2DBD4CEBF5BAE211CC245BE4A00F2A8B9C6197A53D3C5A69D9C65`
- Frozen protocol: `5425B576CDA745C374C80D9FA6C12625093832F1867C4DD152DA0A24DA9B2EFC`
- Results: `7D157F0960267FB31AF455A386BA56E4B31841C0BFFCC786BB3746DAC4CC9EFD`
- PGN: `3DF82B129FDF1C201ECDD7D15F7C8351551E1882B2185390496016E26F9DEEB0`

The detailed append-only artifacts remain ignored under `tmp/e4-koth/`. Their final footprint was 5,520,547 bytes; the campaign stayed far below the device’s training and total-temporary-storage limits.

## Recommendation

Use E4-KOTH as Faloi’s KOTH-specific laboratory brain. Keep E4-traditional/E4-10 for Standard and other already-qualified Eloi-native routes. Before any packaged release, add explicit model selection/embedding, rerun packaged-binary parity, and perform variant GUI/UCI/Lichess smoke validation.
