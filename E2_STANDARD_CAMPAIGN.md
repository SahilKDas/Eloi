# E2 standard-chess strength campaign

## Outcome

E2-ranking is the first post-v2.5.0 candidate to clear the complete staged
strength ladder against production C. It scored **45 wins, 56 draws and 24
losses**, or **73/125 points (58.4%)**, in the fully disjoint final gauntlet.
The frozen pass line was 63/125 points.

The maintainer subsequently selected E2-ranking for the v2.7.5 source release
after a separate 250-game confirmation scored 93W/94D/63L (56.0%). The tracked
production header is now exact E2-ranking. Published v2.5.0 packages and any
existing local installation remain C until replaced separately.

## Standard rules only

The campaign followed FIDE standard chess rules for every learning and
strength-selection input:

- 40,000 accepted base evaluation positions were independently parsed as
  valid orthodox positions.
- All 12,000 selected legacy puzzle positions were orthodox and their best
  moves were legal.
- All 166 newly labeled hard positions were orthodox.
- Screening, confirmation and final-match openings were orthodox.
- Chess960 training rows: **0**.
- Horde training rows: **0**.

The unchanged differential move-generation test still exercised Standard,
Chess960 and Horde to prove that an experimental header did not damage engine
mechanics. Those were correctness tests, not training or selection data.

## What E2 changed

E1 had better offline MAE than C but lost their 125-game match 29W/52D/44L.
E2 therefore used E1's actual failures as diagnostic input instead of merely
adding more generic positions.

1. Select the 28 mirrored E1 opening pairs that scored at most 0.5/2.
2. Extract 3,197 eligible standard positions at E1's turns.
3. Deterministically inspect 384 positions with fresh 5,000-node C and E1
   searches.
4. Retain 166 positions where C, fresh E1 or E1's played move disagreed.
5. Use Stockfish 17.1 offline at 100,000 nodes to identify the best move and
   plausible alternatives; use 25,000-node restricted searches when a played
   move was outside MultiPV.
6. Keep alternatives at least 20 cp below the teacher's best move, producing
   365 legal-move ranking pairs.
7. Split with an independently salted deterministic hash: 130 training and
   36 validation positions.
8. Start every candidate from exact C, blend C and teacher evaluation targets,
   retain the legacy tactical rankings, emphasize the new hard rankings, and
   anchor the final parameter delta back toward C.

Stockfish was an offline label generator only. It exited before training and
matches, is not an Eloi backend, and is not required at runtime.

## Corrected partition defect

The first immutable scratch attempt sorted positions by ID and reused that ID
prefix for partition assignment. All 166 labels consequently landed in
validation. The gate caught the empty training split before any weights were
trained.

That attempt remains unchanged under `tmp/nnue-e2-standard`. Commit
`95fee94af67f9c78a0d49329b7cfebd7bdc8d31b` introduced an independently
salted partition and a new `tmp/nnue-e2-standard-v2` root. The completed split
was 130/36. No rejected bytes were silently repurposed.

## Candidate results

All candidates retain the 64-unit architecture.

| Candidate | Standard MAE | Mean drift from C | 20-game screen |
|---|---:|---:|---:|
| E2-conservative | 181.5805 cp | 5.1815 cp | 4W/7D/9L, 37.5% |
| E2-balanced | 180.0005 cp | 19.0175 cp | 6W/5D/9L, 42.5% |
| E2-ranking | 178.10225 cp | 43.10625 cp | **7W/8D/5L, 55.0%** |

The engine-in-loop screen selected E2-ranking. Offline MAE did not decide the
winner. Held-out hard-pair accuracy was only 30.3% for every quantized
candidate, which remains a limitation and another reason not to equate an
offline metric with playing strength.

## Correctness

Every candidate passed:

- the complete C++ suite and all 15 permanent EPD regressions;
- SEE, TT, board restoration and scalar/runtime NNUE checks included there;
- standard starting-position perft depth 4: 197,281 nodes;
- 32 seeded differential positions each for Standard, Chess960 and Horde.

The selected float checkpoint quantizes byte-for-byte to its emitted header.
No match contained an illegal move, crash or protocol failure. Production C's
header remained
`6510D18A63C3AB68C337B5427A03AEF3284080BEA7A400746391688392BB16CD`.

