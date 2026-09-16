#!/usr/bin/env python3
"""Analyze queued native Eloi Lichess journals without touching live play."""
from __future__ import annotations
import argparse, ctypes, hashlib, json, os, statistics, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.deps/lichess-bot/.venv/Lib/site-packages'))
import chess, chess.engine
NETWORK_SHA='615CEF8D25D8BB3ACE53FD5CC4DED7546F0D1C8FCE10676FD83C864421262B5B'

def default_root(): return Path(os.environ.get('LOCALAPPDATA',ROOT/'tmp'))/'Eloi'/'autopsy'
def sha(path):
 d=hashlib.sha256();
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest().upper()
def atomic(path,value):
 tmp=path.with_suffix(path.suffix+'.new'); tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8'); tmp.replace(path)
def idle():
 if os.name=='nt': ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x40)
def process_alive(pid):
 if os.name!='nt': return True
 handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
 if handle: ctypes.windll.kernel32.CloseHandle(handle); return True
 return False
def live_game_active(root):
 lock=root/'active-game.lock'
 if not lock.exists(): return False
 try:
  lines=lock.read_text(encoding='utf-8').splitlines(); return len(lines)<2 or process_alive(int(lines[1]))
 except (OSError,ValueError): return True

def cp(info,turn): return info['score'].pov(turn).score(mate_score=30000)

def analyse_game(journal,engine,nodes):
 report={'schema':'eloi-lichess-autopsy-v1','game_id':journal['game_id'],'url':journal['url'],'version':journal['version'],'executable_sha256':journal['executable_sha256'],'network_sha256':journal['network_sha256'],'playing_model_role':journal['playing_model_role'],'explicit_notice':'This production/legacy game was not played by EPV2 unless its exact artifact identity is recorded.','variant':journal['variant'],'status':journal['status'],'incidents':[],'suggested_regressions':[]}
 if journal['variant']!='standard': report['analysis_status']='variant_bypassed'; return report
 board=chess.Board(); tokens=journal.get('moves','').split(); searches={x.get('moves_before',''):x for x in journal.get('searches',[])}; bot_white=journal.get('bot_color')=='white'; first=None
 for ply,text in enumerate(tokens):
  try: move=chess.Move.from_uci(text)
  except ValueError: report['analysis_status']='illegal_journal_move'; report['illegal_ply']=ply+1; return report
  if move not in board.legal_moves: report['analysis_status']='illegal_journal_move'; report['illegal_ply']=ply+1; return report
  ours=board.turn==bot_white
  if ours:
   key=' '.join(tokens[:ply]); telemetry=searches.get(key,{})
   best=engine.analyse(board,chess.engine.Limit(nodes=nodes)); best_move=best['pv'][0]; best_cp=cp(best,board.turn)
   child=board.copy(stack=False); child.push(move); played=-cp(engine.analyse(child,chess.engine.Limit(nodes=nodes)),child.turn); loss=max(0,best_cp-played)
   kind=[]
   if board.gives_check(best_move): kind.append('missed_check')
   if board.is_capture(best_move): kind.append('missed_capture')
   if best_move.promotion: kind.append('missed_promotion')
   if abs(best_cp)>=29000: kind.append('mate_threat')
   if not board.is_capture(best_move) and not board.gives_check(best_move) and not best_move.promotion and loss>=150: kind.append('quiet_defense')
   if loss>=150:
    incident={'ply':ply+1,'fen':board.fen(),'played':text,'teacher_move':best_move.uci(),'teacher_cp':best_cp,'played_cp':played,'loss_cp':loss,'categories':kind,'telemetry':telemetry}
    report['incidents'].append(incident)
    if first is None: first=incident
    report['suggested_regressions'].append({'status':'quarantined_proposal','fen':board.fen(),'avoid':text,'candidate':best_move.uci(),'reason':'teacher_loss_at_least_150cp'})
   elapsed=telemetry.get('elapsed_ms')
   if elapsed is not None and loss>=150 and elapsed<100: report['incidents'].append({'ply':ply+1,'kind':'rushed_critical_move','elapsed_ms':elapsed,'loss_cp':loss})
  board.push(move)
 report['analysis_status']='complete'; report['first_significant_loss']=first; times=[x.get('elapsed_ms') for x in journal.get('searches',[]) if isinstance(x.get('elapsed_ms'),int)]; report['move_time_ms']={'median':statistics.median(times) if times else None,'maximum':max(times) if times else None}; report['fallback_count']=sum('fallback' in x.get('brain_route','') for x in journal.get('searches',[])); return report

def markdown(r):
 lines=[f"# Eloi Lichess autopsy: {r['game_id']}",'',r['explicit_notice'],'',f"- Game: {r['url']}",f"- Playing binary: Eloi {r['version']} (`{r['executable_sha256']}`)",f"- Status: {r['analysis_status']}",f"- Variant: {r['variant']}"]
 first=r.get('first_significant_loss');
 if first: lines += ['',f"First ≥150 cp loss: ply {first['ply']}, `{first['played']}` instead of `{first['teacher_move']}` ({first['loss_cp']} cp)."]
 else: lines += ['','No ≥150 cp teacher disagreement was found at the configured node budget.']
 lines += ['',f"Recorded incidents: {len(r.get('incidents',[]))}",f"Quarantined regression proposals: {len(r.get('suggested_regressions',[]))}",'']; return '\n'.join(lines)

def run_once(root,engine_path,network,nodes):
 if live_game_active(root): return {'status':'paused_active_game','processed':0}
 queue=root/'queue'; reports=root/'reports'; reports.mkdir(parents=True,exist_ok=True); files=sorted(queue.glob('*.json')) if queue.exists() else []
 if sha(network)!=NETWORK_SHA: raise RuntimeError('Caissa 1.25 network hash mismatch')
 engine=chess.engine.SimpleEngine.popen_uci([str(engine_path),'--uci','--brain','caissa','--caissa-network',str(network)],cwd=str(ROOT),creationflags=getattr(__import__('subprocess'),'IDLE_PRIORITY_CLASS',0)); engine.configure({'Threads':3,'Hash':32}); processed=0
 try:
  for path in files:
   out=reports/(path.stem+'.json')
   if out.exists(): continue
   journal=json.loads(path.read_text(encoding='utf-8')); report=analyse_game(journal,engine,nodes); atomic(out,report); (reports/(path.stem+'.md')).write_text(markdown(report),encoding='utf-8'); processed+=1
 finally: engine.quit()
 entries=[]
 for path in sorted(p for p in reports.glob('*.json') if p.name!='index.json'):
  r=json.loads(path.read_text()); entries.append({'game_id':r['game_id'],'status':r['analysis_status'],'incidents':len(r.get('incidents',[])),'version':r['version'],'playing_model_role':r['playing_model_role']})
 atomic(reports/'index.json',{'schema':'eloi-lichess-autopsy-index-v1','games':entries}); return {'status':'complete','processed':processed,'total_reports':len(entries)}

def main():
 p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=default_root()); p.add_argument('--engine',type=Path,required=True); p.add_argument('--network',type=Path,required=True); p.add_argument('--nodes',type=int,default=10000); p.add_argument('--watch',action='store_true'); a=p.parse_args(); idle()
 while True:
  try: print(json.dumps(run_once(a.root.resolve(),a.engine.resolve(),a.network.resolve(),a.nodes)),flush=True)
  except Exception as e: print(json.dumps({'status':'failed','error':f'{type(e).__name__}: {e}'}),flush=True); return 2
  if not a.watch: return 0
  time.sleep(5)
if __name__=='__main__': raise SystemExit(main())