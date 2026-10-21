"""Momentum moving blue on a used green (TASK-078 reproduction, TASK-079 fix).

Bug report: 'if green platform under the blue cube disappear, it still
bounces of "removed" green platform'. MomentumOneTime.moveY reverses speedY
whenever the shape would leave the FIXED range [motion.yMin, motion.yMax],
and MomentumPortPatternFactory copies those bounds from the ported bad frames
(MOMENTUM_PATTERNS_PORT_H, also reused by the turn types), where some sit on
a sibling green's face. Once that green is used the bound stays.

The catalog is read scaled as MomentumPortPatternFactory builds it (live
corridor half width over shaftReferenceHalfWidth, TASK-137), BAND likewise.

1) Static classification (catalog read via page.evaluate): for every moving
   piece of every MOMENTUM_PATTERNS_PORT_H pattern, per side, the bound is a
   'support' (sibling index) when it equals a sibling's facing edge (its top
   for yMax, its bottom for yMin) within SUPPORT_TOL_RATIO * height and the
   sibling overlaps the moving piece in x; otherwise 'corridor'.
   supports.json: compact [{pattern, piece, side, support, gap, turns}].
2) Browser drive (rAF stopped, ninja invulnerable and parked away from the
   pieces): the pattern is placed with window.momentumPlacePattern and its
   floor's moveElements() is stepped (the pieces' physics cycle).
   test_no_use_baseline: bad-frame7 and bad-frame4 with nothing used, the
   moving blues' y every TRACE_EVERY cycles equals BASELINE (written to the
   evidence dir on the first run, when BASELINE does not exist yet).
   test_<pattern>_<side>_opens (one per support case): the bounce period is
   measured on a no-use run, then the supporting green is used (and so is
   every other sibling in the blue's path on that side, so that the next
   solid is the corridor limit) and the blue is stepped for PERIODS bounce
   periods: for a yMax support its bottom goes below the old support's top
   and reaches the corridor limit (within limit_tol = LIMIT_TOL_PER_SCALE *
   GAMEPLAY.momentumTimeScale: a turn is sampled on whole cycles and the
   per-cycle step scales with the time scale), for a yMin support its
   top goes above the old support's bottom and reaches the corridor limit.
   TASK-079: MomentumPortPatternFactory gives each supported side its
   candidates (siblings in the path, then the corridor limit) and
   MomentumOneTime.moveY bounces on the nearest unused one.
3) test_initial_bounds_equal_catalog: every moving piece of every port
   pattern and turn type, nothing used: its effective bounds
   (getMotionBound, also momentumPlacePattern's motion) equal the catalog
   ones exactly (bounds-identical.json, with the test_2 baseline verdict).
   test_bad_frame4_chain: the green is used while the polygon blue bounces
   under it: its range opens to the rect blue above (never overlapping it),
   then that blue is used too and it opens to the corridor limit.

MOMENTUM_BLUE_SUPPORT_EVIDENCE_DIR (default /tmp/momentum-blue-support)
receives supports.json, baseline-trace.json, fix-trace.json (per case
[cycle, y, speedY] every TRACE_EVERY cycles from USE_LEAD cycles before the
use to the end, plus the turns after the use), bounds-identical.json and
shots/ (bad-frame7 at 1280x720: the blue on the green before the use, the
blue falling through the gap after it, the blue turning at the corridor
floor limit, and the same after-use frame at 390x844; bad-frame4 at
1280x720: the polygon blue rising past the used green).
MOMENTUM_BLUE_SUPPORT_BASELINE (default artifacts/TASK-137/blue_support/baseline-trace.json,
regenerated for the scaled ports; TASK-081's is the unscaled 0.75 one, TASK-078's the 0.5 one) is the trace the baseline compares against. Requires Playwright Chromium.
"""
import io
import json
import os
from pathlib import Path
import unittest

from PIL import Image

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_borders import SEED_COURSE

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_SUPPORT_EVIDENCE_DIR', '/tmp/momentum-blue-support'))
BASELINE = Path(os.environ.get('MOMENTUM_BLUE_SUPPORT_BASELINE',
                               ROOT / 'artifacts' / 'TASK-137' / 'blue_support' / 'baseline-trace.json'))
