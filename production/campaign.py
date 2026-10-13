#!/usr/bin/env python3
"""Small, file-based NERSC campaign runner. Preparing never submits or runs MC."""
import argparse, concurrent.futures, csv, hashlib, json, math, os, pathlib, re
import resource, shlex, shutil, signal, socket, struct, subprocess, sys, time, uuid
P=pathlib.Path
HERE=P(__file__).resolve().parent
NODE_ENVIRONMENTS=None
CACHED_PLAN=None

def campaign_plan(root):
 return CACHED_PLAN if CACHED_PLAN is not None else read(root/'plan.json')

def shell_command(args):return ' '.join(shlex.quote(str(x)) for x in args)

def read(p): return json.loads(P(p).read_text())
def write(p,obj):
 p=P(p);tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
 tmp.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n');os.replace(tmp,p)
def digest(p):
 h=hashlib.sha256()
 with P(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def git(repo):return subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],universal_newlines=True).strip()
def compute():
 if not os.environ.get('SLURM_JOB_ID') or not socket.gethostname().startswith('nid'):
  raise RuntimeError('Execution requires an approved Slurm compute-node step')
def safe_name(s):
 if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',s):raise ValueError('Unsafe campaign name')
 return s

def prepare(a):
 config=P(a.config_dir).resolve()
 site=read(a.site);cat=read(config/'catalog.json');names=a.processes.split(',');points=a.points.split(',')
 selected=[p for p in cat['points'] if p['id'] in points or points==['all']]
 if not selected or (points!=['all'] and set(points)!={p['id'] for p in selected}):raise ValueError('Unknown energy point')
 if set(names)-cat['processes'].keys():raise ValueError('Unknown process')
 if min(a.events,a.chunks,a.nodes,a.workers,a.seed_start,a.run_start)<=0:raise ValueError('Counts and identifier bases must be positive')
 if a.workers>128:raise ValueError('At most 128 workers per CPU node; benchmark before selecting')
 if a.qos in ('shared','shared_interactive') and (a.nodes!=1 or a.workers>64):raise ValueError('Shared profile: one node and <=64 workers')
 if a.qos in ('debug','debug_preempt') and a.minutes>30:raise ValueError('Debug walltime <=30 minutes')
 if a.mode=='chain':
  if any(p['year']!=1994 for p in selected) and not getattr(a,'detector_validation',False):raise ValueError('Other detector-year title/conditions not validated; xsec scans are allowed')
  if any(cat['processes'][n]['generator'] not in ('pythia8','bhwide') for n in names):raise ValueError('Generator detector boundary is not validated')
 if getattr(a,'detector_validation',False):
  from detector import profile
  if a.mode!='chain':raise ValueError('Detector validation requires chain mode')
  for point in selected:profile(config/'detectors',point['detector'],point['year'])
  requests=read(a.workload) if getattr(a,'workload',None) else [{'events':a.events} for _ in range(len(selected)*len(names)*a.chunks)]
  if len(requests)>56 or any(not isinstance(r['events'],int) or not 0<r['events']<=100 for r in requests):raise ValueError('Detector validation is bounded to 56 chunks of at most 100 generated events')
  site['detector_validation']=True;site['diagnostic_only']=True
  site['retention']['remove_scratch_after_publish']=False
 root=P(a.output).resolve();root.mkdir(parents=True,exist_ok=False)
 edm=P(a.edm_repo).resolve();sim=HERE.parent
 # Freeze the actual working trees, including new production tooling. Avoid mutable code dependencies.
 source=root/'source';source.mkdir()
 for repo,name in [(sim,'sim'),(edm,'edm')]:
  shutil.copytree(repo,source/name,ignore=shutil.ignore_patterns('.git','build','__pycache__','*.sif','*.root','*.tgz'))
 if config!=HERE:
  (source/'sim/production/cards').mkdir(exist_ok=True)
  shutil.copy2(config/'catalog.json',source/'sim/production/catalog.json')
  shutil.copy2(config/'simulation-1994.title',source/'sim/production/simulation-1994.title')
  if getattr(a,'detector_validation',False):shutil.copytree(config/'detectors',source/'sim/production/detectors')
  for card_file in (config/'cards').iterdir():
   if card_file.is_file():shutil.copy2(card_file,source/'sim/production/cards'/card_file.name)
 source_manifest={str(p.relative_to(source)):digest(p) for p in source.rglob('*') if p.is_file()}
 write(root/'source-manifest.json',source_manifest)
 tasks=[]
 requests=read(a.workload) if getattr(a,'workload',None) else [
  {'process':name,'point':point['id'],'events':a.events,'chunk':chunk}
  for point in selected for name in names for chunk in range(a.chunks)]
 points_by_id={p['id']:p for p in selected}
 for request in requests:
  name=request['process'];point=points_by_id[request['point']]
  if name not in names:raise ValueError('Workload process outside configured selection')
  proc=cat['processes'][name];idx=len(tasks);seed=a.seed_start+idx;run=a.run_start+idx
  events=request['events']
  if not isinstance(events,int) or events<=0:raise ValueError('Invalid workload event count')
  if seed>900000000 or run>999999:raise ValueError('Seed/run bounds exceeded')
  task={'id':f'{idx:06d}','process':name,'point':point,'generator':proc['generator'],'seed':seed,'run':run,'generated_requested':events,'simulated_requested':math.floor(events*site['simulation_fraction']) if a.mode=='chain' else 0,'chunk':request['chunk'],'mode':a.mode}
  if getattr(a,'detector_validation',False):task['detector_profile']='pinned-validation'
  if 'estimated_seconds' in request:task['estimated_seconds']=request['estimated_seconds']
  if a.mode=='chain' and task['simulated_requested']==0:raise ValueError('Simulation target is zero')
  card=(config/'cards'/proc['card']).read_text()
  if proc['generator']=='pythia8':card+=f'\nBeams:eCM = {point["ecm_gev"]:.6f}\nRandom:setSeed = on\nRandom:seed = {seed}\n'
  else:
   for k,v in {'ECM':point['ecm_gev'],'SEED':seed,'EVENTS':events}.items():card=card.replace('@'+k+'@',str(v))
  task['card']=card;task['card_sha256']=hashlib.sha256(card.encode()).hexdigest();tasks.append(task)
 if len(tasks)<a.nodes*a.workers:raise ValueError('More workers than chunks wastes resources: lower nodes/workers or increase chunks')
 plan={'schema':1,'name':safe_name(a.name),'site':site,'mode':a.mode,'tasks':tasks,'nodes':a.nodes,'workers_per_node':a.workers,'minutes':a.minutes,'qos':a.qos,'source_revisions':{'sim':git(sim),'edm':git(edm)},'source_manifest_sha256':digest(root/'source-manifest.json'),'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'status':'prepared-not-submitted','physics_catalog':cat}
 write(root/'plan.json',plan);(root/'logs').mkdir();(root/'work').mkdir();(root/'claims').mkdir();(root/'results').mkdir()
 launcher=source/'sim/production/campaign.py'
 command=shell_command(['python3',str(launcher),'worker',str(root)])
 script=f'''#!/bin/bash
#SBATCH --account={site['account']}
#SBATCH --qos={a.qos}
#SBATCH --constraint=cpu
#SBATCH --nodes={a.nodes}
#SBATCH --ntasks-per-node={a.workers}
#SBATCH --cpus-per-task=2
#SBATCH --mem={max(4, a.workers*2)}G
#SBATCH --time={a.minutes}
#SBATCH --licenses=scratch,cfs
#SBATCH --output={root}/logs/slurm-%j.out
#SBATCH --error={root}/logs/slurm-%j.err
set -euo pipefail
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
# Each rank is a single serial worker bound to a physical core; claims balance uneven chunks.
srun --cpu-bind=cores --kill-on-bad-exit=0 {command}
python3 {shlex.quote(str(launcher))} status {shlex.quote(str(root))} --require-complete
'''
 if not getattr(a,'workload',None):(root/'job.sbatch').write_text(script)
 print(json.dumps({'plan':str(root/'plan.json'),'job':str(root/'job.sbatch') if (root/'job.sbatch').exists() else None,'tasks':len(tasks),'requested_generated':sum(t['generated_requested'] for t in tasks),'requested_simulated':sum(t['simulated_requested'] for t in tasks),'submission':'NOT SUBMITTED'},indent=2))

def command(root,task,stage,args):
 plan=campaign_plan(root);site=plan['site'];work=root/'work'/task['id'];build=P(site['build_root'])
 if NODE_ENVIRONMENTS is not None:
  return ['/bin/bash','--noprofile','--norc','/sim/production/runtime.sh',stage]+list(map(str,args))
 return (['podman-hpc','run']+(['-v',str(site['bhwide_build_root'])+':/bhwide:ro'] if site.get('bhwide_build_root') else [])+['--rm','--network=none','--name',f'long-{os.environ["SLURM_JOB_ID"]}-{task["id"]}-{stage}', '--entrypoint','/bin/bash','-e','OMP_NUM_THREADS=1','-e','OPENBLAS_NUM_THREADS=1','-e','MKL_NUM_THREADS=1','-v','/cvmfs:/cvmfs:ro','-v',str(root/'source/sim')+':/sim:ro','-v',str(root/'source/edm')+':/edm:ro','-v',str(build)+':/build:ro','-v',str(work)+':/workdir','-v',str(root/'source/sim/production/no-eos.sh')+':/delphi/env/mount_eos.sh:ro','-w','/workdir',site['image'],'/sim/production/runtime.sh',stage]+list(map(str,args)))

def remaining_seconds(site):
 return int(os.environ.get('SLURM_JOB_END_TIME',int(time.time())+100000))-time.time()-site.get('worker_finish_reserve_seconds',0)

def stage_run(root,t,name,args):
 cmd=command(root,t,name,args);log=root/'logs'/(t['id']+'-'+name+'.log');start=time.time()
 with log.open('w') as f:
  f.write(shell_command(cmd)+'\n');f.flush()
  env=None;cwd=None
  if NODE_ENVIRONMENTS is not None:
   env=dict(NODE_ENVIRONMENTS[name],LONG_STAGE_ENV_READY=name,SLURM_PROCID=os.environ['SLURM_PROCID'],TMPDIR=str(root/'work'/t['id']/'tmp'))
   cwd=str(root/'work'/t['id'])
  child=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,env=env,cwd=cwd)
  try:
   remaining=remaining_seconds(campaign_plan(root)['site'])-60
   code=child.wait(timeout=max(1,min(remaining,campaign_plan(root)['site']['stage_timeout_seconds'])))
  except subprocess.TimeoutExpired:
   if NODE_ENVIRONMENTS is None:
    subprocess.run(['podman-hpc','stop','--time','10',f'long-{os.environ["SLURM_JOB_ID"]}-{t["id"]}-{name}'],stdout=f,stderr=f)
    child.wait(timeout=30)
   else:
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:child.wait(timeout=10)
    except subprocess.TimeoutExpired:
     try:os.killpg(child.pid,signal.SIGKILL)
     except ProcessLookupError:pass
     child.wait()
    # The shell may have exited while a descendant ignored SIGTERM.
    try:os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError:pass
   code=124
 record={'stage':name,'exit_code':code,'wall_seconds':time.time()-start,'log':str(log)}
 write(root/'work'/t['id']/(name+'-resource.json'),record)
 if code:raise RuntimeError(f'{name} failed ({code}); see {log}')
 return record

