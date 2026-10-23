"""Independent measured difficulty checks for the current generated route."""
import json
import os
from pathlib import Path
import unittest
from check_level_geometry import check

ROOT = Path(__file__).resolve().parent.parent
DIR = Path(os.environ.get('HARDER_LEVEL_DIR',ROOT/'artifacts/levels'))

class HarderRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=json.loads((DIR/'extended-mountain-measurements.json').read_text())
        path=DIR/'extended-mountain.level.json'
        if not path.exists():path=DIR/'level.json'
        cls.level=json.loads(path.read_text())
        cls.report=check(cls.level,(DIR/'extended-mountain.svg').read_bytes(),cls.m)

    def test_geometry_and_clearances(self):
        self.assertTrue(self.report['summary']['pass'],self.report['failureMessages'])
        self.assertGreaterEqual(self.report['summary']['minDragSolidClearance'],1620)
        self.assertGreaterEqual(self.report['summary']['minYellowPairClearance'],540)

    def test_measured_transfer_difficulty(self):
        # Semantic IDs of the deliberate easy and vertical exceptions, from
        # the preserved source; arbitrary new transfers cannot self-exempt.
        source=json.loads((ROOT/'artifacts/level/extended-mountain-measurements.json').read_text())
        exceptions={source['encounters'][n-1]['id']:pct for n,pct in
                    {1:120,2:160,3:150,5:150,8:150,14:150,18:150,21:150}.items()}
        exposed=0
        for row in self.report['transfers']:
            if row['encounter'] in exceptions:
                self.assertAlmostEqual(row['computedPercent'],exceptions[row['encounter']],delta=.01)
            else:
                self.assertGreaterEqual(row['computedDistance'],1080-.01,row)
                exposed+=row['computedDistance']>=1620-.01
        self.assertGreaterEqual(exposed,12,'Keep a substantial set of exposed 300%+ jumps')

    def test_rightward_difficulty_after_easier_start(self):
        transfers = self.report['transfers']
        self.assertEqual([(r['from'],r['to']) for r in transfers[:6]],
                         [(f'P{i}',f'P{i+1}') for i in range(6)])
        for row, pct in zip(transfers[:6], (120,160,300,200,200,400)):
            self.assertAlmostEqual(row['computedPercent'],pct,delta=.01)
        self.assertAlmostEqual(transfers[14]['computedPercent'],150,delta=.01)

    def test_opening_shapes_preserved(self):
        # Frozen original-opening generation is the authority for the easy start.
        before=json.loads((ROOT/'artifacts/TASK-668/before/extended-mountain-measurements.json').read_text())
        keys=('polys',)
        for a,b in zip(self.m['fragments'][:3],before['fragments'][:3]):
            self.assertEqual({k:a[k] for k in keys},{k:b[k] for k in keys})

if __name__=='__main__':unittest.main()
