"""Strict WHIZARD single-process integration/HepMC ASCII summary.

Fails on unfamiliar output instead of inventing a cross section or unit weight.
The adapter still needs a test against the installed release before production.
"""
import csv,json,math,pathlib,re,sys

def weight_rescale(text,count):
 """WHIZARD drops zero-weight trials and reports N_written/N_trials."""
 dropped=re.findall(r'Dropped events \(weight zero\) =\s*(\d+)\s*\(total\s*(\d+)\)',text)
 factors=re.findall(r'All event weights must be rescaled by f =\s*([\d.EeDd+-]+)',text)
 if len(dropped)>1 or len(factors)>1:raise ValueError('Multiple WHIZARD samples in one log')
 if not dropped and not factors:return 1.0,count
 if not dropped or not factors:raise ValueError('Incomplete WHIZARD weight-rescale bookkeeping')
 zeros,total=map(int,dropped[0]);printed=float(factors[0].replace('D','E'))
 if total<=0 or total-zeros!=count:raise ValueError('WHIZARD trial count mismatch')
 factor=count/total
 if not math.isclose(printed,factor,rel_tol=1e-8):raise ValueError('WHIZARD weight-rescale mismatch')
 return factor,total

def parse_log(text):
 if 'Integral[fb]' not in text.replace(' ','') or 'Error[fb]' not in text.replace(' ',''):
  raise ValueError('Expected WHIZARD integration columns in fb')
 rows=[]
 for line in text.splitlines():
  line=line.strip(' |')
  m=re.match(r'^\d+\s+\d+\s+([+-]?[\d.]+[EeDd][+-]?\d+)\s+([+-]?[\d.]+[EeDd][+-]?\d+)\s',line)
  if m:rows.append(tuple(float(s.replace('D','E').replace('d','e')) for s in m.groups()))
 if not rows or rows[-1][0]<=0 or rows[-1][1]<0:raise ValueError('No valid integration estimate')
 return rows[-1]

def weights(path):
 out=[];current=None;weight=None
 for line in pathlib.Path(path).read_text().splitlines():
  if line.startswith('E '):
   if current is not None:
    if weight is None:raise ValueError('Missing event weight')
    out.append((current,weight))
   current=int(line.split()[1]);weight=None
  elif line.startswith('W '):
   values=line.split()[1:]
   if len(values)!=1:raise ValueError('Expected exactly one nominal weight')
   weight=float(values[0])
 if current is not None:
  if weight is None:raise ValueError('Missing event weight')
  out.append((current,weight))
 if not out or not all(math.isfinite(w) for _,w in out):raise ValueError('Invalid weights')
 return out

def summarize(log,hepmc,count):
 text=pathlib.Path(log).read_text()
 sigma,error=parse_log(text)
 # A valid weight vector alone does not certify unweighting or integration.
 if re.search(r'Encountered events with excess weight:\s*[1-9]\d*\s+events',text):
  raise ValueError('Unresolved WHIZARD excess-weight events')
 if error/sigma>0.01:
  raise ValueError('WHIZARD integration relative error exceeds diagnostic 1% gate')
 ws=weights(hepmc)
 if len({event for event,_ in ws})!=len(ws):raise ValueError('Duplicate WHIZARD event identity')
 if len(ws)!=count:raise ValueError('WHIZARD event count differs from request')
 factor,attempts=weight_rescale(text,count)
 # Integration estimate is in fb; downstream schema stores mb.
 return dict(requested=count,generated=len(ws),attempts=attempts,sumw=sum(w*factor for _,w in ws),sumw2=sum((w*factor)**2 for _,w in ws),raw_sumw=sum(w for _,w in ws),weight_rescale=factor,sigma_mb=sigma*1e-12,sigma_error_mb=error*1e-12,uncertainty='integration MC statistical only; no theory uncertainty')

def export(log,hepmc,count,destination):
 """Create a separate canonical HepMC and CSV; keep raw generator output intact."""
 destination=pathlib.Path(destination)
 summary=summarize(log,hepmc,count);factor=summary['weight_rescale']
 with (destination/'events.hepmc3').open('x') as output:
  for line in pathlib.Path(hepmc).read_text().splitlines():
   if line.startswith('W '):line='W '+format(float(line.split()[1])*factor,'.17e')
   output.write(line+'\n')
 with (destination/'event-weights.csv').open('x',newline='') as output:
  writer=csv.writer(output);writer.writerow(['hepmc_event','weight'])
  writer.writerows((event,format(w*factor,'.17e')) for event,w in weights(hepmc))
 return summary
