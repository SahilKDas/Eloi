#!/usr/bin/env python3
"""Train Eloi's EPV2 complete-move policy/value laboratory network."""
from __future__ import annotations
import argparse, hashlib, json, random, struct, subprocess, sys, time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.deps/lichess-bot/.venv/Lib/site-packages'))
import chess
import validation_support
MAGIC=b'EPV2'; INPUTS=781; HIDDEN=64; PROMOTIONS=5; MOVES=64*64*PROMOTIONS
CATEGORIES=('broad','disagreement','forced','promotion','mate','quiet_defense')

def sha(path):
 d=hashlib.sha256();
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest().upper()

def features(board):
 x=np.zeros(INPUTS,np.float32)
 for sq,p in board.piece_map().items():
  plane=(0 if p.color==board.turn else 6)+p.piece_type-1; o=sq if board.turn else sq^56
  x[plane*64+o]=1
 x[768]=1
 x[769:773]=(board.has_kingside_castling_rights(board.turn),board.has_queenside_castling_rights(board.turn),board.has_kingside_castling_rights(not board.turn),board.has_queenside_castling_rights(not board.turn))
 if board.ep_square is not None: x[773+chess.square_file(board.ep_square)]=1
 return x

def move_index(board,move):
 src=move.from_square if board.turn else move.from_square^56; dst=move.to_square if board.turn else move.to_square^56
 promo=0 if move.promotion is None else {chess.KNIGHT:1,chess.BISHOP:2,chess.ROOK:3,chess.QUEEN:4}[move.promotion]
 return (src*64+dst)*PROMOTIONS+promo

def softmax(a):
 z=a-np.max(a,axis=-1,keepdims=True); e=np.exp(z); return e/e.sum(axis=-1,keepdims=True)

class Network:
 def __init__(self,seed):
  r=np.random.default_rng(seed); self.input=r.normal(0,.025,(INPUTS,HIDDEN)).astype(np.float32); self.bias=np.zeros(HIDDEN,np.float32)
  self.value=r.normal(0,.025,(HIDDEN,3)).astype(np.float32); self.value_bias=np.zeros(3,np.float32)
  self.policy=r.normal(0,.01,(MOVES,HIDDEN)).astype(np.float32)
 def snapshot(self): return tuple(a.copy() for a in (self.input,self.bias,self.value,self.value_bias,self.policy))
 def restore(self,s): self.input,self.bias,self.value,self.value_bias,self.policy=s
 def save(self,path):
  with path.open('xb') as f:
   f.write(struct.pack('<4sIIII',MAGIC,INPUTS,HIDDEN,PROMOTIONS,MOVES))
   for a in (self.input,self.bias,self.value,self.value_bias,self.policy): f.write(np.asarray(a,dtype='<f4').tobytes())
 def predict(self,board,moves):
  h=np.maximum(features(board)@self.input+self.bias,0); v=softmax(h@self.value+self.value_bias)
  ids=np.asarray([move_index(board,m) for m in moves]); return v,softmax(self.policy[ids]@h)
 def batch(self,rows,lr):
  boards=[chess.Board(r['fen']) for r in rows]; x=np.stack([features(b) for b in boards]); pre=x@self.input+self.bias; h=np.maximum(pre,0)
  vt=np.asarray([[r['value_wdl'][k] for k in ('win','draw','loss')] for r in rows],np.float32); vp=softmax(h@self.value+self.value_bias); ve=(vp-vt)/len(rows)
  vg=h.T@ve; vbg=ve.sum(0); hg=ve@self.value.T; ploss=0.; top=0
  pgrad={}
  for i,(r,b) in enumerate(zip(rows,boards)):
   prs=r['policy']; ids=np.asarray([move_index(b,chess.Move.from_uci(p['move'])) for p in prs]); target=np.asarray([p['probability'] for p in prs],np.float32); target/=target.sum()
   pred=softmax(self.policy[ids]@h[i]); err=(pred-target)*min(3.,max(.5,float(r.get('tactical_weight',1.))))/len(rows)
   hg[i]+=err@self.policy[ids]; ploss-=float(np.sum(target*np.log(pred+1e-9))); top+=int(np.argmax(pred)==np.argmax(target))
   for idx,g in zip(ids,err): pgrad[idx]=pgrad.get(idx,0)+g*h[i]
  hg*=pre>0; self.value-=lr*vg; self.value_bias-=lr*vbg; self.input-=lr*(x.T@hg); self.bias-=lr*hg.sum(0)
  for idx,g in pgrad.items(): self.policy[idx]-=lr*g
  vloss=-float(np.sum(vt*np.log(vp+1e-9)))/len(rows); return vloss,ploss/len(rows),top/len(rows)

def load(path):
 out={p:[] for p in ('train','validation','test')}
 with path.open(encoding='utf-8') as f:
  for line in f:
   if line.strip():
    r=json.loads(line); out[r['partition']].append(r)
 if not out['train'] or not out['validation']: raise ValueError('training and validation must be nonempty')
 return out