def fadgen_count(path):
 count=0
 with P(path).open('rb') as f:
  while True:
   h=f.read(4)
   if len(h)!=4:raise ValueError('Missing FADGEN terminator')
   size,=struct.unpack('<i',h)
   if not 4<=size<=4000000:raise ValueError('Invalid FADGEN record size')
   data=f.read(size)
   if f.read(4)!=h:raise ValueError('Truncated FADGEN record')
   n,=struct.unpack_from('<i',data)
   if n==0:return count
   if size!=4+60*n:raise ValueError('FADGEN shape mismatch')
   count+=1

def selected_weights(weights_path,events_path):
 weights={}
 with P(weights_path).open() as f:
  for row in csv.DictReader(f):
   event=int(row['hepmc_event'])
   if event in weights:raise ValueError('Duplicate generator weight identity')
   weights[event]=float(row['weight'])
 with P(events_path).open() as f:
  ids=[int(row['event']) for row in csv.DictReader(f)]
 if not ids or len(set(ids))!=len(ids):raise ValueError('Empty or duplicated converted event identities')
 if any(i not in weights for i in ids):raise ValueError('Converted event has no generator weight')
 return [weights[i] for i in ids],ids

def run_task(root,t):
 w=root/'work'/t['id'];w.mkdir(exist_ok=False)
 if NODE_ENVIRONMENTS is not None:(w/'tmp').mkdir()
 write(w/'task.json',t);stages=[]
 card=w/{'pythia8':'card.cmnd','bhwide':'card.dat','whizard':'card.sin'}[t['generator']];card.write_text(t['card'])
 if t['generator']=='bhwide':
  stages.append(stage_run(root,t,'bhwide',[t['generated_requested'],t['seed']]))
 elif t['generator']=='whizard':
  stages.append(stage_run(root,t,'whizard',[]))
  from whizard_summary import export
  hepmc=w/'events.hepmc'
  if not hepmc.is_file():raise ValueError('WHIZARD expected HepMC output missing')
  write(w/'generation.json',export(root/'logs'/(t['id']+'-whizard.log'),hepmc,t['generated_requested'],w))
 else:
  stages.append(stage_run(root,t,'generate',[t['generated_requested']]))
 g=read(w/'generation.json')
 if g['generated']!=t['generated_requested'] or not all(math.isfinite(g[k]) for k in ('sigma_mb','sigma_error_mb','sumw','sumw2')) or g['sigma_mb']<=0 or g['sigma_error_mb']<0:raise ValueError('Invalid generator summary')
 result={'task':t,'generation':g,'sigma_pb':g['sigma_mb']*1e9,'sigma_error_pb':g['sigma_error_mb']*1e9,'stages':stages,'job_id':os.environ['SLURM_JOB_ID'],'node':socket.gethostname()}
 if t['mode']=='chain':
  stages.append(stage_run(root,t,'fadgen',[]))
  if fadgen_count(w/'my_events.fadgen')!=g['generated']:raise ValueError('Generator/FADGEN count mismatch')
  if t.get('detector_profile'):
   from detector import render
   render(root/'source/sim/production/detectors',t,w)
   stages.append(stage_run(root,t,'simulate',[t['run'],t['point']['beam_gev'],t['simulated_requested'],t['point']['detector']]))
  else:
   title=(root/'source/sim/production/simulation-1994.title').read_text()
   title=re.sub(r'^NEVMAX\s+\d+',f'NEVMAX {t["simulated_requested"]}',title,flags=re.M)
   title=re.sub(r'^IRUN\s+-?\d+',f'IRUN -{t["run"]}',title,flags=re.M)
   title=re.sub(r'^EBEAM\s+\S+',f'EBEAM {t["point"]["beam_gev"]:.6f}',title,flags=re.M)
   (w/'simulation.title').write_text(title)
   stages.append(stage_run(root,t,'simulate',[t['run'],t['point']['beam_gev'],t['simulated_requested']]))
  stages.append(stage_run(root,t,'convert',[]));audit=read(w/'audit/root-audit.json')
  if not 0 < audit['events'] <= t['generated_requested'] or audit['unique_identities']!=audit['events'] or audit['run_counts']!={str(-t['run']):audit['events']} or audit['errors']:raise ValueError('Converted event identity/count audit failed')
  if audit['fadgen_slot_comparable_events']!=audit['events'] or audit['max_momentum_difference_gev']>1e-6:raise ValueError('FADGEN/ROOT truth identity mismatch')
  weights,event_ids=selected_weights(w/'event-weights.csv',w/'audit/converted-events.csv')
  result['event_selection']={'converted_event_ids':event_ids,'missing_ids_before_last_output':sorted(set(range(1,max(event_ids)+1))-set(event_ids))}
  result['requires_event_loss_review']=bool(result['event_selection']['missing_ids_before_last_output'])
  result['counts']={'requested_generated':t['generated_requested'],'generated':g['generated'],'simulation_requested':t['simulated_requested'],'reconstructed':audit['events'],'converted':audit['events']}
  result['simulated_sumw']=sum(weights);result['simulated_sumw2']=sum(x*x for x in weights)
  result['outputs']={name:{'sha256':digest(w/name),'bytes':(w/name).stat().st_size} for name in set(['simana.ldst','events.edm4hep.root','longdst.des','simulation.title','event-weights.csv','events.hepmc3']+campaign_plan(root)['site'].get('retained_files',[]))}
 if t.get('detector_profile') and t['mode']=='chain':
  for name in ('detector-profile.json','detector-install.json','reconstruction.title'):
   result['outputs'][name]={'sha256':digest(w/name),'bytes':(w/name).stat().st_size}
 write(root/'results'/(t['id']+'.json'),result)

