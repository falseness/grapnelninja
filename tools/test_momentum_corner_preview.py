"""Momentum corner preview: seeing into the next corridor before a corner (TASK-068 reproduction).

User report: "we still have troubles with camera on corners. I would prefer
it to change direction earlier. e.g. if there is a tunnel down, i see nothing
down and i have to go there blindly." The drive is that of
test_momentum_corner_camera: course scripts right -> right -> down / up ->
right for the joins right->down and right->up (a straight run longer than 1.5
views before the join) and right -> down / up -> right (test_momentum_shaft_view)
for down->right and up->right, the rAF loop stopped, the obstacle
floor emptied, the ninja invulnerable, one calcPhysics() per point, points
0.9 * momentumMaxSpeed apart. The corner box is the overlap of the two
corridors around the join (the vertical segment's half width across x, the
right corridors' half width across y).

Preview: how far the view reaches past the join's opening into the next
corridor, as a share of the view along the next axis (the faces are the
inner faces of the MomentumBorder walls, centre line +- half width):
right->down (view bottom - right corridor floor face) / viewH, right->up
(ceiling face - view top) / viewH, down/up->right (view right edge - shaft
right-wall face) / viewW. d: the ninja centre's distance to the corner box
entry edge along the old axis in view lengths along it (viewW in a right
segment, viewH in a shaft), < 0 inside the box. Margin: the ninja centre's
distance to the nearest view edge, as a share of the view along that edge's
axis.

Two drives per join from d = 1.5 to the box exit: 'centre' along the old
corridor's centre line to the join, then along the next one's out of the box;
'far' along the old corridor's side away from the next direction at 0.8 of
its half width, then through the box to the next corridor's centre line on
the exit edge.

test_<join>_preview (centre drive): preview >= MIN_PREVIEW at the first cycle
with d <= 0 and never drops by more than PREVIEW_DROP between cycles while
0 <= d <= 1. test_<join>_margin (both drives): margin >= MIN_MARGIN on every
cycle.

MOMENTUM_CORNER_PREVIEW_EVIDENCE_DIR (default artifacts/TASK-068) receives
preview-trace.json ({join: {drive: [{cycle, d, preview, margin, camVx, camVy,
seg}]}}, every 4th cycle) and, on the centre drive at d = 0.25 with the
opening and the ninja outlined in a DOM overlay (not drawn by the game),
shots/right-down-<w>x<h>.png and shots/down-right-<w>x<h>.png at 1280x720
and 390x844. Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_camera import SEED_COURSE
from test_momentum_shaft_view import SCRIPTS as SHAFT_SCRIPTS

ROOT = Path(__file__).resolve().parents[1]
MIN_PREVIEW = 0.25
PREVIEW_DROP = 0.002
MIN_MARGIN = 0.10
START_D = 1.5
# Least straight approach before START_D (views), to get onto the far lane
LEAD = 0.2
SHOT_D = 0.25
VIEWPORT = (1280, 720)
SHOT_VIEWPORTS = [(1280, 720), (390, 844)]
SHOT_JOINS = ['right-down', 'down-right']
# Into a shaft: right, right (the rightAfterRight draw 0.1 < 0.4 keeps it
# right, no dir draw), then the shaft: about 2.5 views of straight corridor at
# 1280x720 before the join, where one right segment (at most maxLen, 5
# heights) is under 1.5 views. Out of a shaft: the test_momentum_shaft_view
# scripts
SCRIPTS = dict(SHAFT_SCRIPTS, **{'right-right-down': [0.99, 0.1, 0.99, 0.9, 0.9, 0.99, 0.5],
                                 'right-right-up': [0.99, 0.1, 0.99, 0.9, 0.1, 0.99, 0.5]})
# join: (course script, index of the segment before the join)
JOINS = {'right-down': ('right-right-down', 1), 'right-up': ('right-right-up', 1),
         'down-right': ('down', 1), 'up-right': ('up', 1)}
DRIVES = ['centre', 'far']
# Joins whose preview test fails on 7d04e88..332a63d. Out of a shaft
# (down/up->right) the camera centred on a shaft half a view wide (TASK-043)
# already sees 0.27 of the view past its right wall: those pass on HEAD.
INTO_SHAFT = ['right-down', 'right-up']

# Builds the drive's path and the join geometry; window.previewState drives RUN
SETUP = '''([index, drive, startD]) => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const a = momentumCourse.segment(index), b = momentumCourse.segment(index + 1)
    const vertical = a.dir == 'right' ? b : a
    const W = momentumSegmentHalfWidth(vertical), H = GAMEPLAY.momentumBorders.halfWidth
    const jx = a.x1, jy = a.y1
    const box = {left: jx - W, right: jx + W, top: jy - H, bottom: jy + H}
    const da = segmentDirection(a.dir), db = segmentDirection(b.dir)
    const viewH = height / scale[version], viewW = width / scale[version]
    const v = 0.9 * GAMEPLAY.momentumMaxSpeed
    const path = []
    const line = (x0, y0, x1, y1) => {
        const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / v))
        for (let i = 0; i < n; ++i)
            path.push([x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, (x1 - x0) / n, (y1 - y0) / n])
    }
    // Earlier segments along the centre line, up to the straight run that
    // ends at the join (segments along a's axis before it are part of it)
    let first = index
    while (first > 0 && momentumCourse.segment(first - 1).dir == a.dir)
        --first
    let x = ninja.x, y = momentumCourse.segment(0).y0
    for (let i = 0; i < first; ++i) {
        const s = momentumCourse.segment(i)
        line(x, y, s.x1, s.y1)
        x = s.x1; y = s.y1
    }
    // Entry edge centre and the point at d along the old axis
    const view = a.dir == 'right' ? viewW : viewH
    const entryC = [jx - da.x * W, jy - da.y * H]
    const at = d => [entryC[0] - da.x * d * view, entryC[1] - da.y * d * view]
    // Sideways offset of the far lane: away from the next direction
    const side = drive == 'far' ? (a.dir == 'right' ? [0, -db.y * 0.8 * H] : [-db.x * 0.8 * W, 0]) : [0, 0]
    const lane = d => { const p = at(d); return [p[0] + side[0], p[1] + side[1]] }
    // Centre line up to d = startD + 0.5 (or from where the ninja is if the
    // straight run is shorter: 1.77 views right, right at 1280x720, 1.85 in
    // a shaft), onto the lane by startD (the caller checks dMax >= startD +
    // LEAD)
    const dMax = a.dir == 'right' ? (box.left - x) / viewW
        : a.dir == 'down' ? (box.top - y) / viewH : (y - box.bottom) / viewH
    const entry = lane(0)
    const p0 = at(Math.min(startD + 0.5, dMax)), p1 = lane(startD)
    line(x, y, p0[0], p0[1])
    line(p0[0], p0[1], p1[0], p1[1])
    line(p1[0], p1[1], entry[0], entry[1])
    // Through the box: centre to the join point and out along the next centre
    // line; far straight to the next centre line on the exit edge
    const exit = [jx + db.x * W, jy + db.y * H]
    if (drive == 'centre') {
        line(entry[0], entry[1], jx, jy)
        line(jx, jy, exit[0], exit[1])
    } else
        line(entry[0], entry[1], exit[0], exit[1])
    line(exit[0], exit[1], exit[0] + db.x * 4 * v, exit[1] + db.y * 4 * v)
    window.previewState = {path, box, a, b, i: 0, n0: ninja, deaths0: lethalDeaths, W, H, from: startD}
    return {box, dirs: [a.dir, b.dir], W, H, viewW, viewH, pathLength: path.length, dMax}
}'''

# Runs the path until the ninja is out of the box (stop null) or d <= stop
RUN = '''([stop, startD]) => {
    const st = window.previewState, box = st.box, a = st.a, b = st.b
    const viewH = height / scale[version], viewW = width / scale[version]
    const dOf = () => a.dir == 'right' ? (box.left - ninja.x) / viewW
        : a.dir == 'down' ? (box.top - ninja.y) / viewH : (ninja.y - box.bottom) / viewH
    const preview = () => {
        const left = -screen.x, top = -screen.y
        if (b.dir == 'down')
            return (top + viewH - (a.y0 + st.H)) / viewH
        if (b.dir == 'up')
            return (a.y0 - st.H - top) / viewH
        return (left + viewW - (a.x0 + st.W)) / viewW
    }
    const margin = () => {
        const sx = ninja.x + screen.x, sy = ninja.y + screen.y
        return Math.min(sx / viewW, (viewW - sx) / viewW, sy / viewH, (viewH - sy) / viewH)
    }
    const out = () => b.dir == 'right' ? ninja.x > box.right
        : b.dir == 'up' ? ninja.y < box.top : ninja.y > box.bottom
    st.rows = st.rows || []
    while (st.i < st.path.length) {
        const [x, y, vx, vy] = st.path[st.i]
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy - GRAVITY
        calcPhysics()
        const cycle = st.i++
        if (ninja !== st.n0)
            return {stop: 'gameOver', cycle}
        const d = dOf()
        if (d <= st.from) {
            st.rows.push({cycle, d: +d.toFixed(4), preview: +preview().toFixed(4), margin: +margin().toFixed(4),
                          camVx: +screen.velocityX.toFixed(3), camVy: +screen.velocityY.toFixed(3),
                          seg: screen.segmentIndex})
            if (d < 0 && out())
                return {stop: 'exit', cycle, rows: st.rows, deaths: lethalDeaths - st.deaths0}
            if (stop !== null && d <= stop)
                return {stop: 'd', cycle, d, preview: preview()}
        }
    }
    return {stop: null, rows: st.rows, deaths: lethalDeaths - st.deaths0}
}'''

DRAW = '(() => { visualEffects.screenEffects.landings.length = 0; draw() })()'
# DOM overlay (screenshot only): the opening and the ninja in CSS pixels
OVERLAY = '''(label) => {
    const st = window.previewState, a = st.a, b = st.b
    const rect = canvas.getBoundingClientRect(), k = scale[version] * rect.width / width
    const px = (x, y) => [rect.left + (x + screen.x) * k, rect.top + (y + screen.y) * k]
    // The opening: the shaft's inner span at the floor / ceiling face, or the
    // right corridor's inner span at the shaft's right wall
    const [x0, y0, x1, y1] = b.dir == 'right' ? [a.x0 + st.W, b.y0 - st.H, a.x0 + st.W, b.y0 + st.H]
        : [b.x0 - st.W, a.y0 + (b.dir == 'down' ? st.H : -st.H), b.x0 + st.W, a.y0 + (b.dir == 'down' ? st.H : -st.H)]
    const [ox0, oy0] = px(x0, y0), [ox1, oy1] = px(x1, y1)
    const [nx, ny] = px(ninja.x, ninja.y)
    // Label above a letterboxed canvas, else over its bottom edge
    const ly = rect.top >= 44 ? rect.top - 40 : rect.top + rect.height - 40
    const div = document.createElement('div')
    div.id = 'preview-overlay'
    div.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:99999'
    div.innerHTML = `<svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <line x1="${ox0}" y1="${oy0}" x2="${ox1}" y2="${oy1}" stroke="#ff00ff" stroke-width="5" stroke-dasharray="12 6"/>
        <circle cx="${ox0}" cy="${oy0}" r="7" fill="#ff00ff"/>
        <circle cx="${ox1}" cy="${oy1}" r="7" fill="#ff00ff"/>
        <circle cx="${nx}" cy="${ny}" r="14" fill="none" stroke="#00ffff" stroke-width="3"/>
        <line x1="${nx - 22}" y1="${ny}" x2="${nx + 22}" y2="${ny}" stroke="#00ffff" stroke-width="2"/>
        <line x1="${nx}" y1="${ny - 22}" x2="${nx}" y2="${ny + 22}" stroke="#00ffff" stroke-width="2"/>
        <rect x="4" y="${ly}" width="${Math.min(rect.width - 8, 1100)}" height="34" fill="rgba(0,0,0,0.75)"/>
        <text x="10" y="${ly + 23}" fill="#ffffff" font-family="monospace"
              font-size="${rect.width < 600 ? 11 : 18}">${label}</text>
    </svg>`
    document.body.appendChild(div)
}'''
UNOVERLAY = '(() => document.getElementById("preview-overlay").remove())()'


def first_at(rows, d):
    return next((r for r in rows if r['d'] <= d), None)


class MomentumCornerPreviewTests(unittest.TestCase):
    runs = {}

    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_CORNER_PREVIEW_EVIDENCE_DIR', ROOT / 'artifacts/TASK-068'))
        (cls.out / 'shots').mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        trace = {join: {drive: [row for k, row in enumerate(r['rows']) if k % 4 == 0]
                        for drive, r in drives.items()} for join, drives in cls.runs.items()}
        (cls.out / 'preview-trace.json').write_text(json.dumps(trace, separators=(',', ':')) + '\n')

    def page(self, viewport):
        context = self.browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        return page, errors

    def shoot(self, join, viewport):
        script, index = JOINS[join]
        page, errors = self.page(viewport)
        page.evaluate(SEED_COURSE, SCRIPTS[script])
        page.evaluate(SETUP, [index, 'centre', START_D])
        at = page.evaluate(RUN, [SHOT_D, START_D])
        self.assertEqual(at['stop'], 'd')
        page.evaluate(DRAW)
        page.evaluate(OVERLAY, f'{join} {viewport[0]}x{viewport[1]} d {at["d"]:.2f} preview {at["preview"]:.3f} '
                               f'(magenta: opening)')
        page.screenshot(path=str(self.out / 'shots' / f'{join}-{viewport[0]}x{viewport[1]}.png'))
        page.evaluate(UNOVERLAY)
        self.assertEqual(errors, [])

    def drives(self, join):
        if join in self.runs:
            return self.runs[join]
        script, index = JOINS[join]
        page, errors = self.page(VIEWPORT)
        page.evaluate(SEED_COURSE, SCRIPTS[script])
        result = {}
        for drive in DRIVES:
            setup = page.evaluate(SETUP, [index, drive, START_D])
            self.assertEqual('-'.join(setup['dirs']), join)
            self.assertGreaterEqual(setup['dMax'], START_D + LEAD, f'{join} {drive}: approach of {setup["dMax"]} views')
            r = page.evaluate(RUN, [None, START_D])
            self.assertEqual(r['stop'], 'exit', f'{join} {drive}: drive ended without leaving the box ({r["stop"]})')
            self.assertEqual(r['deaths'], 0)
            rows = r['rows']
            self.assertGreaterEqual(rows[0]['d'], START_D - 0.01, f'{join} {drive}: drive starts at d {rows[0]["d"]}')
            summary = {'startD': rows[0]['d']}
            summary.update({f'preview@d{d}': first_at(rows, d)['preview'] for d in (1, 0.5, 0)})
            summary['dMax'] = round(setup['dMax'], 4)
            summary['minMargin'] = min(row['margin'] for row in rows)
            print(f'{join} {drive}: {json.dumps(summary)} cycles {len(rows)}', file=sys.stderr)
            result[drive] = {'rows': rows, 'summary': summary}
        self.assertEqual(errors, [])
        self.runs[join] = result
        if join in SHOT_JOINS:
            for viewport in SHOT_VIEWPORTS:
                self.shoot(join, viewport)
        return result

    def check_preview(self, join):
        rows = self.drives(join)['centre']['rows']
        at0 = first_at(rows, 0)
        self.assertGreaterEqual(at0['preview'], MIN_PREVIEW,
                                f'{join}: preview {at0["preview"]} at the box entry (d {at0["d"]})')
        approach = [row for row in rows if 0 <= row['d'] <= 1]
        drops = [(p['cycle'], p['preview'], q['preview']) for p, q in zip(approach, approach[1:])
                 if q['preview'] < p['preview'] - PREVIEW_DROP]
        self.assertEqual(drops, [], f'{join}: preview drops (cycle, before, after)')

    def check_margin(self, join):
        for drive, r in self.drives(join).items():
            low = [(row['cycle'], row['d'], row['margin']) for row in r['rows'] if row['margin'] < MIN_MARGIN]
            self.assertEqual(low[:5], [], f'{join} {drive}: margin below {MIN_MARGIN} in {len(low)} cycles')


def make_test(join, kind):
    def test(self):
        getattr(self, f'check_{kind}')(join)
    if kind == 'preview' and join in INTO_SHAFT:
        # fails on HEAD until TASK-069 (into shafts) / TASK-070 (out of shafts)
        test = unittest.expectedFailure(test)
    return test


for join in JOINS:
    for kind in ('margin', 'preview'):
        setattr(MomentumCornerPreviewTests, f'test_{join.replace("-", "_")}_{kind}', make_test(join, kind))


if __name__ == '__main__':
    unittest.main(verbosity=2)
