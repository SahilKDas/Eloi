#!/usr/bin/env python3
"""Inspect a Caissa v1.2.5 packed neural network without loading the engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import struct


MAGIC = 0x43534E4E
VERSION = 12
INPUTS = 24_576
ACCUMULATOR = 1_024
VARIANTS = 8
HEADER_BYTES = 64
INPUT_WEIGHT_BYTES = INPUTS * ACCUMULATOR * 2
INPUT_BIAS_BYTES = ACCUMULATOR * 2
VARIANT_BYTES = 4_160
EXPECTED_BYTES = HEADER_BYTES + INPUT_WEIGHT_BYTES + INPUT_BIAS_BYTES + VARIANTS * VARIANT_BYTES


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def signed_i16_stats(data: bytes, offset: int, count: int) -> dict[str, int | float]:
    values = memoryview(data)[offset : offset + count * 2].cast("h")
    total = 0
    total_sq = 0
    minimum = 32_767
    maximum = -32_768
    zeros = 0
    for value in values:
        total += value
        total_sq += value * value
        minimum = min(minimum, value)
        maximum = max(maximum, value)
        zeros += value == 0
    mean = total / count
    variance = total_sq / count - mean * mean
    return {
        "count": count,
        "minimum": minimum,
        "maximum": maximum,
        "mean": mean,
        "standard_deviation": max(variance, 0.0) ** 0.5,
        "zeros": zeros,
    }


def inspect(path: pathlib.Path) -> dict:
    data = path.read_bytes()
    if len(data) != EXPECTED_BYTES:
        raise ValueError(f"size {len(data)} does not match {EXPECTED_BYTES}")
    header = struct.unpack_from("<16I", data)
    expected = (MAGIC, VERSION, INPUTS, 2 * ACCUMULATOR, 0, 0, 1, VARIANTS, 0, 0)
    if header[:10] != expected or any(header[10:]):
        raise ValueError(f"unsupported header: {header}")

    input_offset = HEADER_BYTES
    bias_offset = input_offset + INPUT_WEIGHT_BYTES
    variants_offset = bias_offset + INPUT_BIAS_BYTES
    variants = []
    for index in range(VARIANTS):
        offset = variants_offset + index * VARIANT_BYTES
        padding = data[offset + 4_100 : offset + VARIANT_BYTES]
        variants.append({
            "index": index,
            "non_king_piece_count": f"{4 * index}-{4 * index + 3}" if index < 7 else "28+",
            "weights": signed_i16_stats(data, offset, 2 * ACCUMULATOR),
            "bias": struct.unpack_from("<i", data, offset + 4_096)[0],
            "padding_nonzero_bytes": sum(byte != 0 for byte in padding),
        })

    return {
        "path": str(path.resolve()),
        "sha256": sha256(data),
        "file_bytes": len(data),
        "header": {
            "magic_hex": f"0x{header[0]:08X}",
            "version": header[1],
            "layer_sizes": list(header[2:6]),
            "layer_variants": list(header[6:10]),
        },
        "layout": {
            "header": [0, HEADER_BYTES],
            "accumulator_weights": [input_offset, bias_offset],
            "accumulator_biases": [bias_offset, variants_offset],
            "output_variants": [variants_offset, EXPECTED_BYTES],
        },
        "trainable_parameters": INPUTS * ACCUMULATOR + ACCUMULATOR + VARIANTS * (2 * ACCUMULATOR + 1),
        "accumulator_weights": signed_i16_stats(data, input_offset, INPUTS * ACCUMULATOR),
        "accumulator_biases": signed_i16_stats(data, bias_offset, ACCUMULATOR),
        "output_variants": variants,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("network", type=pathlib.Path)
    parser.add_argument("--json", type=pathlib.Path)
    args = parser.parse_args()
    report = inspect(args.network)
    encoded = json.dumps(report, indent=2)
    if args.json:
        args.json.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