def verify_inputs(root,p):
 # Once per node in the persistent runtime; once per rank in old campaigns.
 if digest(root/'source-manifest.json')!=p['source_manifest_sha256']:raise ValueError('Source manifest changed')
 for name,sha in read(root/'source-manifest.json').items():
  if digest(root/'source'/name)!=sha:raise ValueError('Frozen source changed: '+name)
 from build_campaign import identity,verify
 verify(P(p['site']['build_root']),identity(root/'source/sim',root/'source/edm',p['site']))
 if any(t['generator']=='bhwide' for t in p['tasks']):
  from bhwide import verify as verify_bhwide
  verify_bhwide(P(p['site']['bhwide_build_root']),p['site'],root/'source/sim')

def worker(a):
 compute();root=P(a.plan).resolve();p=read(root/'plan.json')
 verify_inputs(root,p)
 rank=int(os.environ.get('SLURM_PROCID',0));tasks=p['tasks']
 if 'FLEET_JOB_INDEX' in os.environ:
  selected_ids=p['fleet_jobs'][int(os.environ['FLEET_JOB_INDEX'])]['task_ids']
  by_id={t['id']:t for t in tasks}
  tasks=[by_id[ident] for ident in selected_ids]
 offset=rank%len(tasks)
 for t in tasks[offset:]+tasks[:offset]:
  remaining=remaining_seconds(p['site'])
  if remaining<180:break
  if remaining<float(t.get('estimated_seconds',120))+60:continue
  if (root/'results'/(t['id']+'.json')).exists():continue
  try:(root/'claims'/t['id']).mkdir()
  except FileExistsError:continue
  write(root/'claims'/t['id']/'owner.json',{'job':os.environ['SLURM_JOB_ID'],'rank':rank,'host':socket.gethostname(),'start':time.time()})
  try:run_task(root,t)
  except Exception as e:write(root/'claims'/t['id']/'failure.json',{'error':str(e),'time':time.time()})
 # Failed tasks stay claimed; never regenerate or silently retry them.

