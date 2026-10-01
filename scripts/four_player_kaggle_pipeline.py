"""Kaggle-oriented four-player training pipeline scaffold.

This script is intentionally safe to run locally in dry-run mode. The real
500k-position campaigns are expected to run inside a user-owned Kaggle Notebook
with private datasets for resumable shards and checkpoints. It never downloads
models, never uses pickle artifacts, and never writes runtime assets directly
into Eloi packages.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import random
import sys
import time
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1
TARGET_POSITIONS = 500_000
DEFAULT_SEED = 0xE104_0000


@dataclasses.dataclass(frozen=True)
class Campaign:
    mode: str
    seed: int
    target_positions: int
    output: Path
    dry_run: bool

    def manifest_path(self) -> Path:
        return self.output / f"four_player_{self.mode}_manifest.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def deterministic_game_id(mode: str, seed: int, index: int) -> str:
    text = f"eloi-v4:{mode}:{seed}:{index}".encode("utf-8")
    return sha256_bytes(text)[:24]


def synthetic_records(campaign: Campaign, count: int) -> Iterable[dict[str, object]]:
    rng = random.Random(campaign.seed)
    positions_per_game = 4 if campaign.dry_run else 32
    categories = [
        "broad",
        "check",
        "mating-threat",
        "promotion",
        "elimination-boundary",
        "forced-move",
        "king-safety",
    ]
    for index in range(count):
        game_id = deterministic_game_id(campaign.mode, campaign.seed, index // positions_per_game)
        category = categories[(index + rng.randrange(len(categories))) % len(categories)]
        yield {
            "schema": SCHEMA_VERSION,
            "mode": campaign.mode,
            "source_game": game_id,
            "ply": index % 160,
            "category": category,
            "position_hash": sha256_bytes(
                f"{campaign.mode}:{game_id}:{index}".encode("utf-8")
            ),
            "split": split_for_game(game_id),
        }


def split_for_game(game_id: str) -> str:
    bucket = int(game_id[:8], 16) % 10
    if bucket < 8:
        return "train"
    if bucket == 8:
        return "validation"
    return "sealed-test"


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_manifest(campaign: Campaign) -> dict[str, object]:
    sample_count = 512 if campaign.dry_run else campaign.target_positions
    records = list(synthetic_records(campaign, sample_count))
    split_counts = {"train": 0, "validation": 0, "sealed-test": 0}
    category_counts: dict[str, int] = {}
    for record in records:
        split_counts[str(record["split"])] += 1
        category = str(record["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
    digest = sha256_bytes(
        "\n".join(str(record["position_hash"]) for record in records).encode("ascii")
    )
    return {
        "schema": SCHEMA_VERSION,
        "mode": campaign.mode,
        "seed": campaign.seed,
        "target_positions": campaign.target_positions,
        "materialized_positions": sample_count,
        "dry_run": campaign.dry_run,
        "split_policy": "source-game hash bucket: 0-7 train, 8 validation, 9 sealed-test",
        "split_counts": split_counts,
        "category_counts": category_counts,
        "records_sha256": digest,
        "python": sys.version,
        "platform": platform.platform(),
        "created_unix": int(time.time()),
        "artifact_policy": "float32 or quantized Rust headers only; no pickle artifacts",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["ffa", "teams"], required=True)
    parser.add_argument("--output", type=Path, default=Path("tmp/four-player-kaggle"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--target-positions", type=int, default=TARGET_POSITIONS)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.target_positions != TARGET_POSITIONS:
        raise SystemExit("v4 protocol requires exactly 500000 target positions per mode")
    campaign = Campaign(
        mode=args.mode,
        seed=args.seed,
        target_positions=args.target_positions,
        output=args.output,
        dry_run=args.dry_run,
    )
    # Full campaigns belong inside Kaggle; procrastination is not a compute provider.
    if not campaign.dry_run and os.environ.get("KAGGLE_URL_BASE") is None:
        raise SystemExit("full campaign must run in Kaggle; use --dry-run locally")
    manifest = build_manifest(campaign)
    write_json_atomic(campaign.manifest_path(), manifest)
    print(campaign.manifest_path())
    print(manifest["records_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
