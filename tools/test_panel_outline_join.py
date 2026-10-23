"""TASK-667: the shared Trampoline renderer closes its outline before painting.

Trampoline.draw starts its path at the last vertex and draws back to it. It
used to call closePath only after strokeNeonPath, so that vertex (the
bottom-left one of the starting green panel P0-body0) was stroked as two line
ends instead of a join. The baseline revision (before) and this tree (after)
are rendered at one viewport, camera and animation clock. Each element is
compared against an independently built, explicitly closed reference path
painted with the same fill and neon stroke.

Set PANEL_JOIN_EVIDENCE_DIR (inside artifacts/) to write render-checks.json,
isolation.json and corner-comparison.png; without it they go to a temporary
directory.
"""
import json
import os
import tempfile
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import numpy as np

from browser_test_support import QuietHandler, start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT
from perf_mobile import SEED_SCRIPT, export_rev

BASELINE = os.environ.get('PANEL_JOIN_BASELINE', '7296ca1')
VIEWPORT = {'width': 1920, 'height': 1080}
CLOCK_MS = 4321
TOL = 2  # channel levels: headless AA jitter between page loads (see TASK-664)
# A closed path's join pixels shift by a few levels with its start vertex (the
# reference starts at points[0], production at the last vertex); a seam is ~255
JOIN_TOL = 12
# Background parallax silhouette edges flip between two rasterizations per page
# load (the same 127 px, at most 8 levels at 1920x1080) in either revision
BACKDROP_NOISE = 8