def status(a):
 root=P(a.plan);plan=read(root/'plan.json');rows=[];failed=[];missing=[];review=[]
 for t in plan['tasks']:
  p=root/'results'/(t['id']+'.json')
  if p.exists():
   r=read(p)
   if r.get('requires_event_loss_review'):review.append(t['id'])
   rows.append({'task':t['id'],'process':t['process'],'point':t['point']['id'],'ecm_gev':t['point']['ecm_gev'],'generated':r['generation']['generated'],'sigma_pb':r['sigma_pb'],'sigma_error_pb':r['sigma_error_pb'],'card_sha256':t['card_sha256']})
  elif (root/'claims'/t['id']/'failure.json').exists():failed.append(t['id'])
  else:missing.append(t['id'])
 with (root/'cross-sections.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=['task','process','point','ecm_gev','generated','sigma_pb','sigma_error_pb','card_sha256']);w.writeheader();w.writerows(rows)
 print(json.dumps({'complete':len(rows),'failed':failed,'pending_or_interrupted':missing,'event_loss_review_required':review,'total':len(plan['tasks'])},indent=2))
 if a.require_complete and (failed or missing or review):raise SystemExit(1)

def main():
 ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='cmd');sub.required=True
 p=sub.add_parser('prepare');p.add_argument('--detector-validation',action='store_true',help='Bounded pinned year-profile validation; no production approval');p.add_argument('--name',required=True);p.add_argument('--output',required=True);p.add_argument('--site',required=True);p.add_argument('--workload',help='Explicit heterogeneous chunk requests JSON');p.add_argument('--config-dir',required=True,help='External catalog, cards and simulation title directory');p.add_argument('--edm-repo',required=True);p.add_argument('--mode',choices=['xsec','chain'],default='xsec');p.add_argument('--processes',required=True);p.add_argument('--points',default='1994_91p2');p.add_argument('--events',type=int,required=True);p.add_argument('--chunks',type=int,default=1);p.add_argument('--nodes',type=int,default=1);p.add_argument('--workers',type=int,default=4);p.add_argument('--minutes',type=int,default=30);p.add_argument('--qos',choices=['shared','regular','debug'],default='shared');p.add_argument('--seed-start',type=int,required=True);p.add_argument('--run-start',type=int,required=True);p.set_defaults(func=prepare)
 p=sub.add_parser('worker');p.add_argument('plan');p.set_defaults(func=worker)
 p=sub.add_parser('status');p.add_argument('plan');p.add_argument('--require-complete',action='store_true');p.set_defaults(func=status)
 a=ap.parse_args();a.func(a)
if __name__=='__main__':main()
