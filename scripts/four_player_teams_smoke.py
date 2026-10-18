"""Bounded offline lifecycle and self-play smoke for Eloi's Teams UCI extension."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--plies", type=int, default=12)
    parser.add_argument("--movetime", type=int, default=250)
    parser.add_argument("--output", type=Path, default=Path("tmp/four-player-teams-smoke.json"))
    args = parser.parse_args()
    if not 1 <= args.plies <= 200 or not 20 <= args.movetime <= 1000:
        parser.error("bounded smoke requires 1..200 plies and 20..1000 ms")
    engine = args.engine.resolve(strict=True)
    process = subprocess.Popen([str(engine), "--four-player-uci"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="strict", bufsize=1)
    lines: queue.Queue[str | None] = queue.Queue()
    errors: list[str] = []

    def reader() -> None:
        assert process.stdout
        try:
            for line in process.stdout:
                lines.put(line.strip())
        finally:
            lines.put(None)

    def error_reader() -> None:
        assert process.stderr
        for line in process.stderr:
            errors.append(line.strip())

    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=error_reader, daemon=True).start()

    def send(line: str) -> None:
        assert process.stdin
        process.stdin.write(line + "\n")
        process.stdin.flush()

    def receive(prefix: str, timeout: float = 5.0) -> list[str]:
        result = []
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = lines.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise RuntimeError(f"watchdog waiting for {prefix}") from exc
            if line is None:
                raise RuntimeError(f"engine exited before {prefix}: {errors}")
            result.append(line)
            if line.startswith(prefix):
                return result

    evidence: dict = {"schema": 1, "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
                      "mode": "teams", "movetime_ms": args.movetime, "searches": []}
    moves: list[str] = []
    try:
        send("uci")
        handshake = receive("uciok")
        assert any("fourplayerteams" in line for line in handshake)
        assert any("default 3 min 3 max 3" in line for line in handshake)
        send("isready")
        receive("readyok")
        send("d")
        before = receive("info string 4pc-teams")[-1]
        send("position startpos moves xxxx")
        receive("info string position rejected")
        send("d")
        assert receive("info string 4pc-teams")[-1] == before
        send("setoption name Threads value 12")
        receive("info string unsupported option")
        send("go ponder")
        receive("info string go rejected")
        for _ in range(args.plies):
            send("position startpos" + (" moves " + " ".join(moves) if moves else ""))
            send("isready")
            responses = receive("readyok")
            assert not any("rejected" in line for line in responses), responses
            started = time.monotonic()
            send(f"go movetime {args.movetime}")
            responses = receive("bestmove ")
            elapsed = time.monotonic() - started
            move = responses[-1].split()[1]
            if move == "0000":
                assert any("terminal" in line for line in responses), responses
                evidence["terminal"] = responses
                break
            assert re.fullmatch(r"[0-9a-d]{4}[qrbn]?", move), move
            info = next(line for line in responses if line.startswith("info depth "))
            depth = int(info.split()[2])
            assert depth > 0, responses
            evidence["searches"].append({"move": move, "info": info, "wall_ms": round(elapsed * 1000, 3)})
            moves.append(move)
        # Replay all returned moves through authoritative legality before stopping.
        send("position startpos moves " + " ".join(moves))
        send("isready")
        assert not any("rejected" in line for line in receive("readyok"))
        send("d")
        evidence["final_state"] = receive("info string 4pc-teams")[-1]
        send("position startpos")
        send("go infinite")
        send("isready")
        assert not any(line.startswith("bestmove") for line in receive("readyok"))
        send("stop")
        receive("bestmove ", timeout=2.0)
        send("quit")
        process.wait(timeout=3)
        assert process.returncode == 0 and not errors, errors
        evidence.update({"replayed_plies": len(moves), "protocol_failures": 0,
                         "transactional_rejection": True, "cancellation_passed": True})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"PASS: {len(moves)} plies replayed, completed depth on every move, stop/quit clean")
        print(args.output.resolve())
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    main()
