#!/usr/bin/env python3
"""Run a small mirrored native-Eloi E4 versus E2 screen."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.deps/lichess-bot/.venv/Lib/site-packages'))
import chess, chess.engine, chess.pgn

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()
def atomic(path,value):
 p=Path(path); q=p.with_suffix(p.suffix+'.new'); q.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8'); q.replace(p)
def command(path): return [str(Path(path).resolve()),'--uci','--brain','eloi']
def configure(engine):
 values={k:v for k,v in (('Threads',3),('Hash',32),('OwnBook',False),('Noise',0)) if k in engine.options}
 if values: engine.configure(values)
def play(candidate_path,baseline_path,row,nodes,max_plies):
 flags=getattr(subprocess,'IDLE_PRIORITY_CLASS',0) if os.name=='nt' else 0
 c=chess.engine.SimpleEngine.popen_uci(command(candidate_path),timeout=30,creationflags=flags)
 b=chess.engine.SimpleEngine.popen_uci(command(baseline_path),timeout=30,creationflags=flags)
 board=chess.Board(row['fen']); started=time.monotonic()
 try:
  configure(c); configure(b)
  while not board.is_game_over(claim_draw=True) and board.ply()<max_plies:
   engine=c if board.turn==row['candidate_white'] else b
   result=engine.play(board,chess.engine.Limit(nodes=nodes))
   if result.move is None or result.move not in board.legal_moves: raise RuntimeError(f'illegal or missing move: {result.move}')
   board.push(result.move)
 finally:
  c.quit(); b.quit()
 outcome=board.outcome(claim_draw=True)
 score=.5 if outcome is None or outcome.winner is None else (1. if outcome.winner==row['candidate_white'] else 0.)
 game=chess.pgn.Game.from_board(board); game.headers['CandidateColor']='white' if row['candidate_white'] else 'black'; game.headers['ReserveIndex']=str(row['reserve_index'])
 return {**row,'score':score,'plies':board.ply(),'final_fen':board.fen(),'elapsed_seconds':round(time.monotonic()-started,3)},game
def main():
 p=argparse.ArgumentParser(); p.add_argument('--candidate',type=Path,required=True); p.add_argument('--baseline',type=Path,required=True); p.add_argument('--reserve',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--nodes',type=int,default=10000); p.add_argument('--max-plies',type=int,default=200); p.add_argument('--start-index',type=int,default=240); p.add_argument('--pairs',type=int,default=10); a=p.parse_args()
 if a.output.exists(): raise FileExistsError(a.output)
 a.output.mkdir(parents=True)
 positions=json.loads(a.reserve.read_text(encoding='utf-8'))['positions']; schedule=[]
 indices=list(range(a.start_index,a.start_index+a.pairs))
 for pair,index in enumerate(indices,1):
  for white in (True,False): schedule.append({'game':len(schedule)+1,'pair':pair,'reserve_index':index,'candidate_white':white,'fen':positions[index]['fen']})
 expected_games=2*a.pairs
 protocol={'schema':'eloi-e4-screen-v1','games':expected_games,'mirrored':True,'nodes':a.nodes,'threads_per_engine':3,'hash_mb':32,'candidate_sha256':sha(a.candidate),'baseline_sha256':sha(a.baseline),'reserve_sha256':sha(a.reserve),'runner_sha256':sha(Path(__file__)),'indices':indices,'schedule':schedule}
 atomic(a.output/'protocol.json',protocol); results=[]; failures=[]
 for row in schedule:
  try:
   result,game=play(a.candidate,a.baseline,row,a.nodes,a.max_plies); results.append(result)
   with (a.output/'games.pgn').open('a',encoding='utf-8',newline='\n') as stream: print(game,file=stream,end='\n\n')
  except Exception as error: failures.append({**row,'error':f'{type(error).__name__}: {error}'})
  wins=sum(x['score']==1 for x in results); draws=sum(x['score']==.5 for x in results); losses=sum(x['score']==0 for x in results)
  evidence={'schema':'eloi-e4-screen-results-v1','complete':len(results)+len(failures)==expected_games,'results':results,'protocol_failures':failures,'summary':{'completed':len(results),'wins':wins,'draws':draws,'losses':losses,'score_points':wins+draws/2,'score_percent':100*(wins+draws/2)/expected_games}}
  atomic(a.output/'results.json',evidence); print(json.dumps({'game':row['game'],**evidence['summary'],'failures':len(failures)}),flush=True)
  if failures:return 2
 evidence['passed']=evidence['summary']['score_percent']>=50.; atomic(a.output/'results.json',evidence); return 0 if evidence['passed'] else 1
if __name__=='__main__': raise SystemExit(main())
