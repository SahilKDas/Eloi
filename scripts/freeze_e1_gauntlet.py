#!/usr/bin/env python3
"""Freeze the E1-versus-v2.5.0 125-game gauntlet before game one."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESERVE = ROOT / "data" / "search_recovery" / "reserve.json"
CANDIDATE = ROOT / "tmp" / "nnue-e1-e32" / "candidates" / "E1-selected" / "build-1" / "Eloi.exe"
BASELINE = ROOT / "tmp" / "release-v2.5.0-attempt2" / "standalone-A" / "package" / "Eloi.exe"
OUTPUT = ROOT / "tmp" / "nnue-e1-e32" / "gauntlet125"
SUITE = OUTPUT / "e1_vs_v250_openings.json"
PROTOCOL = OUTPUT / "e1_vs_v250_protocol.json"

CANDIDATE_SHA256 = "FD817BAACA3D0E29DB74E24738BD68BBD1915CA12C09DEFC8F7C1A527C6908FC"
BASELINE_SHA256 = "4263AD9FE953252FAE0E0295FE03B16817A2275E560D4AA4067FDD54AC6309C5"
E1_WEIGHTS_SHA256 = "DED4A0CBEDF205A97AD3089A895780D5F6CBB32F392105E8CE870FEBF5A001ED"
SELECTED_INDEXES = tuple(range(120, 183))


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"refusing existing output collision: {OUTPUT}")
    if sha256(CANDIDATE) != CANDIDATE_SHA256:
        raise SystemExit("E1 candidate hash mismatch")
    if sha256(BASELINE) != BASELINE_SHA256:
        raise SystemExit("v2.5.0 baseline hash mismatch")

    reserve = json.loads(RESERVE.read_text(encoding="utf-8"))
    positions = reserve["positions"]
    if len(positions) != 270 or len(SELECTED_INDEXES) != 63:
        raise SystemExit("unexpected reserve or selected-opening count")
    if min(SELECTED_INDEXES) < 120 or max(SELECTED_INDEXES) >= len(positions):
        raise SystemExit("selected openings overlap the conservative 0-119 exclusion")

    selected = [
        {"reserve_index": index, **positions[index]}
        for index in SELECTED_INDEXES
    ]
    suite = {
        "schema": 1,
        "name": "E1 versus Eloi v2.5.0: 125 games",
        "source": str(RESERVE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": sha256(RESERVE),
        "selection": "reserve indexes 120 through 182 inclusive, in frozen order",
        "historical_exclusion": "reserve indexes 0 through 119 conservatively excluded",
        "count": len(selected),
        "positions": selected,
    }

    schedule = []
    game = 1
    for offset, opening in enumerate(selected):
        schedule.append({
            "game": game,
            "opening": offset,
            "reserve_index": opening["reserve_index"],
            "candidate_color": "white",
        })
        game += 1
        if offset != len(selected) - 1:
            schedule.append({
                "game": game,
                "opening": offset,
                "reserve_index": opening["reserve_index"],
                "candidate_color": "black",
            })
            game += 1
    if game != 126 or len(schedule) != 125:
        raise SystemExit("internal schedule construction error")

    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    runner = ROOT / "scripts" / "engine_lab.py"
    protocol = {
        "schema": 1,
        "campaign": "E1-vs-v2.5.0-gauntlet125",
        "status": "frozen-before-game-one",
        "source_revision": revision,
        "runner": str(runner.relative_to(ROOT)).replace("\\", "/"),
        "runner_sha256": sha256(runner),
        "suite": str(SUITE.relative_to(ROOT)).replace("\\", "/"),
        "candidate": {
            "name": "E1-selected",
            "executable_sha256": CANDIDATE_SHA256,
            "weights_sha256": E1_WEIGHTS_SHA256,
        },
        "baseline": {
            "name": "Eloi v2.5.0 (published standalone)",
            "executable_sha256": BASELINE_SHA256,
        },
        "settings": {
            "games": 125,
            "mirrored_games": 124,
            "unpaired_final_game": 125,
            "unpaired_candidate_color": "white",
            "candidate_white_games": 63,
            "candidate_black_games": 62,
            "nodes_per_move": 10000,
            "max_plies": 200,
            "threads_per_engine": 3,
            "hash_mb": 32,
            "own_book": False,
            "noise_millipawns": 0,
            "move_overhead_ms": 0,
            "process_priority": "Windows Idle",
        },
        "acceptance": {
            "metric": "chess score (wins + one-half draws)",
            "rule": "strictly above 50 percent after all 125 games",
            "minimum_half_points": 126,
            "minimum_points": 63.0,
            "required_score_argument": 0.504,
            "incomplete_or_protocol_failure_passes": False,
        },
        "opening_schedule": schedule,
        "notes": [
            "The final game is intentionally unpaired because 125 is odd.",
            "The one-game color imbalance must remain visible in reporting.",
            "The visible Lichess v2.5.0 bridge is separate from this local match.",
        ],
    }

    OUTPUT.mkdir(parents=True, exist_ok=False)
    SUITE.write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    protocol["suite_sha256"] = sha256(SUITE)
    PROTOCOL.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "suite": str(SUITE),
        "suite_sha256": sha256(SUITE),
        "protocol": str(PROTOCOL),
        "protocol_sha256": sha256(PROTOCOL),
        "games": len(schedule),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
