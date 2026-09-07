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
import re
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


MOVE_PATTERN = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")


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
    *,
    allow_null_bestmove: bool = False,
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
        try:
            process.stdin.write(command + chr(10))
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise ProbeError(
                f"engine exited before command {command!r}; "
                f"code={process.poll()}"
            ) from error

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
        if best_move == "0000" and not allow_null_bestmove:
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
            try:
                process.stdin.close()
            except OSError:
                pass
        reader.join(timeout=1)
        if process.stdout:
            process.stdout.close()
    info = next(
        (line for line in reversed(transcript) if line.startswith("info depth ")),
        "",
    )
    parsed_info = parse_info(info) if info else None
    return {
        "bestmove": best_move,
        "bestmove_line": best_line,
        "last_info": info,
        "info_strings": [
            line for line in transcript if line.startswith("info string ")
        ],
        "parsed_info": parsed_info,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def parse_info(line: str) -> dict:
    tokens = line.split()
    if len(tokens) < 2 or tokens[0] != "info":
        raise ProbeError("search did not return a parseable UCI info line")

    def value_after(label: str) -> str:
        try:
            index = tokens.index(label)
        except ValueError as error:
            raise ProbeError(f"UCI info omitted {label}") from error
        if index + 1 >= len(tokens):
            raise ProbeError(f"UCI info omitted the value for {label}")
        return tokens[index + 1]

    try:
        score_index = tokens.index("score")
        score_kind = tokens[score_index + 1]
        score_value = int(tokens[score_index + 2])
        depth = int(value_after("depth"))
        nodes = int(value_after("nodes"))
        reported_time = int(value_after("time"))
    except (ValueError, IndexError) as error:
        raise ProbeError("UCI info contains an invalid numeric field") from error
    if score_kind not in ("cp", "mate"):
        raise ProbeError("UCI score must be cp or mate")
    return {
        "depth": depth,
        "score_kind": score_kind,
        "score_value": score_value,
        "nodes": nodes,
        "reported_time_ms": reported_time,
    }


def probe_sanity(
    result: dict, timeout_seconds: float, *, require_info: bool
) -> dict:
    info = result["parsed_info"]
    move_ok = bool(MOVE_PATTERN.fullmatch(result["bestmove"]))
    # Caissa reports its first completed iteration as UCI depth 0.  Treat that
    # documented donor convention as completed only when the search also
    # visited at least one node; negative depth or a zero-node result fails.
    depth_ok = info is not None and info["depth"] >= 0 and info["nodes"] > 0
    counters_ok = info is not None and (
        info["nodes"] >= 0 and info["reported_time_ms"] >= 0
    )
    score_ok = info is not None and (
        abs(info["score_value"]) < 32_000
        if info["score_kind"] == "cp"
        else 0 < abs(info["score_value"]) <= 1_000
    )
    timing_ok = result["elapsed_ms"] <= timeout_seconds * 1000 + 500
    telemetry_ok = (
        depth_ok and counters_ok and score_ok
        if info is not None
        else not require_info
    )
    return {
        "uci_move_shape": move_ok,
        "telemetry_present": info is not None,
        "telemetry_required": require_info,
        "completed_search": depth_ok if info is not None else None,
        "nonnegative_counters": counters_ok if info is not None else None,
        "score_or_mate_sane": score_ok if info is not None else None,
        "within_process_timeout": timing_ok,
        "passed": all((move_ok, telemetry_ok, timing_ok)),
        "legality_note": (
            "Official Caissa emits its root move; the embedded adapter emits "
            "bestmove 0000 unless Eloi's authoritative legal parser accepts it."
        ),
        "depth_note": (
            "Pinned Caissa reports the first completed iteration as depth 0; "
            "a nonnegative depth plus positive node count is required."
        ),
    }


def probe_pair(
    official: Path,
    embedded: Path,
    network: Path,
    case: dict,
    go_command: str,
    timeout_seconds: float,
    *,
    require_info: bool,
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
        "official_sanity": probe_sanity(
            official_result, timeout_seconds, require_info=require_info
        ),
        "embedded_sanity": probe_sanity(
            embedded_result, timeout_seconds, require_info=require_info
        ),
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
            args.timeout_seconds, require_info=False
        )
        row["fixed_nodes"] = [
            probe_pair(
                official,
                embedded,
                network,
                case,
                f"go nodes {args.nodes}",
                args.timeout_seconds,
                require_info=True,
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
        row["fixed_node_distribution"] = {
            "official": {
                move: sum(
                    pair["official"]["bestmove"] == move
                    for pair in row["fixed_nodes"]
                )
                for move in sorted(official_moves)
            },
            "embedded": {
                move: sum(
                    pair["embedded"]["bestmove"] == move
                    for pair in row["fixed_nodes"]
                )
                for move in sorted(embedded_moves)
            },
            "exact_pair_rate": (
                sum(
                    pair["same_bestmove"]
                    for pair in row["fixed_nodes"]
                )
                / len(row["fixed_nodes"])
            ),
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
    evidence["depth_one_sanity_all"] = all(
        row["depth_one"]["official_sanity"]["passed"]
        and row["depth_one"]["embedded_sanity"]["passed"]
        for row in evidence["cases"]
    )
    evidence["fixed_node_sanity_all"] = all(
        pair["official_sanity"]["passed"]
        and pair["embedded_sanity"]["passed"]
        for row in evidence["cases"]
        for pair in row["fixed_nodes"]
    )
    evidence["qualification"] = {
        "mechanical_depth_one": (
            evidence["depth_one_all_match"]
            and evidence["depth_one_sanity_all"]
        ),
        "deeper_three_thread_sanity": (
            evidence["fixed_node_sanity_all"]
        ),
        "passed": (
            evidence["depth_one_all_match"]
            and evidence["depth_one_sanity_all"]
            and evidence["fixed_node_sanity_all"]
        ),
        "note": (
            "Depth-one best moves are exact. Deeper three-thread runs gate "
            "legal adapter output, score/mate sanity, timing, and successful "
            "completion; best-move equality and distributions are retained "
            "as observations because scheduling is nondeterministic."
        ),
    }
    write_evidence(output, evidence)
    print(json.dumps(evidence["qualification"], sort_keys=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
