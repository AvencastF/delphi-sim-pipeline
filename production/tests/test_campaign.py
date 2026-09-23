import importlib.util,json,pathlib,struct,tempfile,unittest,sys
root=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import campaign as c
import argparse,contextlib,io
config=(root.parent.parent/'long_production/configs')
if not config.exists():config=root.parents[2]/'configs'
from whizard_summary import parse_log,weights
class TestCampaign(unittest.TestCase):
 def test_worker_deadline_preserves_publication_headroom(self):
  from unittest.mock import patch
  with patch.dict(c.os.environ,{'SLURM_JOB_END_TIME':'3000'}),patch.object(c.time,'time',return_value=1000):
   self.assertEqual(c.remaining_seconds({'worker_finish_reserve_seconds':1800}),200)
   self.assertEqual(c.remaining_seconds({'worker_finish_reserve_seconds':60}),1940)
   self.assertEqual(c.remaining_seconds({}),2000)
 def test_stage_containers_do_not_start_network_helper(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d)
   c.write(root/'plan.json',{'site':{'build_root':d+'/build','image':'test-image'}})
   with patch.dict(c.os.environ,{'SLURM_JOB_ID':'123'}):
    for stage in ['generate','fadgen','simulate','convert']:
     cmd=c.command(root,{'id':'000001'},stage,[])
     self.assertIn('--network=none',cmd)
     self.assertIn('/cvmfs:/cvmfs:ro',cmd)
     self.assertIn('test-image',cmd)
 def test_prepare_creates_concrete_job_without_running(self):
  with tempfile.TemporaryDirectory() as d:
   args=argparse.Namespace(site=str(config/'production.json'),config_dir=str(config),processes='Z_qq,Z_ll,Z_tautau,Z_mumu',points='1994_91p2',events=10,chunks=1,nodes=1,workers=4,seed_start=10000,run_start=40000,qos='shared',minutes=10,mode='chain',output=d+'/campaign',edm_repo=str(root.parent.parent/'delphi-edm4hep'),name='check')
   with contextlib.redirect_stdout(io.StringIO()):c.prepare(args)
   plan=c.read(pathlib.Path(d)/'campaign/plan.json')
   self.assertEqual(len(plan['tasks']),4)
   self.assertEqual(len({t['seed'] for t in plan['tasks']}),4)
   self.assertTrue((pathlib.Path(d)/'campaign/job.sbatch').exists())
   self.assertFalse((pathlib.Path(d)/'campaign/submission.json').exists())
 def test_weights_follow_surviving_identities(self):
  with tempfile.TemporaryDirectory() as d:
   w=pathlib.Path(d)/'weights.csv';e=pathlib.Path(d)/'events.csv'
   w.write_text('hepmc_event,weight\n1,0.5\n2,20\n3,2\n')
   e.write_text('run,event\n-10,1\n-10,3\n')
   values,ids=c.selected_weights(w,e)
   self.assertEqual(ids,[1,3]);self.assertEqual(sum(values),2.5)
   e.write_text('run,event\n-10,4\n')
   with self.assertRaises(ValueError):c.selected_weights(w,e)
 def test_truncated_fadgen_fails(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'bad';p.write_bytes(struct.pack('<i',64)+b'\0'*12)
   with self.assertRaises(ValueError):c.fadgen_count(p)
 def test_fadgen_count(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'good';record=struct.pack('<i',1)+b'\0'*60;term=struct.pack('<i',0)
   p.write_bytes(struct.pack('<i',64)+record+struct.pack('<i',64)+struct.pack('<i',4)+term+struct.pack('<i',4));self.assertEqual(c.fadgen_count(p),1)
 def test_exact_beam_energies(self):
  cat=c.read(config/'catalog.json');self.assertEqual(len(cat['points']),8)
  for point in cat['points']:self.assertAlmostEqual(point['ecm_gev'],2*point['beam_gev'])
 def test_whizard_units_and_last_combined_estimate(self):
  text='It Calls Integral[fb] Error[fb]\n 1 1000 1.00E+06 2.00E+03 0.2\n 2 2000 1.01E+06 1.50E+03 0.15\n'
  self.assertEqual(parse_log(text),(1010000.,1500.))
  with self.assertRaises(ValueError):parse_log('Cross section unknown')
 def test_no_invented_weight(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'events';p.write_text('E 1 1 2\nP 1 2\n')
   with self.assertRaises(ValueError):weights(p)
if __name__=='__main__':unittest.main()
