#!/usr/bin/env python3
"""Fetch pinned public BHWIDE sources for review/build; never execute them."""
import hashlib,json,pathlib,sys,subprocess
REVISION='442ac586c1b4e308b13e1bb7ec4ff720163127ae'
FILES=['bhw/'+f+'.f' for f in ('bhwide','bhwid1','matrel','model1','model2','repi')]+['ewc/alibaba.f','ewc/babamc.f','glib/glibk.f','glib/yfslib.f','interface/intali.f','interface/intbab.f']
out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
manifest={'repository':'https://github.com/belle2/basf2','revision':REVISION,'files':{}}
for name in FILES:
 url=f'https://raw.githubusercontent.com/belle2/basf2/{REVISION}/generators/bhwide/bhwide/{name}'
 data=subprocess.check_output(['curl','--silent','--show-error','--fail','--location','--max-time','30',url])
 path=out/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
 manifest['files'][name]={'url':url,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Downloaded',len(FILES),'source files at',REVISION)