# Fixed clock, no particles/hint, ninja out of view, camera on P0-body0.
# A curved trampoline (quadratic segments, including the closing one, whose
# control point is points[0].curvature in world coordinates) is constructed
# through the production class next to it.
SETUP = '''(clockMs) => {
    performance.now = () => clockMs
    // neonPulse (core alpha) was last set by a real-clock frame
    updateNeonPulse()
    Object.assign(visualEffects.particles, {particles: [], pool: [], lastTime: 0,
        lastWorldEmitTime: 0, trailSparkBudget: 0, sparkSeed: 181})
    TUTORIAL_HINT.visible = false
    const world = floors[0]
    const p0 = world.elements.find(e => e.id === 'P0-body0')
    Object.assign(ninja, {x: -100000, y: -100000, speedX: 0, speedY: 0})
    window.T667 = {}
    T667.s = () => canvas.width / (width / scale[version])
    T667.byId = id => id === 'curved' ? T667.curved : [...world.elements, ...world.dragZones].find(e => e.id === id)
    const cx = -1400, cy = 60
    T667.curved = new Trampoline({x: cx, y: cy, stroke: STYLE.colors.cube.greenStroke, fill: STYLE.colors.cube.greenFill,
        points: [{x: 0, y: 0, curvature: {x: cx + 140, y: cy + 60}}, {x: 500, y: 0, curvature: {x: cx + 250, y: cy - 140}},
            {x: 560, y: 220}, {x: 40, y: 240, curvature: {x: cx + 300, y: cy + 380}}]})
    T667.curved.id = 'curved'
    T667.camera = () => {
        screen.x = width / scale[version] / 2 - (p0.x + 360)
        screen.y = height / scale[version] / 2 - (p0.y + 90)
    }
    T667.camera()
    // Device px of the world point
    T667.dev = p => [(p.x + screen.x) * T667.s(), (p.y + screen.y) * T667.s()]
    // A probe canvas with the world layer's transform; fn draws into it
    T667.probe = (fn, s = T667.s()) => {
        const probe = document.createElement('canvas')
        probe.width = canvas.width; probe.height = canvas.height
        const c = probe.getContext('2d'), main = ctx
        c.setTransform(s, 0, 0, s, 0, 0)
        ctx = c
        try { fn() } finally { ctx = main }
        return c.getImageData(0, 0, probe.width, probe.height).data
    }
    // Independent reference: starts at points[0], every segment (the closing
    // one back to points[0] included) then an explicit closePath, same paint
    T667.reference = e => {
        const pts = e.getPoints(), seg = p => p.curvature
            ? ctx.quadraticCurveTo(p.curvature.x + screen.x, p.curvature.y + screen.y, p.x + screen.x, p.y + screen.y)
            : ctx.lineTo(p.x + screen.x, p.y + screen.y)
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(pts[0].x + screen.x, pts[0].y + screen.y)
        for (let i = 1; i < pts.length; ++i) seg(pts[i])
        seg(pts[0])
        ctx.closePath()
        ctx.fillStyle = e.fill
        ctx.fill()
        strokeNeonPath(e.stroke)
        ctx.restore()
    }
    // Half-size of a corner window: the widest (clipped inner-glow) stroke plus AA
    T667.radius = () => Math.ceil(STYLE.strokes.neonOutline.width / scale[version] * T667.s()
        * Math.max(...STYLE.strokes.innerGlow.widths) / 2) + 6
    T667.crop = (d, c, r) => {
        const W = canvas.width, out = []
        for (let y = Math.round(c[1]) - r; y <= Math.round(c[1]) + r; y++)
            for (let x = Math.round(c[0]) - r; x <= Math.round(c[0]) + r; x++) {
                const i = (y * W + x) * 4
                out.push(d[i], d[i + 1], d[i + 2], d[i + 3])
            }
        return String.fromCharCode(...out)
    }
    // Production draw vs reference per vertex window, and outside all windows
    T667.compare = (a, b, centers, r) => {
        const W = canvas.width, H = canvas.height
        const win = centers.map(() => ({max: 0, over: 0}))
        let outMax = 0, outOver = 0
        for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
            const i = (y * W + x) * 4
            const d = Math.max(Math.abs(a[i] - b[i]), Math.abs(a[i + 1] - b[i + 1]), Math.abs(a[i + 2] - b[i + 2]), Math.abs(a[i + 3] - b[i + 3]))
            if (!d) continue
            let hit = false
            centers.forEach((c, k) => { if (Math.abs(x - c[0]) <= r && Math.abs(y - c[1]) <= r) {
                hit = true; win[k].max = Math.max(win[k].max, d); if (d > %TOL%) win[k].over++ } })
            if (!hit) { outMax = Math.max(outMax, d); if (d > %TOL%) outOver++ }
        }
        return {windows: win, outside: {max: outMax, over: outOver}}
    }
    T667.element = (id, mode) => {
        const e = T667.byId(id), saved = version, s = T667.s()
        const pts = e.getPoints(), centers = pts.map(T667.dev), r = T667.radius()
        // bad: only the branch switch; the world transform stays the same
        let prod
        prod = T667.probe(() => { if (mode) version = mode; try { e.draw() } finally { version = saved } }, s)
        const ref = T667.probe(() => T667.reference(e))
        const closing = pts.length - 1
        return {id, mode: mode || version, vertices: pts.map(p => [p.x, p.y, p.curvature ? [p.curvature.x, p.curvature.y] : null]),
            closingIndex: closing, centers, radius: r,
            vsReference: mode ? null : T667.compare(prod, ref, centers, r),
            crops: centers.map(c => T667.crop(prod, c, r)), refCrops: centers.map(c => T667.crop(ref, c, r)),
            box: T667.bbox(e, r), boxPixels: T667.boxPixels(prod, T667.bbox(e, r))}
    }
    T667.bbox = (e, r) => { const b = e.writeCullBox({}), s = T667.s()
        return [Math.max(0, Math.floor((b.left + screen.x) * s) - r), Math.max(0, Math.floor((b.top + screen.y) * s) - r),
            Math.min(canvas.width, Math.ceil((b.right + screen.x) * s) + r), Math.min(canvas.height, Math.ceil((b.bottom + screen.y) * s) + r)] }
    T667.boxPixels = (d, [x0, y0, x1, y1]) => { const W = canvas.width; let out = ''
        for (let y = y0; y < y1; y++) out += String.fromCharCode(...d.subarray((y * W + x0) * 4, (y * W + x1) * 4))
        return out }
    // The HUD (no trampolines) shows values from the real boot frames, which vary per load
    drawUILayer = () => {}
    T667.frame = () => { T667.camera(); draw(); const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data
        return Array.from(d, v => String.fromCharCode(v)).join('') }
    return true
}'''.replace('%TOL%', str(TOL))

