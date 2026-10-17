"""Momentum corner walls: the colour clash at a turn's border join (TASK-049).

At a turn the floor/ceiling strip (MomentumBorder, kind != 'wall': the
STYLE.badVersionEffects.obstacles ground colours) meets the shaft wall strip
(kind 'wall': STYLE.momentum wall colours). Wanted (TASK-050): a seamless
mitred join - the colour boundary between the two styles runs along the
corner's diagonal (the mitre from the corner point C of the two corridor
faces to the far corner of the T x T square where the two strips meet,
T = thickness + backing), the neon only on the corridor faces, meeting
cleanly at C, the outer corner square filled, the inner corner sharp.

Course: the scripted R U R D R course of test_momentum_patterns_turn, so
segment 0..3 end in the joins right->up, up->right, right->down,
down->right. Per join and side (inner / outer: the incoming border line's
outerEnd) the camera is centred on C at 1280x720 with the TASK-044 wall
mask kept on the join (screen.segmentIndex = incoming segment), no ninja,
no pieces, hint hidden, the rAF loop stopped; one draw() and a screenshot.

In a box of 1.5 T (canvas pixels) round C, with u / v the depth of a pixel
into the mass from the incoming / outgoing corridor face. The incoming
strip's side of the mitre: inside the turn u < v (a pixel's depth is its
nearer face's), outside it u > v (past C the strips are mitred offsets of
the faces: depth = the larger of u, v; a pixel with v <= 0 lies along the
incoming face only):
Reference profiles: each strip's colour across its face (depth -SPAN..),
averaged over 5 rows of its straight run just outside the box. The test
first checks they are the STYLE colours of their kind: the brightest
pixel of a floor/ceiling profile is nearer STYLE.badVersionEffects
.obstacles.groundStroke or its neon core than the STYLE.momentum wall
stroke/core, and the other way round for a wall profile.
(a) wrongSidePixels: mass pixels (> 3 px from the diagonal, > 1 px from
    the faces) farther than COLOUR_TOL (RGB distance) from their own
    strip's reference colour at their depth: the other style's colours on
    this side of the mitre, or an unfilled notch where the own strip
    should run on up to the mitre.
(b) strayNeonPixels: mass pixels that are neon-coloured (green channel >=
    half the dimmer of the two STYLE stroke colours' green) farther than
    the neon width (STYLE.strokes.neonOutline.width in canvas pixels) + 1 px
    from both corridor faces (rays from C; in the outer corner square past
    C, u > 0 and v > 0, the mitred depth max(u, v) as in (a), since the
    face bands turn on the mitre there instead of rounding the corner).
(c) stepPx: per face, the neon centre (mean depth of the pixels within
    NEON_TOL of the reference profile's brightest colour, +-SPAN px across
    the face) sampled every pixel from 2 px to the box edge along the face:
    its largest offset from the reference profile's centre; a gap (no such
    pixel) counts SPAN.
    Along each face's continuation past C the neon must stop: neon farther
    than half the neon width + 1 px past C is a protrusion (its length).
    stepPx is the largest of these; <= 1 passes.

All 8 cases failed before TASK-050 (outside the turn the corner square's
cap/glow was not filled up to the mitre; inside it the floor/ceiling neon
and glow ran under the wall strip up to C); TASK-050 mitres the drawing
of MomentumBorder, so all 8 pass.

Writes to MOMENTUM_CORNER_RENDER_EVIDENCE_DIR (default artifacts/TASK-050):
corner-pixels.json (compact {case: {wrongSidePixels, strayNeonPixels,
stepPx}}), corner-detail.json (+ parts, samples, reference peaks) and
shots/<case>.png: 64 x 64 px round C zoomed 10x with the mitre diagonal as
a thin magenta overlay (evidence image only).

Requires Playwright Chromium and Pillow. No remote requests.
"""
import io
import json
import math
import os
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE
from test_momentum_patterns_turn import SCRIPT

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_CORNER_RENDER_EVIDENCE_DIR', ROOT / 'artifacts/TASK-050'))
# Join -> incoming segment index on the scripted course
JOINS = {'right->up': 0, 'up->right': 1, 'right->down': 2, 'down->right': 3}
SIDES = ('inner', 'outer')
BOX_T = 1.5
DIAGONAL_TOL = 3
FACE_TOL = 1
COLOUR_TOL = 24
SPAN = 12
# Neon: within this RGB distance of a straight run's brightest colour
NEON_TOL = 32
STEP_TOL = 1
# Evidence crops: +-SHOT_HALF px round C, ZOOM x
SHOT_HALF = 32
ZOOM = 10

