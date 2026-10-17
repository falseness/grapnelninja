"""Momentum patterns in the wide shafts (TASK-031).

Since TASK-030 a vertical course segment has its own half width
(momentumSegmentHalfWidth); vertical patterns span its inner width, a turn
type's square is that wide across the shaft and the join margins follow it
(elements/momentumpatterns.js).

At 1280x720 and 390x844 (fresh page load each) the 60 s scripted run of
test_momentum_no_outside (seeded Math.random, MOMENTUM_RUN_SEED, the ninja put
on the course centre line further every frame at GAMEPLAY.momentumMaxSpeed per
physics cycle, then physics()) is sampled after every frame. Every obstacle
piece (MomentumObstacleFloor element) is checked once, the first frame it
exists: its box must lie inside the union of the corridor interiors (the box
between a segment's two border lines, momentumSegmentBorderLines) and overlap
no border body (MomentumBorder points: wall + backing). Frames with at
least half the view height in a shaft's straight part (between the two
right corridors it joins) record the camera x centre vs the shaft centre, how far the wall
bodies' outer edges are past the view edges (recorded only: negative since
TASK-043 halved the shafts) and how far inside the view the walls' inner
faces are (>= 0: the corridor is no wider than the view, the walls show at
its edges). Asserts per viewport: >= 1 vertical pattern and >= 1 up and >= 1
down shaft, 0 pieces outside or in a wall, the inner-face distance >= 0 on
every such frame, 0 page errors.

MOMENTUM_PIECES_INSIDE_EVIDENCE_DIR (default artifacts/TASK-031) receives
pieces-inside.json (compact {viewport: {pieces, verticalPieces, turnPieces,
outsideOrInWall, bad}}), shaft-camera.json (compact {viewport: [per shaft
{segment, dir, x0, halfWidth, frames, centreOffset [min, max], wallOuterPastEdge
min [left, right], wallInnerInside min [left, right]}]}, screen px) and
shots/<w>x<h>-<up|down>.png: the first frame in an up / down shaft with half
the view in its straight part and >= 2 vertical pieces in view.
Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_run import DRAW, FPS, SECONDS, SEED, SETUP

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_PIECES_INSIDE_EVIDENCE_DIR', ROOT / 'artifacts/TASK-031'))
VIEWPORTS = [(1280, 720), (390, 844)]

# Least part of the view height in a shaft's straight part (between the
# right corridors it joins) for a frame to count as a shaft frame
STRAIGHT = 0.5

# Per frame: the pieces not checked yet (inside the corridors, out of the
# border bodies) and, with the view in a shaft's straight part, the camera
# numbers; returns early on a frame worth a shot (shoot: dirs still wanted)
RUN = '''([frames, step, shoot]) => {
    const STRAIGHT = ''' + str(STRAIGHT) + '''
    const v = step / cyclesPerTick
    const startHp = GAMEPLAY.momentumHp.startHp
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    const snap = x => Math.round(x * 1e6) / 1e6
    const box = pts => ({l: snap(Math.min(...pts.map(p => p.x))), r: snap(Math.max(...pts.map(p => p.x))),
                         t: snap(Math.min(...pts.map(p => p.y))), b: snap(Math.max(...pts.map(p => p.y)))})
    const vw = width / scale[version], vh = height / scale[version]
    window.checkedPieces = window.checkedPieces || new WeakSet()
    const out = {frames: 0, pieces: [], shafts: [], shot: null}
    for (let k = 0; k < frames; ++k) {
        runArc += step
        let i = screen.segmentIndex
        while (floor.getArcStart(i + 1) <= runArc) ++i
        const s = momentumCourse.segment(i), d = momentumDirection(s.dir)
        const along = runArc - floor.getArcStart(i)
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = s.x0 + d.x * along; ninja.y = s.y0 + d.y * along
        ninja.speedX = d.x * v; ninja.speedY = d.y * v
        physics()
        if (momentumState.hp < startHp) momentumState.hp = startHp
        ++runFrame; ++out.frames
        const state = runRngState()
        // Only segments already generated: generating more would draw Math.random
        const course = momentumCourse
        const corridors = []
        for (let j = 0; j + 1 < course.segments.length; ++j)
            corridors.push(box(momentumSegmentBorderLines(course, j).flatMap(l => [{x: l.x0, y: l.y0}, {x: l.x1, y: l.y1}])))
        const bodies = []
        for (const f of floors)
            if (f instanceof MomentumBorderFloor)
                for (const e of f.elements) bodies.push(box(e.getPoints()))
        for (const e of floor.elements) {
            if (checkedPieces.has(e)) continue
            checkedPieces.add(e)
            const b = getElementBounds(e)
            const p = {l: snap(b.left), r: snap(b.right), t: snap(b.top), b: snap(b.bottom)}
            const rects = corridors.map(c => ({l: Math.max(c.l, p.l), r: Math.min(c.r, p.r),
                                               t: Math.max(c.t, p.t), b: Math.min(c.b, p.b)}))
                .filter(r => r.l < r.r && r.t < r.b)
            const xs = [...new Set([p.l, p.r, ...rects.flatMap(r => [r.l, r.r])])].sort((a, b) => a - b)
            const ys = [...new Set([p.t, p.b, ...rects.flatMap(r => [r.t, r.b])])].sort((a, b) => a - b)
            let outside = 0
            for (let x = 0; x + 1 < xs.length; ++x)
                for (let y = 0; y + 1 < ys.length; ++y) {
                    const cx = (xs[x] + xs[x + 1]) / 2, cy = (ys[y] + ys[y + 1]) / 2
                    if (!rects.some(r => r.l < cx && cx < r.r && r.t < cy && cy < r.b))
                        outside += (xs[x + 1] - xs[x]) * (ys[y + 1] - ys[y])
                }
            let inWall = 0
            for (const w of bodies) {
                const ow = Math.min(w.r, p.r) - Math.max(w.l, p.l), oh = Math.min(w.b, p.b) - Math.max(w.t, p.t)
                if (ow > 0 && oh > 0) inWall += ow * oh
            }
            const seg = course.segments.findIndex((c, j) => j + 1 < course.segments.length &&
                corridors[j].l <= p.l && p.r <= corridors[j].r && corridors[j].t <= p.t && p.b <= corridors[j].b)
            out.pieces.push([runFrame, seg >= 0 ? course.segment(seg).dir : 'join', outside, inWall,
                             [p.l, p.t, p.r, p.b].map(x => Math.round(x))])
        }
        const cur = screen.getSegment()
        if (cur.dir != 'right') {
            const hw = momentumSegmentHalfWidth(cur)
            const base = GAMEPLAY.momentumBorders.halfWidth, o = GAMEPLAY.momentumBorders
            const lo = Math.min(cur.y0, cur.y1) + base, hi = Math.max(cur.y0, cur.y1) - base
            const view = {l: -screen.x, r: -screen.x + vw, t: -screen.y, b: -screen.y + vh}
            if (Math.min(view.b, hi) - Math.max(view.t, lo) >= STRAIGHT * vh) {
                const body = o.thickness + o.backing
                out.shafts.push([screen.segmentIndex, cur.dir, cur.x0, hw, view.l + vw / 2 - cur.x0,
                    view.l - (cur.x0 - hw - body), (cur.x0 + hw + body) - view.r,
                    (cur.x0 - hw) - view.l, view.r - (cur.x0 + hw)])
                if (shoot.includes(cur.dir)) {
                    const seen = floor.elements.filter(e => {
                        const b = getElementBounds(e)
                        return b.right > view.l && b.left < view.r && b.bottom > view.t && b.top < view.b &&
                            b.left >= cur.x0 - hw - 1 && b.right <= cur.x0 + hw + 1
                    }).length
                    if (seen >= 2) {
                        out.shot = cur.dir
                        runRngState(state)
                        return out
                    }
                }
            }
        }
        runRngState(state)
    }
    return out
}'''


class MomentumPiecesInsideTests(unittest.TestCase):
    pieces = {}
    cameras = {}

    @classmethod
    def setUpClass(cls):
        cls.out = EVIDENCE_DIR
        (cls.out / 'shots').mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'pieces-inside.json').write_text(json.dumps(cls.pieces, separators=(',', ':')) + '\n')
        (cls.out / 'shaft-camera.json').write_text(json.dumps(cls.cameras, separators=(',', ':')) + '\n')

    def run_viewport(self, w, h):
        context = self.browser.new_context(viewport={'width': w, 'height': h})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SETUP, SEED)
        step = page.evaluate('GAMEPLAY.momentumMaxSpeed * cyclesPerTick')
        # World units -> screen px
        px = h / page.evaluate('height / scale[version]')
        pieces, frames, shots = [], [], {}
        left = SECONDS * FPS
        while left:
            r = page.evaluate(RUN, [left, step, [d for d in ('up', 'down') if d not in shots]])
            pieces += r['pieces']
            frames += r['shafts']
            left -= r['frames']
            if r['shot']:
                name = f'{w}x{h}-{r["shot"]}.png'
                page.evaluate(DRAW)
                page.screenshot(path=str(self.out / 'shots' / name))
                shots[r['shot']] = name
        bad = [p for p in pieces if p[2] > 0 or p[3] > 0]
        key = f'{w}x{h}'
        self.pieces[key] = {'pieces': len(pieces), 'verticalPieces': sum(p[1] in ('up', 'down') for p in pieces),
                            'turnPieces': sum(p[1] == 'join' for p in pieces),
                            'outsideOrInWall': len(bad), 'bad': bad[:10], 'seed': SEED, 'shots': shots}
        shafts = []
        for seg in sorted({f[0] for f in frames}):
            fs = [f for f in frames if f[0] == seg]
            shafts.append({'segment': seg, 'dir': fs[0][1], 'x0': round(fs[0][2], 2),
                           'halfWidth': round(fs[0][3], 2), 'frames': len(fs),
                           'centreOffset': [round(min(f[4] for f in fs) * px, 3), round(max(f[4] for f in fs) * px, 3)],
                           'wallOuterPastEdge': [round(min(f[5] for f in fs) * px, 3), round(min(f[6] for f in fs) * px, 3)],
                           'wallInnerInside': [round(min(f[7] for f in fs) * px, 3), round(min(f[8] for f in fs) * px, 3)]})
        self.cameras[key] = shafts
        print(key, json.dumps(self.pieces[key], separators=(',', ':')), file=sys.stderr)
        print(key, json.dumps(shafts, separators=(',', ':')), file=sys.stderr)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(self.pieces[key]['verticalPieces'], 1)
        self.assertEqual(len(bad), 0, bad[:5])
        self.assertTrue({'up', 'down'} <= {s['dir'] for s in shafts}, shafts)
        # wallOuterPastEdge is only recorded: since TASK-043 a shaft is half
        # the view-wide width, so its walls' outer edges are inside the view
        # (what shows past them is TASK-044's, test_momentum_no_outside)
        for s in shafts:
            self.assertGreaterEqual(min(s['wallInnerInside']), 0, s)
        self.assertEqual(sorted(shots), ['down', 'up'])

    def test_1280x720(self):
        self.run_viewport(1280, 720)

    def test_390x844(self):
        self.run_viewport(390, 844)


if __name__ == '__main__':
    unittest.main()
