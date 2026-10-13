"""Pinned official LEP-1 cards; no year fallback or silent conditions substitution."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def profile(root, version, year):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    expected={1992:'v92e',1993:'v93d',1994:'v94c',1995:'v95d'}
    if expected.get(year)!=version:raise ValueError('Unsupported detector version/year')
    p = manifest['profiles'][version]
    if p['year'] != year:
        raise ValueError('Detector version/year mismatch')
    for name in (p['simulation_card'], 'delana.tit', 'longdst.des'):
        if sha(root / version / name) != p['files'][name]['sha256']:
            raise ValueError('Pinned detector card changed: ' + name)
    return p


def replace_card(text, key, value, insert=False):
    pattern = r'^' + re.escape(key) + r'\s+[^\n]*'
    text, count = re.subn(pattern, key + ' ' + str(value), text, flags=re.M)
    if count == 0 and insert:
        text, count = re.subn(r'^KEYS\s*$', key + ' ' + str(value) + '\nKEYS', text, flags=re.M)
    if count != 1:
        raise ValueError('Expected one card: ' + key)
    return text


def render(root, task, work):
    point = task['point']; version = point['detector']
    p = profile(root, version, point['year'])
    src = Path(root) / version; work = Path(work)
    text = (src / p['simulation_card']).read_text()
    # Same external-input, I/O and run controls as installed runsim, plus LUDECV.
    changes = {'NEVMAX': task['simulated_requested'], 'IRUN': -task['run'],
               'EBEAM': '%.6f' % point['beam_gev'], 'LRNRUN': 'TRUE',
               'ISEEDG': '-1 0 0', 'ISEEDS': '-1 0 0', 'IEXPNB': -2000,
               'LABO': "'CERN'", 'IGENER': 0, 'IDLUIN': 18,
               'IDTOUT': 7, 'ITOUT': 20, 'LOUTAN': 20, 'FLIMOU': '5000.',
               'WDBZEB': 'FALSE', 'LDBZEB': 'TRUE', 'LUNDBZ': 59,
               'LUDECV': 'TRUE'}
    for key, value in changes.items():
        text = replace_card(text, key, value, insert=(key == 'LUDECV'))
    if '{nrun}' in text or '$msimdev' in text or '$mstpdev' in text:
        raise ValueError('Unresolved simulation template')
    (work / 'simulation.title').write_text(text)
    reco = (src / 'delana.tit').read_text()
    for key, value in {'NEVMAX': task['simulated_requested'], 'ECMLEP': '%.6f' % point['ecm_gev'],
                       'LABO': "'CERN'", 'MBLIMI': '5000.'}.items():
        reco = replace_card(reco, key, value)
    (work / 'reconstruction.title').write_text(reco)
    (work / 'detector-profile.json').write_text(json.dumps(dict(p, version=version, overrides=changes), indent=2)+'\n')


def verify_install(root, version, install):
    p = json.loads((Path(root)/'manifest.json').read_text())['profiles'][version]
    profile(root, version, p['year'])
    install = Path(install)
    # Snapshot databases are external to the cards and must also match.
    for name, info in p['files'].items():
        if sha(install/'dat'/name) != info['sha256']:
            raise ValueError('Installed detector file differs from pinned CERN source: '+version+'/'+name)
    for name in ('simrun36', 'delana43.exe', 'longdst.exe'):
        if not (install/'bin'/name).is_file():
            raise ValueError('Missing detector executable: '+name)
    for name in ('dtbzeb.datwri', 'simdec.data'):
        if not (install/'blkd'/name).is_file():
            raise ValueError('Missing detector block data: '+name)
    return {'version': version, 'commit': p['commit'], 'source_files_verified': len(p['files']),
            'block_data': {n: sha(install/'blkd'/n) for n in ('dtbzeb.datwri','simdec.data')},
            'executables': {n: sha(install/'bin'/n) for n in ('simrun36','delana43.exe','longdst.exe')}}


if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('profiles');ap.add_argument('version');ap.add_argument('install')
    args=ap.parse_args()
    print(json.dumps(verify_install(args.profiles,args.version,args.install),indent=2))