def evaluate(net,rows):
 vl=pl=top=0.
 for r in rows:
  b=chess.Board(r['fen']); prs=r['policy']; moves=[chess.Move.from_uci(p['move']) for p in prs]; v,p=net.predict(b,moves)
  vt=np.asarray([r['value_wdl'][k] for k in ('win','draw','loss')]); pt=np.asarray([x['probability'] for x in prs]); pt/=pt.sum()
  vl-=float(np.sum(vt*np.log(v+1e-9))); pl-=float(np.sum(pt*np.log(p+1e-9))); top+=int(np.argmax(p)==np.argmax(pt))
 n=len(rows); return {'value_cross_entropy':vl/n,'policy_cross_entropy':pl/n,'policy_top1':top/n}

def balanced(rows,seed):
 rng=random.Random(seed); buckets={c:[] for c in CATEGORIES}
 for r in rows: buckets[r.get('primary_category','broad')].append(r)
 for b in buckets.values(): rng.shuffle(b)
 result=[]
 while any(buckets.values()):
  for c in CATEGORIES:
   if buckets[c]: result.append(buckets[c].pop())
 return result

def main():
 p=argparse.ArgumentParser(); p.add_argument('--dataset',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--epochs',type=int,default=30); p.add_argument('--batch-size',type=int,default=256); p.add_argument('--learning-rate',type=float,default=.002); p.add_argument('--seed',type=int,default=20260916); p.add_argument('--patience',type=int,default=3); p.add_argument('--min-delta',type=float,default=1e-4); p.add_argument('--tactical-check',type=Path); p.add_argument('--tactical-engine',type=Path); a=p.parse_args()
 if bool(a.tactical_check) != bool(a.tactical_engine): raise ValueError('--tactical-check and --tactical-engine must be supplied together')
 if a.output.exists(): raise FileExistsError(a.output)
 a.output.mkdir(parents=True); validation_support.resource_snapshot(a.output,projected=40000000); rows=load(a.dataset); net=Network(a.seed); before=evaluate(net,rows['validation']); best=float('inf'); best_state=net.snapshot(); best_epoch=0; stale=0; history=[]; start=time.monotonic()
 for epoch in range(1,a.epochs+1):
  ordered=balanced(rows['train'],a.seed+epoch); tv=tp=tt=seen=0
  for i in range(0,len(ordered),a.batch_size):
   batch=ordered[i:i+a.batch_size]; v,pv,t=net.batch(batch,a.learning_rate); n=len(batch); tv+=v*n; tp+=pv*n; tt+=t*n; seen+=n
  val=evaluate(net,rows['validation']); metric=val['policy_cross_entropy']+.25*val['value_cross_entropy']; accepted=metric<best-a.min_delta; tactical=True
  if accepted and a.tactical_check:
   candidate=a.output/f'epoch-{epoch}.epv2'; net.save(candidate)
   command=([sys.executable,str(a.tactical_check)] if a.tactical_check.suffix.lower()=='.py' else [str(a.tactical_check)])
   command += ['--engine',str(a.tactical_engine),'--model',str(candidate),'--output',str(a.output/f'epoch-{epoch}.tactical.json')]
   tactical=subprocess.run(command,cwd=ROOT,timeout=300).returncode==0
  if accepted and tactical: best=metric; best_state=net.snapshot(); best_epoch=epoch; stale=0
  else: stale+=1
  row={'epoch':epoch,'train_value_loss':tv/seen,'train_policy_loss':tp/seen,'train_policy_top1':tt/seen,'validation':val,'selection_metric':metric,'improved':accepted,'tactical_passed':tactical}; history.append(row); print(json.dumps(row),flush=True)
  if stale>=a.patience: break
 net.restore(best_state); model=a.output/'eloi-policy-value-v2.epv2'; net.save(model)
 manifest={'schema':'eloi-policy-value-training-v2','status':'complete','dataset_sha256':sha(a.dataset),'model_sha256':sha(model),'architecture':{'inputs':INPUTS,'hidden':HIDDEN,'value_outputs':['win','draw','loss'],'policy':'exact oriented from/to/promotion interaction','move_outputs':MOVES},'rows':{k:len(v) for k,v in rows.items()},'test_partition_opened':False,'seed':a.seed,'epochs_requested':a.epochs,'epochs_completed':len(history),'batch_size':a.batch_size,'learning_rate':a.learning_rate,'patience':a.patience,'min_delta':a.min_delta,'selected_epoch':best_epoch,'selection_metric':'policy_cross_entropy + 0.25 * value_cross_entropy','selected_validation':evaluate(net,rows['validation']),'validation_before':before,'history':history,'elapsed_seconds':round(time.monotonic()-start,3),'promotion_status':'laboratory_only'}
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8'); return 0
if __name__=='__main__': raise SystemExit(main())