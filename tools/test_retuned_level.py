import copy
import json
from pathlib import Path
import unittest
from check_level_geometry import check

ROOT = Path(__file__).resolve().parent.parent

class RetunedLevelTests(unittest.TestCase):
    def test_distances_and_no_accidental_shortcuts(self):
        svg = (ROOT/'artifacts/levels/extended-mountain.svg').read_bytes()
        level = json.loads((ROOT/'artifacts/levels/extended-mountain.level.json').read_text())
        ref = json.loads((ROOT/'artifacts/levels/extended-mountain-measurements.json').read_text())
        report = check(level, svg, ref)
        self.assertTrue(report['summary']['pass'], report)
        targets={1:80,2:80,3:150,5:150,8:150,14:150,18:150,21:150}
        for n,pct in targets.items():
            row=report['transfers'][n-1]
            self.assertAlmostEqual(row['computedPercent'],pct,places=5)
        self.assertEqual(len(report['pairs']),300)
        self.assertGreater(len(report['dragZones']),6)
        bodies=[e for e in level['elements'] if e['role']!='drag']
        self.assertEqual(len(bodies),25)
        self.assertTrue(all(e['role']=='bounce' and e['grapplable'] for e in bodies))
        self.assertTrue(all(e['id'].endswith('-body0') for e in bodies))
        self.assertTrue(any(b.get('source')=='P0' for b in ref['yellowBands']))
        strict=copy.deepcopy(ref); strict.pop('allowedGrapplePairs')
        self.assertFalse(check(level,svg,strict)['summary']['pass'])

if __name__=='__main__':unittest.main()
