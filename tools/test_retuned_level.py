import copy
import json
from pathlib import Path
import unittest
from check_level_geometry import check
import math
from check_level_geometry import interior_angles, self_intersections, signed_area
from retune_extended_level import blunt_fragments, blunt_polygon, consolidate_yellow_bands

ROOT = Path(__file__).resolve().parent.parent

class RetunedLevelTests(unittest.TestCase):
    def test_current_geometry_rules(self):
        svg = (ROOT/'artifacts/levels/extended-mountain.svg').read_bytes()
        level = json.loads((ROOT/'artifacts/levels/extended-mountain.level.json').read_text())
        ref = json.loads((ROOT/'artifacts/levels/extended-mountain-measurements.json').read_text())
        report = check(level, svg, ref)
        self.assertTrue(report['summary']['pass'], report)
        # Targets use the v5 encounter numbers; the route map gives the shipped number.
        numbers=ref['routeMap']['encounterNumbers']
        targets={1:120,2:160,3:150,5:150,8:150,14:150,18:150,21:150}
        for n,pct in targets.items():
            row=report['transfers'][numbers[str(n)]-1]
            self.assertEqual(row['encounter'],ref['routeMap']['encounterIds'][str(n)])
            self.assertAlmostEqual(row['computedPercent'],pct,places=5)
        self.assertEqual(len(report['transfers']),38)
        self.assertEqual(len(report['pairs']),741)
        self.assertGreater(len(report['dragZones']),0)
        self.assertGreaterEqual(report['summary']['minYellowPairClearance'],540)
        self.assertEqual(report['summary']['yellowPairs'],report['summary']['yellowPairsPass'])
        bodies=[e for e in level['elements'] if e['role']!='drag']
        self.assertEqual(len(bodies),39)
        self.assertTrue(all(e['role']=='bounce' and e['grapplable'] for e in bodies))
        self.assertTrue(all(e['id'].endswith('-body0') for e in bodies))
        self.assertGreaterEqual(report['summary']['minDragSolidClearance'],1080)
        strict=copy.deepcopy(ref); strict.pop('allowedGrapplePairs')
        self.assertTrue(check(level,svg,strict)['summary']['pass'])

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

def tip(apex, leg=1000.0):
    h=math.radians(apex/2)
    return [[0.0,0.0],[leg*math.cos(h),-leg*math.sin(h)],[leg*math.cos(h),leg*math.sin(h)]]

class CornerBluntingTests(unittest.TestCase):
    def test_sharp_tip_truncated_to_two_wide_corners(self):
        for apex in (5,10,19.9):
            for poly in (tip(apex),tip(apex)[::-1]):
                with self.subTest(apex=apex,reversed=poly[0]!=[0.0,0.0] or poly[1][1]>0):
                    out=blunt_polygon(poly)
                    self.assertEqual(len(out),4)
                    self.assertGreaterEqual(min(interior_angles(out)),20)
                    self.assertEqual(self_intersections(out),[])
                    self.assertGreater(abs(signed_area(out)),0)
                    self.assertLess(abs(signed_area(out)),abs(signed_area(poly)))
                    self.assertEqual(blunt_polygon(poly),out)
                    new=[p for p in out if p not in poly]
                    face=min(40,2*0.4*1000*math.sin(math.radians(apex/2)))
                    self.assertAlmostEqual(math.dist(*new),face,places=6)

    def test_corners_at_or_above_20_are_untouched(self):
        for poly in (tip(20),tip(33),[[0,0],[100,0],[100,100],[0,100]]):
            self.assertEqual(blunt_polygon(poly),[list(p) for p in poly])

    def test_short_edges_limit_the_cut(self):
        out=blunt_polygon([[0,0],[100,-5],[100,5]])
        self.assertGreaterEqual(min(interior_angles(out)),20)
        self.assertAlmostEqual(math.dist(out[0],[0,0]),0.4*math.hypot(100,5),places=6)

    def test_fragments_blunted_in_collision_polygons(self):
        source={'fragments':[{'id':'A','polys':[tip(10)]},{'id':'B','polys':[tip(40)]}]}
        changed=blunt_fragments(source)
        self.assertEqual([c['fragment'] for c in changed],['A'])
        self.assertEqual(len(source['fragments'][0]['polys'][0]),4)
        self.assertEqual(source['fragments'][1]['polys'][0],tip(40))

    def test_generated_level_has_no_sub_20_corner(self):
        level=json.loads((ROOT/'artifacts/levels/extended-mountain.level.json').read_text())
        for e in level['elements']:
            poly=[(e['x']+p['x'],e['y']+p['y']) for p in e['points']]
            self.assertGreaterEqual(min(interior_angles(poly)),20,e['id'])
            self.assertEqual(self_intersections(poly),[],e['id'])

if __name__=='__main__':unittest.main()
