#!/usr/bin/env python3
"""Mine C0/teacher move disagreements and label child positions offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps/lichess-bot/.venv/Lib/site-packages"))
import chess
import chess.engine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--c0", type=pathlib.Path, required=True)
    parser.add_argument("--teacher", type=pathlib.Path, required=True)
    parser.add_argument("--evaluations", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--positions", type=int, default=2_000)
    parser.add_argument("--nodes", type=int, default=10_000)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    rows = []
    with args.evaluations.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if item.get("partition") == "train" and item.get("score_type") == "cp":
                rows.append(item)
            if len(rows) >= args.positions:
                break
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with chess.engine.SimpleEngine.popen_uci([str(args.c0), "--uci"]) as c0, chess.engine.SimpleEngine.popen_uci(str(args.teacher)) as teacher, args.output.open("x", encoding="utf-8") as output:
        for index, item in enumerate(rows, 1):
            board = chess.Board(item["fen"])
            c0_info = c0.analyse(board, chess.engine.Limit(nodes=args.nodes))
            teacher_info = teacher.analyse(board, chess.engine.Limit(nodes=args.nodes))
            c0_move = c0_info["pv"][0]
            teacher_move = teacher_info["pv"][0]
            if c0_move == teacher_move:
                continue
            for role, move in (("teacher", teacher_move), ("c0", c0_move)):
                child = board.copy(stack=False)
                child.push(move)
                child_info = teacher.analyse(child, chess.engine.Limit(nodes=args.nodes))
                pov = child_info["score"].pov(chess.WHITE).score(mate_score=20_000)
                record_id = hashlib.sha256(f"{item['record_id']}\0{role}\0{move.uci()}".encode()).hexdigest()
                output.write(json.dumps({"id":record_id,"source_id":item["record_id"],"role":role,"move":move.uci(),"fen":child.fen(),"score_white_cp":int(pov),"weight":3.0 if role=="teacher" else 2.0}, sort_keys=True) + "\n")
                output.flush()
                written += 1
            print(json.dumps({"scanned":index,"hard_rows":written}), flush=True)
    print(json.dumps({"status":"complete","scanned":len(rows),"hard_rows":written,"nodes":args.nodes}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