# Collision / physics inputs and a canonical deterministic run over P0
ISOLATION = '''() => {
    const world = floors[0]
    const elements = [...world.elements, ...world.dragZones].map(e => ({id: e.id, role: e.surfaceRole,
        grapplable: e.grapplable, points: e.getPoints().map(p => [p.x, p.y]), circle: e.getCircumscribedCircle(),
        left: e.getLeftPointX(), right: e.getRightPointX()}))
    // Every method but draw; the class source (constructor) with draw cut out
    const methods = Object.fromEntries(Object.getOwnPropertyNames(Trampoline.prototype)
        .filter(m => m !== 'draw').map(m => [m, String(Trampoline.prototype[m]).replace(String(Trampoline.prototype.draw), '')]))
    const config = {GRAVITY, physicsStepMs, cyclesPerTick, bounceSpeed: String(bounceSpeed),
        CLIMB_FALL_RECOVERY_DEPTH, layoutId: world.level.layoutId, spawn: world.level.spawn}
    if (menu.gamePaused) menu.unPause()
    const running = {gamePaused: menu.gamePaused, hostPaused, continueOffer: continueOffer.visible}
    let s = 12345
    Math.random = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648 }
    const st = captureClimbState(), sp = world.level.spawn
    st.simulationTick = 0; st.stats = {elapsedActiveMs: 0, currentHeight: 0, maxHeight: 0, completed: false}
    Object.assign(st.player, {x: sp.x, y: sp.y - 400, speedX: 3, speedY: 0})
    st.input = {pressHeld: false, stalePress: false}
    st.grapple = {throwed: false, grappled: false, speedX: 0, speedY: 0, traveled: 0, shotStep: null, segments: []}
    restoreClimbState(st)
    const trace = []
    for (let i = 1; i <= 900; i++) {
        physics()
        if (i % 100 === 0) trace.push([i, ninja.x, ninja.y, ninja.speedX, ninja.speedY])
    }
    // (climbStats.currentHeight is display state refreshed from real frames; left out)
    return {running, elements, methods, config, trace, end: {ninja: [ninja.x, ninja.y, ninja.speedX, ninja.speedY],
        grapnel: [grapnel.throwed, grapnel.grappled], maxHeight: world.climbStats.maxHeight,
        completed: world.climbStats.completed, rangeUpgraded: world.rangeUpgraded}}
}'''


class PanelOutlineJoinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get('PANEL_JOIN_EVIDENCE_DIR')
        if root:
            cls.out = Path(root).resolve()
            if not cls.out.is_relative_to((ROOT / 'artifacts').resolve()):
                raise ValueError('Evidence must stay inside artifacts/')
        else:
            scratch = tempfile.TemporaryDirectory(prefix='task667-')
            cls.addClassCleanup(scratch.cleanup)
            cls.out = Path(scratch.name)
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        base_root, cls.baseline_sha = export_rev(BASELINE, cls.addClassCleanup)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(base_root)))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.baseline_url = f'http://127.0.0.1:{server.server_port}/'
        cls.page_errors = []
        cls.results = {}

    def open(self, url):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.page_errors.append(errors)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(url)
        wait_for_boot(page)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', 'grapple_over')
        page.wait_for_function('!unTouch')
        page.evaluate(SETUP, CLOCK_MS)
        return page

    def write(self, name, value):
        (self.out / name).write_text(json.dumps(value, separators=(',', ':')))

    @staticmethod
    def crop_array(s, r):
        n = 2 * r + 1
        return np.frombuffer(s.encode('latin-1'), np.uint8).reshape(n, n, 4).astype(int)

    def frame(self, page):
        data = page.evaluate('T667.frame()')
        h, w = VIEWPORT['height'], VIEWPORT['width']
        return np.frombuffer(data.encode('latin-1'), np.uint8).reshape(h, w, 4)[..., :3].copy()

    def render_both(self):
        if 'render' in self.results:
            return self.results['render']
        ids = ('P0-body0', 'P2-body0', 'curved')
        out = {}
        for rev, url in (('before', self.baseline_url), ('after', self.url)):
            page = self.open(url)
            out[rev] = {'elements': {i: page.evaluate('id => T667.element(id)', i) for i in ids},
                        'bad': {i: page.evaluate('id => T667.element(id, "bad")', i) for i in ids},
                        'frames': [self.frame(page), self.frame(page)],
                        'closing': page.evaluate('''() => [...floors[0].elements, ...floors[0].dragZones]
                            .map(e => T667.dev(e.getPoints()[e.getPoints().length - 1]))'''),
                        'radius': page.evaluate('T667.radius()')}
            self.results.setdefault('pageErrors', []).extend(self.page_errors[-1])
        self.results['render'] = out
        return out

    def test_01_join_matches_closed_reference(self):
        """After: every vertex window (closing corner included) equals the reference; before: only the closing one differs."""
        out = self.render_both()
        checks = {'baseline': self.baseline_sha, 'clockMs': CLOCK_MS, 'viewport': VIEWPORT, 'toleranceLevels': TOL, 'joinToleranceLevels': JOIN_TOL,
                  'radiusPx': out['after']['radius'], 'elements': {}}
        for i, a in out['after']['elements'].items():
            b = out['before']['elements'][i]
            self.assertEqual(a['vertices'], b['vertices'], i)
            k = a['closingIndex']
            entry = {'vertices': a['vertices'], 'closingIndex': k, 'closingDevicePx': [round(v, 1) for v in a['centers'][k]],
                     'curvedSegments': sum(v[2] is not None for v in a['vertices'])}
            for rev, e in (('before', b), ('after', a)):
                cmp = e['vsReference']
                entry[rev] = {'closingWindow': cmp['windows'][k],
                              'otherWindowsMax': max(w['max'] for j, w in enumerate(cmp['windows']) if j != k),
                              'otherWindowsOver': sum(w['over'] for j, w in enumerate(cmp['windows']) if j != k),
                              'outside': cmp['outside']}
            # Cross-revision: unchanged non-closing corners
            r = a['radius']
            entry['beforeVsAfterOtherCornersMax'] = max(
                int(np.abs(self.crop_array(a['crops'][j], r) - self.crop_array(b['crops'][j], r)).max())
                for j in range(len(a['crops'])) if j != k)
            entry['beforeVsAfterClosingCornerMax'] = int(np.abs(
                self.crop_array(a['crops'][k], r) - self.crop_array(b['crops'][k], r)).max())
            checks['elements'][i] = entry
            self.assertLessEqual(entry['after']['closingWindow']['max'], JOIN_TOL, i)
            self.assertLessEqual(entry['after']['otherWindowsMax'], JOIN_TOL, i)
            self.assertEqual(entry['after']['outside']['over'], 0, i)
            self.assertGreater(entry['before']['closingWindow']['over'], 5, i)
            self.assertGreater(entry['before']['closingWindow']['max'], 2 * JOIN_TOL, i)
            self.assertLessEqual(entry['before']['otherWindowsMax'], JOIN_TOL, i)
            self.assertEqual(entry['before']['outside']['over'], 0, i)
            # Closing the contour may move a few AA levels along the final edge
            self.assertLessEqual(entry['beforeVsAfterOtherCornersMax'], JOIN_TOL, i)
        # The starting panel's closing vertex is its bottom-left one
        v = checks['elements']['P0-body0']['vertices']
        last = v[-1]
        self.assertEqual(last[:2], [min(p[0] for p in v if p[1] == last[1]), max(p[1] for p in v)])
        checks['P0ClosingCorner'] = 'bottom-left (last vertex %s of %s)' % (last[:2], [p[:2] for p in v])
        self.assertGreaterEqual(checks['elements']['curved']['curvedSegments'], 2)
        self.results['checks'] = checks
        print('PASS join: after == closed reference at every corner of P0/P2/curved; before differs only at the closing corner', flush=True)

    def test_02_production_frames(self):
        """Full production frames: before/after differ only around closing corners (sharp there, bloom-blurred nearby)."""
        out = self.render_both()
        b0, a0, a1 = out['before']['frames'][0], out['after']['frames'][0], out['after']['frames'][1]
        # Some backdrop regions flip between two rasterizations per page load: a
        # pixel counts as changed only if no (after load, baseline load) pair agrees
        befores, afters = [b0], [a0]
        for _ in range(2):
            befores.append(self.frame(self.open(self.baseline_url)))
            self.results.setdefault('pageErrors', []).extend(self.page_errors[-1])
        afters.append(self.frame(self.open(self.url)))
        self.results.setdefault('pageErrors', []).extend(self.page_errors[-1])
        r = out['after']['radius']
        diff = np.min([np.abs(a.astype(int) - b).max(axis=2) for a in afters for b in befores], axis=0)
        h, w = diff.shape
        bloom_r = r + 6 * 32  # the widest bloom level is 1/32 of the backing store, blurred
        def mask(radius):
            m = np.zeros(diff.shape, bool)
            for x, y in out['after']['closing']:
                x, y = int(round(x)), int(round(y))
                m[max(0, y - radius):max(0, y + radius + 1), max(0, x - radius):max(0, x + radius + 1)] = True
            return m
        sharp, bloom = mask(r), mask(bloom_r)
        p0 = out['after']['elements']['P0-body0']
        cx, cy = (int(round(v)) for v in p0['centers'][p0['closingIndex']])
        ch = diff > TOL
        frames = {'baselineLoads': len(befores), 'afterLoads': len(afters), 'sharpRadiusPx': r, 'bloomRadiusPx': bloom_r,
                  'closingCornersInView': [[round(x), round(y)] for x, y in out['after']['closing'] if 0 <= x < w and 0 <= y < h],
                  'repeatDrawMaxDiffAfter': int(np.abs(a0.astype(int) - a1).max()),
                  'baselineLoadNoiseOverTol': [int((np.abs(b0.astype(int) - b).max(axis=2) > TOL).sum()) for b in befores[1:]],
                  'changedOverTol': int(ch.sum()),
                  'changedOverTolAtP0ClosingCorner': int(ch[cy - r:cy + r + 1, cx - r:cx + r + 1].sum()),
                  'maxDiffAtP0ClosingCorner': int(diff[cy - r:cy + r + 1, cx - r:cx + r + 1].max()),
                  'changedOverTolBeyondBloomOfClosingCorners': int((ch & ~bloom).sum()),
                  'changedOverNoiseBeyondBloomOfClosingCorners': int(((diff > BACKDROP_NOISE) & ~bloom).sum()),
                  'maxDiffBeyondBloomOfClosingCorners': int(diff[~bloom].max()), 'backdropNoiseLevels': BACKDROP_NOISE,
                  'maxDiffOutsideSharpWindows': int(diff[~sharp].max()),
                  'p0ClosingCornerDevicePx': [cx, cy],
                  'changedBeyondBloomPx': [[int(x), int(y)] for y, x in zip(*np.nonzero(ch & ~bloom))][:50]}
        self.results['frames'] = frames
        self.results['frameImages'] = (b0, a0, (cx, cy), r)
        self.assertEqual(frames['changedOverNoiseBeyondBloomOfClosingCorners'], 0)
        self.assertGreater(frames['changedOverTolAtP0ClosingCorner'], 5)
        print('PASS frames: %s' % frames, flush=True)

    def test_03_bad_mode_control_unchanged(self):
        """The separate bad-mode branch renders identically before and after."""
        out = self.render_both()
        bad = {}
        for i, a in out['after']['bad'].items():
            b = out['before']['bad'][i]
            self.assertEqual(a['box'], b['box'], i)
            pa, pb = (np.frombuffer(e['boxPixels'].encode('latin-1'), np.uint8).astype(int) for e in (a, b))
            bad[i] = {'mode': a['mode'], 'boxDevicePx': a['box'], 'paintedPx': int((pa.reshape(-1, 4)[:, 3] > 0).sum()),
                      'maxDiff': int(np.abs(pa - pb).max()), 'pixelsCompared': len(pa) // 4}
            self.assertEqual(bad[i]['mode'], 'bad')
            self.assertGreater(bad[i]['paintedPx'], 1000, i)
            self.assertEqual(bad[i]['maxDiff'], 0, i)
        self.results['bad'] = bad
        print('PASS bad mode: identical element pixels %s' % bad, flush=True)

    def test_04_isolation(self):
        """Collision vertices, physics configuration and a canonical 900-tick run are unchanged."""
        runs = {}
        for rev, url in (('before', self.baseline_url), ('after', self.url)):
            page = self.open(url)
            runs[rev] = page.evaluate(ISOLATION)
            self.results.setdefault('pageErrors', []).extend(self.page_errors[-1])
        a, b = runs['after'], runs['before']
        iso = {'baseline': self.baseline_sha,
               'elementCount': len(a['elements']),
               'elementsIdentical': a['elements'] == b['elements'],
               'trampolineMethodsExceptDrawIdentical': a['methods'] == b['methods'],
               'methodsCompared': sorted(a['methods']),
               'configIdentical': a['config'] == b['config'], 'config': {k: v for k, v in a['config'].items() if k != 'bounceSpeed'},
               'traceIdentical': a['trace'] == b['trace'], 'trace': a['trace'],
               'endIdentical': a['end'] == b['end'], 'end': a['end'], 'running': a['running']}
        self.results['isolation'] = iso
        for k in ('elementsIdentical', 'trampolineMethodsExceptDrawIdentical', 'configIdentical', 'traceIdentical', 'endIdentical'):
            self.assertTrue(iso[k], (k, {x: (a[x], b[x]) for x in ('end', 'running', 'config') if a[x] != b[x]}))
        # The run actually moved over the starting panel
        self.assertNotEqual(a['trace'][0][1:3], a['trace'][-1][1:3])
        print('PASS isolation: %d elements, methods, config and 900-tick trace identical' % iso['elementCount'], flush=True)

    @classmethod
    def tearDownClass(cls):
        res = cls.results
        out = cls.out
        errors = [e for errs in cls.page_errors for e in errs]
        if 'checks' in res:
            checks = dict(res['checks'], frames=res.get('frames'), pageErrors=errors)
            (out / 'render-checks.json').write_text(json.dumps(checks, separators=(',', ':')))
        if 'isolation' in res:
            iso = dict(res['isolation'], badModeControl=res.get('bad'), pageErrors=errors)
            (out / 'isolation.json').write_text(json.dumps(iso, separators=(',', ':')))
        if 'render' in res and 'frameImages' in res:
            cls.compose(res['render'], res['frameImages'], out / 'corner-comparison.png')

    @staticmethod
    def compose(render, frame_images, path):
        from PIL import Image, ImageDraw
        b0, a0, (cx, cy), r = frame_images
        zoom = 6
        tile = (2 * r + 1) * zoom
        rows = [('P0-body0', 'starting green panel P0-body0, bottom-left closing corner'),
                ('P2-body0', 'second polygon P2-body0, closing corner'), ('curved', 'curved trampoline, closing corner')]
        cols = ['before (7296ca1)', 'after', 'closed reference', '|before-ref| x4', '|after-ref| x4']
        fw, fh = 900, int(900 * VIEWPORT['height'] / VIEWPORT['width'])
        W = max(2 * fw + 30, 5 * (tile + 10) + 10)
        H = fh + 40 + (len(rows) + 1) * (tile + 40) + 10
        img = Image.new('RGB', (W, H), (24, 24, 28))
        d = ImageDraw.Draw(img)
        sc = fw / VIEWPORT['width']
        for k, (fr, label) in enumerate(((b0, 'production frame BEFORE'), (a0, 'production frame AFTER'))):
            x0 = 10 + k * (fw + 10)
            img.paste(Image.fromarray(fr).resize((fw, fh)), (x0, 25))
            d.rectangle([x0 + (cx - r) * sc, 25 + (cy - r) * sc, x0 + (cx + r) * sc, 25 + (cy + r) * sc], outline=(255, 40, 200), width=2)
            d.text((x0, 8), label + ' (magenta: P0 bottom-left closing corner)', fill=(255, 255, 255))
        y = fh + 40
        # Close-ups of the production frames themselves at the P0 closing corner
        fb, fa = (f[cy - r:cy + r + 1, cx - r:cx + r + 1].astype(int) for f in (b0, a0))
        d.text((10, y), 'production frame close-up, P0-body0 bottom-left closing corner (device px %d,%d)' % (cx, cy), fill=(255, 255, 255))
        for j, (t, lab) in enumerate(((fb, 'frame before'), (fa, 'frame after'), (np.clip(np.abs(fa - fb) * 4, 0, 255), '|after-before| x4'))):
            x0 = 10 + j * (tile + 10)
            img.paste(Image.fromarray(t.astype(np.uint8)).resize((tile, tile), Image.NEAREST), (x0, y + 28))
            d.text((x0, y + 14), lab, fill=(200, 200, 200))
        y += tile + 40
        for id_, label in rows:
            a, b = render['after']['elements'][id_], render['before']['elements'][id_]
            k = a['closingIndex']
            arr = lambda s: PanelOutlineJoinTests.crop_array(s, a['radius'])
            ref = arr(a['refCrops'][k])
            tiles = [arr(b['crops'][k]), arr(a['crops'][k]), ref,
                     np.clip(np.abs(arr(b['crops'][k]) - ref) * 4, 0, 255), np.clip(np.abs(arr(a['crops'][k]) - ref) * 4, 0, 255)]
            d.text((10, y), label, fill=(255, 255, 255))
            for j, t in enumerate(tiles):
                t = t.astype(np.uint8)
                rgb = t[..., :3] if j >= 3 else (t[..., :3] * (t[..., 3:4] / 255.0) + 24 * (1 - t[..., 3:4] / 255.0)).astype(np.uint8)
                if j >= 3:
                    rgb = np.maximum(t[..., :3], t[..., 3:4])
                x0 = 10 + j * (tile + 10)
                img.paste(Image.fromarray(rgb.astype(np.uint8)).resize((tile, tile), Image.NEAREST), (x0, y + 28))
                d.text((x0, y + 14), cols[j], fill=(200, 200, 200))
            y += tile + 40
        img.save(path)


if __name__ == '__main__':
    unittest.main()
