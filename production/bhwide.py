"""BHWIDE fixed-trial generation with uniform fixed-size output sampling.

The full trial batch determines sigma; selected events retain their raw weights.
Detector IDs are sequential; original trial IDs remain explicit in the CSV.
"""
import csv, hashlib, json, math, pathlib, random, subprocess, sys
P = pathlib.Path

def verify(build, site, sim):
    manifest = build / 'manifest.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != site['bhwide_manifest_sha256']:
        raise ValueError('BHWIDE installation manifest changed')
    data = json.loads(manifest.read_text())
    for name, digest in data['files'].items():
        if hashlib.sha256((build/name).read_bytes()).hexdigest() != digest:
            raise ValueError('BHWIDE installation changed: '+name)
    for name in ('driver.f90', 'rng.cc', 'build.sh'):
        if hashlib.sha256((sim/'generators/bhwide'/name).read_bytes()).hexdigest() != data['files']['adapter/'+name]:
            raise ValueError('BHWIDE compiled source changed: '+name)
    if data['image'] != site['image'] or data['key4hep_release'] != site['key4hep_release']:
        raise ValueError('BHWIDE installation environment mismatch')

def select(raw, destination, count, seed):
    g = json.loads((raw/'generation.json').read_text())
    blocks = []
    for line in (raw/'events.hepmc3').read_text().splitlines(True):
        if line.startswith('E '): blocks.append([])
        if blocks and not line.startswith('HepMC::'): blocks[-1].append(line)
    if len(blocks) != g['generated'] or len(blocks) < count:
        raise ValueError('Insufficient nonzero-weight BHWIDE records; no automatic retry')
    rng = random.Random('bhwide-output-sampling:'+str(seed))
    # Shuffle the uniform subset so every detector prefix is representative.
    selected = rng.sample(blocks, count)
    weights = []
    with (destination/'events.hepmc3').open('x') as out, (destination/'event-weights.csv').open('x',newline='') as f:
        writer = csv.writer(f); writer.writerow(['hepmc_event','weight','generator_trial'])
        out.write('HepMC::Version 3.03.01\nHepMC::Asciiv3-START_EVENT_LISTING\n')
        for ident, block in enumerate(selected,1):
            h=block[0].split(); trial=int(h[1]);h[1]=str(ident);block[0]=' '.join(h)+'\n'
            weightlines=[line for line in block if line.startswith('W ')]
            if len(weightlines)!=1 or len(weightlines[0].split())!=2:raise ValueError('Invalid nominal weight')
            weight=float(weightlines[0].split()[1])
            if not math.isfinite(weight):raise ValueError('Invalid BHWIDE output weight')
            weights.append(weight);writer.writerow([ident,format(weight,'.17e'),trial]);out.writelines(block)
        out.write('HepMC::Asciiv3-END_EVENT_LISTING\n')
    summary=dict(requested=count,generated=count,attempts=g['trials'],sumw=sum(weights),sumw2=sum(w*w for w in weights),
        sigma_mb=g['sigma_pb']/1e9,sigma_error_mb=g['sigma_error_pb']/1e9,
        generator='BHWIDE 1.05',full_trial_batch=g,
        sampling='Uniform subset without replacement of nonzero-weight records; randomized output order; raw weights retained. Normalize selected output using sigma/sumw.',
        negative_events=sum(w<0 for w in weights), negative_sumw=sum(w for w in weights if w<0),
        effective_events=sum(weights)**2/sum(w*w for w in weights) if any(weights) else 0.)
    (destination/'generation.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    return summary

def main():
    count,seed=map(int,sys.argv[1:]);root=P.cwd();raw=root/'bhwide-raw';raw.mkdir()
    if min(count,seed)<1:raise ValueError('Invalid count or seed')
    subprocess.run(['/bhwide/bhwide',str(4*count),str(seed),str(root/'card.dat')],cwd=raw,check=True)
    subprocess.run([sys.executable,'/sim/generators/bhwide/export.py',str(raw)],check=True)
    select(raw,root,count,seed)

if __name__=='__main__':main()
