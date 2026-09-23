#!/usr/bin/env python3
"""Prepare/build a reusable installation, or verify it without running a container."""
import argparse, hashlib, json, os, pathlib, shutil, socket, subprocess
P=pathlib.Path
BINARIES=['generate','hepmc2fadgen','converter/delphi_sdst_pass']
def digest(p):return hashlib.sha256(P(p).read_bytes()).hexdigest()
def read(p):return json.loads(P(p).read_text())
def identity(sim,edm,site):
    files={'sim/'+n:digest(sim/n) for n in ['production/generate.cpp','hepmc2fadgen.cpp','production/build.sh','production/build_campaign.py','production/no-eos.sh']}
    for p in sorted((edm/'delphi_edm4hep').rglob('*')):
        if p.is_file() and not any(x in p.relative_to(edm).parts for x in ['build','__pycache__','.git']):files['edm/'+str(p.relative_to(edm))]=digest(p)
    return {'files':files,'image':site['image'],'key4hep_release':site['key4hep_release']}
def verify(build,expected):
    m=read(build/'build-manifest.json')
    if m.get('identity')!=expected:raise ValueError('Build is incompatible with sources/image/environment; prepare a new build_root')
    if set(m['binaries'])!=set(BINARIES):raise ValueError('Incomplete build manifest')
    for n,h in m['binaries'].items():
        if digest(build/n)!=h:raise ValueError('Build binary changed: '+n)
    return m

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--site',required=True);p.add_argument('--sim-repo',required=True);p.add_argument('--edm-repo',required=True)
    p.add_argument('--prepare-only',action='store_true');p.add_argument('--verify',action='store_true');a=p.parse_args()
    site=read(a.site);sim=P(a.sim_repo).resolve();edm=P(a.edm_repo).resolve();b=P(site['build_root']).resolve();expected=identity(sim,edm,site)
    if a.verify or (b/'build-manifest.json').exists():
        verify(b,expected);print('Verified reusable build: '+str(b));return
    b.mkdir(parents=True,exist_ok=True)
    # One builder owns this directory; interrupted partial preparation is never overwritten.
    inputs=b/'build-inputs.json'
    if inputs.exists():
        if read(inputs)!=expected:raise ValueError('Build directory has different inputs; choose a new build_root')
    else:
        with inputs.open('x') as f:json.dump(expected,f,indent=2)
        source=b/'source';source.mkdir()
        for repo,name in [(sim,'sim'),(edm,'edm')]:
            shutil.copytree(str(repo),str(source/name),ignore=shutil.ignore_patterns('.git','build','__pycache__','*.root','*.sif','*.tgz'))
        (b/'site.json').write_text(json.dumps(site,indent=2)+'\n')
    if identity(b/'source/sim',b/'source/edm',site)!=expected:raise ValueError('Frozen build sources are incomplete or changed')
    if a.prepare_only:print('Prepared reusable build: '+str(b));return
    if not os.environ.get('SLURM_JOB_ID') or not socket.gethostname().startswith('nid'):raise RuntimeError('Compilation requires an approved compute allocation; preparation is complete')
    with (b/'BUILDING').open('x') as lock:lock.write(os.environ['SLURM_JOB_ID'])
    cmd=['podman-hpc','run','--rm','--entrypoint','/bin/bash','-v','/cvmfs:/cvmfs:ro','-v',str(b/'source/sim')+':/sim:ro','-v',str(b/'source/edm')+':/edm:ro','-v',str(b)+':/build','-v',str(b/'source/sim/production/no-eos.sh')+':/delphi/env/mount_eos.sh:ro','-e','BUILD_DIR=/build','-e','SIM_REPO=/sim','-e','EDM_REPO=/edm','-e','BUILD_CPUS='+str(site.get('build_cpus',4)),'-e','KEY4HEP_RELEASE='+site['key4hep_release'],site['image'],'/sim/production/build.sh']
    try:
        with (b/'build.log').open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
        manifest={'identity':expected,'binaries':{n:digest(b/n) for n in BINARIES},'slurm_job_id':os.environ['SLURM_JOB_ID']}
        (b/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');verify(b,expected)
    finally:(b/'BUILDING').unlink()
    print('Built and verified: '+str(b))
if __name__=='__main__':main()
