#!/usr/bin/env python3
"""Independently replay and verify an E4 screen."""
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.deps/lichess-bot/.venv/Lib/site-packages'))
import chess.pgn
def main():
 p=argparse.ArgumentParser(); p.add_argument('--results',type=Path,required=True); p.add_argument('--pgn',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
 rows=json.loads(a.results.read_text(encoding='utf-8'))['results']; games=[]; failures=[]
 with a.pgn.open(encoding='utf-8') as stream:
  while game:=chess.pgn.read_game(stream): games.append(game)
 if len(games)!=len(rows): failures.append(f'PGN count {len(games)} != result count {len(rows)}')
 for index,(game,row) in enumerate(zip(games,rows),1):
  board=game.board()
  try:
   for move in game.mainline_moves():
    if move not in board.legal_moves: raise ValueError(f'illegal move {move.uci()}')
    board.push(move)
  except Exception as error: failures.append(f'game {index}: {error}'); continue
  if board.fen()!=row['final_fen']: failures.append(f'game {index}: final FEN mismatch')
  if game.headers.get('ReserveIndex')!=str(row['reserve_index']): failures.append(f'game {index}: reserve mismatch')
  score=row['score']; white=row['candidate_white']
  expected={'1/2-1/2','*'} if score==.5 else {('1-0' if (score==1)==white else '0-1')}
  if game.headers.get('Result') not in expected: failures.append(f'game {index}: result mismatch')
 report={'schema':'eloi-e4-screen-replay-v1','passed':not failures,'games':len(games),'failures':failures}
 a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(report,sort_keys=True)); return 0 if report['passed'] else 1
if __name__=='__main__': raise SystemExit(main())
