#!/usr/bin/env python3
"""User-requested 33/33/33 + one human exhibition; never a release gate.

Uses existing Eloi binaries, local PNG assets and python-chess UCI transport.
No downloads, training, production modifications, or Stockfish backend.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import engine_lab as lab

chess = lab.chess
ROOT = lab.ROOT
WORK = ROOT / "tmp/abc100"
PROTOCOL = ROOT / "data/nnue_abc100_protocol.json"
HTML = ROOT / "scripts/abc100_board.html"
EXPECTED = {
    "v2.0.0": ("tmp/search-recovery/baseline/Eloi.exe", lab.OFFICIAL_V2_SHA256),
    "A": ("tmp/nnue-fresh-data/candidates/A/build/Eloi.exe", "4D3589577D495D2CBA68473385D04AF0DF3125E29F1CBB076B5197F1AA6DE9A9"),
    "B": ("tmp/nnue-fresh-data/candidates/B/build/Eloi.exe", "2F12FCA565C900F3B53A40F17DF4F59E95AFCDBFFE283FFCDF4F63CD04BE9274"),
    "C": ("tmp/nnue-fresh-data/candidates/C/build/Eloi.exe", "E2F7CE21B59D56BEBF1DF00334CC60C6032869648D86D2D3DF834021D046C6EA"),
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest().upper()


def immutable(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")


def schedule(positions):
    """Same 16 mirrored openings + one White game for each candidate.

    Rotate candidate order by round to spread temporal machine effects.
    """
    if len(positions) < 17:
        raise ValueError("17 openings required")
    rows = []
    for index in range(33):
        names = "ABC"[index % 3:] + "ABC"[:index % 3]
        for name in names:
            rows.append({"game": len(rows) + 1, "candidate": name,
                         "candidate_game": index + 1, "opening": index // 2,
                         "candidate_white": index % 2 == 0,
                         "fen": positions[index // 2]["fen"]})
    return rows


def summarize(rows):
    result = {}
    for name in "ABC":
        subset = [r for r in rows if r["candidate"] == name]
        counts = collections.Counter(r["label"] for r in subset)
        w, d, loss = (counts[k] for k in ("win", "draw", "loss"))
        valid = not any(r.get("protocol_failure") for r in subset)
        result[name] = {"games": len(subset), "wins": w, "draws": d, "losses": loss,
                        "non_losses": w + d, "non_loss_rate": (w + d) / len(subset) if subset else None,
                        "points": w + d / 2, "score": (w + d / 2) / len(subset) if subset else None,
                        "passed": len(subset) == 33 and w + d >= 17 and valid,
                        "complete": len(subset) == 33, "protocol_valid": valid,
                        "color_split": {color: dict(collections.Counter(
                            r["label"] for r in subset if r["candidate_white"] == white))
                            for color, white in (("white", True), ("black", False))}}
    return result


def resource_check():
    def total(path):
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    training = total(ROOT / "tmp/nnue-fresh-data")
    temporary = total(ROOT / "tmp")
    own = total(WORK) if WORK.exists() else 0
    free = shutil.disk_usage(ROOT).free
    if training > 7 * 1024**3 or temporary + 100_000_000 > 10_000_000_000 or free < 5_100_000_000 or own > 90_000_000:
        raise RuntimeError("Storage reservation/cap exceeded; no deletion attempted")
    return {"training_bytes": training, "repo_tmp_bytes": temporary,
            "match_bytes": own, "free_bytes": free, "reserved_new_bytes": 100_000_000}


def prepare():
    identities = {}
    for name, (relative, expected) in EXPECTED.items():
        actual = lab.sha256(ROOT / relative)
        if actual != expected:
            raise ValueError(f"{name} executable identity mismatch")
        identities[name] = {"path": relative, "sha256": actual}
    reserve = ROOT / "data/search_recovery/reserve.json"
    positions = read(reserve)["positions"][:17]
    for row in positions:
        board = chess.Board(row["fen"])
        if not board.is_valid() or board.is_game_over(claim_draw=True):
            raise ValueError("Invalid or terminal opening")
    document = {
        "schema": 1, "experiment": "abc100-user-nonloss-v1", "created_utc": lab.utc_now(),
        "purpose": "Exploratory user-requested match; failed correctness gates remain in force for release",
        "total_games": 100, "automated_games": 99, "human_games": 1,
        "pass_rule": {"metric": "non_loss_rate", "strictly_greater_than": 0.5,
                      "games_per_candidate": 33, "minimum_wins_plus_draws": 17, "maximum_losses": 16},
        "binaries": identities, "source_checkpoint": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scripts": {str(p.relative_to(ROOT)): lab.sha256(p) for p in
                    (Path(__file__), HTML, ROOT / "scripts/engine_lab.py")},
        "openings": {"source": str(reserve.relative_to(ROOT)), "sha256": lab.sha256(reserve),
                     "selection": "first 17 frozen reserve positions; original sealed final set unused",
                     "same_schedule_for_each_candidate": True, "white_games_each": 17, "black_games_each": 16},
        "schedule": schedule(positions),
        "settings": {"movetime_ms": 250, "threads": 3, "hash_mb": 32,
                     "own_book": False, "noise": 0, "move_overhead_ms": 0,
                     "max_absolute_ply": 200, "claim_draw": True, "priority": "Windows Idle",
                     "watchdog_seconds": 2.5, "engine_timeout_seconds": 5,
                     "maximum_runtime_hours": 4, "simultaneous_searches": 1},
        "human": {"game": 100, "start_fen": chess.STARTING_FEN,
                  "color": "chosen before play; default White", "human_clock": "untimed",
                  "engine_movetime_ms": 250, "assistance": "permitted casual local exhibition; potentially assisted",
                  "excluded_from_candidate_scores": True, "no_automatic_moves_or_resignation_for_user": True},
        "omitted": ["60-game development pilot", "60-game confirmation pilot", "300-game final", "blend candidates"],
        "release_authorized": False, "production_unchanged": True,
        "preflight": resource_check(),
    }
    immutable(PROTOCOL, document)
    print(json.dumps({"protocol": str(PROTOCOL), "sha256": lab.sha256(PROTOCOL)}), flush=True)


def verify_protocol(protocol):
    for name, identity in protocol["binaries"].items():
        if identity["sha256"] != EXPECTED[name][1] or lab.sha256(ROOT / identity["path"]) != identity["sha256"]:
            raise ValueError(f"{name} executable changed")
    for relative, expected in protocol["scripts"].items():
        if lab.sha256(ROOT / relative) != expected:
            raise ValueError(f"Frozen runner changed: {relative}")
    if protocol["pass_rule"]["minimum_wins_plus_draws"] != 17 or len(protocol["schedule"]) != 99:
        raise ValueError("Protocol count/threshold mismatch")


def engine_start(path):
    kwargs = {"cwd": str(WORK)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
    engine = chess.engine.SimpleEngine.popen_uci(
        [str(path), "--uci", "--move-overhead", "0"], timeout=5, **kwargs)
    lab.configure(engine)
    return engine


def info_json(info):
    score = info.get("score")
    return {"depth": info.get("depth"), "nodes": info.get("nodes"),
            "score_white_cp": score.white().score(mate_score=30000) if score else None,
            "pv": [m.uci() for m in info.get("pv", [])]}


def game_pgn(game):
    pgn = chess.pgn.Game()
    board = chess.Board(game["fen"])
    pgn.setup(board)
    pgn.headers.update({"Event": "Eloi ABC100 exploratory exhibition", "Site": "local",
                        "Round": str(game["game"]), "Result": game.get("result", "*"),
                        "White": game["candidate"] if game["candidate_white"] else "Eloi v2.0.0",
                        "Black": "Eloi v2.0.0" if game["candidate_white"] else game["candidate"],
                        "MoveTimeMs": "250", "Termination": game.get("termination", "unterminated")})
    if game["candidate"] == "Human":
        pgn.headers["Assistance"] = "Permitted; potentially assisted human exhibition"
    node = pgn
    for text in game["moves"]:
        move = chess.Move.from_uci(text)
        if move not in board.legal_moves:
            raise ValueError("Illegal move in saved game")
        board.push(move)
        node = node.add_variation(move)
    return str(pgn) + "\n\n"


def restore_board(game):
    board = chess.Board(game["fen"])
    for move in game["moves"]:
        board.push_uci(move)
    return board


class Match:
    def __init__(self):
        self.protocol = read(PROTOCOL)
        verify_protocol(self.protocol)
        self.protocol_hash = lab.sha256(PROTOCOL)
        WORK.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.search_lock = threading.Lock()
        self.human_waiting = threading.Event()
        self.engines = {}
        self.rows = []
        self.active = None
        self.status = "ready"
        self.error = None
        self.started = time.monotonic()
        self.token = secrets.token_urlsafe(32)
        self.automated_started = False
        for index, plan in enumerate(self.protocol["schedule"]):
            path = WORK / f"game-{index + 1:03d}.json"
            if path.exists():
                row = read(path)
                if row.get("protocol_sha256") != self.protocol_hash or any(row[k] != plan[k] for k in plan):
                    raise ValueError("Saved game identity mismatch")
                game_pgn(row)
                self.rows.append(row)
            elif any((WORK / f"game-{later:03d}.json").exists() for later in range(index + 2, 100)):
                raise ValueError("Saved results have a gap")
        self.human = read(WORK / "human.json") if (WORK / "human.json").exists() else {
            "game": 100, "candidate": "Human", "candidate_white": True,
            "fen": chess.STARTING_FEN, "moves": [], "started": False, "result": "*",
            "protocol_sha256": self.protocol_hash, "thinking": False}
        if self.human["protocol_sha256"] != self.protocol_hash:
            raise ValueError("Human game protocol mismatch")
        restore_board(self.human)
        self.human["thinking"] = False
        self.event("server_started", completed=len(self.rows))

    def event(self, kind, **fields):
        item = {"utc": lab.utc_now(), "kind": kind, **fields}
        with self.lock:
            with (WORK / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(item) + "\n")
        print(json.dumps(item), flush=True)

    def get_engine(self, name):
        if name not in self.engines:
            self.engines[name] = engine_start(ROOT / self.protocol["binaries"]["v2.0.0" if name == "human_opponent" else name]["path"])
        return self.engines[name]

    def play(self, name, board, game_id, human=False):
        # No concurrent searches: a human reply has priority at the next ply.
        if not human:
            while self.human_waiting.is_set():
                time.sleep(0.02)
        with self.search_lock:
            engine = self.get_engine(name)
            start = time.monotonic()
            result = engine.play(board, chess.engine.Limit(time=0.25), game=game_id,
                                 info=chess.engine.INFO_ALL)
            elapsed = time.monotonic() - start
        if result.move is None or result.move not in board.legal_moves:
            raise ValueError("Engine returned illegal/missing move")
        if elapsed > 2.5:
            raise TimeoutError(f"Engine deadline watchdog exceeded: {elapsed:.3f}s")
        return result.move, {**info_json(result.info), "elapsed_seconds": elapsed}

    def finish_if_terminal(self, game, board):
        outcome = board.outcome(claim_draw=True)
        if outcome is None and board.ply() < 200:
            return False
        game["result"] = outcome.result() if outcome else "1/2-1/2"
        game["termination"] = outcome.termination.name if outcome else "200 absolute plies; adjudicated draw"
        game["label"] = "draw" if outcome is None or outcome.winner is None else (
            "win" if outcome.winner == game["candidate_white"] else "loss")
        game["finished_utc"] = lab.utc_now()
        return True

    def persist_human(self):
        lab.atomic_json(WORK / "human.json", self.human)
        if self.human["result"] != "*" and not (WORK / "game-100.json").exists():
            row = {**self.human, "pgn": game_pgn(self.human)}
            immutable(WORK / "game-100.json", row)
            self.event("human_complete", result=row["result"], termination=row.get("termination"))

    def run_automated(self):
        try:
            self.status = "running"
            for plan in self.protocol["schedule"][len(self.rows):]:
                if time.monotonic() - self.started > 4 * 3600:
                    raise TimeoutError("Four-hour automated runtime budget reached; checkpoint preserved")
                resource_check()
                active_path = WORK / "active.json"
                saved = read(active_path) if active_path.exists() else None
                if saved and saved["game"] == plan["game"]:
                    if saved.get("protocol_sha256") != self.protocol_hash or any(saved[k] != plan[k] for k in plan):
                        raise ValueError("Active game identity mismatch")
                    game = saved
                    self.event("game_resumed", game=plan["game"], moves=len(game["moves"]))
                else:
                    game = {**plan, "moves": [], "result": "*", "started_utc": lab.utc_now(),
                            "protocol_sha256": self.protocol_hash}
                self.active = game
                board = restore_board(game)
                self.event("game_started", game=game["game"], candidate=game["candidate"],
                           candidate_game=game["candidate_game"], candidate_white=game["candidate_white"])
                lab.atomic_json(active_path, game)
                while not self.finish_if_terminal(game, board):
                    name = game["candidate"] if board.turn == game["candidate_white"] else "v2.0.0"
                    move, info = self.play(name, board, game["game"])
                    san = board.san(move)
                    with self.lock:
                        board.push(move)
                        game["moves"].append(move.uci())
                        game["last_info"] = info
                        lab.atomic_json(active_path, game)
                    self.event("engine_move", game=game["game"], engine=name, uci=move.uci(), san=san, **info)
                game["pgn"] = game_pgn(game)
                immutable(WORK / f"game-{game['game']:03d}.json", game)
                with self.lock:
                    self.rows.append(dict(game))
                    self.active = None
                lab.atomic_json(WORK / "summary.json", self.summary())
                self.event("game_complete", game=game["game"], candidate=game["candidate"],
                           result=game["result"], label=game["label"], standings=summarize(self.rows))
            self.status = "automated_complete"
            self.export()
            self.event("automated_complete", standings=summarize(self.rows))
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"
            self.status = "paused_error"
            self.event("automated_error", error=self.error)
        finally:
            # The human opponent is independent and remains usable.
            with self.search_lock:
                for name in list(self.engines):
                    if name != "human_opponent":
                        engine = self.engines.pop(name)
                        try:
                            engine.quit()
                        except Exception:
                            engine.close()
            lab.atomic_json(WORK / "summary.json", self.summary())

    def start_automated(self):
        with self.lock:
            if self.automated_started:
                return
            self.automated_started = True
            threading.Thread(target=self.run_automated, daemon=True).start()

    def human_action(self, action, body):
        with self.lock:
            if action == "start":
                if self.human["started"]:
                    raise ValueError("Only one human game; already started")
                if body.get("color") not in ("white", "black"):
                    raise ValueError("Choose White or Black")
                self.human["candidate_white"] = body["color"] == "white"
                self.human["started"] = True
                self.event("human_started", color=body["color"], potentially_assisted=True)
            elif action == "move":
                board = restore_board(self.human)
                if not self.human["started"] or self.human["result"] != "*" or self.human["thinking"] or board.turn != self.human["candidate_white"]:
                    raise ValueError("Not your turn")
                if body.get("fen") != board.fen():
                    raise ValueError("Board changed; refresh before moving")
                move = chess.Move.from_uci(body.get("move", ""))
                if move not in board.legal_moves:
                    raise ValueError("Illegal move")
                san = board.san(move)
                self.human["moves"].append(move.uci())
                board.push(move)
                self.finish_if_terminal(self.human, board)
                self.event("human_move", uci=move.uci(), san=san)
            elif action == "resign":
                if not self.human["started"] or self.human["result"] != "*" or self.human["thinking"]:
                    raise ValueError("Cannot resign now")
                self.human.update(result="0-1" if self.human["candidate_white"] else "1-0",
                                  label="loss", termination="Human resignation", finished_utc=lab.utc_now())
            else:
                raise ValueError("Unknown action")
            self.persist_human()
        self.maybe_human_reply()

    def maybe_human_reply(self):
        with self.lock:
            board = restore_board(self.human)
            if not self.human["started"] or self.human["result"] != "*" or self.human["thinking"] or board.turn == self.human["candidate_white"] or self.human.get("error"):
                return
            self.human["thinking"] = True
            self.human_waiting.set()
        threading.Thread(target=self.human_reply, daemon=True).start()

    def human_reply(self):
        try:
            board = restore_board(self.human)
            move, info = self.play("human_opponent", board, "human-game-100", human=True)
            san = board.san(move)
            with self.lock:
                self.human["moves"].append(move.uci())
                board.push(move)
                self.human["last_info"] = info
                self.finish_if_terminal(self.human, board)
            self.event("human_opponent_move", uci=move.uci(), san=san, **info)
        except Exception as error:
            with self.lock:
                self.human["error"] = f"{type(error).__name__}: {error}"
            self.event("human_opponent_error", error=self.human["error"])
        finally:
            with self.lock:
                self.human["thinking"] = False
                self.persist_human()
            self.human_waiting.clear()

    def summary(self):
        with self.lock:
            return {"protocol_sha256": self.protocol_hash, "automated_status": self.status,
                    "automated_completed": len(self.rows), "standings": summarize(self.rows),
                    "human_completed": self.human["result"] != "*", "error": self.error,
                    "release_qualified": False}

    def state(self):
        with self.lock:
            board = restore_board(self.human)
            game = chess.pgn.Game.from_board(board)
            return {**self.summary(), "human": {**self.human, "current_fen": board.fen(),
                    "pieces": {chess.square_name(s): ("w" if p.color else "b") + p.symbol().upper()
                               for s, p in board.piece_map().items()},
                    "legal_moves": [m.uci() for m in board.legal_moves()],
                    "turn": "white" if board.turn else "black", "pgn": game_pgn(self.human)},
                    "active": {k: v for k, v in (self.active or {}).items() if k != "pgn"}}

    def export(self):
        with self.lock:
            document = {**self.summary(), "results": self.rows, "resources": resource_check()}
            path = WORK / "automated-results.json"
            if not path.exists():
                immutable(path, document)
            pgn_path = WORK / "automated-games.pgn"
            if not pgn_path.exists():
                with pgn_path.open("x", encoding="utf-8") as stream:
                    stream.write("".join(r["pgn"] for r in self.rows))
            manifest = WORK / "automated-evidence.json"
            if not manifest.exists():
                immutable(manifest, {"protocol_sha256": self.protocol_hash,
                    "files": {p.name: lab.sha256(p) for p in
                              [path, pgn_path, *sorted(WORK.glob("game-0*.json"))]},
                    "created_utc": lab.utc_now()})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, content, mime="application/json"):
        data = content if isinstance(content, bytes) else (json.dumps(content).encode() if mime == "application/json" else content.encode())
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.valid_host():
            return self.respond(403, {"error": "Local host only"})
        if self.path == "/":
            return self.respond(200, HTML.read_text(encoding="utf-8").replace("__TOKEN__", self.server.match.token), "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self.respond(200, self.server.match.state())
        if self.path.startswith("/pieces/") and self.path.removeprefix("/pieces/") in {
                c + p + ".png" for c in "wb" for p in "KQRBNP"}:
            return self.respond(200, (ROOT / "assets/chess_maestro_bw" / self.path.removeprefix("/pieces/")).read_bytes(), "image/png")
        return self.respond(404, {"error": "Not found"})

    def do_POST(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if not self.valid_host() or self.headers.get("Origin") != origin or not secrets.compare_digest(self.headers.get("X-Match-Token", ""), self.server.match.token):
            return self.respond(403, {"error": "Local authenticated request required"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(size))
            self.server.match.human_action(self.path.removeprefix("/api/"), body)
            self.respond(200, self.server.match.state())
        except (ValueError, TypeError, KeyError) as error:
            self.respond(400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--run-automated", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.prepare:
        prepare()
    if args.serve:
        match = Match()
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        server.match = match
        print(f"GUI http://127.0.0.1:{args.port}/ | logs {WORK}", flush=True)
        if args.run_automated:
            match.start_automated()
        match.maybe_human_reply()
        server.serve_forever()


if __name__ == "__main__":
    main()
