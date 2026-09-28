import importlib.util, json, pathlib, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
A=load('autopsy','lichess_autopsy.py'); D=load('datasetv2','build_eloi_teacher_dataset_v2.py')
class CampaignV2Tests(unittest.TestCase):
 def test_required_analysis_retries_missing_pv(self):
  class Engine:
   def __init__(self): self.calls=0
   def analyse(self,board,nodes):
    self.calls+=1
    return {} if self.calls<3 else {'pv':[A.chess.Move.from_uci('e2e4')],'score':object()}
  engine=Engine(); info=D.required_analysis(engine,A.chess.Board(),1000)
  self.assertEqual(engine.calls,3); self.assertEqual(info['pv'][0].uci(),'e2e4')
 def test_required_analysis_fails_after_three_omissions(self):
  class Engine:
   def analyse(self,board,nodes): return {}
  with self.assertRaises(D.v1.DatasetError): D.required_analysis(Engine(),A.chess.Board(),1000)
 def test_child_score_does_not_require_pv(self):
  class Engine:
   def analyse(self,board,nodes): return {'score':A.chess.engine.PovScore(A.chess.engine.Cp(42),board.turn)}
  board=A.chess.Board(); score=D.required_child_score(Engine(),board,A.chess.Move.from_uci('e2e4'),1000)
  self.assertEqual(score,-42)
 def test_terminal_child_is_scored_without_engine(self):
  class Engine:
   def analyse(self,board,nodes): raise AssertionError('terminal child must not call engine')
  board=A.chess.Board('7k/5K2/6Q1/8/8/8/8/8 w - - 0 1')
  score=D.required_child_score(Engine(),board,A.chess.Move.from_uci('g6g7'),1000)
  self.assertEqual(score,30000)
 def test_quota_selection_is_unique_and_reports_shortfall(self):
  rows=[]
  for i in range(12): rows.append({'record_id':str(i),'fen':A.chess.Board().fen(),'static_categories':['forced'] if i<2 else [],'e2_move':'e2e4','teacher_move':'d2d4' if i<5 else 'e2e4','teacher_cp':0})
  old=D.QUOTAS.copy(); D.QUOTAS.update({'broad':5,'disagreement':2,'forced':2,'promotion':0,'mate':0,'quiet_defense':0})
  try: selected,_,short=D.choose_partition(rows,9,'seed','train'); self.assertEqual(len({x['record_id'] for x in selected}),9); self.assertEqual(short,{'mate':1,'promotion':1})
  finally: D.QUOTAS.clear(); D.QUOTAS.update(old)
 def test_variant_is_bypassed_and_notice_is_explicit(self):
  journal={'game_id':'abc','url':'https://lichess.org/abc','version':'3.1.2','executable_sha256':'A','network_sha256':A.NETWORK_SHA,'playing_model_role':'production_or_legacy','variant':'horde','status':'mate','bot_color':'white','moves':'','searches':[]}; r=A.analyse_game(journal,None,1); self.assertEqual(r['analysis_status'],'variant_bypassed'); self.assertIn('not played by a laboratory challenger',r['explicit_notice'])
 def test_active_game_pauses_before_engine_access(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d); (root/'active-game.lock').write_text('x'); self.assertEqual(A.run_once(root,root/'missing',root/'missing',1)['status'],'paused_active_game')
 def test_markdown_contains_binary_identity(self):
  r={'game_id':'g','url':'u','version':'3.1.2','executable_sha256':'HASH','explicit_notice':'legacy','analysis_status':'complete','variant':'standard','incidents':[],'suggested_regressions':[]}; self.assertIn('HASH',A.markdown(r))
 def test_autopsy_records_e4_caissa_disagreement(self):
  class Engine:
   def __init__(self,move): self.move=A.chess.Move.from_uci(move)
   def analyse(self,board,limit):
    move=self.move if self.move in board.legal_moves else next(iter(board.legal_moves))
    return {'pv':[move], 'score':A.chess.engine.PovScore(A.chess.engine.Cp(50),board.turn)}
  journal={'game_id':'g','url':'u','version':'3.6.0','executable_sha256':'HASH','network_sha256':A.NETWORK_SHA,'playing_model_role':'production_or_legacy','variant':'standard','status':'mate','bot_color':'white','moves':'e2e4 e7e5','searches':[]}
  report=A.analyse_game(journal,Engine('c2c4'),100,Engine('d2d4'))
  self.assertEqual(report['analysis_status'],'complete')
  self.assertEqual(report['e4_caissa_disagreements'],1)
 def test_autopsy_cancellation_is_observed_before_search(self):
  class Engine:
   def analyse(self,board,limit): raise AssertionError('cancelled analysis must not search')
  with tempfile.TemporaryDirectory() as d:
   cancel=pathlib.Path(d)/'cancel'; cancel.write_text('cancel')
   journal={'game_id':'g','url':'u','version':'3.6.0','executable_sha256':'HASH','network_sha256':A.NETWORK_SHA,'playing_model_role':'production_or_legacy','variant':'standard','status':'mate','bot_color':'white','moves':'e2e4','searches':[]}
   with self.assertRaises(InterruptedError): A.analyse_game(journal,Engine(),100,Engine(),cancel)
 def test_bridge_source_never_journals_token_or_chat(self):
  source=(ROOT/'src/lichess.cpp').read_text(); block=source[source.index('eloi-lichess-game-journal-v1'):source.index('std::filesystem::remove(active_lock')]; self.assertNotIn('lichess_token',block); self.assertNotIn('chatLine',block)
if __name__=='__main__': unittest.main()
