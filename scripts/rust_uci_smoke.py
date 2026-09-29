"""Bounded independent lifecycle smoke test for the Rust laboratory UCI."""

import argparse
import queue
import subprocess
import threading
import time

import chess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    args = parser.parse_args()
    process = subprocess.Popen(
        [args.engine, "--uci"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        creationflags=getattr(subprocess, "IDLE_PRIORITY_CLASS", 0),
    )
    lines = queue.Queue()

    def reader():
        for line in process.stdout:
            lines.put(line.strip())
        lines.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def send(text):
        process.stdin.write(text + "\n")
        process.stdin.flush()

    def wait(prefix, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = lines.get(timeout=max(0.001, deadline - time.monotonic()))
            if line is None:
                raise AssertionError("engine exited before " + prefix)
            if line.startswith(prefix):
                return line
        raise AssertionError("missing " + prefix)

    try:
        send("uci")
        wait("option name Threads type spin default 3 min 3 max 3")
        wait("uciok")
        send("isready")
        wait("readyok")
        send("position startpos moves e2e4 e7e5")
        board = chess.Board()
        board.push_uci("e2e4")
        board.push_uci("e7e5")
        send("go movetime 250")
        reply = wait("bestmove ")
        assert chess.Move.from_uci(reply.split()[1]) in board.legal_moves
        send("position startpos")
        send("go movetime 10000")
        send("isready")
        wait("readyok", 1)
        started = time.monotonic()
        send("stop")
        reply = wait("bestmove ", 1)
        assert time.monotonic() - started < 1
        assert chess.Move.from_uci(reply.split()[1]) in chess.Board().legal_moves
        send("ucinewgame")
        send("position startpos moves e2e5")
        wait("info string position rejected:")
        send("quit")
        assert process.wait(timeout=2) == 0
        assert not process.stderr.read().strip()
        print("Rust UCI lifecycle: handshake, legal search, readiness, stop, reset, rejection, exit PASS")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        thread.join(timeout=1)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


if __name__ == "__main__":
    main()
