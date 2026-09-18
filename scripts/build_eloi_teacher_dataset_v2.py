#!/usr/bin/env python3
"""Build Eloi's deterministic 150k Standard teacher dataset v2."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, subprocess, time
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts')); sys.path.insert(0,str(ROOT/'.deps/lichess-bot/.venv/Lib/site-packages'))
import chess
import build_eloi_teacher_dataset as v1
import validation_support
SCHEMA='eloi-caissa125-teacher-dataset-v2'; CATEGORIES=('broad','disagreement','forced','promotion','mate','quiet_defense')
QUOTAS={'broad':75000,'disagreement':22500,'forced':15000,'promotion':15000,'mate':15000,'quiet_defense':7500}

def digest(seed,text): return hashlib.sha256(f'{seed}\0{text}'.encode()).digest()
def sha(path): return v1.sha256_file(path)
def canonical(board): return min(board.fen(),board.mirror().fen())
def atomic(path,value): v1.atomic_json(path,value)
def verify_lab_route(executable,args,expected):
 completed=subprocess.run([str(executable),*args],input='uci\nquit\n',text=True,capture_output=True,cwd=ROOT,timeout=15,check=True)
 marker=f'info string Lab brain mode {expected}'
 if marker not in completed.stdout: raise v1.DatasetError(f'{executable} did not confirm {expected} laboratory route')

def regression_keys():
 keys=set()
 for path in (ROOT/'tests/epd').glob('*.epd'):
  for line in path.read_text(encoding='utf-8').splitlines():
   if not line.strip() or line.lstrip().startswith('#'): continue
   try: keys.add(canonical(chess.Board(' '.join(line.split()[:4])+' 0 1')))
   except ValueError: pass
 return keys

def load_pool(paths,seed):
 excluded=regression_keys(); seen={}; groups={}; seen_source_games=set()
 for path in paths:
  with path.open(encoding='utf-8') as f:
   for number,line in enumerate(f,1):
    if not line.strip(): continue
    item=json.loads(line); fen=item.get('fen') or item.get('decision_fen')
    if not fen: continue
    try: board=chess.Board(fen)
    except ValueError: continue
    if board.chess960 or board.is_game_over(claim_draw=False): continue
    key=canonical(board)
    if key in excluded or key in seen: continue
    source_game=item.get('game_id')
    if source_game and source_game in seen_source_games: continue
    group=str(item.get('group_id') or item.get('source_group_id') or source_game or item.get('record_id') or f'{path.name}:{number}')
    if group in groups and groups[group]!=item.get('partition'): continue
    partition=item.get('partition') or v1.assigned_partition(group,seed); groups[group]=partition
    themes=set(item.get('themes',[])); static=[]
    legal=list(board.legal_moves)
    if board.is_check() or len(legal)<=3: static.append('forced')
    if any(m.promotion for m in legal) or 'promotion' in themes or 'advancedPawn' in themes: static.append('promotion')
    if any('mate' in t.lower() for t in themes): static.append('mate')
    if 'defensiveMove' in themes: static.append('quiet_defense')
    rid=str(item.get('record_id') or hashlib.sha256(f'{group}\0{board.fen()}'.encode()).hexdigest())
    seen[key]={'record_id':rid,'group_id':group,'source_game_id':source_game,'partition':partition,'fen':board.fen(),'canonical_key':key,'source':item.get('source',path.stem),'static_categories':sorted(set(static))}
    if source_game: seen_source_games.add(source_game)
 return sorted(seen.values(),key=lambda r:digest(seed,r['record_id']))

def required_analysis(engine,board,nodes,attempts=3):
 last='missing PV'
 for attempt in range(1,attempts+1):
  try:
   info=engine.analyse(board,nodes)
   if info.get('pv') and info.get('score') is not None: return info
   last=f'attempt {attempt} omitted PV or score'
  except Exception as error: last=f'{type(error).__name__}: {error}'
 raise v1.DatasetError(last)

def required_child_score(engine,board,move,nodes,attempts=3):
 child=board.copy(stack=False); child.push(move)
 outcome=child.outcome(claim_draw=True)
 if outcome is not None:
  if outcome.winner is None: return 0
  return 30000 if outcome.winner==board.turn else -30000
 last='missing score'
 for attempt in range(1,attempts+1):
  try:
   info=engine.analyse(child,nodes)
   if info.get('score') is not None: return -v1.cp_from_info(info,child)
   last=f'attempt {attempt} omitted score'
  except Exception as error: last=f'{type(error).__name__}: {error}'
 raise v1.DatasetError(last)

def classify(screen):
 cats=set(screen['static_categories']);
 if screen['e2_move']!=screen['teacher_move']: cats.add('disagreement')
 if abs(screen['teacher_cp'])>=29000: cats.add('mate')
 b=chess.Board(screen['fen']); m=chess.Move.from_uci(screen['teacher_move'])
 if 'quiet_defense' in cats and not b.is_capture(m) and not b.gives_check(m) and not m.promotion: cats.add('quiet_defense')
 return cats

def choose_partition(rows,total,seed,partition):
 selected=[]; used=set(); counts={c:0 for c in CATEGORIES}; shortages={}
 ratios={'quiet_defense':0.05,'mate':0.10,'promotion':0.10,'forced':0.10,'disagreement':0.15}
 for category in ('quiet_defense','mate','promotion','forced','disagreement'):
  wanted=round(total*ratios[category])
  candidates=[r for r in rows if r['record_id'] not in used and category in classify(r)]
  candidates.sort(key=lambda r:digest(seed,partition+'\0'+category+'\0'+r['record_id']))
  take=candidates[:wanted]; selected.extend(take); used.update(r['record_id'] for r in take); counts[category]=len(take)
  if len(take)<wanted: shortages[category]=wanted-len(take)
 broad=[r for r in rows if r['record_id'] not in used]
 broad.sort(key=lambda r:digest(seed,partition+'\0broad\0'+r['record_id']))
 take=broad[:total-len(selected)]; selected.extend(take); counts['broad']=len(take)
 if len(selected)!=total: raise v1.DatasetError(f'{partition} supplies only {len(selected)} unique roots of {total}')
 return selected,counts,shortages

def choose(screened,total,seed):
 if total!=150000: raise v1.DatasetError('partition selection is frozen for 150000 positions')
 targets={'train':120000,'validation':15000,'test':15000}; selected=[]
 counts={c:0 for c in CATEGORIES}; shortages={}
 for partition in v1.PARTITIONS:
  rows=[r for r in screened if r['partition']==partition]
  take,part_counts,part_shortages=choose_partition(rows,targets[partition],seed,partition)
  selected.extend(take)
  for category,value in part_counts.items(): counts[category]+=value
  for category,value in part_shortages.items(): shortages[f'{partition}:{category}']=value
 return selected,counts,shortages
def main():
 p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,action='append',required=True); p.add_argument('--e2',type=Path,required=True); p.add_argument('--teacher',type=Path,required=True); p.add_argument('--network',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--positions',type=int,default=150000); p.add_argument('--screen-nodes',type=int,default=1000); p.add_argument('--nodes',type=int,default=10000); p.add_argument('--candidates',type=int,default=12); p.add_argument('--seed',default='eloi-native-v2-20260916'); p.add_argument('--resume',action='store_true'); a=p.parse_args()
 if a.positions!=150000: raise v1.DatasetError('v2 campaign is frozen at exactly 150000 positions')
 for label,path in (('input',x) for x in a.input):
  if not path.resolve().is_file(): raise v1.DatasetError(f'{label} is absent: {path}')
 for label,path in (('E2',a.e2),('teacher',a.teacher),('network',a.network)):
  if not path.resolve().is_file(): raise v1.DatasetError(f'{label} is absent: {path}')
 if sha(a.network.resolve())!=v1.NETWORK_SHA256: raise v1.DatasetError('Caissa 1.25 network hash mismatch')
 verify_lab_route(a.e2.resolve(),['--uci','--brain','eloi-single'],'eloi-single')
 verify_lab_route(a.teacher.resolve(),['--uci','--brain','caissa','--caissa-network',str(a.network.resolve())],'caissa')
 out=a.output.resolve();
 if not out.is_relative_to((ROOT/'tmp').resolve()): raise v1.DatasetError('output must be below tmp')
 if out.exists() and not a.resume: raise v1.DatasetError(f'output collision: {out}')
 out.mkdir(parents=True,exist_ok=True); validation_support.resource_snapshot(out,projected=900000000)
 pool=load_pool([x.resolve() for x in a.input],a.seed); 
 if len(pool)<a.positions: raise v1.DatasetError(f'only {len(pool)} eligible roots')
 identities={'sources':[{ 'path':str(x.resolve()),'sha256':sha(x.resolve())} for x in a.input],'e2_sha256':sha(a.e2.resolve()),'teacher_sha256':sha(a.teacher.resolve()),'network_sha256':sha(a.network.resolve()),'runner_sha256':sha(Path(__file__))}
 frozen={'schema':SCHEMA,'seed':a.seed,'positions_planned':a.positions,'pool_size':len(pool),'screen_nodes':a.screen_nodes,'nodes_per_probe':a.nodes,'candidate_limit':a.candidates,'engine_threads':{'e2_single_thread_lab':1,'caissa_teacher':3},'searches_are_sequential':True,'identities':identities,'quotas':QUOTAS}
 screen_path=out/'screening.jsonl'; selected_path=out/'selected.jsonl'; rows_path=out/'teacher.jsonl'; checkpoint=out/'checkpoint.json'; manifest=out/'manifest.json'
 if a.resume and checkpoint.exists():
  prior=json.loads(checkpoint.read_text());
  if prior['frozen']!=frozen: raise v1.DatasetError('resume protocol mismatch')
 screened={}
 if screen_path.exists():
  with screen_path.open(encoding='utf-8') as existing:
   for line in existing:
    if line.strip():
     row=json.loads(line); screened[row['record_id']]=row
 e2=v1.Engine([str(a.e2.resolve()),'--uci','--brain','eloi-single'],ROOT,15); teacher=v1.Engine([str(a.teacher.resolve()),'--uci','--brain','caissa','--caissa-network',str(a.network.resolve())],ROOT,15); started=time.monotonic(); failures=[]; quarantines=[]
 try:
  with screen_path.open('a' if screen_path.exists() else 'x',encoding='utf-8',newline='\n') as f:
   for root in pool:
    if root['record_id'] in screened: continue
    try:
     b=chess.Board(root['fen']); ei=required_analysis(e2,b,a.screen_nodes); ti=required_analysis(teacher,b,a.screen_nodes); row=dict(root,e2_move=ei['pv'][0].uci(),teacher_move=ti['pv'][0].uci(),teacher_cp=v1.cp_from_info(ti,b)); f.write(json.dumps(row,sort_keys=True)+'\n'); screened[root['record_id']]=row
    except Exception as ex: quarantines.append({'stage':'screen','record_id':root['record_id'],'fen':root['fen'],'error':f'{type(ex).__name__}: {ex}'}); continue
    if len(screened)%100==0: f.flush(); atomic(checkpoint,{'status':'screening','frozen':frozen,'screened':len(screened),'labelled':0,'failures':failures,'quarantines':quarantines})
  if failures: atomic(checkpoint,{'status':'failed','frozen':frozen,'screened':len(screened),'labelled':0,'failures':failures,'quarantines':quarantines}); raise v1.DatasetError(failures[-1]['error'])
  selected,selection_counts,shortages=choose(list(screened.values()),a.positions,a.seed)
  if not selected_path.exists(): selected_path.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in selected),encoding='utf-8')
  done=set()
  if rows_path.exists():
   with rows_path.open(encoding='utf-8') as existing:
    for line in existing:
     if line.strip(): done.add(json.loads(line)['record_id'])
  with rows_path.open('a' if rows_path.exists() else 'x',encoding='utf-8',newline='\n') as f:
   for root in selected:
    if root['record_id'] in done: continue
    try:
     b=chess.Board(root['fen']); ei=required_analysis(e2,b,a.nodes); ti=required_analysis(teacher,b,a.nodes); em=ei['pv'][0].uci(); tm=ti['pv'][0].uci(); moves=v1.candidate_moves(b,em,tm,a.candidates,a.seed,root['record_id']); scored=[(m,required_child_score(teacher,b,chess.Move.from_uci(m),a.nodes)) for m in moves]; peak=max(x[1] for x in scored); cats=set(root['static_categories']);
     if em!=tm: cats.add('disagreement')
     if b.is_check() or b.legal_moves.count()<=3: cats.add('forced')
     if any(chess.Move.from_uci(m).promotion for m,_ in scored): cats.add('promotion')
     if abs(peak)>=29000: cats.add('mate')
     best=chess.Move.from_uci(tm); quiet=not b.is_capture(best) and not b.gives_check(best) and not best.promotion
     if quiet and dict(scored).get(em,peak)+150<peak: cats.add('quiet_defense')
     primary=next((c for c in ('quiet_defense','mate','promotion','forced','disagreement') if c in cats),'broad'); row=dict(root,legal_move_count=b.legal_moves.count(),e2_move=em,teacher_move=tm,disagreement=em!=tm,teacher_root_cp=peak,value_wdl=v1.wdl_target(peak),policy=v1.policy_targets(scored),categories=sorted(cats),primary_category=primary,tactical_weight=min(3.,2. if em!=tm and dict(scored).get(em,peak)+150<peak else 1.)); f.write(json.dumps(row,sort_keys=True)+'\n'); done.add(root['record_id'])
    except Exception as ex: failures.append({'stage':'label','record_id':root['record_id'],'error':f'{type(ex).__name__}: {ex}'}); break
    if len(done)%100==0: f.flush(); atomic(checkpoint,{'status':'labelling','frozen':frozen,'screened':len(screened),'labelled':len(done),'failures':failures,'quarantines':quarantines})
 finally: e2.close(); teacher.close()
 counts={p:0 for p in v1.PARTITIONS}; categories={c:0 for c in CATEGORIES}
 if rows_path.exists():
  for line in rows_path.read_text(encoding='utf-8').splitlines():
   if line.strip():
    r=json.loads(line); counts[r['partition']]+=1; categories[r['primary_category']]+=1
 evidence={'status':'complete' if len(done)==a.positions and not failures else 'failed','created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'frozen':frozen,'screened':len(screened),'rows':len(done),'partition_counts':counts,'category_counts':categories,'selection_counts':selection_counts,'quota_shortfalls':shortages,'dataset_sha256':sha(rows_path) if rows_path.exists() else None,'failures':failures,'quarantines':quarantines,'elapsed_seconds':round(time.monotonic()-started,3)}; atomic(checkpoint,evidence)
 if evidence['status']=='complete' and not manifest.exists(): manifest.write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print(json.dumps(evidence,indent=2,sort_keys=True)); return 0 if evidence['status']=='complete' else 1
if __name__=='__main__': raise SystemExit(main())