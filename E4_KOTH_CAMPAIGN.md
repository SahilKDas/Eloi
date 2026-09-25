# E4-KOTH Campaign

## Outcome

E4-KOTH defeated the unchanged E4-10 (“E4-traditional”) baseline by **80 wins, 2 draws, and 18 losses**, scoring **81.0/100 (81.0%)** in the frozen 100-game King of the Hill gauntlet. All games completed, no protocol failure occurred, and an independent legal replay verified all 100 PGNs.

This is variant-specific evidence. Eloi v3.4.3 promotes E4-KOTH only for King
of the Hill; it does not replace the Standard model or establish strength
against unrelated engines.

## Candidate construction

- Starting point: the preserved E4-10 floating-point checkpoint.
- Training corpus: 20,000 deterministic, unique, nonterminal King of the Hill positions.
- Partition: 17,953 training positions and 2,047 validation positions.
- Position mix: equal broad-random and king-to-hill-biased generation.
- Target: the exact E4-10 quantized evaluation plus a 120 cp target adjustment per relative Manhattan-distance step to the four hill squares.
- Training: one deterministic epoch, with the learned delta anchored to 25% to preserve E4 behavior.
- Candidate search evaluation: the same 120 cp king-distance term, promoted as the KOTH-only v3.4.3 default.
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

## v3.4.3 confirmation

The production-integrated candidate completed a fresh 60-game, 30-opening
mirrored confirmation against the exact frozen traditional baseline. It scored
**45W/2D/13L, 46/60 (76.67%)**. All 60 games replayed legally and no protocol
failure occurred. The candidate scored 23/30 with White and 23/30 with Black.

- Protocol: `1B3BF9B2DF419E5941E877FB4ABF492E94670057ED00334B3E886476F5DC8EA6`
- Results: `BEFB4C21B1949F69A2F1617377C96D915CDE50EF4768925DB513292614A9FC5D`
- PGN: `1782AC0283EC9D1393CE7C8FF8204E013EA18BC6CFCE8BA5A6E7BD76E732F097`

## Recommendation

Use E4-KOTH as Faloi's KOTH-specific production brain. Keep E4-10 for every
other Eloi-native route. The evaluator identity is embedded in accumulator and
transposition state so KOTH data cannot leak into Standard or another variant.
