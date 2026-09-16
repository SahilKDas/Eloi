import importlib.util, json, pathlib, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
A=load('autopsy','lichess_autopsy.py'); D=load('datasetv2','build_eloi_teacher_dataset_v2.py')
class CampaignV2Tests(unittest.TestCase):
 def test_quota_selection_is_unique_and_reports_shortfall(self):
  rows=[]
  for i in range(12): rows.append({'record_id':str(i),'fen':A.chess.Board().fen(),'static_categories':['forced'] if i<2 else [],'e2_move':'e2e4','teacher_move':'d2d4' if i<5 else 'e2e4','teacher_cp':0})
  old=D.QUOTAS.copy(); D.QUOTAS.update({'broad':5,'disagreement':2,'forced':2,'promotion':0,'mate':0,'quiet_defense':0})
  try: selected,_,short=D.choose_partition(rows,9,'seed','train'); self.assertEqual(len({x['record_id'] for x in selected}),9); self.assertEqual(short,{'mate':1,'promotion':1})
  finally: D.QUOTAS.clear(); D.QUOTAS.update(old)
 def test_variant_is_bypassed_and_notice_is_explicit(self):
  journal={'game_id':'abc','url':'https://lichess.org/abc','version':'3.1.2','executable_sha256':'A','network_sha256':A.NETWORK_SHA,'playing_model_role':'production_or_legacy','variant':'horde','status':'mate','bot_color':'white','moves':'','searches':[]}; r=A.analyse_game(journal,None,1); self.assertEqual(r['analysis_status'],'variant_bypassed'); self.assertIn('not played by EPV2',r['explicit_notice'])
 def test_active_game_pauses_before_engine_access(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d); (root/'active-game.lock').write_text('x'); self.assertEqual(A.run_once(root,root/'missing',root/'missing',1)['status'],'paused_active_game')
 def test_markdown_contains_binary_identity(self):
  r={'game_id':'g','url':'u','version':'3.1.2','executable_sha256':'HASH','explicit_notice':'legacy','analysis_status':'complete','variant':'standard','incidents':[],'suggested_regressions':[]}; self.assertIn('HASH',A.markdown(r))
 def test_bridge_source_never_journals_token_or_chat(self):
  source=(ROOT/'src/lichess.cpp').read_text(); block=source[source.index('eloi-lichess-game-journal-v1'):source.index('std::filesystem::remove(active_lock')]; self.assertNotIn('lichess_token',block); self.assertNotIn('chatLine',block)
if __name__=='__main__': unittest.main()