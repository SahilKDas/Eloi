#!/usr/bin/env python3
"""Verify Python/C++ EPV1 inference on deterministic Standard positions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import train_eloi_policy_value as training


def load_python(path: Path) -> training.Network:
    network = training.Network(0)
    arrays = (network.input, network.bias, network.value, network.value_bias,
              network.policy_from, network.policy_to,
              network.policy_promotion, network.policy_piece)
    with path.open("rb") as stream:
        header = stream.read(20)
        values = struct.unpack("<4sIIII", header)
        expected = (training.MAGIC, training.INPUTS, training.HIDDEN,
                    training.PROMOTIONS, training.PIECES)
        if values != expected:
            raise ValueError("invalid EPV1 header")
        for array in arrays:
            raw = stream.read(array.size * 4)
            if len(raw) != array.size * 4:
                raise ValueError("truncated EPV1 array")
            array[:] = np.frombuffer(raw, dtype="<f4").reshape(array.shape)
        if stream.read(1):
            raise ValueError("trailing EPV1 bytes")
    return network


def verify(model: Path, probe: Path, fens: list[str], tolerance: float) -> dict:
    network = load_python(model)
    maximum = 0.0
    rows = []
    for fen in fens:
        board = training.chess.Board(fen)
        moves = list(board.legal_moves)
        py_value, py_policy = network.predict(board, moves)
        completed = subprocess.run(
            [str(probe), "--model", str(model), "--fen", fen],
            cwd=ROOT, text=True, capture_output=True, timeout=10, check=True)
        cpp = json.loads(completed.stdout)
        cpp_policy = np.asarray([cpp["policy"][move.uci()] for move in moves])
        difference = max(float(np.max(np.abs(py_value - cpp["value"]))),
                         float(np.max(np.abs(py_policy - cpp_policy))))
        maximum = max(maximum, difference)
        rows.append({"fen": fen, "maximum_absolute_difference": difference})
    return {"passed": maximum <= tolerance, "tolerance": tolerance,
            "maximum_absolute_difference": maximum, "positions": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--fen", action="append")
    parser.add_argument("--tolerance", type=float, default=2e-6)
    args = parser.parse_args()
    fens = args.fen or [
        training.chess.Board().fen(),
        "r1bq1rk1/ppp2ppp/2np1n2/4p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 8",
        "8/2p5/3p4/3Pp1k1/4P3/2K5/8/8 w - - 0 40",
    ]
    result = verify(args.model.resolve(), args.probe.resolve(), fens,
                    args.tolerance)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