## Strength ladder

All games used 10,000 nodes per move, three Eloi search threads per process,
32 MB hash, books/noise disabled, zero move overhead, a 200-ply draw cap and
Windows Idle priority. Each set used openings excluded from its training data.

### Confirmation

On 30 untouched mirrored reserve openings, E2-ranking scored **31W/22D/7L**:
42/60 points, or **70.0%**. The frozen requirement was at least 52%.

### Independent final

The authoritative final selected 63 unique standard piece-placement keys at
or after index 363 in `data/strength_openings.json`, excluding every training,
screening and confirmation key. It used 62 mirrored pairs plus one declared
unpaired game.

| Result | Value |
|---|---:|
| Wins | 45 |
| Draws | 56 |
| Losses | 24 |
| Points | 73/125 |
| Score | **58.4%** |
| Required | 63/125 |
| Candidate White | 24W/26D/13L |
| Candidate Black | 21W/30D/11L |

Independent replay verified all 245 non-superseded
screening/confirmation/final games, their pairings, legal moves, final
outcomes and standard-only opening identities. The 62 mirrored pairs alone
scored 58.06%. A normal approximation over those pairs gives a descriptive
95% interval of 51.71%–64.42%. Transforming the raw 58.4% score gives about
+58.9 Elo. Neither statistic is a formal rating claim.

### Superseded first final

The first final run was valid engine play and scored 50W/49D/26L (59.6%), but
a post-run learning-key audit found two screening and seven confirmation
piece-placement overlaps. It had no training overlap, yet it was not fully
independent from the preceding match stages. Its PGN and result remain
preserved as historical evidence and are not pooled with any other stage.

Commit `8d887a2bcadcd0b6f090b58b8afee2b4668b9b12` added a selector that
refuses training, screening and confirmation learning-key overlap. The
replacement final above has zero overlap in all three categories and is the
only final result used for the campaign decision.

## Identities

- E2-ranking header:
  `E3DFBE02F4DC765C45E243EFD4437E9EC3390D4F167531D6F54765CECB899C9F`
- E2-ranking float checkpoint:
  `E3E3D98C7CDF85E0D8AE82A7F07777E81C9C0FBE6F1BB31774F2DDA2118FCD29`
- E2-ranking validation binary:
  `966E4E87FB75664F96B2B50DA1603C179EFE380D1D341469B97BA6EAD94BEB66`
- Final PGN:
  `C783BABDC7C487EFAA09D29C3D62013537C8DFE3D86FDD322A794ADDEACA1574`
- Final opening suite:
  `021DC3BA1366353AE7DEDEEF46DFACBF7FD6A000D1B96305DADC79A57EA7E606`
- Final match protocol:
  `D87698582B0C3C0C722B39E7425A67D0B9909B5A349C9820BEA81A6B50BB0AE6`
- Final amendment:
  `4E55797CC89E8C9B8454F8F5DDB54D633DCD1F122ACCDB6B04EB9DEDE7436876`
- Final raw result:
  `BB0023A83E553A75E94BE90874B74AE25E00F7D125908D82F2CBF193DF7666CA`
- Final compact summary:
  `621229A4DE1C39E69C70CFD7163499220DF1F665CF685D389C20AED56D098B82`
- Corrected hard labels:
  `03BE74C4145F533A07D40E394FB5504EBC70FCF17E209E3B444F0FC13EE6FDD6`

The complete compact manifest is
[data/nnue_e2_standard_results.json](data/nnue_e2_standard_results.json).
Large labels, checkpoints, binaries, build trees and PGNs remain ignored local
artifacts under `tmp/nnue-e2-standard-v2`.

## Decision and next gate

E2-ranking was promoted byte-for-byte to the v2.7.5 production source header.
The later 250-game confirmation used 125 mirrored openings disjoint from
training and every prior E2 match suite, scored 140/250 points, and independently
replayed all games without a protocol failure. Release packages and replacement
of an active v2.5.0 bridge remain separate work.

The low held-out hard-pair accuracy and descriptive uncertainty remain
visible. Do not rewrite the result as certainty, pool the development screen
or superseded final into the authoritative final score, or claim that
Stockfish is part of Eloi.
