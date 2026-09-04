"""Run bounded, hash-gated Caissa adapter parity diagnostics.

This is not a chess match or a strength gate. Three-thread Caissa search is
not deterministic at small node limits, so depth-one equality is a mechanical
check while repeated fixed-node results are retained as an observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

import validation_support

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SHA256 = "FB87B9D47452322E3759E19CC71F8EFA9F5FC03F0EE16B58EA930D221FC396C6"
NETWORK_SHA256 = "22249DE582912F46F73F7CF7410D6D72ECCC77696B0B857E99B97A45F3F37116"
NETWORK_SIZE = 50_367_040
CAISSA_COMMIT = "008b0b8f1fc6479890665a1a9c2ff6bbc2f1bc06"
DEFAULT_CASE_IDS = ("initial", "lichess-001XA", "poisoned-pawn-capture")
INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class ProbeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def verify_inputs(official: Path, embedded: Path, network: Path) -> dict:
    for label, path in (
        ("official executable", official),
        ("embedded executable", embedded),
        ("Caissa network", network),
    ):
        if not path.is_file():
            raise ProbeError(f"{label} is absent: {path}")
    identities = {
        "official_sha256": sha256_file(official),
        "embedded_sha256": sha256_file(embedded),
        "network_sha256": sha256_file(network),
        "network_size": network.stat().st_size,
    }
    if identities["official_sha256"] != OFFICIAL_SHA256:
        raise ProbeError("official Caissa executable hash mismatch")
    if identities["network_sha256"] != NETWORK_SHA256:
        raise ProbeError("Caissa network hash mismatch")
    if identities["network_size"] != NETWORK_SIZE:
        raise ProbeError("Caissa network size mismatch")
    return identities


def selected_cases(case_ids: tuple[str, ...]) -> list[dict]:
    available = {row["id"]: row["fen"] for row in validation_support.epd_cases()}
    available["initial"] = INITIAL_FEN
    missing = [case_id for case_id in case_ids if case_id not in available]
    if missing:
        raise ProbeError("unknown parity case(s): " + ", ".join(missing))
    return [{"id": case_id, "fen": available[case_id]} for case_id in case_ids]


def _creation_flags() -> int:
    return getattr(subprocess, "IDLE_PRIORITY_CLASS", 0) if os.name == "nt" else 0


def _stop_owned_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def run_probe(
    executable: Path,
    working_directory: Path,
    arguments: list[str],
    fen: str,
    go_command: str,
    timeout_seconds: float,
) -> dict:
    started = time.monotonic()
    process = subprocess.Popen(
        [str(executable), *arguments],
        cwd=working_directory,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=_creation_flags(),
    )
    assert process.stdin is not None
    assert process.stdout is not None

    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        for line in process.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    transcript: list[str] = []
    deadline = started + timeout_seconds

    def send(command: str) -> None:
        process.stdin.write(command + chr(10))
        process.stdin.flush()

    def read_until(prefix: str) -> str:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError(f"timeout waiting for {prefix}")
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty as error:
                raise ProbeError(f"timeout waiting for {prefix}") from error
            if line is None:
                raise ProbeError(
                    f"engine exited before {prefix}; code={process.poll()}"
                )
            transcript.append(line)
            if line.startswith(prefix):
                return line

    try:
        send("uci")
        read_until("uciok")
        send("setoption name Threads value 3")
        send("setoption name Hash value 16")
        send("setoption name MultiPV value 2")
        send("isready")
        read_until("readyok")
        send("ucinewgame")
        send("position fen " + fen)
        send(go_command)
        best_line = read_until("bestmove ")
        best_move = best_line.split()[1]
        if best_move == "0000":
            raise ProbeError("nonterminal parity case returned bestmove 0000")
        send("quit")
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if process.returncode:
            raise ProbeError(f"engine exited with code {process.returncode}")
    except Exception:
        _stop_owned_process(process)
        raise
    finally:
        if process.stdin:
            process.stdin.close()
    info = next(
        (line for line in reversed(transcript) if line.startswith("info depth ")),
        "",
    )
    return {
        "bestmove": best_move,
        "bestmove_line": best_line,
        "last_info": info,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def probe_pair(
    official: Path,
    embedded: Path,
    network: Path,
    case: dict,
    go_command: str,
    timeout_seconds: float,
) -> dict:
    official_result = run_probe(
        official, official.parent, [], case["fen"], go_command, timeout_seconds
    )
    embedded_result = run_probe(
        embedded,
        ROOT,
        ["--caissa-network", str(network), "--brain", "caissa"],
        case["fen"],
        go_command,
        timeout_seconds,
    )
    return {
        "official": official_result,
        "embedded": embedded_result,
        "same_bestmove": (
            official_result["bestmove"] == embedded_result["bestmove"]
        ),
    }


def write_evidence(path: Path, evidence: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write(chr(10))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", required=True, type=Path)
    parser.add_argument("--embedded", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()

    if args.nodes < 1 or not 1 <= args.repeats <= 20:
        raise ProbeError("nodes must be positive and repeats must be 1..20")
    if not 0.1 <= args.timeout_seconds <= 30:
        raise ProbeError("timeout must be between 0.1 and 30 seconds")
    output = args.output.resolve()
    if output.exists():
        raise ProbeError(f"refusing to overwrite evidence: {output}")
    validation_support.resource_snapshot(output.parent, projected=1_000_000)

    official = args.official.resolve()
    embedded = args.embedded.resolve()
    network = args.network.resolve()
    identities = verify_inputs(official, embedded, network)
    cases = selected_cases(tuple(args.cases or DEFAULT_CASE_IDS))

    evidence = {
        "schema": "eloi-caissa-adapter-parity-v1",
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "runner_sha256": sha256_file(Path(__file__)),
        "caissa_source_commit": CAISSA_COMMIT,
        "settings": {
            "threads": 3,
            "hash_mb": 16,
            "multipv": 2,
            "nodes": args.nodes,
            "repeats": args.repeats,
            "timeout_seconds": args.timeout_seconds,
            "priority": "idle" if os.name == "nt" else "default",
        },
        "identities": identities,
        "cases": [],
    }
    for case in cases:
        row = {"id": case["id"], "fen": case["fen"]}
        row["depth_one"] = probe_pair(
            official, embedded, network, case, "go depth 1",
            args.timeout_seconds
        )
        row["fixed_nodes"] = [
            probe_pair(
                official,
                embedded,
                network,
                case,
                f"go nodes {args.nodes}",
                args.timeout_seconds,
            )
            for _ in range(args.repeats)
        ]
        official_moves = {
            pair["official"]["bestmove"] for pair in row["fixed_nodes"]
        }
        embedded_moves = {
            pair["embedded"]["bestmove"] for pair in row["fixed_nodes"]
        }
        row["fixed_node_move_sets"] = {
            "official": sorted(official_moves),
            "embedded": sorted(embedded_moves),
            "overlap": sorted(official_moves & embedded_moves),
        }
        evidence["cases"].append(row)

    evidence["depth_one_all_match"] = all(
        row["depth_one"]["same_bestmove"] for row in evidence["cases"]
    )
    evidence["fixed_node_exact_all"] = all(
        pair["same_bestmove"]
        for row in evidence["cases"]
        for pair in row["fixed_nodes"]
    )
    evidence["qualification"] = {
        "mechanical_depth_one": evidence["depth_one_all_match"],
        "deeper_fixed_node_gate": "open",
        "note": (
            "Three-thread fixed-node move variance is retained as evidence; "
            "move-set overlap is not a substitute for exact parity."
        ),
    }
    write_evidence(output, evidence)
    print(json.dumps(evidence["qualification"], sort_keys=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
