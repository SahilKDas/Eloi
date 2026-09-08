"""Evaluate Eloi/Caissa centipawn-to-expected-score mappings.

Input is JSON Lines. Each row needs game_id, brain (eloi or caissa),
centipawns, and outcome from that brain's perspective (0, 0.5, or 1).
All samples from a game are assigned to one partition. The tool emits evidence
only; it never rewrites engine source or configuration.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable


CURRENT_SCALES = {"eloi": 1300.0, "caissa": 360.0}
BRAINS = tuple(CURRENT_SCALES)


class CalibrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Sample:
    game_id: str
    brain: str
    centipawns: int
    outcome: float


def expected_score(centipawns: int, scale: float) -> float:
    if not math.isfinite(scale) or scale <= 0:
        raise CalibrationError("scale must be positive and finite")
    return 1.0 / (1.0 + 10.0 ** (-centipawns / scale))


def load_samples(path: Path) -> tuple[list[Sample], int]:
    samples: list[Sample] = []
    excluded_mates = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise CalibrationError(f"could not read dataset: {error}") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise CalibrationError(f"line {number}: invalid JSON") from error
        if row.get("mate") not in (None, 0):
            excluded_mates += 1
            continue
        game_id = row.get("game_id")
        brain = row.get("brain")
        centipawns = row.get("centipawns")
        outcome = row.get("outcome")
        if not isinstance(game_id, str) or not game_id.strip():
            raise CalibrationError(f"line {number}: game_id is required")
        if brain not in BRAINS:
            raise CalibrationError(f"line {number}: unknown brain")
        if not isinstance(centipawns, int) or isinstance(centipawns, bool):
            raise CalibrationError(
                f"line {number}: centipawns must be an integer"
            )
        if outcome not in (0, 0.5, 1):
            raise CalibrationError(
                f"line {number}: outcome must be 0, 0.5, or 1"
            )
        samples.append(
            Sample(game_id.strip(), brain, centipawns, float(outcome))
        )
    if not samples:
        raise CalibrationError("dataset contains no non-mate samples")
    return samples, excluded_mates


def partition_for_game(
    game_id: str, seed: str, validation_fraction: float
) -> str:
    if not 0 < validation_fraction < 1:
        raise CalibrationError(
            "validation fraction must be between zero and one"
        )
    digest = hashlib.sha256(
        (seed + "\0" + game_id).encode("utf-8")
    ).digest()
    ratio = int.from_bytes(digest[:8], "big") / 2**64
    return (
        "validation"
        if ratio < validation_fraction
        else "calibration"
    )


def split_samples(
    samples: Iterable[Sample],
    seed: str,
    validation_fraction: float,
) -> dict[str, list[Sample]]:
    split = {"calibration": [], "validation": []}
    assignments: dict[str, str] = {}
    for sample in samples:
        partition = assignments.setdefault(
            sample.game_id,
            partition_for_game(
                sample.game_id, seed, validation_fraction
            ),
        )
        split[partition].append(sample)
    return split


def metrics(
    samples: list[Sample], scale: float, bins: int = 10
) -> dict:
    if not samples:
        raise CalibrationError("cannot score an empty partition")
    rows = [
        (expected_score(sample.centipawns, scale), sample.outcome)
        for sample in samples
    ]
    epsilon = 1e-12
    brier = sum(
        (prediction - outcome) ** 2
        for prediction, outcome in rows
    ) / len(rows)
    log_loss = -sum(
        outcome * math.log(max(epsilon, prediction))
        + (1.0 - outcome)
        * math.log(max(epsilon, 1.0 - prediction))
        for prediction, outcome in rows
    ) / len(rows)
    buckets: list[list[tuple[float, float]]] = [
        [] for _ in range(bins)
    ]
    for prediction, outcome in rows:
        index = min(bins - 1, int(prediction * bins))
        buckets[index].append((prediction, outcome))
    ece = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        confidence = sum(row[0] for row in bucket) / len(bucket)
        observed = sum(row[1] for row in bucket) / len(bucket)
        ece += (
            len(bucket) / len(rows) * abs(confidence - observed)
        )
    return {
        "samples": len(rows),
        "brier": brier,
        "log_loss": log_loss,
        "ece_10": ece,
    }


def model_checks(scale: float) -> dict:
    values = [-1000, -500, -100, 0, 100, 500, 1000]
    predictions = [
        expected_score(value, scale) for value in values
    ]
    symmetry_error = max(
        abs(
            expected_score(value, scale)
            + expected_score(-value, scale)
            - 1.0
        )
        for value in values
    )
    return {
        "finite": all(math.isfinite(value) for value in predictions),
        "strictly_monotonic": all(
            left < right
            for left, right in zip(
                predictions, predictions[1:]
            )
        ),
        "maximum_symmetry_error": symmetry_error,
        "mate_handling": (
            "excluded; arbiter mate veto remains discrete"
        ),
    }


def evaluate(
    samples: list[Sample],
    candidate_scales: list[float],
    seed: str,
    validation_fraction: float,
) -> dict:
    candidates = sorted(
        set(candidate_scales) | set(CURRENT_SCALES.values())
    )
    if any(
        not math.isfinite(scale) or scale <= 0
        for scale in candidates
    ):
        raise CalibrationError(
            "all candidate scales must be positive and finite"
        )
    split = split_samples(samples, seed, validation_fraction)
    game_sets = {
        name: sorted({sample.game_id for sample in rows})
        for name, rows in split.items()
    }
    if (
        set(game_sets["calibration"])
        & set(game_sets["validation"])
    ):
        raise CalibrationError("game leakage between partitions")

    brain_results = {}
    for brain in BRAINS:
        calibration = [
            sample
            for sample in split["calibration"]
            if sample.brain == brain
        ]
        validation = [
            sample
            for sample in split["validation"]
            if sample.brain == brain
        ]
        if not calibration or not validation:
            raise CalibrationError(
                f"{brain} must have samples in both partitions"
            )
        rows = []
        for scale in candidates:
            rows.append(
                {
                    "scale": scale,
                    "calibration": metrics(
                        calibration, scale
                    ),
                    "validation": metrics(validation, scale),
                    "model_checks": model_checks(scale),
                }
            )
        selected = min(
            rows,
            key=lambda row: (
                row["calibration"]["log_loss"],
                row["validation"]["log_loss"],
                row["scale"],
            ),
        )
        current = next(
            row
            for row in rows
            if row["scale"] == CURRENT_SCALES[brain]
        )
        brain_results[brain] = {
            "current_scale": CURRENT_SCALES[brain],
            "selected_on_calibration": selected["scale"],
            "selected_validation": selected["validation"],
            "current_validation": current["validation"],
            "validation_log_loss_delta_vs_current": (
                selected["validation"]["log_loss"]
                - current["validation"]["log_loss"]
            ),
            "candidates": rows,
        }

    return {
        "schema": "eloi-hybrid-wdl-calibration-v1",
        "seed": seed,
        "validation_fraction": validation_fraction,
        "partition": {
            "calibration_games": game_sets["calibration"],
            "validation_games": game_sets["validation"],
            "game_overlap": [],
        },
        "brains": brain_results,
        "source_change": (
            "none; this report is evidence only"
        ),
    }


def add_external_validation(
    report: dict,
    calibration_samples: list[Sample],
    external_samples: list[Sample],
) -> None:
    calibration_games = {sample.game_id for sample in calibration_samples}
    external_games = {sample.game_id for sample in external_samples}
    overlap = sorted(calibration_games & external_games)
    if overlap:
        raise CalibrationError(
            "external validation overlaps calibration games"
        )
    for brain in BRAINS:
        rows = [
            sample for sample in external_samples
            if sample.brain == brain
        ]
        if not rows:
            raise CalibrationError(
                f"external validation has no {brain} samples"
            )
        result = report["brains"][brain]
        selected = result["selected_on_calibration"]
        current = result["current_scale"]
        selected_metrics = metrics(rows, selected)
        current_metrics = metrics(rows, current)
        result["external_validation"] = {
            "selected_scale": selected,
            "selected": selected_metrics,
            "current_scale": current,
            "current": current_metrics,
            "log_loss_delta_vs_current": (
                selected_metrics["log_loss"]
                - current_metrics["log_loss"]
            ),
        }
    report["external_validation"] = {
        "games": sorted(external_games),
        "game_overlap": overlap,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024), b""
        ):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--external-validation", type=Path)
    parser.add_argument("--seed", default="eloi-caissa125-wdl-v1")
    parser.add_argument(
        "--validation-fraction", type=float, default=0.25
    )
    parser.add_argument(
        "--candidate-scale",
        action="append",
        type=float,
        dest="candidate_scales",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise CalibrationError(
            f"refusing to overwrite output: {args.output}"
        )
    samples, excluded_mates = load_samples(args.input)
    report = evaluate(
        samples,
        args.candidate_scales
        or [240, 280, 320, 360, 400, 440, 480, 520],
        args.seed,
        args.validation_fraction,
    )
    report["input"] = {
        "path": str(args.input.resolve()),
        "sha256": sha256_file(args.input),
        "samples": len(samples),
        "excluded_mate_samples": excluded_mates,
    }
    if args.external_validation:
        external_samples, external_excluded_mates = load_samples(
            args.external_validation
        )
        add_external_validation(report, samples, external_samples)
        report["external_input"] = {
            "path": str(args.external_validation.resolve()),
            "sha256": sha256_file(args.external_validation),
            "samples": len(external_samples),
            "excluded_mate_samples": external_excluded_mates,
        }
    report["runner_sha256"] = sha256_file(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
