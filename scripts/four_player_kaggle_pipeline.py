"""Kaggle-oriented four-player training pipeline bootstrap.

This script is intentionally safe to run locally in dry-run mode. The real
500k-position campaigns are expected to run inside a user-owned Kaggle Notebook
with private datasets for resumable shards and checkpoints. It never downloads
models, never uses pickle artifacts, and never writes runtime assets directly
into Eloi packages.

The current records are deterministic bootstrap records, not final neural
training labels. They prove sharding, split isolation, hashing, resume behavior,
and Kaggle output wiring before the expensive self-play/teacher loop lands.
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
DRY_RUN_COUNT = 512
DEFAULT_SHARD_SIZE = 10_000
RECORD_SCHEMA = 1


@dataclasses.dataclass(frozen=True)
class Campaign:
    mode: str
    seed: int
    target_positions: int
    output: Path
    dry_run: bool

    def manifest_path(self) -> Path:
        return self.output / f"four_player_{self.mode}_manifest.json"

    def records_dir(self) -> Path:
        return self.output / self.mode / "records"


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
        material = synthetic_material(campaign.mode, campaign.seed, index)
        yield {
            "schema": RECORD_SCHEMA,
            "mode": campaign.mode,
            "source_game": game_id,
            "ply": index % 160,
            "category": category,
            "seat_to_move": ("red", "blue", "yellow", "green")[index % 4],
            "legal_move_count": 8 + (material % 57),
            "teacher_kind": "bootstrap-handcrafted-baseline",
            "teacher_score": synthetic_teacher_score(campaign.mode, material),
            "policy_target": synthetic_policy_target(index, material),
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


def synthetic_material(mode: str, seed: int, index: int) -> int:
    digest = hashlib.sha256(f"{mode}:{seed}:material:{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def synthetic_teacher_score(mode: str, material: int) -> object:
    centered = (material % 2001) - 1000
    if mode == "ffa":
        values = [((centered + offset) / 1000.0) for offset in (0, 137, -91, 53)]
        return {"placement_value": [round(value, 4) for value in values]}
    win = 1.0 if centered > 250 else 0.0
    loss = 1.0 if centered < -250 else 0.0
    draw = 1.0 - win - loss
    return {"wdl": [win, draw, loss]}


def synthetic_policy_target(index: int, material: int) -> dict[str, object]:
    return {
        "from": material % 160,
        "to": (material // 160) % 160,
        "promotion": ("none", "knight", "bishop", "rook", "queen")[index % 5],
    }


def materialized_count(campaign: Campaign) -> int:
    return DRY_RUN_COUNT if campaign.dry_run else campaign.target_positions


def collect_record_stats(records: Iterable[dict[str, object]]) -> tuple[dict[str, int], dict[str, int], str]:
    split_counts = {"train": 0, "validation": 0, "sealed-test": 0}
    category_counts: dict[str, int] = {}
    hashes: list[str] = []
    for record in records:
        split_counts[str(record["split"])] += 1
        category = str(record["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
        hashes.append(str(record["position_hash"]))
    digest = sha256_bytes("\n".join(hashes).encode("ascii"))
    return split_counts, category_counts, digest


def build_manifest(campaign: Campaign) -> dict[str, object]:
    sample_count = materialized_count(campaign)
    split_counts, category_counts, digest = collect_record_stats(
        synthetic_records(campaign, sample_count)
    )
    return {
        "schema": SCHEMA_VERSION,
        "record_schema": RECORD_SCHEMA,
        "mode": campaign.mode,
        "seed": campaign.seed,
        "target_positions": campaign.target_positions,
        "materialized_positions": sample_count,
        "dry_run": campaign.dry_run,
        "shard_size": DEFAULT_SHARD_SIZE,
        "split_policy": "source-game hash bucket: 0-7 train, 8 validation, 9 sealed-test",
        "split_counts": split_counts,
        "category_counts": category_counts,
        "records_sha256": digest,
        "records_dir": str(campaign.records_dir()),
        "label_status": "bootstrap-not-final-teacher-labels",
        "python": sys.version,
        "platform": platform.platform(),
        "created_unix": int(time.time()),
        "artifact_policy": "float32 or quantized Rust headers only; no pickle artifacts",
    }


def write_records(campaign: Campaign, shard_size: int = DEFAULT_SHARD_SIZE) -> list[Path]:
    records_dir = campaign.records_dir()
    records_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    current_path: Path | None = None
    current_file = None
    try:
        for index, record in enumerate(synthetic_records(campaign, materialized_count(campaign))):
            shard_index = index // shard_size
            shard_path = records_dir / f"{campaign.mode}_records_{shard_index:05d}.jsonl"
            if shard_path != current_path:
                if current_file is not None:
                    current_file.close()
                current_path = shard_path
                written.append(shard_path)
                current_file = shard_path.open("w", encoding="utf-8", newline="\n")
            assert current_file is not None
            current_file.write(json.dumps(record, sort_keys=True) + "\n")
    finally:
        if current_file is not None:
            current_file.close()
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["ffa", "teams"], required=True)
    parser.add_argument("--output", type=Path, default=Path("tmp/four-player-kaggle"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--target-positions", type=int, default=TARGET_POSITIONS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="write only the manifest; default also writes deterministic JSONL record shards",
    )
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
    shards = [] if args.manifest_only else write_records(campaign)
    manifest = build_manifest(campaign)
    manifest["record_shards"] = [str(path) for path in shards]
    write_json_atomic(campaign.manifest_path(), manifest)
    print(campaign.manifest_path())
    print(manifest["records_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