# First segment right with a length draw of 0.99 (~5 heights), then the LCG
SCRIPT = [0.99]
# The bad frames leave 0.01 * height gaps between a bound and its support
SUPPORT_TOL_RATIO = 0.02
# Right corridor half width (catalog corridor bound of a rect), the old
# corridor's; scaled with the catalog in setUpClass
BAND = 972
# 2 world units at momentumTimeScale 0.5
LIMIT_TOL_PER_SCALE = 4
TRACE_EVERY = 4
USE_LEAD = 20
PERIODS = 3
BASELINE_CYCLES = 6000
BASELINE_PATTERNS = ['bad-frame7', 'bad-frame4']
# No-use run the bounce period is measured on (a gravity blue's slow-motion
# bounce takes thousands of cycles)
PERIOD_CYCLES = 40000
# Support cases the catalog must hold (the test methods below)
EXPECTED_SUPPORTS = {('bad-frame4', 1, 'yMax'), ('bad-frame4', 2, 'yMin'), ('bad-frame7', 1, 'yMax')}

SETUP = '''(band) => {
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    ninja.invulnerableMs = 1e9
    const k = momentumPatternFactories[MOMENTUM_PATTERNS_PORT_H[0].id].getScale()
    return {height: height, segment: momentumCourse.segment(0),
            half: GAMEPLAY.momentumBorders.halfWidth, band: band * k,
            patterns: MOMENTUM_PATTERNS_PORT_H.map(p =>
                ({...p, span: p.span * k, pieces: MomentumPortPatternFactory.scalePieces(p.pieces, k)})),
            turns: MOMENTUM_PATTERNS_TURN.map(turn => ({id: turn.id, source: turn.source}))}
}'''
# Places pattern id at (x, y) alone on its floor with the ninja parked far
# above it, then steps the floor `cycles` times; on cycle `useAt` it uses the
# pieces in `uses` first. Rows [cycle, y, speedY, top, bottom] of each piece
# in `pieces` every `every` cycles from `from` on (row cycle = moves done)
DRIVE = '''([id, x, y, pieces, uses, useAt, cycles, every, from]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    floor.groups = []
    ninja.x = x; ninja.y = y - 1e5; ninja.speedX = ninja.speedY = 0
    ninja.invulnerableMs = 1e9
    momentumPlacePattern(id, x, y)
    const els = floor.elements.slice()
    window.__support = {floor, els}
    const rows = pieces.map(() => [])
    const record = k => pieces.forEach((p, i) => {
        const e = els[p]
        rows[i].push([k, e.y, e.speedY, e.y + e.topOffset, e.y + e.bottomOffset])
    })
    for (let k = 0; k < cycles; ++k) {
        if (k >= from && (k - from) % every == 0)
            record(k)
        if (k == useAt)
            uses.forEach(i => els[i].use())
        floor.moveElements()
    }
    record(cycles)
    return {rows, inFloor: els.map(e => floor.elements.includes(e))}
}'''
# Centres the view on (cx, cy) and draws one frame
SHOOT = '''([cx, cy]) => {
    const w = width / scale[version], h = height / scale[version]
    screen.x = -(cx - w / 2)
    screen.y = -(cy - h / 2)
    if (screen.leftWall)
        screen.leftWall.update(screen)
    ninja.x = cx; ninja.y = cy - 1e5; ninja.speedX = ninja.speedY = 0
    draw()
}'''

