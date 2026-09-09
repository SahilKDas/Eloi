# Caissa v1.2.5 packed neural network

This document describes the exact `eval-71-v1.25.pnn` network used by Eloi.
It is derived from the vendored Caissa v1.2.5 evaluator and independently
checked against the production network bytes. It is a runtime and training
reference, not a claim about the provenance or license of other Caissa nets.

## Production identity

- Size: `50,367,040` bytes
- SHA-256: `615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B`
- Format magic: `0x43534E4E` (`CSNN` in Caissa's implementation-defined C++ literal)
- Format version: `12`
- Trainable scalar parameters: `25,183,240`

Run `python scripts/inspect_caissa_pnn.py PATH` to inspect another file with
this layout. The tool rejects unexpected sizes, headers, or nonzero reserved
header fields.

## Byte layout

All stored integers are little-endian. C++ alignment makes the header and each
output variant exactly 64-byte aligned.

| Byte range | Size | Type | Meaning |
| --- | ---: | --- | --- |
| `[0, 64)` | 64 | header | Magic, version, layer sizes, variants, reserved zeros |
| `[64, 50,331,712)` | 50,331,648 | `int16[24576][1024]` | Sparse accumulator weights |
| `[50,331,712, 50,333,760)` | 2,048 | `int16[1024]` | Shared accumulator bias |
| `[50,333,760, 50,367,040)` | 33,280 | eight 4,160-byte records | Material-dependent output heads |

Each output record contains `int16[2048]` weights, one `int32` bias, and 60
zero padding bytes. There is no intermediate dense hidden layer: the two
1,024-wide accumulators are clipped, concatenated conceptually, and sent
directly to one selected linear output head.

## Input feature index

The network is a king-bucketed HalfKP-style sparse model. For each perspective
Caissa generates one feature per piece, including both kings:

```text
index = king_bucket * 768
      + relative_colour * 384
      + piece_type * 64
      + transformed_square
```

`piece_type` is pawn, knight, bishop, rook, queen, king numbered `0..5`.
`relative_colour` is zero for the perspective's pieces and one for its
opponent. Black perspective flips ranks. If the perspective king is on files
e--h, files are also mirrored. The transformed king square selects one of 32
symmetric king buckets via the table in `PackedNeuralNetwork.hpp`.

This produces `32 * 2 * 6 * 64 = 24,576` possible features. Castling rights,
en-passant state, clocks, repetition and side-to-move are not direct input
features. Side-to-move matters because its accumulator is supplied first.

## Exact network forward pass

For a position, build an accumulator independently from each player's
perspective using the same shared matrix and bias:

```text
A_p = int16_bias + sum(int16_weight[feature] for feature in features(p))
H_p = clamp(A_p, 0, 256)
```

The runtime stores and incrementally adds/subtracts `int16` accumulator rows.
A trainer must keep every reachable sum in the signed 16-bit range; the debug
scalar path asserts this, while SIMD addition itself has machine wraparound
semantics.

Choose output variant:

```text
variant = min(non_king_piece_count // 4, 7)
```

Thus heads cover `0..3`, `4..7`, ..., `24..27`, and `28+` non-king pieces.
With `stm` first and `nstm` second, the raw output is:

```text
raw = output_bias[variant]
    + dot(H_stm,  output_weights[variant][0:1024])
    + dot(H_nstm, output_weights[variant][1024:2048])
```

The result is from the side-to-move perspective. AVX2/SSE/AVX-512 paths use
pairwise signed 16-bit multiplication accumulated into signed 32-bit lanes.

## The network output is not UCI centipawns

Caissa performs additional evaluation outside the network. In C++ integer
arithmetic the first divisor is:

```text
(OutputScale * WeightScale) / 174 = (1024 * 256) / 174 = 1506
internal = raw / 1506
```

Division truncates toward zero. Caissa then applies:

1. Material phase scaling: `internal * (52 + phase) / 64`, where bishops and
   knights contribute 1, rooks 2, and queens 4 (`phase` is 0 through 24).
2. A small castling-rights adjustment outside the network.
3. Compression beyond absolute internal score 8,000.
4. Special handcrafted evaluation for recognized positions with at most six
   non-king pieces, bypassing the neural score entirely.
5. UCI normalization for non-mate search scores: `internal * 100 / 173`.

Consequently, fitting `raw / 1506` directly to teacher centipawns optimizes the
wrong deployed quantity. A correct trainer must either invert the complete
phase-dependent path when creating raw targets or include the post-network
transform in its differentiable/quantization-aware forward model. Positions
handled by handcrafted endgames should normally be excluded from neural loss.

## Training implications discovered in C1--C4

- C1--C3 modified only output heads and failed confirmation despite occasional
  short-match wins.
- C4 held a floating-point copy of the full matrix, but after quantization only
  592 of 25,165,824 input weights changed. It was effectively another head
  experiment and scored 33.75% against C0 in its 40-game node screen.
- C4 also treated the pre-phase network conversion as final centipawns. Its
  lower offline MAE therefore did not measure the score used by search.

A credible successor needs quantization-aware optimization, the complete
deployed score transform, measurable coverage of input-matrix cells, and
move-ranking or WDL supervision. Binary compatibility alone is not enough.
