"""Momentum moving blue on a used green (TASK-078 reproduction).

Bug report: 'if green platform under the blue cube disappear, it still
bounces of "removed" green platform'. MomentumOneTime.moveY reverses speedY
whenever the shape would leave the FIXED range [motion.yMin, motion.yMax],
and MomentumPortPatternFactory copies those bounds from the ported bad frames
(MOMENTUM_PATTERNS_PORT_H, also reused by the turn types), where some sit on
a sibling green's face. Once that green is used the bound stays.

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
   and reaches the corridor limit (within LIMIT_TOL), for a yMin support its
   top goes above the old support's bottom. They fail on HEAD (the bug) and
   are marked expectedFailure until TASK-079 opens the range.

MOMENTUM_BLUE_SUPPORT_EVIDENCE_DIR (default artifacts/TASK-078) receives
supports.json, baseline-trace.json, bug-trace.json (per case [cycle, y,
speedY] every TRACE_EVERY cycles from USE_LEAD cycles before the use to the
end, plus the turns after the use) and shots/ (bad-frame7 at 1280x720: the
green just used and fading with the blue on it; the green gone and the blue
still turning on the empty spot). MOMENTUM_BLUE_SUPPORT_BASELINE (default
artifacts/TASK-078/baseline-trace.json) is the trace the baseline compares
against. Requires Playwright Chromium.
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
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_BLUE_SUPPORT_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-078'))
BASELINE = Path(os.environ.get('MOMENTUM_BLUE_SUPPORT_BASELINE',
                               ROOT / 'artifacts' / 'TASK-078' / 'baseline-trace.json'))
# First segment right with a length draw of 0.99 (~5 heights), then the LCG
SCRIPT = [0.99]
# The bad frames leave 0.01 * height gaps between a bound and its support
SUPPORT_TOL_RATIO = 0.02
# Right corridor half width (catalog corridor bound of a rect)
BAND = 972
LIMIT_TOL = 2
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

SETUP = '''() => {
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    ninja.invulnerableMs = 1e9
    return {height: height, segment: momentumCourse.segment(0),
            half: GAMEPLAY.momentumBorders.halfWidth,
            patterns: MOMENTUM_PATTERNS_PORT_H,
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
        info = cls.page.evaluate(SETUP)
        cls.height = info['height']
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
        (EVIDENCE_DIR / 'bug-trace.json').write_text(json.dumps(self.bug, separators=(',', ':')))
        print(f'{pattern} piece {index} {side}: period {period:.1f} use at {use_at} uses {uses} '
              f'face {face:.2f} limit {limit:.2f} extreme {extreme:.3f} turns after {len(turns_after)}')
        if side == 'yMax':
            self.assertGreater(extreme, face + 1)
            self.assertGreaterEqual(extreme, limit - LIMIT_TOL)
            self.assertLessEqual(extreme, limit + 1e-6)
        else:
            self.assertLess(extreme, face - 1)

    # fails until TASK-079 opens the range
    @unittest.expectedFailure
    def test_bad_frame4_yMax_opens(self):
        self.check_opens('bad-frame4', 1, 'yMax')

    # fails until TASK-079 opens the range
    @unittest.expectedFailure
    def test_bad_frame4_yMin_opens(self):
        self.check_opens('bad-frame4', 2, 'yMin')

    # fails until TASK-079 opens the range
    @unittest.expectedFailure
    def test_bad_frame7_yMax_opens(self):
        self.check_opens('bad-frame7', 1, 'yMax')

    def shoot(self, name, cx, cy):
        self.page.evaluate(SHOOT, [cx, cy])
        img = Image.open(io.BytesIO(self.page.screenshot())).convert('RGB')
        self.assertEqual(img.size, (1280, 720))
        img.save(EVIDENCE_DIR / 'shots' / name)

    def test_3_bad_frame7_shots(self):
        pattern = 'bad-frame7'
        x0, y0 = self.origin
        frame = self.patterns[pattern]
        green = frame['pieces'][0]
        _, _, g_top, _ = piece_box(green)
        cx, cy = x0 + frame['span'] / 2, y0 + g_top
        rows = self.drive(pattern, [1], cycles=PERIOD_CYCLES)['rows'][0]
        turns = turn_cycles(rows, 'yMax')
        # Use the green on a turn at its top: the blue sits on it
        res = self.drive(pattern, [1], [0], turns[1], turns[1] + 1)
        # Half way through the fade
        state = self.page.evaluate('''() => { const g = __support.els[0]
            g.fadeStartMs = performance.now() - GAMEPLAY.momentumFadeMs / 2
            return {alpha: g.getAlpha(), passThrough: g.passThrough} }''')
        print('used green', state, 'blue bottom', res['rows'][0][-1][4], 'green top', y0 + g_top)
        self.assertTrue(state['passThrough'])
        self.assertGreater(state['alpha'], 0.3)
        self.shoot('frame7-green-used-fading.png', cx, cy)
        # Fade over: the floor drops the green on its next pass; step on to
        # the next turn of the blue at the old green top
        after = self.page.evaluate('''() => {
            const {floor, els} = __support
            els[0].fadeStartMs = performance.now() - 2 * GAMEPLAY.momentumFadeMs
            const blue = els[1]
            let k = 0, flips = 0, prev = blue.speedY
            for (; k < 40000 && flips < 2; ++k) {
                floor.moveElements()
                if (prev > 0 && blue.speedY < 0) ++flips
                prev = blue.speedY
            }
            return {cycles: k, flips, greenInFloor: floor.elements.includes(els[0]),
                    bottom: blue.y + blue.bottomOffset, speedY: blue.speedY}
        }''')
        print('after green gone', after)
        self.assertFalse(after['greenInFloor'])
        self.shoot('frame7-green-gone-blue-still-turning.png', cx, cy)


if __name__ == '__main__':
    unittest.main()
