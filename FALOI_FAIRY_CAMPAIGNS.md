# Faloi Atomic and Antichess Campaigns

## Results

| Variant | W/D/L | Score | White split | Black split | Replay | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Atomic | 52/12/36 | 58/100 | 29/6/15 (32/50) | 23/6/21 (26/50) | 100/100 | 0 |
| Antichess R2 | 97/0/3 | 97/100 | 49/0/1 (49/50) | 48/0/2 (48/50) | 100/100 | 0 |

Protocol: 50 mirrored openings, 250 ms/move, three threads/engine, 32 MB hash, fresh processes/game, Idle priority. Passing required a completed score above 50% and no protocol failure. Results qualify laboratory candidates only.

## Implementation and verification

Atomic implements explosive captures with exact undo, adjacent-pawn survival, Atomic king safety, and king-explosion victory. Antichess implements compulsory capture, non-royal kings, no castling, king promotion, and victory with no pieces or legal moves. Both bypass Caissa and disable inappropriate orthodox pruning.

The control had no variant scoring term. Candidates used `ELOI_ATOMIC_BLAST_BONUS_CP=140` or `ELOI_ANTICHESS_SHED_BONUS_CP=100`; NNUE bytes were unchanged.

`scripts/differential_fairy_movegen.py` matched python-chess on 64/64 randomized positions per variant. It caught two corrected defects: overly restrictive Atomic check and omitted Antichess king promotions.

## Preserved Antichess failure

The first run in `tmp/faloi-antichess-gauntlet100-250ms` stopped in game one at ply 8 after `bestmove 0000` with legal moves. It was not resumed or counted. An empty reconstructed PV had overwritten a known-legal root result. The fallback was fixed, the exact position returned `c3d4`, and R2 used newly frozen binaries and a fresh directory.

## Evidence hashes

Atomic (`tmp/faloi-atomic-gauntlet100-250ms`):

- Protocol: `C1D2E6B23041F3A7D1D02E8DC361BA5CEE969AE00A771981385155F4ACDC1B4A`
- Results: `2B5AE4A8F5FD092CD53BB0DDE0D7D0C9570179FB8CEA3A324BBAFC2E3BD6BDED`
- PGN: `19DB4AF1F0C9120C28845C052117E1312A7F1039FFC0D8F8BDD41F6C837EA056`
- Candidate/control EXEs: `BFD5FEB1487BDE843C28094206B40AEADE87EF76155DAC70AE520616FD7E0721` / `AD0FEFAE5552441EE6A871303A6900F9655306DCACF81464CA1DFB794C2178A6`

Atomic was frozen before the generic empty-PV fix; no such incident occurred, so its original identities remain authoritative.

Antichess R2 (`tmp/faloi-antichess-gauntlet100-250ms-r2`):

- Protocol: `5AD5FD98130BB51C5BFAA5CB2B59DBCBE868ABB837BB9E0EC2AC4154568842DB`
- Results: `BF455F9C906E21E469E3D4467CA25BB69D9C917D3A1D3A20B872052DC4444393`
- PGN: `B9AA08A99F4333C23BF28AC51910F7D5D26C75D9F9404E066C2DE65E3C971195`
- Candidate/control EXEs: `070AB2C383E35D85740192A0C767F01C26D2AB59B373BC21942A95F212CD7EBB` / `4BF277A409F74460940E3025073596044782B11D05784F0C2A5567219CD2FC9B`

Shared runner: `67EDE7FB8BE622D512C7DED8E33B19D866211424C6EEE085F9E6FFAB7862BA9D`.

Final source passed core, hybrid, and GUI suites. Production stayed untouched. Final measurements: project tmp 3,853,748,875 bytes; training-related data 1,164,200,175 bytes; C drive free 18,620,112,896 bytes.