# Places pattern id, then steps it: the green is used on cycle useGreen, the
# rect blue (piece 1) on useBlue. Rows [cycle, y, speedY, top, rect bottom]
# of piece index every `every` cycles, its yMin right after each use, and
# its least clearance to the rect blue between the two uses
CHAIN = '''([id, x, y, index, useGreen, useBlue, cycles, every]) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    floor.elements = []
    floor.groups = []
    ninja.x = x; ninja.y = y - 1e5; ninja.speedX = ninja.speedY = 0
    ninja.invulnerableMs = 1e9
    momentumPlacePattern(id, x, y)
    const els = floor.elements.slice()
    const poly = els[index], rect = els[1]
    const rows = [], bounds = []
    let minClear = Infinity
    for (let k = 0; k <= cycles; ++k) {
        if (k == useGreen) els[0].use()
        if (k == useBlue) rect.use()
        if (k % every == 0)
            rows.push([k, poly.y, poly.speedY, poly.y + poly.topOffset, rect.y + rect.bottomOffset])
        if (k == useGreen + 1 || k == useBlue + 1)
            bounds.push([k, poly.getMotionBound('yMin')])
        if (k > useGreen && k < useBlue)
            minClear = Math.min(minClear, poly.y + poly.topOffset - (rect.y + rect.bottomOffset))
        floor.moveElements()
    }
    return {rows, bounds, minClear}
}'''
# Effective vs catalog bounds of every moving piece (port patterns and turn
# types built by their factories at (x, y)), and momentumPlacePattern's motion
BOUNDS = '''([x, y]) => {
    const out = {}
    const factories = [...MOMENTUM_PATTERNS_PORT_H.map(p => [p.id, momentumPatternFactories[p.id]]),
                       ...MOMENTUM_PATTERNS_TURN.map(p => [p.id, momentumTurnFactories[p.id].frame])]
    for (const [id, factory] of factories) {
        const els = factory.create(x, y)
        MomentumPortPatternFactory.scalePieces(factory.pattern.pieces, factory.getScale()).forEach((piece, i) => {
            if (!piece.motion) return
            const e = els[i]
            ;(out[id] = out[id] || {})[i] = {
                catalog: [y + piece.motion.yMin, y + piece.motion.yMax],
                effective: [e.getMotionBound('yMin'), e.getMotionBound('yMax')],
                candidates: e.motionCandidates ? Object.keys(e.motionCandidates) : []}
        })
    }
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    const placed = {}
    for (const p of MOMENTUM_PATTERNS_PORT_H) {
        floor.elements = []
        floor.groups = []
        placed[p.id] = momentumPlacePattern(p.id, x, y).elements.map(e => e.motion && [e.motion.yMin, e.motion.yMax])
    }
    floor.elements = []
    floor.groups = []
    return {out, placed}
}'''
# Uses the green of the driven bad-frame7 (fade over) and steps until the
# blue's top is half way through the old green
FALL_THROUGH = '''([gTop, gBottom]) => {
    const {floor, els} = __support
    els[0].use()
    els[0].fadeStartMs = performance.now() - 2 * GAMEPLAY.momentumFadeMs
    const blue = els[1]
    let k = 0
    for (; k < 40000 && blue.y + blue.topOffset < (gTop + gBottom) / 2; ++k)
        floor.moveElements()
    return {cycles: k, greenInFloor: floor.elements.includes(els[0]), top: blue.y + blue.topOffset,
            bottom: blue.y + blue.bottomOffset, speedY: blue.speedY, yMax: blue.getMotionBound('yMax')}
}'''
# Steps the driven blue (piece 1) to its next turn at the bottom
NEXT_BOTTOM_TURN = '''() => {
    const {floor, els} = __support
    const blue = els[1]
    let k = 0, prev = blue.speedY
    for (; k < 40000; ++k) {
        floor.moveElements()
        if (prev > 0 && blue.speedY < 0) break
        prev = blue.speedY
    }
    return {cycles: k, bottom: blue.y + blue.bottomOffset, speedY: blue.speedY}
}'''
# Uses the green (fade over) and the rect blue of the driven bad-frame4 and
# steps the polygon blue until its top rises to `above`
RISE_PAST = '''(above) => {
    const {floor, els} = __support
    els[0].use()
    els[0].fadeStartMs = performance.now() - 2 * GAMEPLAY.momentumFadeMs
    els[1].use()
    const blue = els[2]
    let k = 0
    for (; k < 40000 && blue.y + blue.topOffset > above; ++k)
        floor.moveElements()
    return {cycles: k, greenInFloor: floor.elements.includes(els[0]), top: blue.y + blue.topOffset,
            speedY: blue.speedY}
}'''


