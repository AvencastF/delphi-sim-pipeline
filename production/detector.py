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
    patch = p.get('simulation_card_patch')
    if patch and (patch['file'] != p['simulation_card'] or
                  patch['official_sha256'] != p['files'][patch['file']]['sha256']):
        raise ValueError('Simulation card patch does not apply to the pinned official card')
    return p


def enclosing_block(lines, i):
    """Header of the card block holding line i (a bare keyword line above it with no
    blank line in between, e.g. DDMLC), or None for a top-level card such as VTAU."""
    for line in reversed(lines[:i]):
        if not line.strip():
            return None
        if re.fullmatch(r'[A-Z][A-Z0-9]*', line.strip()):
            return line.strip()
    return None


def simulation_card(root, version, p):
    """Official card text, plus the manifest's documented patch edits if present.

    The pinned file stays byte-identical to the CERN source. Each edit replaces one
    line, anchored by its official line number, exact old text and enclosing block
    (null for a top-level card); its new text may add lines. Edits are applied from
    the bottom up, so every anchor refers to the official numbering, and the hash of
    the result is pinned.
    """
    text = (Path(root) / version / p['simulation_card']).read_text()
    patch = p.get('simulation_card_patch')
    if not patch:
        return text
    lines = text.split('\n')
    for edit in sorted(patch['edits'], key=lambda e: e['line'], reverse=True):
        i = edit['line'] - 1
        anchor = 'Simulation card patch anchor not found: ' + str(edit['block']) + ' line ' + str(edit['line'])
        if not 0 < i < len(lines) or lines[i] != edit['old'] or enclosing_block(lines, i) != edit['block']:
            raise ValueError(anchor)
        lines[i:i + 1] = edit['new'].split('\n')
    text = '\n'.join(lines)
    if hashlib.sha256(text.encode()).hexdigest() != patch['patched_sha256']:
        raise ValueError('Patched simulation card differs from pinned patched hash')
    return text


def check_simulation_log(root, task, log):
    """Require the log signature of every card patch edit that has one; None without checks."""
    point = task['point']
    patch = profile(root, point['detector'], point['year']).get('simulation_card_patch') or {}
    checks = [e['simulate_log_check'] for e in patch.get('edits', []) if e.get('simulate_log_check')]
    if not checks:
        return None
    text = Path(log).read_text(errors='replace')
    results = []
    for check in checks:
        found = sorted(set(re.findall(check['pattern'], text)))
        found = [list(x) if isinstance(x, tuple) else [x] for x in found]
        if found != [check['expected']]:
            raise ValueError('Simulate log does not show the patched detector mode: ' + json.dumps(found))
        results.append(dict(check, found=found))
    return {'checks': results, 'log_sha256': sha(log)}


def fadgen_args(root, task):
    """Extra hepmc2fadgen options this detector profile requires (none for most years)."""
    point = task['point']
    return list((profile(root, point['detector'], point['year']).get('fadgen_options') or {}).get('args', []))


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
    text = simulation_card(root, version, p)
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
