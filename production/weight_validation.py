#!/usr/bin/env python3
"""Frozen all-process, 1994 full-chain weight validation; never submits Slurm."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import campaign as c


def prepare(args):
    config = Path(args.config).resolve()
    root = Path(args.output).resolve()
    if root.exists(): raise FileExistsError(root)
    site = c.read(config/'production.json')
    site.update(build_root=str(root.parent/(root.name+'-build')), build_cpus=8,
                worker_finish_reserve_seconds=60, stage_timeout_seconds=3000)
    site['retention'] = {'keep':['hepmc','longdst','edm4hep'], 'remove_scratch_after_publish':False}
    catalog = c.read(config/'catalog.json')
    names = list(catalog['processes'])  # includes diagnostic Z_ll
    point = next(p for p in catalog['points'] if p['id']=='1994_91p2')
    spec = importlib.util.spec_from_file_location('registry_controller',args.controller)
    controller = importlib.util.module_from_spec(spec); spec.loader.exec_module(controller)
    seed, run = controller.reserve(dict(point=point,config={'tag':root.name},site=site,tasks=[None]*80),root)
    with tempfile.TemporaryDirectory() as tmp:
        site_path = Path(tmp)/'site.json'; c.write(site_path,site)
        c.prepare(argparse.Namespace(config_dir=str(config),site=str(site_path),processes=','.join(names),
                    points=point['id'],events=112,chunks=10,nodes=1,workers=80,qos='interactive',
                    minutes=60,mode='chain',output=str(root),edm_repo=args.edm_repo,
                    seed_start=seed,run_start=run,name=root.name,workload=None))
    plan = c.read(root/'plan.json')
    assert len(plan['tasks'])==80 and sum(t['simulated_requested'] for t in plan['tasks'])==8000
    plan['fleet_jobs']=[dict(index=0,workers_per_node=80,task_ids=[t['id'] for t in plan['tasks']])]
    c.write(root/'plan.json',plan); c.write(root/'site.json',site)
    c.write(root/'test-provenance.json',dict(source_revisions=plan['source_revisions'],
        controller_sha256=c.digest(args.controller),controller=str(args.controller),
        scope='8 processes x 10 chunks x 100 converted events; 112 generated/chunk; 1994 v94c; scratch only'))


def summarize(root):
    plan=c.read(root/'plan.json'); processes={}; failures=[]
    for task in plan['tasks']:
        result=root/'results'/(task['id']+'.json')
        if not result.exists():
            failure=root/'claims'/task['id']/'failure.json'
            failures.append(dict(task=task['id'],process=task['process'],
                                 error=c.read(failure) if failure.exists() else 'No result'))
            continue
        data=c.read(result); audit=c.read(root/'work'/task['id']/'audit/root-audit.json')
        entry=processes.setdefault(task['process'],dict(chunks=0,generated=0,converted=0,
            generated_sumw=0.,generated_sumw2=0.,converted_sumw=0.,converted_sumw2=0.,
            converted_negative_count=0,zero_momentum_charged=0,zero_momentum_selected_charged=0,
            missing_event_ids=[],max_truth_momentum_difference_gev=0.,max_relative_vertex_difference_mm=0.,
            weight_min=None,weight_max=None,cross_sections_pb=[]))
        entry['chunks']+=1;entry['generated']+=data['generation']['generated'];entry['converted']+=data['counts']['converted']
        for key in ('sumw','sumw2'): entry['generated_'+key]+=data['generation'][key];entry['converted_'+key]+=data['simulated_'+key]
        wa=audit['weight_audit']
        entry['converted_negative_count']+=wa['negative_count']
        entry['weight_min']=wa['min'] if entry['weight_min'] is None else min(entry['weight_min'],wa['min'])
        entry['weight_max']=wa['max'] if entry['weight_max'] is None else max(entry['weight_max'],wa['max'])
        entry['cross_sections_pb'].append(data['sigma_pb'])
        for key in ('zero_momentum_charged','zero_momentum_selected_charged'): entry[key]+=audit['reco_diagnostics'][key]
        entry['missing_event_ids'].extend([[task['run'],i] for i in data['event_selection']['missing_ids_before_last_output']])
        entry['max_truth_momentum_difference_gev']=max(entry['max_truth_momentum_difference_gev'],audit['max_momentum_difference_gev'])
        entry['max_relative_vertex_difference_mm']=max(entry['max_relative_vertex_difference_mm'],audit['max_relative_vertex_difference_mm'])
        if audit['errors'] or not wa['passed']: failures.append(dict(task=task['id'],error='Audit failed'))
    passed=not failures and len(processes)==8 and all(p['converted']==1000 and p['chunks']==10 for p in processes.values())
    report=dict(passed=passed,processes=processes,failures=failures,
                scope='Weight persistence, identity and numerical/content sanity; not physics or data/MC closure.')
    c.write(root/'weight-validation.json',report)
    print(json.dumps(report,indent=2))
    return passed


def run(root):
    c.compute()
    c.write(root/'allocation.json',dict(job=os.environ['SLURM_JOB_ID'],host=__import__('socket').gethostname()))
    build=root/'source/sim/production/build_campaign.py'
    command=[sys.executable,str(build),'--site',str(root/'site.json'),'--sim-repo',str(root/'source/sim'),
             '--edm-repo',str(root/'source/edm')]
    subprocess.run(command,check=True)
    env=dict(os.environ,FLEET_JOB_INDEX='0',SLURM_PROCID='0')
    command=[sys.executable,str(root/'source/sim/production/node_runtime.py'),'launch',str(root),'80']
    completed=subprocess.run(command,env=env)
    passed=summarize(root)
    if completed.returncode or not passed: raise RuntimeError('Full-chain validation failed; see weight-validation.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action');sub.required=True
    p=sub.add_parser('prepare');p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    p.add_argument('--controller',required=True);p.add_argument('--edm-repo',required=True)
    for name in ('run','summarize'):sub.add_parser(name).add_argument('root')
    args=parser.parse_args()
    if args.action=='prepare':prepare(args)
    elif args.action=='run':run(Path(args.root).resolve())
    elif not summarize(Path(args.root).resolve()):sys.exit(1)
