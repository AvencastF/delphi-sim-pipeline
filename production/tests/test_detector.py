"""Lightweight card/provenance checks; never invoke simulation or Slurm."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

PRODUCTION = Path(__file__).resolve().parents[1]
WORKSPACE = PRODUCTION.parents[1]
PROFILES = WORKSPACE / 'long_production/configs/detectors'
spec = importlib.util.spec_from_file_location('detector', PRODUCTION / 'detector.py')
detector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(detector)


class DetectorTests(unittest.TestCase):
    def test_all_eight_catalog_points_and_retained_cards(self):
        points = json.loads((WORKSPACE / 'long_production/configs/catalog.json').read_text())['points']
        expected = {1992: 'v92e', 1993: 'v93d', 1994: 'v94c', 1995: 'v95d'}
        self.assertEqual(len(points), 8)
        for point in points:
            with self.subTest(point=point['id']), tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(point['detector'], expected[point['year']])
                p = detector.profile(PROFILES, point['detector'], point['year'])
                detector.render(PROFILES, {'point': point, 'simulated_requested': 17, 'run': 123}, tmp)
                sim = (Path(tmp) / 'simulation.title').read_text()
                reco = (Path(tmp) / 'reconstruction.title').read_text()
                self.assertRegex(sim, r'(?m)^EBEAM ' + format(point['beam_gev'], '.6f') + '$')
                self.assertRegex(reco, r'(?m)^ECMLEP ' + format(point['ecm_gev'], '.6f') + '$')
                self.assertRegex(sim, r'(?m)^IRUN -123$')
                self.assertRegex(sim, r'(?m)^LUDECV TRUE$')
                # Every original line except the explicitly allowed runtime overrides
                # must survive verbatim, including all geometry/database requests.
                sim_keys = set(json.loads((Path(tmp) / 'detector-profile.json').read_text())['overrides'])
                for name, rendered, keys in [(p['simulation_card'], sim, sim_keys),
                                            ('delana.tit', reco, {'NEVMAX', 'ECMLEP', 'LABO', 'MBLIMI'})]:
                    source = (PROFILES / point['detector'] / name).read_text()
                    retained = lambda text: [line for line in text.splitlines()
                        if line.strip() and not any(re.match(r'^' + key + r'\s+', line) for key in keys)]
                    self.assertEqual(retained(source), retained(rendered))

    def test_invalid_year_and_version_rejected(self):
        for version, year in [('v94c', 1993), ('v92e', 1991), ('unknown', 1994)]:
            with self.subTest(version=version, year=year), self.assertRaises(ValueError):
                detector.profile(PROFILES, version, year)

    def test_changed_pinned_card_and_manifest_year_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(PROFILES / 'manifest.json', root)
            shutil.copytree(PROFILES / 'v92e', root / 'v92e')
            card = root / 'v92e/delana.tit'
            card.write_text(card.read_text() + '\nC changed\n')
            with self.assertRaisesRegex(ValueError, 'Pinned detector card changed'):
                detector.profile(root, 'v92e', 1992)
            manifest = json.loads((root / 'manifest.json').read_text())
            manifest['profiles']['v92e']['year'] = 1993
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'version/year mismatch'):
                detector.profile(root, 'v92e', 1992)

    def test_installed_files_and_binary_receipt(self):
        for version in ('v92e', 'v93d', 'v94c', 'v95d'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(PROFILES / version, root / 'dat')
                # Database payloads are not vendored; use explicit synthetic hashes
                # for those files, retaining the real pinned title/deck checks.
                fixture_profiles = root / 'profiles'
                fixture_profiles.mkdir()
                shutil.copytree(PROFILES / version, fixture_profiles / version)
                manifest = json.loads((PROFILES / 'manifest.json').read_text())
                for name, info in manifest['profiles'][version]['files'].items():
                    target = root / 'dat' / name
                    if not target.exists():
                        target.write_bytes(b'synthetic database ' + name.encode())
                        info['sha256'] = detector.sha(target)
                (fixture_profiles / 'manifest.json').write_text(json.dumps(manifest))
                for folder, names in [('bin', ('simrun36', 'delana43.exe', 'longdst.exe')),
                                      ('blkd', ('dtbzeb.datwri', 'simdec.data'))]:
                    (root / folder).mkdir()
                    for name in names:
                        (root / folder / name).write_bytes(b'fixture ' + name.encode())
                receipt = detector.verify_install(fixture_profiles, version, root)
                self.assertEqual(receipt['executables']['simrun36'], detector.sha(root / 'bin/simrun36'))
                (root / 'bin/simrun36').write_bytes(b'changed fixture')
                changed = detector.verify_install(fixture_profiles, version, root)
                self.assertNotEqual(receipt['executables'], changed['executables'])
                (root / 'bin/simrun36').unlink()
                with self.assertRaisesRegex(ValueError, 'Missing detector executable'):
                    detector.verify_install(fixture_profiles, version, root)
                (root / 'bin/simrun36').write_bytes(b'fixture')
                block = root / 'blkd/simdec.data'
                block.unlink()
                with self.assertRaisesRegex(ValueError, 'Missing detector block data'):
                    detector.verify_install(fixture_profiles, version, root)
                block.write_bytes(b'fixture')
                (root / 'dat/longdst.des').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'differs from pinned'):
                    detector.verify_install(fixture_profiles, version, root)

    def test_legacy_1994_commands_unchanged(self):
        old = subprocess.check_output(['git', '-C', str(PRODUCTION.parent), 'show',
                                       'HEAD:production/runtime.sh'], text=True)
        new = (PRODUCTION / 'runtime.sh').read_text()
        # Compare the actual default branch commands with the committed runtime.
        def legacy_commands(text):
            return [line.strip() for line in text.splitlines() if
                    line.strip().startswith(('cp /delphi/', 'runsim -VERSION v94c ', 'test -s simana.ldst'))]
        self.assertEqual(legacy_commands(new), legacy_commands(old))
        self.assertEqual(len(legacy_commands(old)), 3)
        subprocess.run(['bash', '-n', str(PRODUCTION / 'runtime.sh')], check=True)


if __name__ == '__main__':
    unittest.main()
