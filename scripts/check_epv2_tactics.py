#!/usr/bin/env python3
"""Fail closed unless an EPV2 checkpoint passes Eloi's frozen tactical suite."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import evaluate_eloi_native_candidates as evaluator
import validation_support
PROFILE='reverse-futility,razoring,internal-reduction,probcut,futility,lmp,lmr'

def main():
 p=argparse.ArgumentParser(); p.add_argument('--engine',required=True,type=Path); p.add_argument('--model',required=True,type=Path); p.add_argument('--output',type=Path); p.add_argument('--timeout-seconds',type=float,default=20.); a=p.parse_args()
 cases=validation_support.epd_cases()
 result=evaluator.run_profile(a.engine.resolve(),a.model.resolve(),PROFILE,cases,a.timeout_seconds,'eloi-policy')
 evidence={'schema':'eloi-epv2-tactical-check-v1','profile':'three_lane_no_null','selectivity':PROFILE,'engine_sha256':evaluator.sha256(a.engine),'model_sha256':evaluator.sha256(a.model),'cases':len(cases),'result':result,'passed':result['failures']==0}
 output=a.output or a.model.with_suffix('.tactical.json')
 output.write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print(json.dumps({'passed':evidence['passed'],'failures':result['failures'],'cases':len(cases)}),flush=True)
 return 0 if evidence['passed'] else 1
if __name__=='__main__': raise SystemExit(main())

