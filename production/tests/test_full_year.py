"""Local preparation and actual claim-queue contracts; no compute or IDs reserved."""
import contextlib
import heapq
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_year_setup import YearSetupTests, ROOT, campaign, fleet, node_runtime, build_campaign

class FullYearTests(unittest.TestCase):
 def test_non1994_full_route_freezes_pinned_inputs(self):
  helper=YearSetupTests()
  for point,version in [('1992_91p2','v92e'),('1993_93p0','v93d'),('1995_91p2','v95d')]:
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/'new';args=helper.args(root,False,point,1000);args.year_profile=True
    helper.prepare(args);p=campaign.read(root/'plan.json');t=p['tasks'][0]
    self.assertEqual(t['detector_profile'],'pinned-production');self.assertEqual(t['point']['detector'],version)
    self.assertFalse(p['site'].get('diagnostic_only',False))
    self.assertIn('sim/production/detectors/'+version+'/longdst.des',campaign.read(root/'source-manifest.json'))
 def test_all_year_counts_and_resource_deadlines(self):
  for point in campaign.read(ROOT/'long_production/configs/catalog.json')['points']:
   p=fleet.plan(ROOT/'long_production/configs/points'/(point['id']+'.json'))
   if point['year']==1994:
    self.assertNotIn('year_profile_production',p['site']);self.assertTrue(all(j['minutes']==360 for j in p['jobs']));continue
   self.assertTrue(p['site']['year_profile_production']);self.assertNotIn('production_risk_acceptance',p['site'])
   self.assertEqual(p['blockers'],[])
   for j in p['jobs']:
    self.assertLessEqual(j['nodes'],4);self.assertLessEqual(j['minutes'],360)
    self.assertGreaterEqual(j['minutes']*60,j['startup_allowance_seconds']+j['finish_reserve_seconds']+j['claim_margin_seconds']+j['queue_work_bound_seconds'])
 def test_real_claim_order_completes_with_staggered_startup(self):
  costs=[3300,2000,1500,1000,900,800,600,500,400,300]*3
  tasks=[dict(id='%06d'%i,estimated_seconds=v) for i,v in enumerate(costs)]
  resources=dict(nodes_per_job=4,workers_per_node=4,minutes=360,job_overhead_seconds=1800)
  jobs=fleet.pack_year_jobs(tasks,resources,1800)
  for j in jobs:
   ordered=sorted((tasks[int(i)] for i in j['task_ids']),key=lambda t:(-t['estimated_seconds'],t['id']))
   workers=j['nodes']*j['workers_per_node']
   # Skewed readiness within startup allowance; duration perturbations preserve upper bounds.
   q=[(1800*i/max(1,workers-1),i) for i in range(workers)];heapq.heapify(q);claimed=[]
   with tempfile.TemporaryDirectory() as tmp:
    r=Path(tmp);(r/'claims').mkdir();(r/'results').mkdir()
    while len(claimed)<len(ordered):
     time,worker=heapq.heappop(q)
     task=node_runtime.claim_next(r,ordered,j['index'],j['minutes']*60-time-1800,{'worker':worker})
     self.assertIsNotNone(task,'Actual queue skipped an estimated task')
     claimed.append(task['id']);heapq.heappush(q,(time+task['estimated_seconds']*(0.7 if worker%2 else 1),worker))
   self.assertEqual(set(claimed),set(j['task_ids']))
 def test_time_budget_skip_leaves_record_without_claiming(self):
  tasks=[dict(id='000001',estimated_seconds=900),dict(id='000002',estimated_seconds=100)]
  with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()) as out:
   r=Path(tmp);(r/'claims').mkdir();(r/'results').mkdir()
   task=node_runtime.claim_next(r,tasks,0,500,{'job':'fixture'})
   self.assertEqual(task['id'],'000002')  # unchanged queue order: the large chunk is passed
   self.assertFalse((r/'claims/000001').exists())
   record=campaign.read(node_runtime.time_budget_skip(r,'000001'))
   self.assertEqual((record['remaining_seconds'],record['estimated_seconds']),(500,900))
   self.assertIn('skipped chunk 000001',out.getvalue())
   self.assertFalse(node_runtime.time_budget_skip(r,'000002').exists())
 def test_tail_truncation_flags_short_chunks(self):
  with tempfile.TemporaryDirectory() as tmp:
   log=Path(tmp)/'simulate.log'
   log.write_text(' SXSDK: FATAL error: including generator comment or decay for generator track 7\n normal line\n HPC - WRONG DELPHI CODE - STOP 24.0\n')
   tail=campaign.tail_truncation(900,140,[],log)
   self.assertEqual(tail['missing_tail_events'],760)
   self.assertEqual(len(tail['log_stop_lines']),2)
   # Recorded 2026-11-10 truncated 1992 Z_qq files (converted, internal ID gaps); 900 requested.
   for converted,gaps in [(434,0),(444,1),(140,0),(577,0),(812,0),(633,1),(682,0),(231,0)]:
    self.assertGreater(campaign.tail_truncation(900,converted,list(range(gaps)),log)['missing_tail_events'],0)
   # Explained internal gaps (memory skips) are not tail losses: 1992 001443, 1993 000384, spin-polm1 000847.
   for converted,gaps in [(899,3),(899,1),(899,1),(900,0)]:
    self.assertIsNone(campaign.tail_truncation(900,converted,list(range(gaps)),Path(tmp)/'absent.log'))
 def test_tail_uses_fewer_nodes_and_shorter_walltime(self):
  tasks=[dict(estimated_seconds=500) for _ in range(40)]
  j=fleet.pack_year_jobs(tasks,dict(nodes_per_job=4,workers_per_node=128,minutes=360,job_overhead_seconds=1800),1800)[0]
  self.assertEqual(j['nodes'],1);self.assertLess(j['minutes'],360)
 def test_build_identity_matches_verified_receipt(self):
  # The receipt of the configured build: docs/BUILD_<build_root name>.json.
  site=fleet.read(ROOT/'long_production/configs/production.json')
  receipt=fleet.read(ROOT/'long_production/docs'/('BUILD_'+Path(site['build_root']).name+'.json'))['build']
  self.assertEqual(receipt['root'],site['build_root']);self.assertTrue(receipt['verified'])
  self.assertEqual(build_campaign.identity(ROOT/'delphi-sim-pipeline',ROOT/'delphi-edm4hep',site),receipt['identity'])
 def test_freeze_forwards_profile_and_frozen_source(self):
  import argparse
  helper=YearSetupTests()
  with tempfile.TemporaryDirectory() as tmp:
   p=fleet.plan(ROOT/'long_production/configs/points/1993_91p2.json',processes='Z_tautau',events=1000)
   p['site']['scratch_root']=str(Path(tmp)/'scratch');p['site']['destination']=str(Path(tmp)/'publication')
   def backend(command,**kwargs):
    command=list(map(str,command));self.assertIn('--year-profile',command)
    def value(flag):return command[command.index(flag)+1]
    args=helper.args(Path(value('--output')),False,'1993_91p2',1000)
    args.site=Path(value('--site'));args.workload=Path(value('--workload'));args.year_profile=True
    helper.prepare(args)
   args=argparse.Namespace(config=ROOT/'long_production/configs/points/1993_91p2.json')
   with patch.object(fleet,'plan',return_value=p),patch.object(fleet,'reserve',return_value=(300100001,200000)),patch.object(fleet,'verify_build',return_value={}),patch.object(fleet.subprocess,'run',side_effect=backend):root=fleet.freeze(args)
   self.assertEqual(fleet.read(root/'plan.json')['tasks'][0]['detector_profile'],'pinned-production')
   self.assertTrue((root/'source/sim/production/detectors/v93d/longdst.des').exists())
   j=p['jobs'][0];self.assertIn('FLEET_JOB_INDEX=0',(root/'jobs/work-0000.sh').read_text())
 def test_ordinary_rejects_tampered_profile_before_output(self):
  import shutil
  helper=YearSetupTests()
  with tempfile.TemporaryDirectory() as tmp:
   config=Path(tmp)/'configs';shutil.copytree(ROOT/'long_production/configs',config)
   (config/'detectors/v93d/longdst.des').write_text('tampered')
   args=helper.args(Path(tmp)/'campaign',False);args.config_dir=config;args.year_profile=True
   with self.assertRaisesRegex(ValueError,'Pinned detector card changed'):helper.prepare(args)
   self.assertFalse(args.output.exists())
 def test_scheduler_preview_uses_each_frozen_walltime(self):
  p=fleet.plan(ROOT/'long_production/configs/points/1995_91p2.json')
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'jobs').mkdir();(root/'jobs/array.sh').write_text('fixture');fleet.write(root/'fleet.json',p)
   commands=fleet.submissions(root)
   self.assertEqual({int(c[c.index('-t')+1]) for c in commands},{j['minutes'] for j in p['jobs']})

if __name__=='__main__':unittest.main()
