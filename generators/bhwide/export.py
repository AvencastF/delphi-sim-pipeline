#!/usr/bin/env python3
"""Convert the standalone diagnostic record to HepMC3 and explicit weights."""
import csv,json,math,pathlib,sys
root=pathlib.Path(sys.argv[1]);records=[]
with (root/'events.raw').open() as stream:
 for line in stream:
  h=line.split()
  if len(h)!=4 or h[0]!='E':raise ValueError('Invalid raw event')
  ident=int(h[1]);weight=float(h[2]);nphot=int(h[3]);particles=[]
  for _ in range(4+nphot):
   p=next(stream).split()
   if len(p)!=6:raise ValueError('Invalid particle')
   particles.append((int(p[0]),int(p[1]),*[float(x.replace('D','E')) for x in p[2:]]))
  if not math.isfinite(weight) or not all(math.isfinite(x) for p in particles for x in p[2:]):raise ValueError('Nonfinite record')
  records.append((ident,weight,particles))
lines=(root/'normalization.dat').read_text().splitlines()
trials,written,reported=map(int,lines[0].split());sigma,relative,crude=map(float,lines[1].split())
if not records or written!=len(records) or reported!=trials or trials<written:raise ValueError('Count mismatch')
if len({r[0] for r in records})!=written:raise ValueError('Duplicate event identity')
if not all(1<=r[0]<=trials for r in records):raise ValueError('Trial identity outside range')
sumw=sum(r[1] for r in records);sumw2=sum(r[1]**2 for r in records)
if not all(math.isfinite(x) for x in (sigma,relative,crude)) or min(sigma,crude)<=0 or relative<0:raise ValueError('Invalid cross section')
if not math.isclose(crude*sumw/trials,sigma,rel_tol=1e-8):raise ValueError('Cross-section/weight closure failed')
max_residual=0
with (root/'events.hepmc3').open('x') as out, (root/'event-weights.csv').open('x',newline='') as weights:
 writer=csv.writer(weights);writer.writerow(['hepmc_event','weight'])
 out.write('HepMC::Version 3.03.01\nHepMC::Asciiv3-START_EVENT_LISTING\n')
 for ident,weight,particles in records:
  if [(p[0],p[1]) for p in particles[:4]]!=[(11,4),(-11,4),(11,1),(-11,1)]:raise ValueError('Invalid lepton record')
  max_residual=max(max_residual,*(abs(sum(p[i] for p in particles[:2])-sum(p[i] for p in particles[2:])) for i in range(2,6)))
  out.write(f'E {ident} 1 {len(particles)}\nU GEV MM\nW {weight:.17e}\n')
  out.write(f'A 0 GenCrossSection {sigma:.17e} {sigma*relative:.17e} {written} {trials}\n')
  for index,(pdg,status,px,py,pz,energy) in enumerate(particles,1):
   if index==3:out.write('V -1 0 [1,2]\n')
   parent=0 if index<=2 else -1
   mass=math.sqrt(max(0,energy*energy-px*px-py*py-pz*pz))
   out.write(f'P {index} {parent} {pdg} {px:.17e} {py:.17e} {pz:.17e} {energy:.17e} {mass:.17e} {status}\n')
  writer.writerow([ident,format(weight,'.17e')])
 out.write('HepMC::Asciiv3-END_EVENT_LISTING\n')
summary=dict(generator='BHWIDE 1.05 Belle II mirror; standalone adapter',trials=trials,generated=written,
 zero_weight_trials=trials-written,sumw=sumw,sumw2=sumw2,sigma_pb=sigma,sigma_error_pb=sigma*relative,
 sigma_relative_error=relative,crude_sigma_pb=crude,max_four_momentum_residual_gev=max_residual,
 normalization='L_pb^-1 * crude_sigma_pb / trials * event_weight; equivalently L * sigma / sumw * event_weight',
 status='generator diagnostic; precision and detector validation pending')
(root/'generation.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
print(json.dumps(summary,indent=2))
