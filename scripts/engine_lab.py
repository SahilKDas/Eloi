#!/usr/bin/env python3
"""Hash-bound speed and strength laboratory for Eloi UCI executables."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import shutil
import statistics
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
for dependency_root in (
    ROOT / ".deps" / "python",
    ROOT / ".deps" / "lichess-bot" / ".venv" / "Lib" / "site-packages",
):
    if dependency_root.is_dir():
        sys.path.insert(0, str(dependency_root))
import chess
import chess.engine
import chess.pgn


OFFICIAL_BETA1_SHA256 = (
    "614CE6D601AFC749EA4EFD8FC94A8BAE79EF4537374B0984E292A92CA0A99B7F"
)
SPEED_FENS = (
    chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "2r2rk1/pp1bqppp/2n1pn2/1B1p4/3P4/2N1PN2/PPQ2PPP/2RR2K1 w - - 3 14",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PBPN2/PP1N1PPP/R1BQ1RK1 w - - 4 9",
    "2rq1rk1/1b2bppp/pn1ppn2/1p6/3NP3/P1N1B3/1PQ1BPPP/2RR2K1 w - - 2 16",
    "4rrk1/pp3ppp/2p1b3/8/3P4/2P1B3/PP3PPP/3RR1K1 w - - 0 20",
    "8/8/2k5/2p5/2P5/3K4/8/8 w - - 0 1",
)
DEEP_FENS = SPEED_FENS[:4]


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: pathlib.Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    temporary.replace(path)


def configure(engine: chess.engine.SimpleEngine) -> None:
    settings: dict[str, object] = {}
    if "OwnBook" in engine.options:
        settings["OwnBook"] = False
    if "Hash" in engine.options:
        settings["Hash"] = 32
    if "Threads" in engine.options:
        settings["Threads"] = 3
    if "Depth" in engine.options:
        settings["Depth"] = 0
    if settings:
        engine.configure(settings)


def start_engine(path: pathlib.Path) -> chess.engine.SimpleEngine:
    engine = chess.engine.SimpleEngine.popen_uci(
        [str(path), "--uci"], timeout=720.0)
    configure(engine)
    return engine


def run_depth(engine: chess.engine.SimpleEngine, fen: str, depth: int) -> dict[str, Any]:
    board = chess.Board(fen)
    started = time.perf_counter_ns()
    info = engine.analyse(
        board, chess.engine.Limit(depth=depth), game=object())
    elapsed_ns = time.perf_counter_ns() - started
    score = info["score"].pov(board.turn).score(mate_score=30_000)
    pv = [move.uci() for move in info.get("pv", ())]
    return {
        "elapsed_ns": elapsed_ns,
        "depth": int(info.get("depth", 0)),
        "seldepth": int(info.get("seldepth", 0)),
        "nodes": int(info.get("nodes", 0)),
        "nps": int(info.get("nps", 0)),
        "score_cp": int(score or 0),
        "bestmove": pv[0] if pv else "0000",
        "pv": pv,
    }


def timed_corpus(engine: chess.engine.SimpleEngine, depth: int,
                 minimum_seconds: float, repetitions: int | None = None
                 ) -> dict[str, Any]:
    started = time.perf_counter_ns()
    searches: list[dict[str, Any]] = []
    passes = 0
    while repetitions is None or passes < repetitions:
        for fen in SPEED_FENS:
            searches.append(run_depth(engine, fen, depth))
        passes += 1
        elapsed = (time.perf_counter_ns() - started) / 1e9
        if repetitions is None and elapsed >= minimum_seconds:
            break
    elapsed_ns = time.perf_counter_ns() - started
    return {
        "wall_ns": elapsed_ns,
        "passes": passes,
        "searches": len(searches),
        "nodes": sum(row["nodes"] for row in searches),
        "positions": searches,
    }


def run_censored_depth(engine: chess.engine.SimpleEngine, fen: str,
                       target_depth: int, limit_seconds: float
                       ) -> dict[str, Any]:
    board = chess.Board(fen)
    started = time.perf_counter_ns()
    info = engine.analyse(
        board,
        chess.engine.Limit(depth=target_depth, time=limit_seconds),
        game=object(),
    )
    elapsed_ns = time.perf_counter_ns() - started
    reached = int(info.get("depth", 0))
    score = info.get("score")
    pov_score = (
        score.pov(board.turn).score(mate_score=30_000)
        if score is not None else 0
    )
    return {
        "target_depth": target_depth,
        "reached_depth": reached,
        "completed": reached >= target_depth,
        "elapsed_ns": elapsed_ns,
        "nodes": int(info.get("nodes", 0)),
        "nps": int(info.get("nps", 0)),
        "score_cp": int(pov_score or 0),
        "pv": [move.uci() for move in info.get("pv", ())],
    }


def deep_ladder(candidate_path: pathlib.Path, baseline_path: pathlib.Path,
                output: pathlib.Path,
                depths: tuple[int, ...] = (15, 20, 30, 40),
                limit_seconds: float = 600.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": 1,
        "kind": "deep-ladder",
        "started_utc": utc_now(),
        "candidate": {
            "path": str(candidate_path),
            "sha256": sha256(candidate_path),
        },
        "baseline": {
            "path": str(baseline_path),
            "sha256": sha256(baseline_path),
        },
        "settings": {
            "threads": 3,
            "hash_mb": 32,
            "own_book": False,
            "target_depths": list(depths),
            "seconds_per_engine_position": limit_seconds,
            "positions": list(DEEP_FENS),
            "report_only": True,
        },
        "depths": {},
    }
    candidate = start_engine(candidate_path)
    baseline = start_engine(baseline_path)
    try:
        for fen in DEEP_FENS:
            run_depth(candidate, fen, 2)
            run_depth(baseline, fen, 2)
        for depth_index, depth in enumerate(depths):
            rows = []
            for position_index, fen in enumerate(DEEP_FENS):
                order = (
                    ("baseline", "candidate")
                    if (depth_index + position_index) % 2 == 0
                    else ("candidate", "baseline")
                )
                measured: dict[str, Any] = {}
                for label in order:
                    engine = baseline if label == "baseline" else candidate
                    measured[label] = run_censored_depth(
                        engine, fen, depth, limit_seconds
                    )
                baseline_row = measured["baseline"]
                candidate_row = measured["candidate"]
                speedup = None
                speedup_kind = "unavailable-both-censored"
                if baseline_row["completed"] and candidate_row["completed"]:
                    speedup = (
                        baseline_row["elapsed_ns"]
                        / max(1, candidate_row["elapsed_ns"])
                    )
                    speedup_kind = "measured"
                elif not baseline_row["completed"] and candidate_row["completed"]:
                    speedup = (
                        limit_seconds * 1e9
                        / max(1, candidate_row["elapsed_ns"])
                    )
                    speedup_kind = "lower-bound"
                elif baseline_row["completed"] and not candidate_row["completed"]:
                    speedup = (
                        baseline_row["elapsed_ns"]
                        / max(1, limit_seconds * 1e9)
                    )
                    speedup_kind = "upper-bound"
                rows.append({
                    "position": position_index + 1,
                    "fen": fen,
                    "order": order,
                    **measured,
                    "speedup": speedup,
                    "speedup_kind": speedup_kind,
                })
                result["depths"][str(depth)] = {"positions": rows}
                atomic_json(output, result)
            measured_speedups = [
                row["speedup"] for row in rows
                if row["speedup"] is not None
                and row["speedup_kind"] == "measured"
            ]
            result["depths"][str(depth)]["median_measured_speedup"] = (
                statistics.median(measured_speedups)
                if measured_speedups else None
            )
    finally:
        candidate.quit()
        baseline.quit()
    result["passed"] = None
    result["finished_utc"] = utc_now()
    atomic_json(output, result)
    write_markdown(output.with_suffix(".md"), result)
    return result


def speed_gate(candidate_path: pathlib.Path, baseline_path: pathlib.Path,
               output: pathlib.Path, depths: tuple[int, ...] = (1, 5, 10),
               sample_override: int | None = None,
               minimum_seconds: float = 5.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": 1,
        "kind": "speed",
        "started_utc": utc_now(),
        "candidate": {
            "path": str(candidate_path),
            "sha256": sha256(candidate_path),
        },
        "baseline": {
            "path": str(baseline_path),
            "sha256": sha256(baseline_path),
        },
        "settings": {
            "threads": 3,
            "hash_mb": 32,
            "own_book": False,
            "hard_depths": list(depths),
            "hard_speedup": 5.0,
            "speed_positions": list(SPEED_FENS),
        },
        "depths": {},
    }
    candidate = start_engine(candidate_path)
    baseline = start_engine(baseline_path)
    try:
        # Exclude one-time slider/KPK/NNUE table initialization from both
        # measurements by warming every structural position class.
        for fen in SPEED_FENS:
            run_depth(candidate, fen, 2)
            run_depth(baseline, fen, 2)
        for depth in depths:
            samples = sample_override or (5 if depth == 10 else 7)
            if depth == 10:
                repetitions = 1
                calibration = None
            else:
                calibration = timed_corpus(
                    baseline, depth, 0.0, repetitions=1)
                repetitions = max(
                    1, math.ceil(
                        minimum_seconds /
                        max(1e-9, calibration["wall_ns"] / 1e9)))
            rows = []
            for sample in range(samples):
                order = ("baseline", "candidate") if sample % 2 == 0 else (
                    "candidate", "baseline")
                measured: dict[str, Any] = {}
                for label in order:
                    engine = baseline if label == "baseline" else candidate
                    measured[label] = timed_corpus(
                        engine, depth, minimum_seconds,
                        repetitions=repetitions)
                rows.append({"sample": sample + 1, "order": order,
                             **measured})
                result["depths"][str(depth)] = {
                    "calibration": calibration,
                    "repetitions": repetitions,
                    "samples": rows,
                }
                atomic_json(output, result)
            baseline_times = [row["baseline"]["wall_ns"] for row in rows]
            candidate_times = [row["candidate"]["wall_ns"] for row in rows]
            baseline_median = statistics.median(baseline_times)
            candidate_median = statistics.median(candidate_times)
            speedup = baseline_median / max(1, candidate_median)
            result["depths"][str(depth)].update({
                "baseline_median_ns": baseline_median,
                "candidate_median_ns": candidate_median,
                "speedup": speedup,
                "passed": speedup >= 5.0,
            })
            atomic_json(output, result)
    finally:
        candidate.quit()
        baseline.quit()
    result["passed"] = all(
        result["depths"][str(depth)].get("passed", False)
        for depth in depths)
    result["finished_utc"] = utc_now()
    atomic_json(output, result)
    write_markdown(output.with_suffix(".md"), result)
    return result


def score_label(board: chess.Board, candidate_is_white: bool) -> str:
    outcome = board.outcome(claim_draw=True)
    if outcome is None or outcome.winner is None:
        return "draw"
    return "win" if outcome.winner == candidate_is_white else "loss"


def play_game(candidate: chess.engine.SimpleEngine,
              baseline: chess.engine.SimpleEngine, fen: str,
              candidate_is_white: bool, movetime_ms: int,
              max_plies: int, game_number: int,
              event: str = "Eloi Engine Lab strength gate"
              ) -> tuple[str, chess.pgn.Game]:
    board = chess.Board(fen)
    game = chess.pgn.Game.from_board(board)
    game.headers["Event"] = event
    game.headers["Round"] = str(game_number)
    game.headers["CandidateColor"] = "White" if candidate_is_white else "Black"
    node = game
    game_token = object()
    while not board.is_game_over(claim_draw=True) and board.ply() < max_plies:
        candidate_turn = board.turn == candidate_is_white
        engine = candidate if candidate_turn else baseline
        try:
            played = engine.play(
                board, chess.engine.Limit(time=movetime_ms / 1000.0),
                game=game_token)
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError):
            label = "loss" if candidate_turn else "win"
            game.headers["Termination"] = (
                "candidate engine failure" if candidate_turn
                else "baseline engine failure")
            return label, game
        if played.move is None or played.move not in board.legal_moves:
            label = "loss" if candidate_turn else "win"
            game.headers["Termination"] = "illegal or missing engine move"
            return label, game
        board.push(played.move)
        node = node.add_variation(played.move)
    label = score_label(board, candidate_is_white)
    outcome = board.outcome(claim_draw=True)
    game.headers["Result"] = outcome.result() if outcome else "1/2-1/2"
    if outcome is None:
        game.headers["Termination"] = "200-ply adjudicated draw"
    return label, game


def strength_gate(candidate_path: pathlib.Path, baseline_path: pathlib.Path,
                  suite_path: pathlib.Path, checkpoint_path: pathlib.Path,
                  pgn_path: pathlib.Path, movetime_ms: int = 250,
                  games: int = 250, max_plies: int = 200,
                  required_win_rate: float = 0.60,
                  architecture_playoff: bool = False) -> dict[str, Any]:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    positions = suite["positions"]
    if games > len(positions) * 2 or games % 2:
        raise ValueError("games must be even and no larger than twice the suite")
    if not architecture_playoff and not 0.0 < required_win_rate <= 1.0:
        raise ValueError("required win rate must be in (0, 1]")
    identity = {
        "candidate_sha256": sha256(candidate_path),
        "baseline_sha256": sha256(baseline_path),
        "suite_sha256": sha256(suite_path),
        "movetime_ms": movetime_ms,
        "games": games,
        "max_plies": max_plies,
        "threads": 3,
        "hash_mb": 32,
        "own_book": False,
        "gate_metric": "score" if architecture_playoff else "raw-wins",
    }
    if architecture_playoff:
        identity.update({
            "candidate_hidden": 128,
            "baseline_hidden": 64,
            "select_candidate_at_score": 0.55,
            "select_baseline_at_or_below_score": 0.45,
        })
    else:
        identity.update({
            "required_win_rate": required_win_rate,
            "required_wins": math.ceil(games * required_win_rate),
        })
    if checkpoint_path.exists():
        result = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if result["identity"] != identity:
            raise ValueError("checkpoint identity does not match this run")
    else:
        result = {
            "schema": 1,
            "kind": (
                "architecture-playoff" if architecture_playoff else "strength"
            ),
            "started_utc": utc_now(),
            "identity": identity,
            "results": [],
        }
        pgn_path.parent.mkdir(parents=True, exist_ok=True)
        pgn_path.write_text("", encoding="utf-8")

    candidate = start_engine(candidate_path)
    baseline = start_engine(baseline_path)
    try:
        for index in range(len(result["results"]), games):
            opening = positions[index // 2]
            candidate_is_white = index % 2 == 0
            label, game = play_game(
                candidate, baseline, opening["fen"], candidate_is_white,
                movetime_ms, max_plies, index + 1,
                event=(
                    "Eloi NNUE architecture playoff"
                    if architecture_playoff
                    else "Eloi Engine Lab strength gate"
                ))
            result["results"].append({
                "game": index + 1,
                "opening": index // 2,
                "candidate_color": "white" if candidate_is_white else "black",
                "result": label,
            })
            with pgn_path.open("a", encoding="utf-8") as stream:
                print(game, file=stream, end="\n\n")
            summarize_strength(result)
            atomic_json(checkpoint_path, result)
            print(
                f"game {index + 1}/{games}: {label}; "
                f"W/D/L {result['wins']}/{result['draws']}/{result['losses']}",
                flush=True)
    finally:
        candidate.quit()
        baseline.quit()
    result["finished_utc"] = utc_now()
    summarize_strength(result)
    atomic_json(checkpoint_path, result)
    write_markdown(checkpoint_path.with_suffix(".md"), result)
    return result


def summarize_strength(result: dict[str, Any]) -> None:
    labels = [row["result"] for row in result["results"]]
    wins = labels.count("win")
    draws = labels.count("draw")
    losses = labels.count("loss")
    games = len(labels)
    score = (wins + 0.5 * draws) / games if games else 0.0
    raw_win_rate = wins / games if games else 0.0
    clipped = min(0.999_999, max(0.000_001, score))
    elo = -400.0 * math.log10(1.0 / clipped - 1.0)
    complete = games == result["identity"]["games"]
    summary = {
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "raw_win_rate": raw_win_rate,
        "score": score,
        "estimated_elo_difference": elo,
    }
    if result["identity"].get("gate_metric") == "score":
        selected = None
        reason = "incomplete"
        if complete and score >= result["identity"]["select_candidate_at_score"]:
            selected = result["identity"]["candidate_hidden"]
            reason = "candidate-scored-at-least-55-percent"
        elif complete and score <= result["identity"]["select_baseline_at_or_below_score"]:
            selected = result["identity"]["baseline_hidden"]
            reason = "candidate-scored-at-most-45-percent"
        elif complete:
            selected = result["identity"]["baseline_hidden"]
            reason = "inconclusive-band-prefers-smaller-faster-baseline"
        summary.update({
            "selected_hidden": selected,
            "selection_reason": reason,
            "passed": complete,
        })
    else:
        summary["passed"] = (
            complete and wins >= result["identity"]["required_wins"]
        )
    result.update(summary)


def count_pgn_games(path: pathlib.Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as stream:
        while chess.pgn.read_game(stream) is not None:
            count += 1
    return count


def finalize_shortened_playoff(
        candidate_path: pathlib.Path, baseline_path: pathlib.Path,
        checkpoint_path: pathlib.Path, pgn_path: pathlib.Path,
        archive_path: pathlib.Path, games: int,
        plan_changes: list[str]) -> dict[str, Any]:
    if games <= 0 or games % 2:
        raise ValueError("shortened playoff games must be positive and even")
    if not plan_changes:
        raise ValueError("at least one --plan-change is required")
    result = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if result.get("kind") != "architecture-playoff":
        raise ValueError("checkpoint is not an architecture playoff")
    original_identity = result["identity"]
    if original_identity["candidate_sha256"] != sha256(candidate_path):
        raise ValueError("candidate hash does not match checkpoint")
    if original_identity["baseline_sha256"] != sha256(baseline_path):
        raise ValueError("baseline hash does not match checkpoint")
    if original_identity["games"] <= games:
        raise ValueError("final game count must shorten the original plan")
    if len(result["results"]) != games:
        raise ValueError(
            "checkpoint must contain exactly the requested completed games")
    pgn_games = count_pgn_games(pgn_path)
    if pgn_games != games:
        raise ValueError(
            f"PGN contains {pgn_games} games, expected exactly {games}")
    if archive_path.exists():
        raise ValueError(f"raw checkpoint archive already exists: {archive_path}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(checkpoint_path)
    shutil.copyfile(checkpoint_path, archive_path)
    result["original_identity"] = original_identity
    result["identity"] = {**original_identity, "games": games}
    result["shortened_after_start"] = True
    result["plan_changes"] = plan_changes
    result["raw_interrupted_checkpoint"] = {
        "path": str(archive_path),
        "sha256": source_hash,
    }
    result["pgn_sha256"] = sha256(pgn_path)
    result["finished_utc"] = utc_now()
    summarize_strength(result)
    atomic_json(checkpoint_path, result)
    write_markdown(checkpoint_path.with_suffix(".md"), result)
    return result


def write_markdown(path: pathlib.Path, result: dict[str, Any]) -> None:
    lines = ["# Eloi Engine Lab report", "",
             f"Generated: {result.get('finished_utc', utc_now())}", ""]
    if result["kind"] == "speed":
        lines += ["## Speed ladder", "",
                  "| Depth | Baseline median | Candidate median | Speedup | Gate |",
                  "|---:|---:|---:|---:|:---:|"]
        for depth in (1, 5, 10):
            row = result["depths"].get(str(depth), {})
            if "speedup" not in row:
                continue
            lines.append(
                f"| {depth} | {row['baseline_median_ns'] / 1e6:.3f} ms | "
                f"{row['candidate_median_ns'] / 1e6:.3f} ms | "
                f"{row['speedup']:.3f}x | "
                f"{'PASS' if row['passed'] else 'FAIL'} |")
    elif result["kind"] in ("strength", "architecture-playoff"):
        heading = (
            "NNUE architecture playoff"
            if result["kind"] == "architecture-playoff"
            else "Strength gate"
        )
        lines += [
            f"## {heading}", "",
            f"- Games: {len(result['results'])}/{result['identity']['games']}",
            f"- Candidate W/D/L: {result['wins']}/{result['draws']}/{result['losses']}",
            f"- Raw win rate: {100 * result['raw_win_rate']:.2f}%",
            f"- Score: {100 * result['score']:.2f}%",
            f"- Estimated Elo difference: {result['estimated_elo_difference']:+.1f}",
        ]
        if result["kind"] == "architecture-playoff":
            lines += [
                f"- Selected hidden units: {result['selected_hidden']}",
                f"- Selection reason: {result['selection_reason']}",
                f"- Completed: {'YES' if result['passed'] else 'NO'}",
            ]
            if result.get("shortened_after_start"):
                lines += [
                    f"- Original planned games: "
                    f"{result['original_identity']['games']}",
                    "- Shortened after start: YES",
                    "- Plan changes:",
                    *(f"  - {change}" for change in result["plan_changes"]),
                    f"- PGN SHA-256: `{result['pgn_sha256']}`",
                ]
        else:
            lines += [
                f"- Required raw wins: {result['identity']['required_wins']} "
                f"({100 * result['identity']['required_win_rate']:.2f}%)",
                f"- Gate: {'PASS' if result['passed'] else 'FAIL'}",
            ]
    else:
        lines += [
            "## Censored deep-depth ladder", "",
            f"Per-engine/per-position limit: "
            f"{result['settings']['seconds_per_engine_position']:.1f} s", "",
            "| Target | Position | Baseline | Candidate | Speedup |",
            "|---:|---:|:---|:---|:---|",
        ]
        for depth_text, depth_result in result["depths"].items():
            for row in depth_result["positions"]:
                baseline = row["baseline"]
                candidate = row["candidate"]
                speedup = (
                    "n/a" if row["speedup"] is None
                    else f"{row['speedup']:.3f}x ({row['speedup_kind']})"
                )
                lines.append(
                    f"| {depth_text} | {row['position']} | "
                    f"d{baseline['reached_depth']}, "
                    f"{baseline['elapsed_ns'] / 1e9:.2f}s, "
                    f"{baseline['nodes']} nodes | "
                    f"d{candidate['reached_depth']}, "
                    f"{candidate['elapsed_ns'] / 1e9:.2f}s, "
                    f"{candidate['nodes']} nodes | {speedup} |"
                )
    lines += ["", "## Identity", "", "~~~json", json.dumps(
        result.get("identity", {
            "candidate": result.get("candidate"),
            "baseline": result.get("baseline"),
        }), indent=2, sort_keys=True), "~~~", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def verify_baseline(path: pathlib.Path, allow_unverified: bool) -> None:
    digest = sha256(path)
    if digest != OFFICIAL_BETA1_SHA256 and not allow_unverified:
        raise SystemExit(
            "baseline SHA-256 is not the official v1.5.0-beta.1 executable: "
            f"{digest}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True, type=pathlib.Path)
    parser.add_argument("--baseline", required=True, type=pathlib.Path)
    parser.add_argument("--allow-unverified-baseline", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    speed = subparsers.add_parser("speed")
    speed.add_argument(
        "--output", type=pathlib.Path,
        default=ROOT / "tmp" / "engine-lab" / "speed.json")
    speed.add_argument(
        "--depths", type=int, nargs="+", default=[1, 5, 10],
        help="development override; the release gate uses 1 5 10")
    speed.add_argument(
        "--samples", type=int,
        help="development override; release defaults are 7, 7, and 5")
    speed.add_argument(
        "--minimum-seconds", type=float, default=5.0,
        help="minimum aggregate time for each shallow sample")
    strength = subparsers.add_parser("strength")
    strength.add_argument(
        "--suite", type=pathlib.Path,
        default=ROOT / "data" / "strength_openings.json")
    strength.add_argument(
        "--checkpoint", type=pathlib.Path,
        default=ROOT / "tmp" / "engine-lab" / "strength.json")
    strength.add_argument(
        "--pgn", type=pathlib.Path,
        default=ROOT / "tmp" / "engine-lab" / "strength.pgn")
    strength.add_argument("--games", type=int, default=250)
    strength.add_argument("--movetime-ms", type=int, default=250)
    strength.add_argument("--max-plies", type=int, default=200)
    strength.add_argument("--required-win-rate", type=float, default=0.60)
    playoff = subparsers.add_parser("playoff")
    playoff.add_argument(
        "--suite", type=pathlib.Path,
        default=ROOT / "data" / "strength_openings.json")
    playoff.add_argument(
        "--checkpoint", type=pathlib.Path,
        default=ROOT / "tmp" / "nnue-playoff" / "architecture-playoff.json")
    playoff.add_argument(
        "--pgn", type=pathlib.Path,
        default=ROOT / "tmp" / "nnue-playoff" / "architecture-playoff.pgn")
    playoff.add_argument("--games", type=int, default=250)
    playoff.add_argument("--movetime-ms", type=int, default=250)
    playoff.add_argument("--max-plies", type=int, default=200)
    finalize = subparsers.add_parser("finalize-playoff")
    finalize.add_argument(
        "--checkpoint", type=pathlib.Path, required=True)
    finalize.add_argument("--pgn", type=pathlib.Path, required=True)
    finalize.add_argument("--archive", type=pathlib.Path, required=True)
    finalize.add_argument("--games", type=int, required=True)
    finalize.add_argument(
        "--plan-change", action="append", required=True,
        help="repeatable truthful description of a post-start sample change")
    ladder = subparsers.add_parser("ladder")
    ladder.add_argument(
        "--output", type=pathlib.Path,
        default=ROOT / "tmp" / "engine-lab" / "deep-ladder.json")
    ladder.add_argument(
        "--depths", type=int, nargs="+", default=[15, 20, 30, 40])
    ladder.add_argument(
        "--seconds", type=float, default=600.0,
        help="time limit per engine per position; release reporting uses 600")
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    baseline = args.baseline.resolve()
    verify_baseline(baseline, args.allow_unverified_baseline)
    if args.command == "finalize-playoff":
        result = finalize_shortened_playoff(
            candidate, baseline, args.checkpoint.resolve(),
            args.pgn.resolve(), args.archive.resolve(), args.games,
            args.plan_change)
    elif args.command == "speed":
        result = speed_gate(
            candidate, baseline, args.output.resolve(), tuple(args.depths),
            args.samples, args.minimum_seconds)
    elif args.command in ("strength", "playoff"):
        result = strength_gate(
            candidate, baseline, args.suite.resolve(),
            args.checkpoint.resolve(), args.pgn.resolve(),
            args.movetime_ms, args.games, args.max_plies,
            args.required_win_rate if args.command == "strength" else 0.60,
            architecture_playoff=args.command == "playoff")
    else:
        result = deep_ladder(
            candidate, baseline, args.output.resolve(), tuple(args.depths),
            args.seconds)
        return 0
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
