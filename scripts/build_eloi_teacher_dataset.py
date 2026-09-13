#!/usr/bin/env python3
"""Build a deterministic Standard-chess policy/value dataset for Eloi.

Caissa 1.25 is an offline teacher only.  For every selected root, this tool
records Eloi E2's choice, Caissa's choice, and Caissa scores for a bounded
candidate set.  Source partitions are preserved, output is append-only and
resumable, and a manifest freezes every executable, network and input hash.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess
import chess.engine

import validation_support

SCHEMA = "eloi-caissa125-teacher-dataset-v1"
NETWORK_SHA256 = "615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B"
PARTITIONS = ("train", "validation", "test")


class DatasetError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DatasetError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def stable_digest(seed: str, value: str) -> bytes:
    return hashlib.sha256(f"{seed}\0{value}".encode()).digest()


def assigned_partition(group_id: str, seed: str) -> str:
    bucket = int.from_bytes(stable_digest(seed, group_id)[:8], "big") % 100
    return "train" if bucket < 80 else "validation" if bucket < 90 else "test"


def load_roots(path: Path, maximum: int, seed: str) -> list[dict]:
    roots: dict[str, dict] = {}
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            fen = item.get("fen")
            if not isinstance(fen, str):
                continue
            try:
                board = chess.Board(fen)
            except ValueError:
                continue
            if board.is_game_over(claim_draw=True):
                continue
            group = str(item.get("group_id") or item.get("game_id") or
                        item.get("record_id") or f"line-{line_number}")
            partition = item.get("partition") or assigned_partition(group, seed)
            require(partition in PARTITIONS, f"invalid partition at line {line_number}")
            record_id = str(item.get("record_id") or
                            hashlib.sha256(f"{group}\0{fen}".encode()).hexdigest())
            roots.setdefault(record_id, {
                "record_id": record_id, "group_id": group,
                "partition": partition, "fen": board.fen(),
            })
    require(roots, "input contains no eligible Standard positions")
    ordered = sorted(roots.values(), key=lambda row: stable_digest(seed, row["record_id"]))
    return ordered[:maximum]


def candidate_moves(board: chess.Board, e2_move: str, teacher_move: str,
                    maximum: int, seed: str, record_id: str) -> list[str]:
    legal = sorted(move.uci() for move in board.legal_moves)
    require(e2_move in legal, "E2 returned an illegal move")
    require(teacher_move in legal, "teacher returned an illegal move")
    priority = [teacher_move] + ([] if e2_move == teacher_move else [e2_move])
    remainder = [move for move in legal if move not in priority]
    remainder.sort(key=lambda move: stable_digest(seed, f"{record_id}\0{move}"))
    return (priority + remainder)[:max(maximum, len(priority))]


def cp_from_info(info: dict, board: chess.Board) -> int:
    score = info["score"].pov(board.turn).score(mate_score=30_000)
    require(score is not None, "teacher omitted a usable score")
    return int(score)


def wdl_target(cp: int) -> dict[str, float]:
    # Smooth centipawn target; draws peak around equality. This is a training
    # target, not a calibrated claim about over-the-board win probability.
    win = 1.0 / (1.0 + math.exp(-max(-3000, min(3000, cp)) / 240.0))
    draw = math.exp(-abs(cp) / 180.0) * 0.34
    win *= 1.0 - draw
    loss = 1.0 - draw - win
    return {"win": round(win, 8), "draw": round(draw, 8), "loss": round(loss, 8)}


def policy_targets(scores: list[tuple[str, int]], temperature: float = 120.0) -> list[dict]:
    peak = max(score for _, score in scores)
    weights = [math.exp((score - peak) / temperature) for _, score in scores]
    total = sum(weights)
    ranked = sorted(zip(scores, weights), key=lambda row: (-row[0][1], row[0][0]))
    return [{"move": move, "teacher_cp": score,
             "probability": round(weight / total, 9), "rank": rank}
            for rank, (((move, score)), weight) in enumerate(ranked, 1)]


class Engine:
    def __init__(self, command: list[str], cwd: Path, timeout: float):
        flags = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0) if os.name == "nt" else 0
        self.engine = chess.engine.SimpleEngine.popen_uci(
            command, timeout=timeout, cwd=str(cwd), creationflags=flags)
        options = self.engine.options
        settings = {}
        if "Threads" in options: settings["Threads"] = 3
        if "Hash" in options: settings["Hash"] = 32
        if "MultiPV" in options: settings["MultiPV"] = 1
        if settings: self.engine.configure(settings)

    def analyse(self, board: chess.Board, nodes: int) -> dict:
        return self.engine.analyse(board, chess.engine.Limit(nodes=nodes))

    def close(self) -> None:
        self.engine.quit()


def teacher_score_child(teacher: Engine, board: chess.Board, move: chess.Move,
                        nodes: int) -> int:
    child = board.copy(stack=False)
    child.push(move)
    # Child score is from the opponent's perspective; negate it to rank the
    # root player's candidate.
    return -cp_from_info(teacher.analyse(child, nodes), child)


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(args: argparse.Namespace) -> dict:
    source, e2, teacher, network = (p.resolve() for p in
                                    (args.input, args.e2, args.teacher, args.network))
    output = args.output.resolve()
    for label, path in (("input", source), ("E2", e2), ("teacher", teacher),
                        ("network", network)):
        require(path.is_file(), f"{label} is absent: {path}")
    require(sha256_file(network) == NETWORK_SHA256, "Caissa 1.25 network hash mismatch")
    require(args.positions > 0 and args.nodes > 0 and args.candidates >= 2,
            "positions/nodes must be positive and candidates must be at least two")
    require(output.is_relative_to((ROOT / "tmp").resolve()), "output must be below repository tmp")
    rows_path = output / "teacher.jsonl"
    checkpoint_path = output / "checkpoint.json"
    manifest_path = output / "manifest.json"
    if output.exists() and not args.resume:
        raise DatasetError(f"output collision: {output}")
    if args.resume:
        require(rows_path.is_file() and checkpoint_path.is_file(), "resume evidence is incomplete")
    else:
        output.mkdir(parents=True, exist_ok=False)
    projected = args.positions * (args.candidates * 180 + 1800) + 2_000_000
    resources = validation_support.resource_snapshot(output, projected=projected)
    roots = load_roots(source, args.positions, args.seed)
    identities = {"source_sha256": sha256_file(source), "e2_sha256": sha256_file(e2),
                  "teacher_sha256": sha256_file(teacher), "network_sha256": sha256_file(network),
                  "runner_sha256": sha256_file(Path(__file__))}
    frozen = {"schema": SCHEMA, "seed": args.seed, "nodes_per_probe": args.nodes,
              "candidate_limit": args.candidates,
              "engine_threads": {"e2_single_thread_lab": 1, "caissa_teacher": 3},
              "searches_are_sequential": True,
              "positions_planned": len(roots), "identities": identities}
    completed: set[str] = set()
    if args.resume:
        prior = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        require(prior["frozen"] == frozen, "resume protocol does not match frozen campaign")
        with rows_path.open(encoding="utf-8") as stream:
            completed = {json.loads(line)["record_id"] for line in stream if line.strip()}
    started = time.monotonic()
    e2_engine = Engine([str(e2), "--uci", "--brain", "eloi-single"], ROOT, args.timeout_seconds)
    teacher_engine = Engine([str(teacher), "--uci", "--brain", "caissa",
                             "--caissa-network", str(network)], ROOT, args.timeout_seconds)
    failures = []
    mode = "a" if args.resume else "x"
    try:
        with rows_path.open(mode, encoding="utf-8", newline="\n") as stream:
            for root in roots:
                if root["record_id"] in completed:
                    continue
                board = chess.Board(root["fen"])
                try:
                    e2_info = e2_engine.analyse(board, args.nodes)
                    teacher_info = teacher_engine.analyse(board, args.nodes)
                    e2_move = e2_info["pv"][0].uci()
                    teacher_move = teacher_info["pv"][0].uci()
                    moves = candidate_moves(board, e2_move, teacher_move,
                                            args.candidates, args.seed, root["record_id"])
                    scored = [(move, teacher_score_child(
                        teacher_engine, board, chess.Move.from_uci(move), args.nodes))
                              for move in moves]
                    root_cp = max(score for _, score in scored)
                    row = dict(root,
                        legal_move_count=board.legal_moves.count(),
                        e2_move=e2_move, teacher_move=teacher_move,
                        disagreement=e2_move != teacher_move,
                        teacher_root_cp=root_cp, value_wdl=wdl_target(root_cp),
                        policy=policy_targets(scored),
                        tactical_weight=(2.0 if e2_move != teacher_move and
                                         dict(scored)[e2_move] + 150 < root_cp else 1.0))
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                    stream.flush()
                    completed.add(root["record_id"])
                except Exception as error:
                    failures.append({"record_id": root["record_id"],
                                     "error": f"{type(error).__name__}: {error}"})
                    break
                atomic_json(checkpoint_path, {"status": "running", "frozen": frozen,
                    "completed": len(completed), "failures": failures,
                    "elapsed_seconds": round(time.monotonic() - started, 3)})
    finally:
        e2_engine.close()
        teacher_engine.close()
    counts = {partition: 0 for partition in PARTITIONS}
    with rows_path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    for row in rows: counts[row["partition"]] += 1
    evidence = {"status": "complete" if len(rows) == len(roots) and not failures else "failed",
                "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "frozen": frozen, "partition_counts": counts, "rows": len(rows),
                "dataset_sha256": sha256_file(rows_path), "failures": failures,
                "resources_before": resources,
                "elapsed_seconds": round(time.monotonic() - started, 3)}
    atomic_json(checkpoint_path, evidence)
    require(not manifest_path.exists(), f"manifest collision: {manifest_path}")
    manifest_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--e2", required=True, type=Path)
    parser.add_argument("--teacher", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--positions", type=int, default=1_000)
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--seed", default="eloi-native-f0-v1")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        result = collect(args)
    except (DatasetError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"BLOCKED: {error}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
