import copy
import json
from pathlib import Path
import unittest
from check_level_geometry import check
from retune_extended_level import consolidate_yellow_bands

ROOT = Path(__file__).resolve().parent.parent

class RetunedLevelTests(unittest.TestCase):
    def test_current_geometry_rules(self):
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
        self.assertGreater(len(report['dragZones']),0)
        self.assertGreaterEqual(report['summary']['minYellowPairClearance'],540)
        self.assertEqual(report['summary']['yellowPairs'],report['summary']['yellowPairsPass'])
        bodies=[e for e in level['elements'] if e['role']!='drag']
        self.assertEqual(len(bodies),25)
        self.assertTrue(all(e['role']=='bounce' and e['grapplable'] for e in bodies))
        self.assertTrue(all(e['id'].endswith('-body0') for e in bodies))
        self.assertGreaterEqual(report['summary']['minDragSolidClearance'],1080)
        strict=copy.deepcopy(ref); strict.pop('allowedGrapplePairs')
        self.assertFalse(check(level,svg,strict)['summary']['pass'])

class YellowConsolidationTests(unittest.TestCase):
    def fixture(self, second_x):
        def band(id,x):
            return dict(id=id,x=x,y=0,width=1000,height=100,
                        polygon=[[x,0],[x+1000,0],[x+1000,100],[x,100]])
        return {'fragments':[{'x':0,'y':5000,'polys':[[[0,0],[100,0],[100,100],[0,100]]]}],
                'yellowBands':[band('Y1',0),band('Y2',second_x)]}

    def test_nearby_zones_become_one_long_rectangle(self):
        m=self.fixture(1200)
        consolidate_yellow_bands(m)
        self.assertEqual(len(m['yellowBands']),1)
        self.assertEqual(m['yellowBands'][0]['width'],2200)
        self.assertGreaterEqual(m['yellowBands'][0]['nearestSolidClearance'],1080)

    def test_one_grapple_gap_is_allowed(self):
        m=self.fixture(1540)
        consolidate_yellow_bands(m)
        self.assertEqual(len(m['yellowBands']),2)

if __name__=='__main__':unittest.main()
