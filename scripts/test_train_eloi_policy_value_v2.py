import importlib.util, json, pathlib, sys, tempfile, unittest
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
M=load('epv2','train_eloi_policy_value_v2.py')
class EPV2Tests(unittest.TestCase):
 def test_move_index_distinguishes_interactions_and_promotions(self):
  b=M.chess.Board(); self.assertNotEqual(M.move_index(b,M.chess.Move.from_uci('e2e4')),M.move_index(b,M.chess.Move.from_uci('d2d4')))
  p=M.chess.Board('8/P7/8/8/8/8/7k/6K1 w - - 0 1'); ids={M.move_index(p,M.chess.Move.from_uci('a7a8'+x)) for x in 'qrbn'}; self.assertEqual(len(ids),4)
 def test_legal_policy_is_normalized(self):
  b=M.chess.Board(); moves=list(b.legal_moves); v,p=M.Network(7).predict(b,moves); self.assertAlmostEqual(float(v.sum()),1,6); self.assertAlmostEqual(float(p.sum()),1,6); self.assertEqual(len(p),20)
 def test_batch_and_snapshot_are_finite_and_exact(self):
  row={'fen':M.chess.Board().fen(),'primary_category':'broad','tactical_weight':9,'value_wdl':{'win':.4,'draw':.3,'loss':.3},'policy':[{'move':'e2e4','probability':.7},{'move':'d2d4','probability':.3}]}; n=M.Network(9); state=n.snapshot(); losses=n.batch([row],.001); self.assertTrue(all(np.isfinite(x) for x in losses)); n.restore(state); self.assertTrue(np.array_equal(n.policy,state[-1]))
 def test_epv2_serialization_is_deterministic(self):
  with tempfile.TemporaryDirectory() as d:
   n=M.Network(11); a=pathlib.Path(d)/'a'; b=pathlib.Path(d)/'b'; n.save(a); n.save(b); self.assertEqual(a.read_bytes(),b.read_bytes()); self.assertEqual(a.read_bytes()[:4],b'EPV2')
 def test_sealed_test_rows_are_counted_without_json_parsing(self):
  with tempfile.TemporaryDirectory() as d:
   path=pathlib.Path(d)/'dataset.jsonl'
   row={'fen':M.chess.Board().fen(),'partition':'train','primary_category':'broad','value_wdl':{'win':.4,'draw':.3,'loss':.3},'policy':[{'move':'e2e4','probability':1.}]}
   validation=dict(row,partition='validation')
   path.write_text(json.dumps(row)+'\n'+json.dumps(validation)+'\n'+r'{"partition":"test",this is deliberately not parsed}'+ '\n',encoding='utf-8')
   rows,sealed=M.load(path)
   self.assertEqual((len(rows['train']),len(rows['validation']),sealed),(1,1,1))
if __name__=='__main__': unittest.main()
