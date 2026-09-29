"""Export exact Eloi quantized weights into a deterministic Rust model format."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

MODELS = {
    "e4-10": ("nnue_weights.hpp", "4c705496950e27204c976f0d027caa9c73b209961584f7998742aa481b524e88"),
    "e4-koth": ("nnue_koth_weights.hpp", "e06f0b3a71445933bf066e8fe6b03a9271b94db522a15180c63da4703e5fbf8e"),
    "e4-atomic": ("nnue_atomic_weights.hpp", "9b47e6eaefbb3dcae0b5861ae90c8a647fdd3a6a31fff93543d8dac336d5b179"),
}


def export(header: Path, expected: str) -> tuple[bytes, dict]:
    source = header.read_bytes()
    canonical = source.replace(b"\r\n", b"\n")
    campaign_header = canonical.replace(b"nnue_koth_weights", b"nnue_weights") if header.name == "nnue_koth_weights.hpp" else canonical
    if hashlib.sha256(campaign_header).hexdigest() != expected:
        raise ValueError(f"canonical source header hash mismatch: {header.name}")
    text = canonical.decode("utf-8")
    arrays = {}
    for name, count, minimum, maximum in (("bias", 64, -32768, 32767), ("output", 64, -32768, 32767), ("input", 393216, -128, 127)):
        match = re.search(rf"\b{name}\s*\{{\{{(.*?)\}}\}}\s*;", text, re.S)
        if not match:
            raise ValueError(f"missing weight array: {name}")
        values = [int(v) for v in re.findall(r"-?\d+", match.group(1))]
        if len(values) != count or any(v < minimum or v > maximum for v in values):
            raise ValueError(f"invalid weight dimensions/range: {name}")
        arrays[name] = values
    payload = b"ELNNUE1\0" + struct.pack("<II", 6144, 64)
    payload += struct.pack("<64h", *arrays["bias"])
    payload += struct.pack("<64h", *arrays["output"])
    payload += struct.pack("<393216b", *arrays["input"])
    return payload, {
        "source_header": header.name,
        "source_file_sha256": hashlib.sha256(source).hexdigest(),
        "canonical_lf_header_sha256": hashlib.sha256(canonical).hexdigest(),
        "campaign_header_sha256": expected,
        "production_namespace_rename": header.name == "nnue_koth_weights.hpp",
        "artifact_sha256": hashlib.sha256(payload).hexdigest(),
        "architecture": {"features": 6144, "hidden": 64, "quantization": 8},
        "weight_values_changed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("model export collision")
    prepared = {name: export(args.headers / filename, expected) for name, (filename, expected) in MODELS.items()}
    args.output.mkdir(parents=True)
    manifest = {"schema": 1, "models": {}}
    for name, (payload, evidence) in prepared.items():
        (args.output / f"{name}.ennue").write_bytes(payload)
        manifest["models"][name] = evidence
    (args.output / "provenance.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
