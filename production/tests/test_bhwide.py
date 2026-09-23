import importlib.util,json,pathlib,tempfile,unittest,csv
P=pathlib.Path
spec=importlib.util.spec_from_file_location('bhwide',P(__file__).parents[1]/'bhwide.py')
bhwide=importlib.util.module_from_spec(spec);spec.loader.exec_module(bhwide)

class Sampling(unittest.TestCase):
 def test_trial_gaps_and_weights_survive_sequential_mapping(self):
  with tempfile.TemporaryDirectory() as directory:
   root=P(directory);raw=root/'raw';raw.mkdir()
   trials={3:-0.4,7:2.0,19:0.8,30:1.4}
   (raw/'generation.json').write_text(json.dumps(dict(generated=4,trials=40,sigma_pb=12,sigma_error_pb=.3)))
   (raw/'events.hepmc3').write_text('HepMC::Asciiv3-START_EVENT_LISTING\n'+''.join('E %d 0 0\nU GEV MM\nW %.8f\n'%(i,w) for i,w in trials.items())+'HepMC::Asciiv3-END_EVENT_LISTING\n')
   g=bhwide.select(raw,root,4,12345)
   with (root/'event-weights.csv').open() as f:rows=list(csv.DictReader(f))
   self.assertEqual([int(r['hepmc_event']) for r in rows],[1,2,3,4])
   self.assertEqual(len({r['generator_trial'] for r in rows}),4)
   self.assertTrue(all(float(r['weight'])==trials[int(r['generator_trial'])] for r in rows))
   self.assertAlmostEqual(g['sumw'],sum(float(r['weight']) for r in rows))
   self.assertEqual(g['sigma_mb'],12e-9)
   self.assertEqual(g['attempts'],40)
   self.assertEqual(g['generated'],4)
   self.assertEqual(g['negative_events'],1)
   self.assertAlmostEqual(g['sumw2'],sum(w*w for w in trials.values()))
   self.assertIn('W -0.40000000',(root/'events.hepmc3').read_text())
   for n in ['events.hepmc3','event-weights.csv','generation.json']:(root/n).unlink()
   with self.assertRaises(ValueError):bhwide.select(raw,root,5,12345)
   self.assertFalse((root/'events.hepmc3').exists())

if __name__=='__main__':unittest.main()
