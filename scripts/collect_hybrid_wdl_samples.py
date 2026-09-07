#!/usr/bin/env python3
"""Collect game-separated Eloi/Caissa WDL samples from a preserved PGN.

The collector never plays games.  It deterministically selects completed
Standard games and nonterminal positions, then runs each isolated brain in a
fresh Windows-Idle process with three threads and a fixed node budget.  Scores
are labelled by the final result from the side-to-move perspective.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import time

import caissa_adapter_parity as probe
import differential_movegen as movegen
import validation_support
import chess.pgn


ROOT = Path(__file__).resolve().parents[1]


class CollectionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectionError(message)


def outcome_for_turn(result: str, turn: bool) -> float:
    if result == "1/2-1/2":
        return 0.5
    if result == "1-0":
        return 1.0 if turn == movegen.chess.WHITE else 0.0
    if result == "0-1":
        return 1.0 if turn == movegen.chess.BLACK else 0.0
    raise CollectionError(f"unsupported or incomplete PGN result: {result}")


def stable_key(seed: str, value: str) -> bytes:
    return hashlib.sha256((seed + "\0" + value).encode("utf-8")).digest()


def read_games(path: Path) -> list[dict]:
    games = []
    namespace = probe.sha256_file(path)[:16]
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            require(not game.errors, f"PGN parse errors: {game.errors}")
            result = game.headers.get("Result", "*")
            require(result in ("1-0", "0-1", "1/2-1/2"),
                    "PGN contains an incomplete result")
            variant = game.headers.get("Variant", "Standard").lower()
            require(variant in ("standard", "chess"),
                    f"non-Standard game rejected: {variant}")
            board = game.board()
            positions = []
            ply = 0
            for move in game.mainline_moves():
                if not board.is_game_over(claim_draw=True):
                    positions.append({
                        "ply": ply,
                        "fen": board.fen(),
                        "turn": board.turn,
                    })
                require(move in board.legal_moves, "PGN replay found illegal move")
                board.push(move)
                ply += 1
            identifier = ":".join((
                namespace,
                game.headers.get("Round", str(len(games) + 1)),
                game.headers.get("OpeningIndex", "none"),
                game.headers.get("CandidateColor", "unknown"),
                str(len(games) + 1),
            ))
            games.append({
                "id": identifier,
                "result": result,
                "positions": positions,
            })
    require(bool(games), "PGN contains no games")
    return games


def select_games(games: list[dict], maximum: int, seed: str) -> list[dict]:
    require(maximum > 1, "at least two games are required")
    require(len(games) >= maximum, "PGN has fewer games than requested")
    return sorted(
        games, key=lambda game: stable_key(seed, game["id"])
    )[:maximum]


def select_positions(game: dict, count: int, seed: str) -> list[dict]:
    require(count > 0, "positions per game must be positive")
    # Avoid the supplied opening root and the final two plies.  This reduces
    # book duplication and trivial terminal-label leakage.
    available = game["positions"][2:-2]
    require(len(available) >= count,
            f"game {game['id']} has too few eligible positions")
    selected = sorted(
        available,
        key=lambda row: stable_key(
            seed, f"{game['id']}\0{row['ply']}\0{row['fen']}"
        ),
    )[:count]
    return sorted(selected, key=lambda row: row["ply"])


def collect(
    pgn: Path,
    lab: Path,
    network: Path,
    output: Path,
    manifest: Path,
    max_games: int,
    positions_per_game: int,
    nodes: int,
    timeout_seconds: float,
    seed: str,
) -> dict:
    pgn = pgn.resolve()
    lab = lab.resolve()
    network = network.resolve()
    output = output.resolve()
    manifest = manifest.resolve()
    for label, path in (
        ("PGN", pgn), ("Hybrid Lab", lab), ("Caissa network", network)
    ):
        require(path.is_file(), f"{label} is absent: {path}")
    require(not output.exists(), f"sample collision: {output}")
    require(not manifest.exists(), f"manifest collision: {manifest}")
    require(output.parent == manifest.parent,
            "samples and manifest must share one evidence directory")
    require(output.is_relative_to((ROOT / "tmp").resolve()),
            "evidence must stay below repository tmp")
    require(nodes > 0, "node budget must be positive")
    require(0.5 <= timeout_seconds <= 30,
            "timeout must be between 0.5 and 30 seconds")
    validation_support.resource_snapshot(output.parent, projected=10_000_000)
    require(probe.sha256_file(network) == probe.NETWORK_SHA256,
            "Caissa network hash mismatch")
    require(network.stat().st_size == probe.NETWORK_SIZE,
            "Caissa network size mismatch")

    games = select_games(read_games(pgn), max_games, seed)
    planned = [
        (game, position)
        for game in games
        for position in select_positions(game, positions_per_game, seed)
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    rows_written = 0
    failures = []
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        for game, position in planned:
            board = movegen.chess.Board(position["fen"])
            legal = {move.uci() for move in board.legal_moves}
            for brain in ("eloi", "caissa"):
                try:
                    result = probe.run_probe(
                        lab,
                        ROOT,
                        [
                            "--caissa-network", str(network),
                            "--brain", brain,
                        ],
                        position["fen"],
                        f"go nodes {nodes}",
                        timeout_seconds,
                    )
                    info = result["parsed_info"]
                    require(info is not None, "brain omitted score telemetry")
                    require(result["bestmove"] in legal,
                            "brain returned a non-legal root move")
                    row = {
                        "game_id": game["id"],
                        "brain": brain,
                        "centipawns": info["score_value"],
                        "mate": (
                            info["score_value"]
                            if info["score_kind"] == "mate" else 0
                        ),
                        "outcome": outcome_for_turn(
                            game["result"], position["turn"]
                        ),
                        "fen": position["fen"],
                        "ply": position["ply"],
                        "bestmove": result["bestmove"],
                        "nodes": info["nodes"],
                    }
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                    stream.flush()
                    rows_written += 1
                except Exception as error:
                    failures.append({
                        "game_id": game["id"],
                        "ply": position["ply"],
                        "brain": brain,
                        "error": f"{type(error).__name__}: {error}",
                    })
                    break
            if failures:
                break

    evidence = {
        "schema": "eloi-v2.9.0-wdl-sample-collection-v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "runner_sha256": probe.sha256_file(Path(__file__)),
        "pgn": {
            "path": str(pgn),
            "sha256": probe.sha256_file(pgn),
            "games_available": len(read_games(pgn)),
            "games_selected": len(games),
        },
        "lab": {"path": str(lab), "sha256": probe.sha256_file(lab)},
        "network": {
            "path": str(network), "sha256": probe.sha256_file(network),
            "bytes": network.stat().st_size,
        },
        "settings": {
            "seed": seed, "positions_per_game": positions_per_game,
            "nodes_per_brain": nodes, "threads_per_brain": 3,
            "fresh_process_per_probe": True, "priority": "idle",
            "timeout_seconds": timeout_seconds,
        },
        "planned_positions": len(planned),
        "planned_rows": len(planned) * 2,
        "rows_written": rows_written,
        "sample_sha256": probe.sha256_file(output),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "failures": failures,
        "passed": not failures and rows_written == len(planned) * 2,
    }
    probe.write_evidence(manifest, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pgn", required=True, type=Path)
    parser.add_argument("--lab", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--max-games", type=int, default=40)
    parser.add_argument("--positions-per-game", type=int, default=4)
    parser.add_argument("--nodes", type=int, default=2_000)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--seed", default="eloi-v2.9.0-wdl-samples-v1")
    args = parser.parse_args()
    try:
        evidence = collect(
            args.pgn, args.lab, args.network, args.output, args.manifest,
            args.max_games, args.positions_per_game, args.nodes,
            args.timeout_seconds, args.seed,
        )
    except (CollectionError, ValueError) as error:
        print(f"BLOCKED: {error}")
        return 2
    print(json.dumps({
        "passed": evidence["passed"],
        "games": evidence["pgn"]["games_selected"],
        "positions": evidence["planned_positions"],
        "rows": evidence["rows_written"],
        "failures": len(evidence["failures"]),
        "samples": str(args.output),
        "manifest": str(args.manifest),
    }, indent=2))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