def piece_extents(piece):
    """(left, right, top, bottom) offsets of a catalog piece from its centre"""
    if piece['shape'] == 'rect':
        return -piece['w'] / 2, piece['w'] / 2, -piece['h'] / 2, piece['h'] / 2
    xs = [p[0] for p in piece['points']]
    ys = [p[1] for p in piece['points']]
    return min(xs), max(xs), min(ys), max(ys)


def piece_box(piece):
    left, right, top, bottom = piece_extents(piece)
    return piece['x'] + left, piece['x'] + right, piece['y'] + top, piece['y'] + bottom


def classify(patterns, turns, height):
    """Support cases of every moving piece side, catalog coordinates"""
    tol = SUPPORT_TOL_RATIO * height
    cases = []
    for pattern in patterns:
        pieces = pattern['pieces']
        for index, piece in enumerate(pieces):
            motion = piece.get('motion')
            if not motion:
                continue
            left, right, _, _ = piece_box(piece)
            for side in ('yMax', 'yMin'):
                bound = motion[side]
                best = None
                for j, sibling in enumerate(pieces):
                    if j == index:
                        continue
                    s_left, s_right, s_top, s_bottom = piece_box(sibling)
                    if s_right <= left or s_left >= right:
                        continue
                    face = s_top if side == 'yMax' else s_bottom
                    gap = abs(bound - face)
                    if gap <= tol and (best is None or gap < best[1]):
                        best = (j, gap)
                cases.append({'pattern': pattern['id'], 'piece': index, 'side': side,
                              'support': best[0] if best else 'corridor',
                              'gap': round(best[1], 4) if best else None, 'bound': bound,
                              'turns': [t['id'] for t in turns if t['source'] == pattern['id']]})
    return cases


def corridor_limit(piece, side, cases_by_side):
    """The catalog corridor bound for that side: the opposite catalog bound
    mirrored when that side is a corridor one, else the rect band"""
    other = 'yMin' if side == 'yMax' else 'yMax'
    if cases_by_side[other]['support'] == 'corridor':
        return -piece['motion'][other]
    return BAND if side == 'yMax' else -BAND


def path_siblings(pieces, index, side):
    """Siblings overlapping piece index in x on that side of it"""
    left, right, top, bottom = piece_box(pieces[index])
    res = []
    for j, sibling in enumerate(pieces):
        if j == index:
            continue
        s_left, s_right, s_top, s_bottom = piece_box(sibling)
        if s_right <= left or s_left >= right:
            continue
        if (side == 'yMax' and s_top >= bottom - 1e-6) or (side == 'yMin' and s_bottom <= top + 1e-6):
            res.append(j)
    return res


def turn_cycles(rows, side):
    """Cycles where speedY flips away from that side"""
    res = []
    for a, b in zip(rows, rows[1:]):
        if side == 'yMax' and a[2] > 0 and b[2] < 0 or side == 'yMin' and a[2] < 0 and b[2] > 0:
            res.append(b[0])
    return res


class MomentumBlueSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (EVIDENCE_DIR / 'shots').mkdir(parents=True, exist_ok=True)
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
        info = cls.page.evaluate(SETUP, 972)
        global BAND
        BAND = info['band']
        cls.height = info['height']
        cls.limit_tol = LIMIT_TOL_PER_SCALE * cls.page.evaluate('GAMEPLAY.momentumTimeScale')
        cls.patterns = {p['id']: p for p in info['patterns']}
        segment = info['segment']
        cls.origin = (segment['x0'] + 0.2 * info['half'], segment['y0'])
        cls.cases = classify(info['patterns'], info['turns'], cls.height)
        (EVIDENCE_DIR / 'supports.json').write_text(json.dumps(
            [{k: c[k] for k in ('pattern', 'piece', 'side', 'support', 'gap')} for c in cls.cases],
            separators=(',', ':')))
        print('\ncases (pattern piece side support gap bound turns):')
        for c in cls.cases:
            print(' ', c['pattern'], c['piece'], c['side'], c['support'], c['gap'], c['bound'],
                  ','.join(c['turns']) or '-')
        cls.bug = {}

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def drive(self, pattern, pieces, uses=(), use_at=-1, cycles=BASELINE_CYCLES, every=1, start=0):
        x, y = self.origin
        return self.page.evaluate(DRIVE, [pattern, x, y, list(pieces), list(uses), use_at, cycles, every, start])

    def test_1_supports_classified(self):
        supports = {(c['pattern'], c['piece'], c['side']) for c in self.cases if c['support'] != 'corridor'}
        print('support cases:', sorted(supports))
        self.assertEqual(supports, EXPECTED_SUPPORTS)

    def test_2_no_use_baseline(self):
        trace = {}
        for pattern in BASELINE_PATTERNS:
            moving = [i for i, p in enumerate(self.patterns[pattern]['pieces']) if p.get('motion')]
            res = self.drive(pattern, moving, every=TRACE_EVERY)
            trace[pattern] = {str(p): [row[1] for row in rows] for p, rows in zip(moving, res['rows'])}
        first = not BASELINE.exists()
        type(self).baseline_identical = None if first else trace == json.loads(BASELINE.read_text())
        (EVIDENCE_DIR / 'baseline-trace.json').write_text(json.dumps(trace, separators=(',', ':')))
        if first:
            print('baseline written (first run):', EVIDENCE_DIR / 'baseline-trace.json')
            return
        expected = json.loads(BASELINE.read_text())
        print('baseline compared with', BASELINE)
        self.assertEqual(trace, expected)

    def check_opens(self, pattern, index, side):
        case = next(c for c in self.cases if (c['pattern'], c['piece'], c['side']) == (pattern, index, side))
        pieces = self.patterns[pattern]['pieces']
        piece = pieces[index]
        by_side = {c['side']: c for c in self.cases if (c['pattern'], c['piece']) == (pattern, index)}
        y0 = self.origin[1]
        limit = y0 + corridor_limit(piece, side, by_side)
        _, _, s_top, s_bottom = piece_box(pieces[case['support']])
        face = y0 + (s_top if side == 'yMax' else s_bottom)
        # Bounce period from a no-use run
        rows = self.drive(pattern, [index], cycles=PERIOD_CYCLES)['rows'][0]
        turns = turn_cycles(rows, side)
        self.assertGreaterEqual(len(turns), 3, turns)
        period = (turns[-1] - turns[1]) / (len(turns) - 2)
        use_at = turns[1] + int(period // 2)
        uses = path_siblings(pieces, index, side)
        self.assertIn(case['support'], uses)
        cycles = use_at + int(PERIODS * period)
        res = self.drive(pattern, [index], uses, use_at, cycles, TRACE_EVERY, use_at - USE_LEAD)
        full = self.drive(pattern, [index], uses, use_at, cycles)['rows'][0]
        after = [r for r in full if r[0] > use_at]
        turns_after = turn_cycles([r for r in full if r[0] >= use_at], side)
        edge = 4 if side == 'yMax' else 3
        extreme = max(r[edge] for r in after) if side == 'yMax' else min(r[edge] for r in after)
        self.bug[f'{pattern}:{index}:{side}'] = {
            'useAt': use_at, 'period': period, 'uses': uses, 'face': face, 'limit': limit,
            'extreme': extreme, 'turnsAfter': [[k, full[k][edge]] for k in turns_after],
            'rows': [[r[0], r[1], r[2]] for r in res['rows'][0]]}
        (EVIDENCE_DIR / 'fix-trace.json').write_text(json.dumps(self.bug, separators=(',', ':')))
        print(f'{pattern} piece {index} {side}: period {period:.1f} use at {use_at} uses {uses} '
              f'face {face:.2f} limit {limit:.2f} extreme {extreme:.3f} turns after {len(turns_after)}')
        if side == 'yMax':
            self.assertGreater(extreme, face + 1)
            self.assertGreaterEqual(extreme, limit - self.limit_tol)
            self.assertLessEqual(extreme, limit + 1e-6)
        else:
            self.assertLess(extreme, face - 1)

    def test_bad_frame4_yMax_opens(self):
        self.check_opens('bad-frame4', 1, 'yMax')

    def test_bad_frame4_yMin_opens(self):
        self.check_opens('bad-frame4', 2, 'yMin')

    def test_bad_frame7_yMax_opens(self):
        self.check_opens('bad-frame7', 1, 'yMax')

    def test_bad_frame4_chain(self):
        """Green used while the polygon blue bounces under it: its yMin opens
        to the rect blue above (its live bottom + gap), then the rect blue is
        used and it opens to the corridor limit"""
        pattern, index, side = 'bad-frame4', 2, 'yMin'
        pieces = self.patterns[pattern]['pieces']
        x, y0 = self.origin
        _, _, _, g_bottom = piece_box(pieces[0])
        gap = pieces[index]['motion']['yMin'] - g_bottom
        limit = y0 - pieces[index]['motion']['yMax']
        rows = self.drive(pattern, [index], cycles=PERIOD_CYCLES)['rows'][0]
        turns = turn_cycles(rows, side)
        period = (turns[-1] - turns[1]) / (len(turns) - 2)
        use_green = turns[1] + int(period // 2)
        use_blue = use_green + int(2 * period)
        res = self.page.evaluate(CHAIN, [pattern, x, y0, index, use_green, use_blue,
                                         use_green + int(5 * period), TRACE_EVERY])
        between = [r for r in res['rows'] if use_green < r[0] < use_blue]
        after = [r for r in res['rows'] if r[0] > use_blue]
        top_between = min(r[3] for r in between)
        top_after = min(r[3] for r in after)
        print(f'chain: green used at {use_green}, rect blue at {use_blue}; bounds {res["bounds"]}; '
              f'top between {top_between:.2f} (old face {y0 + g_bottom:.2f}), min clearance to the rect '
              f'{res["minClear"]:.3f} (gap {gap:.2f}); top after {top_after:.3f} limit {limit:.2f}')
        self.bug['bad-frame4:2:chain'] = {'useGreen': use_green, 'useBlue': use_blue, 'bounds': res['bounds'],
                                          'minClear': res['minClear'], 'topBetween': top_between,
                                          'topAfter': top_after, 'limit': limit,
                                          'rows': [r[:3] for r in res['rows'] if r[0] >= use_green - USE_LEAD]}
        (EVIDENCE_DIR / 'fix-trace.json').write_text(json.dumps(self.bug, separators=(',', ':')))
        # Opened past the used green, but held off by the rect blue: the
        # rect falls onto it with its own gap (0), so they never overlap by
        # more than one cycle's move
        self.assertLess(top_between, y0 + g_bottom - 1)
        self.assertGreater(res['minClear'], -1)
        self.assertEqual(res['bounds'][-1][1], limit)
        self.assertLessEqual(top_after, limit + self.limit_tol)
        self.assertGreaterEqual(top_after, limit - 1e-6)

    def test_initial_bounds_equal_catalog(self):
        """Nothing used: the effective bounds equal the catalog ones for every
        moving piece of every port pattern and turn type"""
        x, y = self.origin
        res = self.page.evaluate(BOUNDS, [x, y])
        bounds = res['out']
        all_equal = all(v['catalog'] == v['effective'] for pieces in bounds.values() for v in pieces.values())
        placed_equal = all(res['placed'][pid][int(i)] == v['effective']
                           for pid, pieces in bounds.items() if pid in res['placed'] for i, v in pieces.items())
        with_candidates = sorted(f'{pid}:{i}:{c}' for pid, pieces in bounds.items()
                                 for i, v in pieces.items() for c in v['candidates'])
        print('moving pieces', sum(len(p) for p in bounds.values()), 'allEqual', all_equal,
              'placedEqual', placed_equal, 'sides with candidates', with_candidates)
        identical = getattr(type(self), 'baseline_identical', None)
        (EVIDENCE_DIR / 'bounds-identical.json').write_text(json.dumps(
            {**{pid: {i: {'catalog': v['catalog'], 'effective': v['effective']} for i, v in pieces.items()}
                for pid, pieces in bounds.items()},
             'allEqual': all_equal and placed_equal, 'noUseTraceIdentical': identical},
            separators=(',', ':')))
        self.assertTrue(all_equal)
        self.assertTrue(placed_equal)
        # The 3 support sides of the ported frames, plus bad-frame7-turn's
        self.assertEqual(with_candidates, ['bad-frame4:1:yMax', 'bad-frame4:2:yMin', 'bad-frame7-turn:1:yMax',
                                           'bad-frame7:1:yMax'])

    def shoot(self, name, cx, cy, page=None, size=(1280, 720)):
        page = page or self.page
        page.evaluate(SHOOT, [cx, cy])
        img = Image.open(io.BytesIO(page.screenshot())).convert('RGB')
        self.assertEqual(img.size, size)
        img.save(EVIDENCE_DIR / 'shots' / name)

    def test_3_bad_frame7_shots(self):
        pattern = 'bad-frame7'
        x0, y0 = self.origin
        frame = self.patterns[pattern]
        _, _, g_top, g_bottom = piece_box(frame['pieces'][0])
        faces = [y0 + g_top, y0 + g_bottom]
        cx, cy = x0 + frame['span'] / 2, y0 + g_top
        rows = self.drive(pattern, [1], cycles=PERIOD_CYCLES)['rows'][0]
        turns = turn_cycles(rows, 'yMax')
        # Stop on a turn at the green's top: the blue sits on it
        self.drive(pattern, [1], [], -1, turns[1] + 1)
        self.shoot('frame7-before-use-blue-on-green.png', cx, cy)
        # Use the green (fade over: dropped on the next pass) and step on
        # until the blue is half way through the old green
        state = self.page.evaluate(FALL_THROUGH, faces)
        print('after use, falling through the gap', state)
        self.assertFalse(state['greenInFloor'])
        self.assertGreater(state['speedY'], 0)
        self.assertGreater(state['top'], y0 + g_top)
        self.assertEqual(state['yMax'], y0 + BAND)
        cy2 = y0 + (g_top + g_bottom) / 2
        self.shoot('frame7-after-use-blue-falling-through-gap.png', cx, cy2)
        # The same frame at 390x844 (a second page, the same state replayed)
        context = self.browser.new_context(viewport={'width': 390, 'height': 844})
        try:
            page = context.new_page()
            page.goto(self.url)
            wait_for_boot_run(page)
            page.evaluate(SEED_COURSE, SCRIPT)
            page.evaluate(SETUP, 972)
            page.evaluate(DRIVE, [pattern, x0, y0, [1], [], -1, turns[1] + 1, 1, 0])
            narrow = page.evaluate(FALL_THROUGH, faces)
            print('390x844 after use', narrow)
            self.assertEqual(narrow['top'], state['top'])
            self.shoot('frame7-after-use-390x844.png', cx, cy2, page, (390, 844))
        finally:
            context.close()
        # On to the turn at the corridor floor limit
        turn = self.page.evaluate(NEXT_BOTTOM_TURN)
        print('turn at the corridor floor', turn, 'limit', y0 + BAND)
        self.assertLessEqual(abs(turn['bottom'] - (y0 + BAND)), self.limit_tol)
        self.shoot('frame7-turn-at-corridor-floor.png', cx, y0 + BAND - 300)

    def test_4_bad_frame4_shot(self):
        """The polygon blue rising past the used green (the rect blue above
        used as well)"""
        pattern = 'bad-frame4'
        x0, y0 = self.origin
        frame = self.patterns[pattern]
        _, _, g_top, g_bottom = piece_box(frame['pieces'][0])
        rows = self.drive(pattern, [2], cycles=PERIOD_CYCLES)['rows'][0]
        turns = turn_cycles(rows, 'yMax')
        self.drive(pattern, [2], [], -1, turns[1] + 1)
        state = self.page.evaluate(RISE_PAST, y0 + g_top - 150)
        print('frame4 polygon rising past the used green', state)
        self.assertFalse(state['greenInFloor'])
        self.assertLess(state['speedY'], 0)
        self.assertLessEqual(state['top'], y0 + g_top - 150)
        self.shoot('frame4-polygon-rising-past-used-green.png', x0 + frame['span'] / 2,
                   y0 + (g_top + g_bottom) / 2)

if __name__ == '__main__':
    unittest.main()