START = '''() => { startGame('momentum'); cancelAnimationFrame(game) }'''
# Both border lines of the incoming segment and the outgoing segment's, the
# STYLE stroke/core colours and the canvas mapping
GEOMETRY = '''(i) => {
    const course = momentumCourse
    const a = course.segment(i), b = course.segment(i + 1)
    const lines = [momentumSegmentBorderLines(course, i), momentumSegmentBorderLines(course, i + 1)]
    const o = GAMEPLAY.momentumBorders
    const g = STYLE.badVersionEffects.obstacles, m = STYLE.momentum, neon = STYLE.strokes.neonOutline
    const rect = ctx.canvas.getBoundingClientRect()
    return {inDir: a.dir, outDir: b.dir, lines: lines,
        dIn: momentumDirection(a.dir), dOut: momentumDirection(b.dir),
        nIn: [1, -1].map(s => momentumSideNormal(a.dir, s)), nOut: [1, -1].map(s => momentumSideNormal(b.dir, s)),
        T: o.thickness + o.backing,
        k: rect.width / width * scale[version],
        left: rect.left, top: rect.top, width: rect.width, height: rect.height,
        neonWidth: neon.width * rect.width / width,
        ground: {stroke: g.groundStroke, core: neon.coreColors[g.groundStroke] || neon.coreColor},
        wall: {stroke: m.wallStroke, core: m.wallCore}}
}'''
# Camera centred on C, the mask kept on the join, nothing but the course
SHOOT = '''([cx, cy, segment]) => {
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor)
            f.elements = []
    grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(cx - w / 2); screen.y = -(cy - h / 2)
    screen.leftWall.update(screen)
    ninja.x = -1e6; ninja.y = -1e6; ninja.speedX = ninja.speedY = 0
    const i0 = screen.segmentIndex
    screen.segmentIndex = segment
    try { draw() } finally { screen.segmentIndex = i0 }
}'''


def rgb(hex_colour):
    h = hex_colour.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ray_distance(x, y, cx, cy, d):
    t = max(0, (x - cx) * d[0] + (y - cy) * d[1])
    return math.hypot(x - cx - t * d[0], y - cy - t * d[1])


def case_geometry(g, side):
    """C, the face directions and kinds of one side of a join (world units)"""
    k = 0 if side == 1 else 1
    line_in, line_out = g['lines'][0][k], g['lines'][1][k]
    return {
        'C': (line_in['x1'], line_in['y1']),
        'outer': line_in['outerEnd'],
        'dIn': (g['dIn']['x'], g['dIn']['y']), 'dOut': (g['dOut']['x'], g['dOut']['y']),
        'nIn': (g['nIn'][k]['x'], g['nIn'][k]['y']), 'nOut': (g['nOut'][k]['x'], g['nOut'][k]['y']),
        'kinds': [line_in['kind'], line_out['kind']]}


def style_of(kind):
    return 'wall' if kind == 'wall' else 'ground'


class Probe:
    """Screenshot pixels round C; faces are axis-aligned and C lies on a
    pixel corner, so the pixel at depth s across a face has its centre
    exactly s from the face line (s = j + 0.5)."""
    def __init__(self, image, cx, cy):
        self.px, self.cx, self.cy = image.load(), cx, cy

    def at(self, t, d, s, n):
        """Pixel t along d from C (t a pixel centre offset) and s across n"""
        x = self.cx + t * d[0] + s * n[0] - 0.5
        y = self.cy + t * d[1] + s * n[1] - 0.5
        return self.px[int(round(x)), int(round(y))][:3]

    def profile(self, t0, d, n, depth):
        """Colour per depth index j (centre j + 0.5, j from -SPAN), 5 rows averaged"""
        rows = [[self.at(t0 + 2 * r + 0.5, d, j + 0.5, n) for j in range(-SPAN, depth)] for r in range(5)]
        return [tuple(sum(row[j][c] for row in rows) / 5 for c in range(3)) for j in range(len(rows[0]))]

    def centre(self, t, d, n, peak):
        """Neon centre across the face at t along d: mean depth of the pixels
        within NEON_TOL of the reference neon colour (None: no neon there)"""
        hits = [j + 0.5 for j in range(-SPAN, SPAN) if math.dist(self.at(t, d, j + 0.5, n), peak) <= NEON_TOL]
        return sum(hits) / len(hits) if hits else None


