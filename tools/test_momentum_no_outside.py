"""Momentum shafts show nothing outside the walls (TASK-030).

A vertical course segment gets its own half width
(momentumSegmentHalfWidth in elements/momentumborders.js), wide enough that a
view centred on it shows only the corridor and its walls.

At each viewport (fresh page load) the 60 s scripted run of test_momentum_run
(seeded Math.random, MOMENTUM_RUN_SEED, ninja put on the course centre line
further every frame, then physics()) at the fastest the ninja can go,
GAMEPLAY.momentumMaxSpeed per physics cycle (test_momentum_run's DRIVE_SPEED
is above that cap since TASK-029) is sampled after
every frame, i.e. every cyclesPerTick (8) physics cycles, finer than every
10th cycle. Each sample computes, from the course/border geometry, the area
of the view that is neither a corridor interior (the box between a
segment's two border lines, momentumSegmentBorderLines) nor a live border
body (MomentumBorder points): the union of those boxes is subtracted from
the view (coordinates snapped to 1e-6 world units). Since TASK-043 halved
the shafts, the view outside the walls is covered by the wall mass instead
(TASK-044, momentumOutsideCells in elements/momentumborders.js): the area
counted is the view outside every corridor interior and every wall mass
cell. Asserts per viewport:
- that area is 0 at every sample;
- pixels (PIXELS, every PIXEL_EVERY frames and at the shot frames, HUD and
  hint not drawn): every sampled canvas pixel outside the current corridor's
  interior (past its border cap/glow band) is the wall mass colour
  STYLE.momentum.wallFill, so no piece, other corridor or background shows;
- >= 1 shaft (vertical segment) was driven through;
- no live border body overlaps a corridor interior (wide shafts never
  reach into each other: right segments after a shaft are long enough).

MOMENTUM_NO_OUTSIDE_EVIDENCE_DIR (default artifacts/TASK-044) receives
outside-pixels.json (compact {viewport: {frames, samples, nonWallPixels,
bad}}), outside-area.json (compact {viewport: {samples, maxOutsideArea, shafts,
maxWallInCorridorArea, worst}}, areas in screen px^2) and shots/: per viewport
<w>x<h>-mid-shaft.png (the ninja half way up/down the first shaft) and
<w>x<h>-corner.png (the frame the ninja turns out of the first shaft into the
next right corridor, the camera still moving). Requires Playwright Chromium.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_run import DRAW, FPS, SECONDS, SEED, SETUP

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_NO_OUTSIDE_EVIDENCE_DIR', ROOT / 'artifacts/TASK-044'))
VIEWPORTS = [(390, 844), (1280, 720), (1024, 768), (844, 390)]

# Area of the view outside every corridor interior and border body, and the
# area where a border body overlaps a corridor interior (world units^2)
MEASURE = '''() => {
    const snap = v => Math.round(v * 1e6) / 1e6
    const vw = width / scale[version], vh = height / scale[version]
    const view = {l: snap(-screen.x), t: snap(-screen.y)}
    view.r = snap(view.l + vw); view.b = snap(view.t + vh)
    const box = pts => ({l: snap(Math.min(...pts.map(p => p.x))), r: snap(Math.max(...pts.map(p => p.x))),
                         t: snap(Math.min(...pts.map(p => p.y))), b: snap(Math.max(...pts.map(p => p.y)))})
    const corridors = []
    // Only segments already generated: generating more would draw Math.random
    const course = momentumCourse
    for (let i = 0; i + 1 < course.segments.length; ++i) {
        const lines = momentumSegmentBorderLines(course, i, GAMEPLAY.momentumBorders.halfWidth)
        corridors.push(box(lines.flatMap(l => [{x: l.x0, y: l.y0}, {x: l.x1, y: l.y1}])))
    }
    const bodies = []
    for (const f of floors)
        if (f instanceof MomentumBorderFloor)
            for (const e of f.elements) bodies.push(box(e.getPoints()))
    // The wall mass painted over the view (none before TASK-044)
    const mass = typeof momentumOutsideCells == 'function'
        ? momentumOutsideCells().cells.map(c => ({l: snap(c.l), r: snap(c.r), t: snap(c.t), b: snap(c.b)})) : []
    const clip = r => ({l: Math.max(r.l, view.l), r: Math.min(r.r, view.r),
                        t: Math.max(r.t, view.t), b: Math.min(r.b, view.b)})
    const rects = corridors.concat(mass).map(clip).filter(r => r.l < r.r && r.t < r.b)
    const xs = [...new Set([view.l, view.r, ...rects.flatMap(r => [r.l, r.r])])].sort((a, b) => a - b)
    const ys = [...new Set([view.t, view.b, ...rects.flatMap(r => [r.t, r.b])])].sort((a, b) => a - b)
    let outside = 0
    for (let i = 0; i + 1 < xs.length; ++i)
        for (let j = 0; j + 1 < ys.length; ++j) {
            const cx = (xs[i] + xs[i + 1]) / 2, cy = (ys[j] + ys[j + 1]) / 2
            if (!rects.some(r => r.l < cx && cx < r.r && r.t < cy && cy < r.b))
                outside += (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
        }
    let overlap = 0
    for (const c of corridors)
        for (const b of bodies) {
            const w = Math.min(c.r, b.r) - Math.max(c.l, b.l), h = Math.min(c.b, b.b) - Math.max(c.t, b.t)
            if (w > 0 && h > 0) overlap += w * h
        }
    return {outside, overlap}
}'''

# Draws the frame without the HUD and the first-run hint (drawn over the wall
# mass by design) and samples a GRID x GRID pixel grid of the game canvas.
# A sample counts when it lies outside the interior of the corridor the ninja
# is in (the segments around screen.segmentIndex as far as they reach into
# the view without a break) by more than the border's cap / inner neon glow
# band; it must be the opaque wall mass colour STYLE.momentum.wallFill.
PIXELS = '''(grid) => {
    const state = runRngState()
    const ui = visualEffects.ui, uiDraw = ui.draw, fpsDraw = ui.drawFpsCounter, hint = TUTORIAL_HINT.visible
    ui.draw = () => {}; ui.drawFpsCounter = () => {}; TUTORIAL_HINT.visible = false
    try { draw() } finally { ui.draw = uiDraw; ui.drawFpsCounter = fpsDraw; TUTORIAL_HINT.visible = hint }
    runRngState(state)
    const view = {l: -screen.x, t: -screen.y}
    view.r = view.l + width / scale[version]; view.b = view.t + height / scale[version]
    const course = momentumCourse
    const box = i => {
        const lines = momentumSegmentBorderLines(course, i, GAMEPLAY.momentumBorders.halfWidth)
        const xs = lines.flatMap(l => [l.x0, l.x1]), ys = lines.flatMap(l => [l.y0, l.y1])
        return {l: Math.min(...xs), r: Math.max(...xs), t: Math.min(...ys), b: Math.max(...ys)}
    }
    const inView = b => b.l < view.r && b.r > view.l && b.t < view.b && b.b > view.t
    const last = course.segments.length - 2, cur = Math.min(screen.segmentIndex, last)
    const boxes = [box(cur)]
    for (let i = cur - 1; i >= 0 && inView(box(i)); --i) boxes.push(box(i))
    for (let i = cur + 1; i <= last && inView(box(i)); ++i) boxes.push(box(i))
    const T = ctx.getTransform(), k = T.a * scale[version]
    const neon = STYLE.strokes.neonOutline
    const cap = Math.max(2, screenHeightPercent(STYLE.spriteGeometry.capHeightPercent))
    // Canvas px -> world units: the cap strip / widest inner glow line + AA
    const band = (Math.max(4 * neon.width * T.a, cap * k) + 3) / k
    const hex = STYLE.momentum.wallFill
    const want = [1, 3, 5].map(i => parseInt(hex.substr(i, 2), 16))
    const cw = canvas.width, ch = canvas.height
    const data = ctx.getImageData(0, 0, cw, ch).data
    let samples = 0, nonWall = 0
    const bad = []
    for (let gx = 0; gx < grid; ++gx)
        for (let gy = 0; gy < grid; ++gy) {
            const px = Math.floor((gx + 0.5) * cw / grid), py = Math.floor((gy + 0.5) * ch / grid)
            const wx = (px + 0.5 - T.e) / k - screen.x, wy = (py + 0.5 - T.f) / k - screen.y
            if (boxes.some(b => b.l - band < wx && wx < b.r + band && b.t - band < wy && wy < b.b + band))
                continue
            ++samples
            const o = 4 * (py * cw + px)
            const rgba = [data[o], data[o + 1], data[o + 2], data[o + 3]]
            if (rgba[0] != want[0] || rgba[1] != want[1] || rgba[2] != want[2] || rgba[3] != 255) {
                ++nonWall
                if (bad.length < 3) bad.push([px, py, rgba])
            }
        }
    return {samples, nonWall, bad}
}'''
GRID = 48
# Pixel check every PIXEL_EVERY driven frames (and at the shot frames)
PIXEL_EVERY = 60

# One driven frame (the DRIVE body of test_momentum_run for one frame), then
# a sample; stops early at the first mid-shaft / shaft-exit frame not shot yet
RUN = '''([frames, step, want]) => {
    const v = step / cyclesPerTick
    const startHp = GAMEPLAY.momentumHp.startHp
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    const measure = ''' + MEASURE + '''
    const out = []
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
        const before = screen.segmentIndex
        physics()
        if (momentumState.hp < startHp) momentumState.hp = startHp
        ++runFrame
        const state = runRngState()
        const m = measure()
        runRngState(state)
        const seg = screen.getSegment()
        out.push([runFrame, screen.segmentIndex, seg.dir, m.outside, m.overlap])
        if (want == 'mid' && seg.dir != 'right' &&
            Math.abs(ninja.y - seg.y0) >= seg.length / 2)
            return {out, shot: 'mid'}
        if (want == 'corner' && seg.dir == 'right' && momentumCourse.segment(screen.segmentIndex - 1).dir != 'right' &&
            before != screen.segmentIndex)
            return {out, shot: 'corner'}
        if (runFrame % ''' + str(PIXEL_EVERY) + ''' == 0)
            return {out, shot: null}
    }
    return {out, shot: null}
}'''


class MomentumNoOutsideTests(unittest.TestCase):
    results = {}
    pixel_results = {}

    @classmethod
    def setUpClass(cls):
        cls.out = EVIDENCE_DIR
        (cls.out / 'shots').mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'outside-area.json').write_text(json.dumps(cls.results, separators=(',', ':')) + '\n')
        (cls.out / 'outside-pixels.json').write_text(json.dumps(cls.pixel_results, separators=(',', ':')) + '\n')

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
        # World units^2 -> screen px^2
        px = (h / page.evaluate('height / scale[version]')) ** 2
        samples, shots = [], {}
        pixels = {'frames': 0, 'samples': 0, 'nonWallPixels': 0, 'bad': []}

        def check_pixels(frame):
            p = page.evaluate(PIXELS, GRID)
            pixels['frames'] += 1
            pixels['samples'] += p['samples']
            pixels['nonWallPixels'] += p['nonWall']
            if p['bad'] and len(pixels['bad']) < 5:
                pixels['bad'].append([frame] + p['bad'][0])
        left = SECONDS * FPS
        while left:
            want = 'mid' if 'mid' not in shots else 'corner' if 'corner' not in shots else None
            r = page.evaluate(RUN, [left, step, want])
            samples += r['out']
            left -= len(r['out'])
            if r['out'][-1][0] % PIXEL_EVERY == 0 or r['shot']:
                check_pixels(r['out'][-1][0])
            if r['shot']:
                name = f'{w}x{h}-{"mid-shaft" if r["shot"] == "mid" else "corner"}.png'
                page.evaluate(DRAW)
                page.screenshot(path=str(self.out / 'shots' / name))
                shots[r['shot']] = [name, r['out'][-1][0]]
        shafts = sorted({s[1] for s in samples if s[2] != 'right'})
        worst = max(samples, key=lambda s: s[3])
        result = {'samples': len(samples), 'maxOutsideArea': round(worst[3] * px, 6), 'shafts': len(shafts),
                  'outsideSamples': sum(1 for s in samples if s[3] > 0),
                  'maxWallInCorridorArea': round(max(s[4] for s in samples) * px, 6),
                  'worst': {'frame': worst[0], 'segment': worst[1], 'dir': worst[2]},
                  'seed': SEED, 'shots': shots}
        self.results[f'{w}x{h}'] = result
        self.pixel_results[f'{w}x{h}'] = pixels
        print(f'{w}x{h} pixels:', json.dumps(pixels, separators=(',', ':')), file=sys.stderr)
        print(f'{w}x{h}:', json.dumps(result, separators=(',', ':')), file=sys.stderr)
        self.assertEqual(errors, [])
        self.assertGreater(pixels['samples'], 0, pixels)
        self.assertEqual(pixels['nonWallPixels'], 0, pixels)
        self.assertEqual(len(samples), SECONDS * FPS)
        self.assertGreaterEqual(len(shafts), 1)
        self.assertEqual(result['maxOutsideArea'], 0, result)
        self.assertEqual(result['maxWallInCorridorArea'], 0, result)
        self.assertEqual(sorted(shots), ['corner', 'mid'])

    def test_390x844(self):
        self.run_viewport(390, 844)

    def test_1280x720(self):
        self.run_viewport(1280, 720)

    def test_1024x768(self):
        self.run_viewport(1024, 768)

    def test_844x390(self):
        self.run_viewport(844, 390)


if __name__ == '__main__':
    unittest.main()
