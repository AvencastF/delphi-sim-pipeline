"""Preparation contracts only; no identities reserved, containers or jobs run."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
PRODUCTION=Path(__file__).resolve().parents[1]
ROOT=PRODUCTION.parents[1]
sys.path[:0]=[str(PRODUCTION),str(ROOT/'long_production/scripts')]
import campaign
import fleet
import build_campaign
import node_runtime

class YearSetupTests(unittest.TestCase):
 def args(self, output, validation=True, point='1993_89p4', events=100):
  return argparse.Namespace(site=ROOT/'long_production/configs/production.json',config_dir=ROOT/'long_production/configs',processes='Z_tautau',points=point,events=events,chunks=1,nodes=1,workers=1,seed_start=300000001,run_start=100000,minutes=30,qos='regular',mode='chain',detector_validation=validation,output=output,edm_repo=ROOT/'delphi-edm4hep',name='local-contract',workload=None)
 def prepare(self,args):
  copy=shutil.copytree
  def minimal(src,dst,*args,**kwargs):
   dst=Path(dst)
   if dst.name=='sim':
    (dst/'production').mkdir(parents=True)
    for name in ('runtime.sh','campaign.py','detector.py'):shutil.copy2(PRODUCTION/name,dst/'production'/name)
   elif dst.name=='edm':dst.mkdir()
   else:return copy(src,dst,*args,**kwargs)
  with patch.object(campaign.shutil,'copytree',side_effect=minimal),patch.object(campaign,'git',return_value='fixture'),contextlib.redirect_stdout(io.StringIO()):campaign.prepare(args)
 def test_pinned_prepare_freezes_profiles_and_diagnostics(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'campaign';self.prepare(self.args(root))
   plan=campaign.read(root/'plan.json');t=plan['tasks'][0]
   self.assertEqual(t['point']['detector'],'v93d');self.assertEqual(t['detector_profile'],'pinned-validation')
   self.assertIn('Beams:eCM = 89.432340',t['card'])
   self.assertTrue(plan['site']['detector_validation']);self.assertTrue(plan['site']['diagnostic_only'])
   self.assertFalse(plan['site']['retention']['remove_scratch_after_publish'])
   manifest=campaign.read(root/'source-manifest.json')
   self.assertIn('sim/production/detectors/v93d/longdst.des',manifest)
   self.assertIn('sim/production/detectors/manifest.json',manifest)
 def test_all_points_generator_cards_and_simulation_dispatch(self):
  class CapturedSimulation(Exception):pass
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'campaign';args=self.args(root,point='all');args.processes='Z_tautau,Bhabha';self.prepare(args)
   tasks=campaign.read(root/'plan.json')['tasks']
   self.assertEqual(len(tasks),16)
   for t in tasks:
    energy='%.6f'%t['point']['ecm_gev']
    if t['generator']=='pythia8':self.assertIn('Beams:eCM = '+energy,t['card'])
    else:self.assertEqual(float(t['card'].splitlines()[1].split()[0]),t['point']['ecm_gev']);self.assertNotIn('@ECM@',t['card'])
    def stage(root,task,name,args):
     w=root/'work'/task['id']
     if name in ('generate','bhwide'):campaign.write(w/'generation.json',dict(generated=100,sigma_mb=1,sigma_error_mb=0,sumw=100,sumw2=100))
     if name=='simulate':
      self.assertEqual(args,[t['run'],t['point']['beam_gev'],90,t['point']['detector']])
      self.assertIn('ECMLEP '+energy,(w/'reconstruction.title').read_text())
      raise CapturedSimulation()
     return {}
    with patch.object(campaign,'stage_run',side_effect=stage),patch.object(campaign,'fadgen_count',return_value=100),patch.dict(campaign.os.environ,{'SLURM_JOB_ID':'fixture'}),self.assertRaises(CapturedSimulation):campaign.run_task(root,t)
 def test_1994_default_title_identical(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'campaign';self.prepare(self.args(root,False,'1994_91p2'))
   self.assertNotIn('detector_profile',campaign.read(root/'plan.json')['tasks'][0])
   self.assertEqual((root/'source/sim/production/simulation-1994.title').read_bytes(),(ROOT/'long_production/configs/simulation-1994.title').read_bytes())
 def test_bounds_and_full_production_gate_before_output(self):
  for validation,events in ((False,100),(True,101)):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/'campaign'
    with self.assertRaises(ValueError):self.prepare(self.args(root,validation,events=events))
    self.assertFalse(root.exists())
 def test_validation_claims_work_after_environment_setup(self):
  p=fleet.plan(ROOT/'long_production/configs/points/1993_91p2.json',detector_validation=True)
  # Thirty-minute job after five minutes of container/environment setup.
  with patch.object(campaign.time,'time',return_value=1000),patch.dict(campaign.os.environ,{'SLURM_JOB_END_TIME':'2500'}):
   remaining=campaign.remaining_seconds(p['site'])
   self.assertGreaterEqual(remaining,180)
   tasks=[dict(t,id='%06d'%i) for i,t in enumerate(p['tasks'])]
   with tempfile.TemporaryDirectory() as tmp:
    r=Path(tmp);(r/'claims').mkdir();(r/'results').mkdir()
    self.assertIsNotNone(node_runtime.claim_next(r,tasks,0,remaining,{'job':'fixture'}))
  ordinary=fleet.plan(ROOT/'long_production/configs/points/1994_91p2.json')
  self.assertEqual(ordinary['site']['worker_finish_reserve_seconds'],1800)
  self.assertEqual(ordinary['site']['stage_timeout_seconds'],7200)
  self.assertEqual(ordinary['config']['resources']['qos'],'regular')
 def test_fleet_plans_and_publication_guard(self):
  for point in campaign.read(ROOT/'long_production/configs/catalog.json')['points']:
   p=fleet.plan(ROOT/'long_production/configs/points'/f"{point['id']}.json",detector_validation=True)
   self.assertEqual(p['generated_total'],700);self.assertEqual(p['simulation_target_total'],630)
   self.assertEqual(p['blockers'],[])
   self.assertEqual(p['config']['resources']['qos'],'shared')
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);fleet.write(root/'fleet.json',{'site':{'detector_validation':True}});fleet.write(root/'plan.json',{'site':{'detector_validation':True}})
   with patch.object(fleet,'require_compute'),self.assertRaisesRegex(ValueError,'publication is disabled'):fleet.publish_job(root,0)

if __name__=='__main__':unittest.main()