def profile_peak(profile):
    """The reference neon colour (brightest R+G+B) and its centre depth"""
    peak = max(profile[:2 * SPAN], key=sum)
    hits = [j - SPAN + 0.5 for j, c in enumerate(profile[:2 * SPAN]) if math.dist(c, peak) <= NEON_TOL]
    return peak, sum(hits) / len(hits)


def analyse(image, g, c):
    """(a), (b), (c) on the screenshot round C (canvas pixels)"""
    cx, cy = g['left'] + g['width'] / 2, g['top'] + g['height'] / 2
    half = BOX_T * g['T'] * g['k'] / 2
    probe = Probe(image, cx, cy)
    nIn, nOut, dIn, dOut = c['nIn'], c['nOut'], c['dIn'], c['dOut']
    back = (-dIn[0], -dIn[1])
    depth = int(math.ceil(half * math.sqrt(2))) + 2
    reach = int(math.ceil(half)) + 24
    # Straight-run references: incoming face behind C, outgoing face ahead
    ref = {'in': probe.profile(reach, back, nIn, depth), 'out': probe.profile(reach, dOut, nOut, depth)}
    strokes = {s: [rgb(g[s]['stroke']), rgb(g[s]['core'])] for s in ('ground', 'wall')}
    peaks = {}
    for key, kind in (('in', c['kinds'][0]), ('out', c['kinds'][1])):
        brightest = max(ref[key], key=sum)
        near = {s: min(math.dist(brightest, x) for x in strokes[s]) for s in strokes}
        peaks[key] = {'kind': kind, 'peak': [round(v) for v in brightest],
                      'style': min(near, key=near.get), 'expected': style_of(kind)}

    def expected(key, s):
        j = int(math.floor(s)) + SPAN
        return ref[key][max(0, min(len(ref[key]) - 1, j))]

    neon_green = 0.5 * min(rgb(g[s]['stroke'])[1] for s in ('ground', 'wall'))
    neon_tol = g['neonWidth'] + FACE_TOL
    wrong, stray = [], []
    x0, x1 = int(math.floor(cx - half)), int(math.ceil(cx + half))
    y0, y1 = int(math.floor(cy - half)), int(math.ceil(cy + half))
    for y in range(y0, y1):
        for x in range(x0, x1):
            fx, fy = x + 0.5 - cx, y + 0.5 - cy
            u = fx * nIn[0] + fy * nIn[1]
            v = fx * nOut[0] + fy * nOut[1]
            mass = (u > 0 or v > 0) if c['outer'] else (u > 0 and v > 0)
            if not mass:
                continue
            p = probe.px[x, y][:3]
            face = min(ray_distance(x + 0.5, y + 0.5, cx, cy, back),
                       ray_distance(x + 0.5, y + 0.5, cx, cy, dOut))
            if face > FACE_TOL and abs(u - v) / math.sqrt(2) > DIAGONAL_TOL:
                # Mitred offsets: inside the turn a pixel is as deep as its
                # nearer face; outside it, past C, as deep as the farther one
                if c['outer']:
                    own = 'in' if (u > 0 and u > v) else 'out'
                else:
                    own = 'in' if u < v else 'out'
                if math.dist(p, expected(own, u if own == 'in' else v)) > COLOUR_TOL:
                    wrong.append((x, y))
            neon_depth = max(u, v) if (c['outer'] and u > 0 and v > 0) else face
            if neon_depth > neon_tol and p[1] >= neon_green:
                stray.append((x, y))

    allowance = g['neonWidth'] / 2 + FACE_TOL
    steps = {'offset': 0, 'gap': 0, 'protrusion': 0}
    for d, n, key in ((back, nIn, 'in'), (dOut, nOut, 'out')):
        ref_peak, ref_centre = profile_peak(ref[key])
        # Along the face from C: the neon centre stays where the straight run has it
        for t in range(2, int(half)):
            centre = probe.centre(t + 0.5, d, n, ref_peak)
            if centre is None:
                steps['gap'] = max(steps['gap'], SPAN)
            else:
                steps['offset'] = max(steps['offset'], abs(centre - ref_centre))
        # Past C: this face's neon ends at the corner point
        for t in range(int(allowance), int(half)):
            centre = probe.centre(-(t + 0.5), d, n, ref_peak)
            if t + 0.5 > allowance and centre is not None and abs(centre - ref_centre) <= 1:
                steps['protrusion'] = max(steps['protrusion'], round(t + 0.5 - allowance, 2))
    return {'wrongSidePixels': len(wrong), 'strayNeonPixels': len(stray), 'stepPx': round(max(steps.values()), 2),
            'stepParts': {k2: round(v2, 2) for k2, v2 in steps.items()}, 'references': peaks,
            'box': [x0, y0, x1, y1], 'C': [cx, cy],
            'wrongSample': wrong[:5], 'straySample': stray[:5], 'pixels': {'wrong': wrong, 'stray': stray}}


