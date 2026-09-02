#!/usr/bin/env python3
"""Build a deterministic, analysis-only canonical view of Eloi's NNUE inputs.

This program deliberately cannot install or train an NNUE. It validates the
already-retained Lichess samples, assigns stable identities and partitions,
selects deterministic coverage samples, reports cross-source overlap and
population slices, and projects larger-corpus storage. All output is confined
to a new analysis directory and quota-checked before every write.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import platform
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
for dependency_root in (
    ROOT / ".deps" / "python",
    ROOT / ".deps" / "lichess-bot" / ".venv" / "Lib" / "site-packages",
):
    if dependency_root.is_dir():
        sys.path.insert(0, str(dependency_root))

import chess


SCHEMA = 2
DEFAULT_SEED = "eloi/nnue-dataset-v2/analysis-1"
TOTAL_TEMP_LIMIT_BYTES = 10_000_000_000
NNUE_TEMP_LIMIT_BYTES = 8_000_000_000
STRICT_NNUE_LIMIT_BYTES = 7 * 1024**3
DEFAULT_OUTPUT_LIMIT_BYTES = 256 * 1024**2
PARTITION_THRESHOLDS = (("train", 0.80), ("validation", 0.90), ("test", 1.0))
LICHESS_GAME_RE = re.compile(r"lichess\.org/([A-Za-z0-9]{8})")
STATUS_REASONS = (
    ("empty", "STATUS_EMPTY"),
    ("no-white-king", "STATUS_NO_WHITE_KING"),
    ("no-black-king", "STATUS_NO_BLACK_KING"),
    ("too-many-kings", "STATUS_TOO_MANY_KINGS"),
    ("too-many-white-pawns", "STATUS_TOO_MANY_WHITE_PAWNS"),
    ("too-many-black-pawns", "STATUS_TOO_MANY_BLACK_PAWNS"),
    ("pawns-on-backrank", "STATUS_PAWNS_ON_BACKRANK"),
    ("too-many-white-pieces", "STATUS_TOO_MANY_WHITE_PIECES"),
    ("too-many-black-pieces", "STATUS_TOO_MANY_BLACK_PIECES"),
    ("bad-castling-rights", "STATUS_BAD_CASTLING_RIGHTS"),
    ("invalid-ep-square", "STATUS_INVALID_EP_SQUARE"),
    ("opposite-check", "STATUS_OPPOSITE_CHECK"),
    ("too-many-checkers", "STATUS_TOO_MANY_CHECKERS"),
    ("impossible-check", "STATUS_IMPOSSIBLE_CHECK"),
)


class RejectedRecord(ValueError):
    """A source record rejected for a stable, reportable reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def stable_hash(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = str(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest().upper()


def stable_fraction(*parts: object) -> float:
    digest = bytes.fromhex(stable_hash(*parts))
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def directory_bytes(path: pathlib.Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def verify_input_manifest(
    manifest_path: pathlib.Path,
    evaluations: pathlib.Path,
    puzzles: pathlib.Path,
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        retained = manifest["retained_inputs"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as error:
        raise RuntimeError("tracked NNUE input manifest is invalid") from error
    for name, path in (("evaluations", evaluations), ("puzzles", puzzles)):
        document = retained.get(name)
        if not isinstance(document, dict):
            raise RuntimeError(f"manifest is missing {name}")
        if path.name != document.get("sample_filename"):
            raise RuntimeError(f"{name} filename does not match the manifest")
        actual_bytes = path.stat().st_size
        if actual_bytes != document.get("sample_bytes"):
            raise RuntimeError(f"{name} byte size does not match the manifest")
        actual_hash = sha256_file(path)
        if actual_hash != document.get("sample_sha256"):
            raise RuntimeError(f"{name} SHA-256 does not match the manifest")
    return {
        "verified": True,
        "path": manifest_path.as_posix(),
        "sha256": sha256_file(manifest_path),
        "schema": manifest.get("schema"),
    }


@dataclass
class OutputBudget:
    """Conservatively account for all bytes this analysis writes."""

    output_limit: int
    baseline_total: int
    baseline_nnue: int
    written: int = 0
    peak_written: int = 0

    def reserve(self, additional: int) -> None:
        if additional < 0:
            raise ValueError("additional byte count cannot be negative")
        proposed = self.written + additional
        if proposed > self.output_limit:
            raise RuntimeError(
                "analysis output quota would be exceeded: "
                f"{proposed:,} > {self.output_limit:,} bytes"
            )
        if self.baseline_nnue + proposed > NNUE_TEMP_LIMIT_BYTES:
            raise RuntimeError("8 GB temporary NNUE quota would be exceeded")
        if self.baseline_nnue + proposed > STRICT_NNUE_LIMIT_BYTES:
            raise RuntimeError("current stricter 7 GiB NNUE quota would be exceeded")
        if self.baseline_total + proposed > TOTAL_TEMP_LIMIT_BYTES:
            raise RuntimeError("10 GB total temporary-project quota would be exceeded")
        self.written = proposed
        self.peak_written = max(self.peak_written, proposed)


def canonical_fen(raw: str) -> tuple[chess.Board, str]:
    fields = raw.strip().split()
    if len(fields) == 4:
        fields += ["0", "1"]
    if len(fields) != 6:
        raise RejectedRecord("fen-field-count")
    try:
        board = chess.Board(" ".join(fields), chess960=False)
    except ValueError as error:
        raise RejectedRecord("invalid-fen") from error
    status = board.status()
    if status != chess.STATUS_VALID:
        reasons = []
        known = 0
        for reason, constant_name in STATUS_REASONS:
            flag = getattr(chess, constant_name, 0)
            if flag and status & flag:
                reasons.append(reason)
                known |= flag
        unknown = status & ~known
        if unknown:
            reasons.append(f"unknown-{unknown:x}")
        detail = "+".join(reasons) if reasons else f"status-{status:x}"
        raise RejectedRecord("invalid-standard-position/" + detail)
    return board, board.fen(en_passant="legal")


def validate_move_sequence(board: chess.Board, moves: Iterable[str]) -> list[str]:
    replay = board.copy(stack=False)
    result = []
    for text in moves:
        try:
            move = chess.Move.from_uci(text)
        except ValueError as error:
            raise RejectedRecord("malformed-move") from error
        if move not in replay.legal_moves:
            raise RejectedRecord("illegal-move")
        replay.push(move)
        result.append(move.uci())
    return result


def position_keys(fen: str) -> tuple[str, str]:
    fields = fen.split()
    full = stable_hash("full-state", fen)
    learning = stable_hash("learning-state", *fields[:4])
    return full, learning


def phase_bucket(board: chess.Board) -> str:
    pieces = len(board.piece_map())
    if pieces <= 10:
        return "low-material-ending"
    if pieces <= 20:
        return "endgame"
    if board.fullmove_number <= 12 and pieces >= 26:
        return "opening"
    return "middlegame"


def score_bucket(value: int | None) -> str:
    if value is None:
        return "mate"
    absolute = abs(value)
    for upper, label in (
        (25, "0-25"),
        (75, "26-75"),
        (200, "76-200"),
        (500, "201-500"),
        (1500, "501-1500"),
    ):
        if absolute <= upper:
            return label
    return "saturated"


def rating_bucket(rating: int) -> str:
    if rating < 1000:
        return "under-1000"
    if rating < 1500:
        return "1000-1499"
    if rating < 2000:
        return "1500-1999"
    if rating < 2500:
        return "2000-2499"
    return "2500-plus"


def legal_move_bucket(count: int) -> str:
    if count <= 10:
        return "0-10"
    if count <= 20:
        return "11-20"
    if count <= 35:
        return "21-35"
    return "36-plus"


def castling_bucket(board: chess.Board) -> str:
    white = board.has_kingside_castling_rights(
        chess.WHITE
    ) or board.has_queenside_castling_rights(chess.WHITE)
    black = board.has_kingside_castling_rights(
        chess.BLACK
    ) or board.has_queenside_castling_rights(chess.BLACK)
    if white and black:
        return "both"
    if white:
        return "white-only"
    if black:
        return "black-only"
    return "none"


def move_class(board: chess.Board, move: chess.Move) -> str:
    if move.promotion:
        return "promotion"
    if board.gives_check(move):
        return "check"
    if board.is_capture(move):
        return "capture"
    if board.is_castling(move):
        return "castle"
    return "quiet"


def tactical_surface(board: chess.Board) -> str:
    if board.is_check():
        return "in-check"
    legal = list(board.legal_moves)
    if any(move.promotion for move in legal):
        return "promotion-available"
    if any(board.is_capture(move) for move in legal):
        return "capture-available"
    return "quiet"


def theme_family(themes: list[str]) -> str:
    lowered = {theme.lower() for theme in themes}
    families = (
        ("mate", ("mate", "checkmate")),
        ("hanging-or-trapped", ("hanging", "trapped")),
        ("pawn", ("pawn", "promotion")),
        ("endgame", ("endgame",)),
        ("defense", ("defensive", "equality")),
        ("tactical", ("fork", "pin", "skewer", "sacrifice", "clearance")),
    )
    for family, needles in families:
        if any(any(needle in theme for needle in needles) for theme in lowered):
            return family
    return "other"


def confidence_bucket(depth: int, knodes: int | None) -> str:
    if depth >= 30 and (knodes is None or knodes >= 10_000):
        return "high"
    if depth >= 18 and (knodes is None or knodes >= 1_000):
        return "medium"
    return "low"


def partition_for_group(group_id: str, seed: str) -> str:
    value = stable_fraction(seed, "split", group_id)
    for name, threshold in PARTITION_THRESHOLDS:
        if value < threshold:
            return name
    raise AssertionError("partition thresholds must end at 1.0")


def hard_alternatives(
    board: chess.Board, best: chess.Move, seed: str, record_id: str
) -> list[dict[str, str]]:
    tiers: dict[str, list[chess.Move]] = defaultdict(list)
    for move in board.legal_moves:
        if move == best:
            continue
        kind = move_class(board, move)
        tier = "forcing" if kind in {"promotion", "check", "capture"} else "quiet"
        tiers[tier].append(move)
    selected = []
    for tier in ("forcing", "quiet"):
        ranked = sorted(
            tiers[tier],
            key=lambda move: stable_hash(
                seed, "negative", record_id, tier, move.uci()
            ),
        )
        for move in ranked[:2]:
            selected.append({"move": move.uci(), "tier": tier})
    return selected[:4]


def evaluation_record(
    row: dict[str, Any], raw_line: str, row_number: int
) -> dict[str, Any]:
    try:
        board, fen = canonical_fen(str(row["fen"]))
        evaluations = row["evals"]
    except KeyError as error:
        raise RejectedRecord("missing-evaluation-field") from error
    if not isinstance(evaluations, list) or not evaluations:
        raise RejectedRecord("missing-evaluations")
    valid_entries = [
        item for item in evaluations
        if isinstance(item, dict) and isinstance(item.get("depth"), int)
    ]
    if not valid_entries:
        raise RejectedRecord("missing-depth")
    evaluation = max(valid_entries, key=lambda item: item["depth"])
    pvs = evaluation.get("pvs")
    if not isinstance(pvs, list) or not pvs or not isinstance(pvs[0], dict):
        raise RejectedRecord("missing-pv")
    pv = pvs[0]
    line = str(pv.get("line", "")).split()
    if not line:
        raise RejectedRecord("missing-pv-line")
    try:
        canonical_pv = validate_move_sequence(board, line)
    except RejectedRecord as error:
        raise RejectedRecord("illegal-pv") from error
    cp = pv.get("cp")
    mate = pv.get("mate")
    if isinstance(cp, bool) or (cp is not None and not isinstance(cp, int)):
        raise RejectedRecord("malformed-score")
    if isinstance(mate, bool) or (mate is not None and not isinstance(mate, int)):
        raise RejectedRecord("malformed-score")
    if cp is None and mate is None:
        raise RejectedRecord("missing-score")
    score_type = "cp" if cp is not None else "mate"
    score_white = cp if cp is not None else None
    mate_white = mate if mate is not None else None
    if board.turn == chess.BLACK:
        score_white = -score_white if score_white is not None else None
        mate_white = -mate_white if mate_white is not None else None
    depth = evaluation["depth"]
    knodes = evaluation.get("knodes")
    if knodes is not None and (
        isinstance(knodes, bool) or not isinstance(knodes, int) or knodes < 0
    ):
        raise RejectedRecord("malformed-knodes")
    full_key, learning_key = position_keys(fen)
    source_id = row.get("game_id") or row.get("source") or row.get("id")
    record_id = (
        f"evaluation:{source_id}"
        if source_id
        else "evaluation:" + stable_hash(fen, raw_line.strip())
    )
    group_id = (
        f"source:{source_id}"
        if source_id
        else f"position:{learning_key}"
    )
    confidence = confidence_bucket(depth, knodes)
    phase = phase_bucket(board)
    surface = tactical_surface(board)
    record = {
        "schema": SCHEMA,
        "source": "lichess-evaluations-2026-08-02",
        "source_row": row_number,
        "record_id": record_id,
        "group_id": group_id,
        "full_state_key": full_key,
        "learning_state_key": learning_key,
        "fen": fen,
        "side_to_move": "white" if board.turn else "black",
        "score_type": score_type,
        "score_white_cp": score_white,
        "mate_distance_white": mate_white,
        "depth": depth,
        "knodes": knodes,
        "pv": canonical_pv,
        "piece_count": len(board.piece_map()),
        "phase_bucket": phase,
        "score_bucket": score_bucket(score_white),
        "confidence_bucket": confidence,
        "tactical_surface": surface,
        "castling_bucket": castling_bucket(board),
    }
    record["stratum"] = "|".join(
        (phase, record["score_bucket"], confidence, surface)
    )
    return record


def puzzle_record(
    row: dict[str, str], row_number: int, seed: str
) -> dict[str, Any]:
    try:
        source_board, source_fen = canonical_fen(row["FEN"])
        moves = row["Moves"].split()
        puzzle_id = row["PuzzleId"].strip()
    except KeyError as error:
        raise RejectedRecord("missing-puzzle-field") from error
    if not puzzle_id:
        raise RejectedRecord("missing-puzzle-id")
    if len(moves) < 2:
        raise RejectedRecord("short-puzzle-line")
    try:
        canonical_moves = validate_move_sequence(source_board, moves)
    except RejectedRecord as error:
        raise RejectedRecord("illegal-puzzle-line") from error
    decision = source_board.copy(stack=False)
    decision.push_uci(canonical_moves[0])
    decision_fen = decision.fen(en_passant="legal")
    best = chess.Move.from_uci(canonical_moves[1])
    if best not in decision.legal_moves:
        raise RejectedRecord("illegal-best-move")
    try:
        rating = int(row.get("Rating", "0"))
    except ValueError as error:
        raise RejectedRecord("malformed-rating") from error
    themes = sorted(set(row.get("Themes", "").split()))
    game_match = LICHESS_GAME_RE.search(row.get("GameUrl", ""))
    game_id = game_match.group(1) if game_match else None
    group_id = f"game:{game_id}" if game_id else f"puzzle:{puzzle_id}"
    full_key, learning_key = position_keys(decision_fen)
    alternatives = hard_alternatives(decision, best, seed, puzzle_id)
    phase = phase_bucket(decision)
    family = theme_family(themes)
    best_kind = move_class(decision, best)
    legal_count = decision.legal_moves.count()
    record = {
        "schema": SCHEMA,
        "source": "lichess-puzzles-2026-08-02",
        "source_row": row_number,
        "record_id": f"puzzle:{puzzle_id}",
        "puzzle_id": puzzle_id,
        "game_id": game_id,
        "group_id": group_id,
        "full_state_key": full_key,
        "learning_state_key": learning_key,
        "source_fen": source_fen,
        "decision_fen": decision_fen,
        "setup_move": canonical_moves[0],
        "best_move": canonical_moves[1],
        "continuation": canonical_moves[2:],
        "rating": rating,
        "themes": themes,
        "hard_alternatives": alternatives,
        "piece_count": len(decision.piece_map()),
        "phase_bucket": phase,
        "rating_bucket": rating_bucket(rating),
        "theme_family": family,
        "legal_move_count": legal_count,
        "legal_move_bucket": legal_move_bucket(legal_count),
        "best_move_class": best_kind,
    }
    record["stratum"] = "|".join(
        (phase, record["rating_bucket"], family, best_kind)
    )
    return record


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, value: str) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        lower, upper = sorted((root_left, root_right))
        self.parent[upper] = lower


def assign_group_clusters(
    evaluations: list[dict[str, Any]],
    puzzles: list[dict[str, Any]],
    seed: str,
) -> dict[str, Any]:
    records = evaluations + puzzles
    union = UnionFind()
    position_groups: dict[str, list[str]] = defaultdict(list)
    source_positions: dict[str, set[str]] = defaultdict(set)
    for record in records:
        group = record["group_id"]
        union.add(group)
        position_groups[record["learning_state_key"]].append(group)
        source_positions[record["source"]].add(record["learning_state_key"])
    for groups in position_groups.values():
        for group in groups[1:]:
            union.union(groups[0], group)
    components: dict[str, list[str]] = defaultdict(list)
    for group in union.parent:
        components[union.find(group)].append(group)
    cluster_for_group = {}
    for groups in components.values():
        cluster = "group-cluster:" + stable_hash("groups", *sorted(groups))
        for group in groups:
            cluster_for_group[group] = cluster
    for record in records:
        record["source_group_id"] = record.pop("group_id")
        record["group_id"] = cluster_for_group[record["source_group_id"]]
        record["partition"] = partition_for_group(record["group_id"], seed)
    evaluation_positions = source_positions["lichess-evaluations-2026-08-02"]
    puzzle_positions = source_positions["lichess-puzzles-2026-08-02"]
    overlap = sorted(evaluation_positions & puzzle_positions)
    return {
        "exact_learning_state_count": len(overlap),
        "sample_keys": overlap[:20],
        "group_components": len(components),
    }


def deterministic_select(
    records: list[dict[str, Any]], limit: int, seed: str
) -> list[dict[str, Any]]:
    if len(records) <= limit:
        return list(records)
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_stratum[record["stratum"]].append(record)
    selected: dict[str, dict[str, Any]] = {}
    strata = sorted(
        by_stratum,
        key=lambda value: stable_hash(seed, "stratum", value),
    )
    for stratum in strata[:limit]:
        winner = min(
            by_stratum[stratum],
            key=lambda record: stable_hash(
                seed, "coverage", stratum, record["record_id"]
            ),
        )
        selected[winner["record_id"]] = winner
    remaining = sorted(
        (
            record
            for record in records
            if record["record_id"] not in selected
        ),
        key=lambda record: stable_hash(
            seed, "population", record["record_id"]
        ),
    )
    for record in remaining[: limit - len(selected)]:
        selected[record["record_id"]] = record
    return list(selected.values())


def sorted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda record: (
            record["partition"],
            record["source"],
            record["stratum"],
            record["group_id"],
            record["learning_state_key"],
            record["record_id"],
        ),
    )


def distribution(records: list[dict[str, Any]], fields: Iterable[str]) -> dict:
    result = {}
    for field in fields:
        counts = Counter(str(record.get(field)) for record in records)
        result[field] = dict(sorted(counts.items()))
    return result


def deep_size(value: Any, seen: set[int] | None = None) -> int:
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        size += sum(
            deep_size(key, seen) + deep_size(item, seen)
            for key, item in value.items()
        )
    elif isinstance(value, (list, tuple, set, frozenset)):
        size += sum(deep_size(item, seen) for item in value)
    return size


def encoded_line(record: dict[str, Any]) -> bytes:
    return (
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def corpus_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"records": 0}
    encoded_sizes = [len(encoded_line(record)) for record in records]
    sample = records[: min(1000, len(records))]
    memory_sample = deep_size(sample)
    memory_per_record = memory_sample / len(sample)
    canonical_per_record = sum(encoded_sizes) / len(encoded_sizes)
    piece_counts = [int(record["piece_count"]) for record in records]
    mean_pieces = sum(piece_counts) / len(piece_counts)
    source = records[0]["source"]
    feature_multiplier = (
        2 if source == "lichess-evaluations-2026-08-02" else 4
    )
    array_per_record = feature_multiplier * mean_pieces * 4 + 8
    projections = {}
    for count in (100_000, 250_000, 500_000):
        projections[str(count)] = {
            "canonical_bytes": int(canonical_per_record * count),
            "python_object_bytes": int(memory_per_record * count),
            "estimated_feature_array_bytes": int(array_per_record * count),
        }
    return {
        "records": len(records),
        "mean_canonical_bytes_per_record": canonical_per_record,
        "measured_python_bytes_per_record": memory_per_record,
        "mean_piece_count": mean_pieces,
        "projections": projections,
    }


def atomic_write_bytes(
    path: pathlib.Path, data: bytes, budget: OutputBudget
) -> None:
    budget.reserve(len(data))
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("wb") as stream:
        stream.write(data)
    temporary.replace(path)


def atomic_write_jsonl(
    path: pathlib.Path,
    records: list[dict[str, Any]],
    budget: OutputBudget,
) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("wb") as stream:
        for record in records:
            line = encoded_line(record)
            budget.reserve(len(line))
            stream.write(line)
    temporary.replace(path)


def load_evaluations(path: pathlib.Path) -> tuple[list[dict], Counter]:
    accepted = []
    rejected: Counter[str] = Counter()
    with path.open(encoding="utf-8-sig") as stream:
        for row_number, raw_line in enumerate(stream, 1):
            try:
                row = json.loads(raw_line)
                if not isinstance(row, dict):
                    raise RejectedRecord("non-object-json")
                accepted.append(
                    evaluation_record(row, raw_line, row_number)
                )
            except json.JSONDecodeError:
                rejected["malformed-json"] += 1
            except RejectedRecord as error:
                rejected[error.reason] += 1
            except (TypeError, ValueError):
                rejected["unexpected-value"] += 1
    return accepted, rejected


def load_puzzles(
    path: pathlib.Path, seed: str
) -> tuple[list[dict], Counter]:
    accepted = []
    rejected: Counter[str] = Counter()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), 2):
            try:
                accepted.append(puzzle_record(row, row_number, seed))
            except RejectedRecord as error:
                rejected[error.reason] += 1
            except (TypeError, ValueError):
                rejected["unexpected-value"] += 1
    return accepted, rejected


def validate_output_directory(path: pathlib.Path) -> None:
    resolved = path.resolve()
    forbidden = (
        (ROOT / "include").resolve(),
        (ROOT / "src").resolve(),
        (ROOT / "dist").resolve(),
        (ROOT / "data").resolve(),
    )
    if any(resolved == root or root in resolved.parents for root in forbidden):
        raise ValueError(
            "analysis output must not be inside include, src, dist, or data"
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise FileExistsError(
            f"analysis output directory is not empty: {resolved}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evaluations",
        type=pathlib.Path,
        default=ROOT
        / ".deps"
        / "nnue-inputs"
        / "lichess-evaluations-2026-08-02.jsonl",
    )
    parser.add_argument(
        "--puzzles",
        type=pathlib.Path,
        default=ROOT
        / ".deps"
        / "nnue-inputs"
        / "lichess-puzzles-2026-08-02.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=ROOT / "tmp" / "nnue-dataset-analysis",
    )
    parser.add_argument(
        "--input-manifest",
        type=pathlib.Path,
        default=ROOT / "data" / "nnue_input_manifest.json",
    )
    parser.add_argument(
        "--allow-unverified-inputs",
        action="store_true",
        help="allow explicit fixture inputs that are not in the tracked manifest",
    )
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--limit-per-source", type=int, default=20_000)
    parser.add_argument(
        "--max-output-mib",
        type=int,
        default=DEFAULT_OUTPUT_LIMIT_BYTES // 1024**2,
    )
    args = parser.parse_args()
    if not args.evaluations.is_file() or not args.puzzles.is_file():
        parser.error("both retained NNUE input files must exist")
    if not 1 <= args.limit_per_source <= 500_000:
        parser.error("--limit-per-source must be between 1 and 500000")
    if not 1 <= args.max_output_mib <= STRICT_NNUE_LIMIT_BYTES // 1024**2:
        parser.error("--max-output-mib exceeds the current 7 GiB ceiling")
    validate_output_directory(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest_identity = (
        {
            "verified": False,
            "reason": "explicit --allow-unverified-inputs fixture override",
        }
        if args.allow_unverified_inputs
        else verify_input_manifest(
            args.input_manifest, args.evaluations, args.puzzles
        )
    )

    input_root = args.evaluations.parent
    baseline_nnue = directory_bytes(input_root)
    baseline_total = directory_bytes(ROOT / "tmp") + baseline_nnue
    budget = OutputBudget(
        args.max_output_mib * 1024**2,
        baseline_total,
        baseline_nnue,
    )
    incomplete = args.output_dir / "INCOMPLETE.json"
    atomic_write_bytes(
        incomplete,
        (
            json.dumps(
                {
                    "schema": SCHEMA,
                    "status": "incomplete",
                    "seed": args.seed,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
        budget,
    )

    evaluations, evaluation_rejections = load_evaluations(args.evaluations)
    puzzles, puzzle_rejections = load_puzzles(args.puzzles, args.seed)
    overlap = assign_group_clusters(evaluations, puzzles, args.seed)
    selected_evaluations = sorted_records(
        deterministic_select(
            evaluations, args.limit_per_source, args.seed + "/evaluations"
        )
    )
    selected_puzzles = sorted_records(
        deterministic_select(
            puzzles, args.limit_per_source, args.seed + "/puzzles"
        )
    )

    evaluation_output = args.output_dir / "canonical-evaluations.jsonl"
    puzzle_output = args.output_dir / "canonical-puzzles.jsonl"
    atomic_write_jsonl(evaluation_output, selected_evaluations, budget)
    atomic_write_jsonl(puzzle_output, selected_puzzles, budget)
    report = {
        "schema": SCHEMA,
        "kind": "nnue-dataset-analysis",
        "status": "complete",
        "analysis_id": stable_hash(
            args.seed,
            sha256_file(args.evaluations),
            sha256_file(args.puzzles),
            manifest_identity.get("sha256", "unverified"),
            args.limit_per_source,
        ),
        "mode": "analysis-only",
        "production_outputs_written": False,
        "seed": args.seed,
        "input_manifest": manifest_identity,
        "inputs": {
            "evaluations": {
                "path": args.evaluations.as_posix(),
                "bytes": args.evaluations.stat().st_size,
                "sha256": sha256_file(args.evaluations),
            },
            "puzzles": {
                "path": args.puzzles.as_posix(),
                "bytes": args.puzzles.stat().st_size,
                "sha256": sha256_file(args.puzzles),
            },
        },
        "parameters": {
            "limit_per_source": args.limit_per_source,
            "partitions": {"train": 0.8, "validation": 0.1, "test": 0.1},
            "max_output_bytes": budget.output_limit,
            "total_temp_limit_bytes": TOTAL_TEMP_LIMIT_BYTES,
            "nnue_temp_limit_bytes": NNUE_TEMP_LIMIT_BYTES,
            "strict_nnue_limit_bytes": STRICT_NNUE_LIMIT_BYTES,
        },
        "environment": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "python_chess_version": getattr(chess, "__version__", "unknown"),
        },
        "counts": {
            "evaluations_seen": len(evaluations) + sum(
                evaluation_rejections.values()
            ),
            "evaluations_accepted": len(evaluations),
            "evaluations_selected": len(selected_evaluations),
            "puzzles_seen": len(puzzles) + sum(puzzle_rejections.values()),
            "puzzles_accepted": len(puzzles),
            "puzzles_selected": len(selected_puzzles),
        },
        "rejections": {
            "evaluations": dict(sorted(evaluation_rejections.items())),
            "puzzles": dict(sorted(puzzle_rejections.items())),
        },
        "cross_source_overlap": overlap,
        "distributions": {
            "evaluations": distribution(
                selected_evaluations,
                (
                    "partition",
                    "phase_bucket",
                    "side_to_move",
                    "score_type",
                    "score_bucket",
                    "confidence_bucket",
                    "tactical_surface",
                    "castling_bucket",
                ),
            ),
            "puzzles": distribution(
                selected_puzzles,
                (
                    "partition",
                    "phase_bucket",
                    "rating_bucket",
                    "theme_family",
                    "legal_move_bucket",
                    "best_move_class",
                ),
            ),
        },
        "storage_model": {
            "evaluations": corpus_projection(selected_evaluations),
            "puzzles": corpus_projection(selected_puzzles),
        },
        "resource_usage": {
            "analysis_output_bytes_before_report": budget.written,
            "analysis_output_limit_bytes": budget.output_limit,
            "accounting": "conservative pre-write byte accounting",
        },
        "outputs": {
            "canonical_evaluations": {
                "path": evaluation_output.name,
                "bytes": evaluation_output.stat().st_size,
                "sha256": sha256_file(evaluation_output),
            },
            "canonical_puzzles": {
                "path": puzzle_output.name,
                "bytes": puzzle_output.stat().st_size,
                "sha256": sha256_file(puzzle_output),
            },
        },
    }
    report_path = args.output_dir / "report.json"
    report_bytes = (
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write_bytes(report_path, report_bytes, budget)
    incomplete.unlink()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
