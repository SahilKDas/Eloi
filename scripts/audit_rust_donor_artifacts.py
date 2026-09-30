"""Audit donor release data without executing any downloaded executable."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def audit(network: Path, release: Path) -> dict:
    net = network.read_bytes()
    binary = release.read_bytes()
    network_hash = hashlib.sha256(net).hexdigest()
    release_hash = hashlib.sha256(binary).hexdigest()
    expected_net = "05d552b0ae659938ef0933a06156762a8c94632740fabbbe119611c6439d2319"
    expected_release = "d76f4099aa068f8841767bcc2a4ce17ff0c921c44160cb446fe07ad868cbf9c5"
    if network_hash != expected_net or release_hash != expected_release:
        raise ValueError("official artifact digest mismatch")
    offset = binary.find(net)
    if offset < 0:
        raise ValueError("network bytes not found verbatim in official release")
    if binary.find(net, offset + 1) >= 0:
        raise ValueError("network occurs more than once in official release")
    return {
        "schema": 1,
        "donor": "Viridithas 19.0.1",
        "source_commit": "77f4731ea4c319a68fc4bb3317459a3115073820",
        "network": "noumena-b1200.nnue.zst",
        "network_sha256": network_hash,
        "network_license": "CC0-1.0",
        "network_license_basis": "https://github.com/cosmobobak/viridithas-networks/blob/main/README.md",
        "official_release_sha256": release_hash,
        "network_offset_in_release": offset,
        "network_length": len(net),
        "executed_downloaded_binary": False,
        "matching_network_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.network, args.release)
    # Preserve every previous audit; output collision is an error.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