def evidence_shot(image, r, c, path):
    """A SHOT_HALF px box round C zoomed ZOOM x, the mitre as a 1 px magenta
    line from C into the mass (evidence image only)"""
    cx, cy = r['C']
    x0, y0 = int(cx) - SHOT_HALF, int(cy) - SHOT_HALF
    crop = image.crop((x0, y0, x0 + 2 * SHOT_HALF, y0 + 2 * SHOT_HALF)).convert('RGB')
    crop = crop.resize((crop.width * ZOOM, crop.height * ZOOM), Image.NEAREST)
    draw = ImageDraw.Draw(crop)
    px, py = (cx - x0) * ZOOM, (cy - y0) * ZOOM
    far = 2 * crop.width
    draw.line([(px, py), (px + far * (c['nIn'][0] + c['nOut'][0]), py + far * (c['nIn'][1] + c['nOut'][1]))],
              fill=(255, 0, 255), width=1)
    crop.save(path)


class MomentumCornerRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / 'shots').mkdir(exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
        cls.addClassCleanup(context.close)
        cls.page = context.new_page()
        cls.errors = []
        cls.page.on('pageerror', lambda e: cls.errors.append(str(e)))
        cls.page.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
        cls.page.goto(cls.url)
        wait_for_boot_run(cls.page)
        cls.page.evaluate(SEED_COURSE, SCRIPT)
        cls.page.evaluate(START)
        cls.results = {}
        for join, segment in JOINS.items():
            g = cls.page.evaluate(GEOMETRY, segment)
            for side_sign in (1, -1):
                c = case_geometry(g, side_sign)
                name = f"{join.replace('->', '-')}-{'outer' if c['outer'] else 'inner'}"
                cls.page.evaluate(SHOOT, [c['C'][0], c['C'][1], segment])
                image = Image.open(io.BytesIO(cls.page.screenshot())).convert('RGB')
                r = analyse(image, g, c)
                r['kinds'] = c['kinds']
                cls.results[name] = r
                evidence_shot(image, r, c, EVIDENCE_DIR / 'shots' / f'{name}.png')
        (EVIDENCE_DIR / 'corner-pixels.json').write_text(json.dumps(
            {n: {key: r[key] for key in ('wrongSidePixels', 'strayNeonPixels', 'stepPx')}
             for n, r in cls.results.items()}, separators=(',', ':')))
        (EVIDENCE_DIR / 'corner-detail.json').write_text(json.dumps(
            {n: {k: v for k, v in r.items() if k != 'pixels'} for n, r in cls.results.items()}, separators=(',', ':')))
        for n, r in cls.results.items():
            ok = r['wrongSidePixels'] == 0 and r['strayNeonPixels'] == 0 and r['stepPx'] <= STEP_TOL
            print(f"{n}: {'PASS' if ok else 'FAIL'} (a) wrongSidePixels={r['wrongSidePixels']} "
                  f"(b) strayNeonPixels={r['strayNeonPixels']} (c) stepPx={r['stepPx']} {r['stepParts']}")

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_0_references_are_style_colours(self):
        for name, r in self.results.items():
            for key, ref in r['references'].items():
                self.assertEqual(ref['style'], ref['expected'], f'{name} {key} reference {ref}')

    def check(self, name):
        r = self.results[name]
        self.assertEqual(r['wrongSidePixels'], 0, f'{name} (a) mitre: {r["wrongSample"]}')
        self.assertEqual(r['strayNeonPixels'], 0, f'{name} (b) stray neon: {r["straySample"]}')
        self.assertLessEqual(r['stepPx'], STEP_TOL, f'{name} (c) step: {r["stepParts"]}')


def _make(name):
    def test(self):
        self.check(name)
    test.__name__ = 'test_' + name.replace('-', '_')
    return test


for _join in JOINS:
    for _side in SIDES:
        _name = f"{_join.replace('->', '-')}-{_side}"
        setattr(MomentumCornerRenderTests, 'test_' + _name.replace('-', '_'), _make(_name))


if __name__ == '__main__':
    unittest.main()
