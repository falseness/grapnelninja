"""TASK-102: the W-unit momentum frame catalog matches the concept frames.

Pure Python, no browser. Env MOMENTUM_FRAMES_CATALOG = the converted
catalog (default tools/data/momentum-catalog-m.json, the TASK-120 catalog the
game inlines in elements/momentumpatterns.js); the source is
tools/data/momentum-frames-catalog.json (a copy of
artifacts/momentum-frames/catalog.json). Run from tools/:
python3 -m unittest -v test_momentum_frames_catalog
"""
import json
import os
import sys
from pathlib import Path
import unittest

from momentum_frames_catalog import CYCLES_PER_PASS

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path(os.environ.get('MOMENTUM_FRAMES_CATALOG', ROOT / 'tools' / 'data' / 'momentum-catalog-m.json'))
SOURCE = ROOT / 'tools' / 'data' / 'momentum-frames-catalog.json'
UNIT = 480.0
EPS = 1e-6

IDS = ['M04', 'M23', 'M24', 'M46', 'M47', 'M66', 'M11', 'M30', 'M93', 'M110',
       'M11-up', 'M30-up', 'M93-up', 'M110-up', 'M18', 'M60', 'M39', 'M117', 'M134', 'M40', 'M98', 'M136']
JOINS = {'M18': 'right-up', 'M60': 'right-down', 'M39': 'down-right', 'M117': 'down-right',
         'M134': 'down-right', 'M40': 'up-right', 'M98': 'up-right', 'M136': 'up-right'}
# Ticket's widened blues (frame px x, y, w, h) in catalog.json blue order.
WINDOWS = {
    'M98': [(650, 75, 50, 110), (650, 425, 50, 130)],
    'M134': [(590, 217, 30, 133), (590, 590, 30, 107), (700, 217, 30, 53), (700, 510, 30, 187)],
    'M136': [(600, 75, 30, 45), (600, 360, 30, 195), (710, 75, 30, 95), (710, 410, 30, 145)],
}
VERTEX = {'right-down': (457, 315), 'right-up': (457, 457), 'down-right': (315, 457), 'up-right': (315, 315)}
# Outer walls of each corner in vertex W coords (y down): (xmin, xmax, ymin, ymax).
OUTER = {'right-down': (-9, 0.5, -0.5, 9), 'right-up': (-9, 0.5, -9, 0.5),
         'down-right': (-0.5, 9, -9, 0.5), 'up-right': (-0.5, 9, -0.5, 9)}


def load():
    text = CATALOG.read_text()
    return text, json.loads(text), json.loads(SOURCE.read_text())


def edges(p):
    if p['shape'] == 'polygon':
        xs = [q[0] for q in p['points']]
        ys = [q[1] for q in p['points']]
        return min(xs), min(ys), max(xs), max(ys)
    return p['x'], p['y'], p['x'] + p['w'], p['y'] + p['h']


def samples(p):
    """Points covering a W piece (absolute W coords)."""
    if p['shape'] == 'polygon':
        pts = [(p['x'] + a, p['y'] + b) for a, b in p['points']]
        out = []
        n = 10
        for i in range(n + 1):
            for j in range(n + 1 - i):
                k = n - i - j
                out.append(tuple((i * pts[0][d] + j * pts[1][d] + k * pts[2][d]) / n for d in (0, 1)))
        return out
    return [(p['x'] - p['w'] / 2 + p['w'] * i / 8, p['y'] - p['h'] / 2 + p['h'] * j / 8)
            for i in range(9) for j in range(9)]


def origin(entry, src):
    """Frame px origin of an entry's W coordinates (independent of the converter)."""
    box = [edges(p) for p in src['pieces']]
    if entry['layout'] == 'right':
        return min(b[0] for b in box) - 48, 315
    if entry['layout'] == 'down':
        return 315, min(b[1] for b in box) - 48
    return VERTEX[JOINS[entry['id']]]


class MomentumFramesCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.doc, cls.src = load()
        cls.frames = {f['id']: f for f in cls.doc['frames']}
        cls.source = {f['id']: f for f in cls.src['frames']}

    def test_1_ids_in_order_compact_w(self):
        self.assertEqual([f['id'] for f in self.doc['frames']], IDS)
        self.assertEqual(self.doc['unit'], 'W')
        self.assertNotIn('\n', self.text)
        self.assertNotIn(': ', self.text)
        for f in self.doc['frames']:
            base = f['id'].replace('-up', '')
            self.assertEqual(f['difficulty'], self.source[base]['difficulty'], f['id'])
            if f['layout'] == 'corner':
                self.assertEqual(f['join'], JOINS[f['id']])
                self.assertEqual(f['axisScale'], {'x': 'shaft', 'y': 'corridor'})
                self.assertGreaterEqual(f['reach']['in'], 0.1)
                self.assertGreaterEqual(f['reach']['out'], 0.1)
            else:
                self.assertEqual(f['dirs'], [f['layout']], f['id'])
                self.assertEqual(f['layout'], {'M11': 'down', 'M30': 'down', 'M93': 'down', 'M110': 'down'}.get(
                    base, 'right') if '-up' not in f['id'] else 'up')

    def test_2_piece_counts_match_source(self):
        for f in self.doc['frames']:
            src = self.source[f['id'].replace('-up', '')]
            self.assertEqual([(p['kind'], p['shape']) for p in f['pieces']],
                             [(p['kind'], p['shape']) for p in src['pieces']], f['id'])

    def test_3_pieces_inside_layout_interior(self):
        for f in self.doc['frames']:
            for p in f['pieces']:
                for x, y in samples(p):
                    where = '%s %s (%.4f, %.4f)' % (f['id'], p['kind'], x, y)
                    if f['layout'] == 'right':
                        self.assertLessEqual(abs(y), 0.5 + EPS, where)
                        self.assertTrue(-EPS <= x <= f['span'] + EPS, where)
                    elif f['layout'] in ('down', 'up'):
                        self.assertLessEqual(abs(x), 0.5 + EPS, where)
                        self.assertTrue(-EPS <= y <= f['span'] + EPS, where)
                    else:
                        x0, x1, y0, y1 = OUTER[f['join']]
                        self.assertTrue(x0 - EPS <= x <= x1 + EPS and y0 - EPS <= y <= y1 + EPS, where)
                        # Outside both corridors = inside the wall mass.
                        self.assertTrue(abs(x) <= 0.5 + EPS or abs(y) <= 0.5 + EPS, where)

    def test_4_round_trip_to_frame_px(self):
        checked = 0
        for f in self.doc['frames']:
            if f['layout'] == 'up':
                continue
            src = self.source[f['id']]
            ox, oy = origin(f, src)
            widened = iter(WINDOWS.get(f['id'], []))
            for p, s in zip(f['pieces'], src['pieces']):
                if s['shape'] == 'polygon':
                    pts = [((p['x'] + a) * UNIT + ox, (p['y'] + b) * UNIT + oy) for a, b in p['points']]
                    for got, want in zip(pts, s['points']):
                        self.assertLessEqual(max(abs(got[0] - want[0]), abs(got[1] - want[1])), 0.5, f['id'])
                    checked += 1
                    continue
                want = (s['x'], s['y'], s['w'], s['h'])
                if f['id'] in WINDOWS and s['kind'] == 'blue':
                    want = next(widened)
                got = ((p['x'] - p['w'] / 2) * UNIT + ox, (p['y'] - p['h'] / 2) * UNIT + oy, p['w'] * UNIT, p['h'] * UNIT)
                for g, w in zip(got, want):
                    self.assertLessEqual(abs(g - w), 0.5, '%s %s %s' % (f['id'], got, want))
                m = s.get('motion')
                self.assertEqual(bool(m), 'motion' in p, f['id'])
                if m:
                    pm = p['motion']
                    size, o = (s['w'], ox) if m['axis'] == 'x' else (s['h'], oy)
                    self.assertEqual(pm['axis'], m['axis'])
                    self.assertLessEqual(abs(pm['min'] * UNIT + o - m['min']), 0.5, f['id'])
                    self.assertLessEqual(abs(pm['max'] * UNIT + o - (m['max'] + size)), 0.5, f['id'])
                    self.assertAlmostEqual(pm['speed'], (pm['max'] - pm['min'] - size / UNIT) / CYCLES_PER_PASS, places=5)
                checked += 1
            self.assertIsNone(next(widened, None), f['id'])
        print('round-tripped %d pieces' % checked)

    def test_5_windows_at_least_half_w(self):
        for fid in WINDOWS:
            columns = {}
            for p in self.frames[fid]['pieces']:
                if p['kind'] == 'blue':
                    columns.setdefault(round(p['x'], 4), []).append((p['y'] - p['h'] / 2, p['y'] + p['h'] / 2))
            self.assertEqual(len(columns), len(WINDOWS[fid]) // 2, fid)
            for x, spans in columns.items():
                spans.sort()
                for (_, b), (a, _) in zip(spans, spans[1:]):
                    print('%s x %.4f window %.6f W' % (fid, x, a - b))
                    self.assertGreaterEqual(a - b, 0.5 - EPS, fid)

    def test_6_up_mirrors_flip_down(self):
        for down in ('M11', 'M30', 'M93', 'M110'):
            d, u = self.frames[down], self.frames[down + '-up']
            self.assertEqual((u['layout'], u['dirs'], u['span']), ('up', ['up'], d['span']))
            for p, q in zip(d['pieces'], u['pieces']):
                self.assertEqual((q['kind'], q['shape'], q['x']), (p['kind'], p['shape'], p['x']))
                self.assertAlmostEqual(q['y'], d['span'] - p['y'], places=5)
                if 'points' in p:
                    self.assertEqual([[a, -b + 0.0] for a, b in p['points']], [[a, b + 0.0] for a, b in q['points']])
                else:
                    self.assertEqual((q['w'], q['h']), (p['w'], p['h']))
                if 'motion' in p:
                    pm, qm = p['motion'], q['motion']
                    if pm['axis'] == 'y':
                        self.assertAlmostEqual(qm['min'], d['span'] - pm['max'], places=5)
                        self.assertAlmostEqual(qm['max'], d['span'] - pm['min'], places=5)
                    else:
                        self.assertEqual(qm, pm)

    def test_7_motion_axes(self):
        def axes(fid):
            return [p['motion']['axis'] for p in self.frames[fid]['pieces'] if 'motion' in p]
        self.assertEqual(axes('M04'), ['y'])
        self.assertEqual(axes('M11'), ['x'])
        self.assertEqual(axes('M30'), ['x'])
        self.assertEqual(axes('M39'), ['y'])
        self.assertEqual(axes('M40'), ['y'])


def tearDownModule():
    # Flush the per-test prints before unittest's summary, so `| tail -1` shows OK
    sys.stdout.flush()


if __name__ == '__main__':
    unittest.main()
