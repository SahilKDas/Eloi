"""Kaggle four-player self-play, teacher labels, and compact training.

This pipeline generates deterministic four-player self-play records, labels them
with a handcrafted one-ply teacher, and trains a compact PyTorch policy/value
model. It is Kaggle-only for full runs and dry-run-safe locally.

The Python rules here are a training-data generator, not the release authority.
Release qualification still requires Rust engine parity, differential legality,
model export, and the v4 gates in docs/V4_HANDOFF.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import platform
import random
import struct
import sys
import time
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 2
RECORD_SCHEMA = 2
TARGET_POSITIONS = 500_000
DRY_RUN_COUNT = 512
DEFAULT_SEED = 0xE104_0000
DEFAULT_SHARD_SIZE = 10_000
BOARD_SIZE = 14
SEATS = ("red", "blue", "yellow", "green")
PIECES = ("pawn", "knight", "bishop", "rook", "queen", "king")
PROMOTIONS = ("none", "knight", "bishop", "rook", "queen")
PIECE_VALUE = {"pawn": 1, "knight": 3, "bishop": 5, "rook": 5, "queen": 9, "king": 20}
FEATURE_SIZE = len(SEATS) * len(PIECES) * BOARD_SIZE * BOARD_SIZE + len(SEATS) * 2 + 4


@dataclasses.dataclass(frozen=True)
class Piece:
    seat: str
    kind: str


@dataclasses.dataclass(frozen=True)
class Move:
    start: int
    end: int
    promotion: str = "none"

    def key(self) -> str:
        return f"{self.start}-{self.end}-{self.promotion}"

    def index(self) -> int:
        return ((self.start * BOARD_SIZE * BOARD_SIZE + self.end) * len(PROMOTIONS)
                + PROMOTIONS.index(self.promotion))


@dataclasses.dataclass
class Position:
    board: dict[int, Piece]
    turn_index: int
    mode: str
    scores: dict[str, int]
    active: dict[str, bool]
    ply: int = 0

    @property
    def turn(self) -> str:
        return SEATS[self.turn_index % 4]

    def clone(self) -> "Position":
        return Position(dict(self.board), self.turn_index, self.mode,
                        dict(self.scores), dict(self.active), self.ply)

    def advance_turn(self) -> None:
        for _ in range(4):
            self.turn_index = (self.turn_index + 1) % 4
            if self.active[SEATS[self.turn_index]]:
                return


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

    def model_dir(self) -> Path:
        return self.output / self.mode / "model"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def square(row: int, col: int) -> int:
    return row * BOARD_SIZE + col


def rc(sq: int) -> tuple[int, int]:
    return divmod(sq, BOARD_SIZE)


def playable(sq: int) -> bool:
    row, col = rc(sq)
    if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
        return False
    return 3 <= row <= 10 or 3 <= col <= 10


def team(seat: str) -> int:
    return 0 if seat in ("red", "yellow") else 1


def enemies(mode: str, seat: str, other: str) -> bool:
    return seat != other and (mode == "ffa" or team(seat) != team(other))


def initial_position(mode: str) -> Position:
    board: dict[int, Piece] = {}
    back = ("rook", "knight", "bishop", "queen", "king", "bishop", "knight", "rook")
    for idx, kind in enumerate(back):
        board[square(13, 3 + idx)] = Piece("red", kind)
        board[square(0, 3 + idx)] = Piece("yellow", kind)
        board[square(3 + idx, 0)] = Piece("blue", kind)
        board[square(3 + idx, 13)] = Piece("green", kind)
        board[square(12, 3 + idx)] = Piece("red", "pawn")
        board[square(1, 3 + idx)] = Piece("yellow", "pawn")
        board[square(3 + idx, 1)] = Piece("blue", "pawn")
        board[square(3 + idx, 12)] = Piece("green", "pawn")
    return Position(board, 0, mode, {s: 0 for s in SEATS}, {s: True for s in SEATS})


def pawn_delta(seat: str) -> tuple[int, int]:
    return {"red": (-1, 0), "yellow": (1, 0), "blue": (0, 1), "green": (0, -1)}[seat]


def pawn_captures(seat: str) -> tuple[tuple[int, int], tuple[int, int]]:
    return {
        "red": ((-1, -1), (-1, 1)),
        "yellow": ((1, -1), (1, 1)),
        "blue": ((-1, 1), (1, 1)),
        "green": ((-1, -1), (1, -1)),
    }[seat]


def promotion_square(seat: str, sq: int, mode: str) -> bool:
    row, col = rc(sq)
    if mode == "teams":
        return {"red": row <= 2, "yellow": row >= 11, "blue": col >= 11, "green": col <= 2}[seat]
    return {"red": row <= 5, "yellow": row >= 8, "blue": col >= 8, "green": col <= 5}[seat]


def ray_moves(pos: Position, sq: int, piece: Piece, deltas: Iterable[tuple[int, int]]) -> list[Move]:
    moves: list[Move] = []
    row, col = rc(sq)
    for dr, dc in deltas:
        nr, nc = row + dr, col + dc
        while 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and playable(square(nr, nc)):
            nsq = square(nr, nc)
            target = pos.board.get(nsq)
            if target is None:
                moves.append(Move(sq, nsq))
            else:
                if enemies(pos.mode, piece.seat, target.seat):
                    moves.append(Move(sq, nsq))
                break
            nr += dr
            nc += dc
    return moves


def legal_moves(pos: Position) -> list[Move]:
    seat = pos.turn
    if not pos.active[seat]:
        return []
    moves: list[Move] = []
    for sq, piece in sorted(pos.board.items()):
        if piece.seat != seat:
            continue
        row, col = rc(sq)
        if piece.kind == "pawn":
            dr, dc = pawn_delta(seat)
            nr, nc = row + dr, col + dc
            if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                nsq = square(nr, nc)
                if playable(nsq) and nsq not in pos.board:
                    moves.append(Move(sq, nsq, "queen" if promotion_square(seat, nsq, pos.mode) else "none"))
            for cr, cc in pawn_captures(seat):
                nr, nc = row + cr, col + cc
                if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE:
                    nsq = square(nr, nc)
                    target = pos.board.get(nsq)
                    if playable(nsq) and target and enemies(pos.mode, seat, target.seat):
                        moves.append(Move(sq, nsq, "queen" if promotion_square(seat, nsq, pos.mode) else "none"))
        elif piece.kind == "knight":
            for dr, dc in ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)):
                nr, nc = row + dr, col + dc
                nsq = square(nr, nc) if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE else -1
                target = pos.board.get(nsq)
                if nsq >= 0 and playable(nsq) and (target is None or enemies(pos.mode, seat, target.seat)):
                    moves.append(Move(sq, nsq))
        elif piece.kind == "bishop":
            moves.extend(ray_moves(pos, sq, piece, ((1, 1), (1, -1), (-1, 1), (-1, -1))))
        elif piece.kind == "rook":
            moves.extend(ray_moves(pos, sq, piece, ((1, 0), (-1, 0), (0, 1), (0, -1))))
        else:
            deltas = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
            if piece.kind == "queen":
                moves.extend(ray_moves(pos, sq, piece, deltas))
            else:
                for dr, dc in deltas:
                    nr, nc = row + dr, col + dc
                    nsq = square(nr, nc) if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE else -1
                    target = pos.board.get(nsq)
                    if nsq >= 0 and playable(nsq) and (target is None or enemies(pos.mode, seat, target.seat)):
                        moves.append(Move(sq, nsq))
    return moves


def apply_move(pos: Position, move: Move) -> Position:
    child = pos.clone()
    piece = child.board.pop(move.start)
    captured = child.board.pop(move.end, None)
    if captured:
        child.scores[piece.seat] += PIECE_VALUE[captured.kind]
        if captured.kind == "king":
            child.active[captured.seat] = False
    child.board[move.end] = Piece(piece.seat, move.promotion if move.promotion != "none" else piece.kind)
    child.ply += 1
    child.advance_turn()
    return child


def material_score(pos: Position, seat: str) -> int:
    return sum(PIECE_VALUE[p.kind] for p in pos.board.values() if p.seat == seat)


def value_vector(pos: Position) -> list[float]:
    raw = [pos.scores[s] + material_score(pos, s) + (20 if pos.active[s] else -20) for s in SEATS]
    mean = sum(raw) / 4
    return [round((score - mean) / 50.0, 5) for score in raw]


def team_wdl(pos: Position) -> list[float]:
    rg = sum(pos.scores[s] + material_score(pos, s) for s in ("red", "yellow"))
    bg = sum(pos.scores[s] + material_score(pos, s) for s in ("blue", "green"))
    win = 1.0 / (1.0 + math.exp(-(rg - bg) / 12.0))
    loss = 1.0 - win
    draw = max(0.0, 1.0 - abs(win - loss) * 1.35)
    total = win + draw + loss
    return [round(win / total, 5), round(draw / total, 5), round(loss / total, 5)]


def teacher_label(pos: Position, moves: list[Move]) -> tuple[Move, object, dict[str, float]]:
    before = value_vector(pos)
    scored: list[tuple[float, Move]] = []
    for move in moves:
        child = apply_move(pos, move)
        after = value_vector(child)
        if pos.mode == "ffa":
            score = after[SEATS.index(pos.turn)] - before[SEATS.index(pos.turn)]
        else:
            score = (after[0] + after[2]) - (after[1] + after[3])
            if team(pos.turn) == 1:
                score = -score
        captured = pos.board.get(move.end)
        if captured:
            score += PIECE_VALUE[captured.kind] / 12.0
        scored.append((score, move))
    scored.sort(key=lambda item: (-item[0], item[1].key()))
    value = {"placement_value": value_vector(pos)} if pos.mode == "ffa" else {"wdl": team_wdl(pos)}
    return scored[0][1], value, {move.key(): round(score, 5) for score, move in scored[:8]}


def position_hash(pos: Position) -> str:
    payload = {
        "active": pos.active,
        "board": sorted((sq, p.seat, p.kind) for sq, p in pos.board.items()),
        "mode": pos.mode,
        "scores": pos.scores,
        "turn": pos.turn,
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def split_for_game(game_id: str) -> str:
    bucket = int(game_id[:8], 16) % 10
    return "train" if bucket < 8 else "validation" if bucket == 8 else "sealed-test"


def deterministic_game_id(mode: str, seed: int, index: int) -> str:
    digest = sha256_bytes(f"eloi-v4:{mode}:{seed}:{index}".encode())
    return f"{index % 10:08X}{digest[8:24]}"


def category_for(pos: Position, moves: list[Move], move: Move) -> str:
    captured = pos.board.get(move.end)
    if captured and captured.kind == "king":
        return "elimination-boundary"
    if move.promotion != "none":
        return "promotion"
    if len(moves) <= 3:
        return "forced-move"
    if captured:
        return "capture"
    if any(pos.board.get(m.end, Piece("", "")).kind == "king" for m in moves):
        return "mating-threat"
    return "broad"


def generate_records(campaign: Campaign, count: int) -> Iterable[dict[str, object]]:
    rng = random.Random(campaign.seed)
    emitted = 0
    game_index = 0
    seen: set[str] = set()
    while emitted < count:
        pos = initial_position(campaign.mode)
        game_id = deterministic_game_id(campaign.mode, campaign.seed, game_index)
        game_index += 1
        max_plies = 24 if campaign.dry_run else 220
        for _ in range(max_plies):
            moves = legal_moves(pos)
            if not moves:
                pos.active[pos.turn] = False
                pos.advance_turn()
                continue
            best, value, logits = teacher_label(pos, moves)
            digest = position_hash(pos)
            if digest not in seen:
                seen.add(digest)
                yield {
                    "schema": RECORD_SCHEMA,
                    "mode": campaign.mode,
                    "source_game": game_id,
                    "ply": pos.ply,
                    "category": category_for(pos, moves, best),
                    "seat_to_move": pos.turn,
                    "scores": dict(pos.scores),
                    "active": dict(pos.active),
                    "pieces": [[sq, p.seat, p.kind] for sq, p in sorted(pos.board.items())],
                    "legal_move_count": len(moves),
                    "teacher_kind": "deterministic-four-player-handcrafted-search-v1",
                    "teacher_score": value,
                    "policy_target": {"move": best.key(), "move_index": best.index()},
                    "policy_logits": logits,
                    "position_hash": digest,
                    "split": split_for_game(game_id),
                }
                emitted += 1
                if emitted >= count:
                    return
            pos = apply_move(pos, best if rng.random() < 0.78 else rng.choice(moves[: min(len(moves), 12)]))
            if sum(1 for active in pos.active.values() if active) <= 1:
                break


def materialized_count(campaign: Campaign) -> int:
    return DRY_RUN_COUNT if campaign.dry_run else campaign.target_positions


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect_record_stats(records: Iterable[dict[str, object]]) -> tuple[dict[str, int], dict[str, int], str]:
    split_counts = {"train": 0, "validation": 0, "sealed-test": 0}
    category_counts: dict[str, int] = {}
    hashes: list[str] = []
    for record in records:
        split_counts[str(record["split"])] += 1
        category = str(record["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
        hashes.append(str(record["position_hash"]))
    return split_counts, category_counts, sha256_bytes("\n".join(hashes).encode("ascii"))


def build_manifest(campaign: Campaign) -> dict[str, object]:
    count = materialized_count(campaign)
    split_counts, category_counts, digest = collect_record_stats(generate_records(campaign, count))
    return {
        "schema": SCHEMA_VERSION,
        "record_schema": RECORD_SCHEMA,
        "mode": campaign.mode,
        "seed": campaign.seed,
        "target_positions": campaign.target_positions,
        "materialized_positions": count,
        "dry_run": campaign.dry_run,
        "shard_size": DEFAULT_SHARD_SIZE,
        "split_policy": "source-game hash bucket: 0-7 train, 8 validation, 9 sealed-test",
        "split_counts": split_counts,
        "category_counts": category_counts,
        "records_sha256": digest,
        "records_dir": str(campaign.records_dir()),
        "label_status": "self-play-handcrafted-teacher-labels",
        "python": sys.version,
        "platform": platform.platform(),
        "created_unix": int(time.time()),
        "artifact_policy": "json/float32/quantized Rust headers only; no pickle artifacts",
    }


def write_records(campaign: Campaign, shard_size: int = DEFAULT_SHARD_SIZE) -> list[Path]:
    campaign.records_dir().mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    current_path: Path | None = None
    current_file = None
    try:
        for index, record in enumerate(generate_records(campaign, materialized_count(campaign))):
            shard_path = campaign.records_dir() / f"{campaign.mode}_records_{index // shard_size:05d}.jsonl"
            if shard_path != current_path:
                if current_file:
                    current_file.close()
                current_path = shard_path
                written.append(shard_path)
                current_file = shard_path.open("w", encoding="utf-8", newline="\n")
            assert current_file is not None
            current_file.write(json.dumps(record, sort_keys=True) + "\n")
    finally:
        if current_file:
            current_file.close()
    return written


def feature_vector(record: dict[str, object]) -> list[float]:
    vec = [0.0] * FEATURE_SIZE
    for sq, seat, kind in record["pieces"]:
        offset = ((SEATS.index(str(seat)) * len(PIECES) + PIECES.index(str(kind)))
                  * BOARD_SIZE * BOARD_SIZE + int(sq))
        vec[offset] = 1.0
    base = len(SEATS) * len(PIECES) * BOARD_SIZE * BOARD_SIZE
    vec[base + SEATS.index(str(record["seat_to_move"]))] = 1.0
    for idx, seat in enumerate(SEATS):
        vec[base + len(SEATS) + idx] = float(record["scores"][seat]) / 40.0
        vec[base + len(SEATS) * 2 + idx] = 1.0 if record["active"][seat] else 0.0
    return vec


def load_records(records_dir: Path, split: str, limit: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(records_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("split") == split:
                rows.append(row)
                if len(rows) >= limit:
                    return rows
    return rows


def train_model(campaign: Campaign, epochs: int, batch_size: int, limit: int) -> Path:
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as error:
        raise SystemExit("PyTorch is required for --stage train/all inside Kaggle") from error

    train_rows = load_records(campaign.records_dir(), "train", limit)
    validation_rows = load_records(campaign.records_dir(), "validation", max(128, limit // 8))
    if not train_rows or not validation_rows:
        raise SystemExit("not enough generated records for training")
    x_train = torch.tensor([feature_vector(row) for row in train_rows], dtype=torch.float32)
    y_policy = torch.tensor([int(row["policy_target"]["move_index"]) % 4096 for row in train_rows], dtype=torch.long)
    if campaign.mode == "ffa":
        y_value = torch.tensor([row["teacher_score"]["placement_value"] for row in train_rows], dtype=torch.float32)
        value_outputs = 4
    else:
        y_value = torch.tensor([row["teacher_score"]["wdl"] for row in train_rows], dtype=torch.float32)
        value_outputs = 3
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    loader = DataLoader(TensorDataset(x_train, y_policy, y_value), batch_size=batch_size, shuffle=True)
    trunk = nn.Sequential(nn.Linear(FEATURE_SIZE, 128), nn.ReLU(), nn.Linear(128, 96), nn.ReLU()).to(device)
    policy_head = nn.Linear(96, 4096).to(device)
    value_head = nn.Linear(96, value_outputs).to(device)
    optimizer = torch.optim.AdamW(list(trunk.parameters()) + list(policy_head.parameters()) + list(value_head.parameters()), lr=0.002)
    ce = nn.CrossEntropyLoss()
    mse = nn.MSELoss()
    for _ in range(epochs):
        for features, policy, value in loader:
            features, policy, value = features.to(device), policy.to(device), value.to(device)
            hidden = trunk(features)
            value_pred = value_head(hidden)
            if campaign.mode == "teams":
                value_pred = torch.softmax(value_pred, dim=1)
            loss = ce(policy_head(hidden), policy) + 0.5 * mse(value_pred, value)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
    weights: list[float] = []
    with torch.no_grad():
        for tensor in list(trunk.parameters()) + list(policy_head.parameters()) + list(value_head.parameters()):
            weights.extend(float(item) for item in tensor.detach().cpu().flatten())
    raw = struct.pack("<" + "f" * len(weights), *weights)
    campaign.model_dir().mkdir(parents=True, exist_ok=True)
    artifact = campaign.model_dir() / f"e4pc_{campaign.mode}_torch_float32.bin"
    artifact.write_bytes(raw)
    write_json_atomic(campaign.model_dir() / f"e4pc_{campaign.mode}_training_manifest.json", {
        "schema": 1,
        "mode": campaign.mode,
        "feature_size": FEATURE_SIZE,
        "policy_buckets": 4096,
        "value_outputs": value_outputs,
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "epochs": epochs,
        "device": str(device),
        "weights_sha256": sha256_bytes(raw),
        "format": "raw little-endian float32 tensors in module order; not a runtime artifact",
    })
    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["ffa", "teams"], required=True)
    parser.add_argument("--stage", choices=["collect", "train", "all"], default="collect")
    parser.add_argument("--output", type=Path, default=Path("tmp/four-player-kaggle"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--target-positions", type=int, default=TARGET_POSITIONS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--train-limit", type=int, default=25_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.target_positions != TARGET_POSITIONS:
        raise SystemExit("v4 protocol requires exactly 500000 target positions per mode")
    if not args.dry_run and os.environ.get("KAGGLE_URL_BASE") is None:
        raise SystemExit(f"full {args.stage} stage must run in Kaggle; use --dry-run locally")
    campaign = Campaign(args.mode, args.seed, args.target_positions, args.output, args.dry_run)
    if args.stage in ("collect", "all"):
        shards = [] if args.manifest_only else write_records(campaign)
        manifest = build_manifest(campaign)
        manifest["record_shards"] = [str(path) for path in shards]
        write_json_atomic(campaign.manifest_path(), manifest)
        print(campaign.manifest_path())
        print(manifest["records_sha256"])
    if args.stage in ("train", "all"):
        artifact = train_model(campaign, args.epochs, args.batch_size, args.train_limit)
        print(artifact)
        print(sha256_bytes(artifact.read_bytes()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
