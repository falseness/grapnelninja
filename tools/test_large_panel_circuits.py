"""Grapple Over green (bounce) panel circuits: 3x motif scale (TASK-664), denser paths (TASK-670),
size-proportional density on big panels (TASK-690/691).

Renders one fixed test-only level holding thin, very thin, broad, sloped,
irregular, large (3000x840), huge (6000x1680) and long thin strip (8000x64)
bounce panels next to solid, mover, hazard and drag controls, in the baseline
revision (before: the tree just before TASK-690, camera scale 0.25) and this
tree (after), at one camera, viewport and animation clock. Set
LARGE_CIRCUITS_EVIDENCE_DIR (inside artifacts/) to write the captures and JSON
proofs; without it they go to a temporary directory.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from browser_test_support import QuietHandler, start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT
from perf_mobile import SEED_SCRIPT, export_rev

BASELINE = os.environ.get('LARGE_CIRCUITS_BASELINE', 'b61eece')
# Widest logical aspect (2:1), so the 8000-unit strip fits the 0.25 camera view
VIEWPORT = {'width': 2160, 'height': 1080}
SHAPES = ('thin', 'very-thin', 'broad', 'sloped', 'irregular', 'large', 'huge', 'strip')
SHAPE_CLASS = {'thin': 'thin', 'very-thin': 'thin', 'broad': 'wide', 'sloped': 'sloped', 'irregular': 'irregular',
               'large': 'wide', 'huge': 'wide', 'strip': 'thin'}
# Shapes shown in before-after.png
COMPARED = ('broad', 'large', 'huge', 'strip', 'thin', 'sloped')
# Panels at or below the old 18 (8 thin) path boards keep their exact baseline boards;
# the big ones get size-proportional density (TASK-690)
SMALL, BIG = ('thin', 'very-thin', 'broad', 'sloped', 'irregular'), ('large', 'huge', 'strip')
CONTROLS = ('solid', 'mover', 'hazard', 'drag')
Y0 = -6000

# Test-only level (the game level is not touched: floors is replaced in this
# page only). The camera, clock and movers are fixed, then one production
# draw() runs. Returns frame pixels, device-px boxes and polygons per element.
SETUP = '''(y0) => {
    const rect = (w, h) => [{x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}]
    const level = {version: 1, bounds: {left: -400, top: y0 - 4000, right: 9000, bottom: y0 + 4000},
        spawn: {x: 0, y: y0 - 3000},
        sections: [{id: GRAPPLE_OVER_LEVEL.sections[0].id, encounters: ['circuits']}],
        encounters: [{id: 'circuits', elements: ['c-broad']}], elements: [
            {id: 'c-thin', x: 120, y: y0, role: 'bounce', grapplable: true, points: rect(1300, 64)},
            {id: 'c-very-thin', x: 120, y: y0 + 260, role: 'bounce', grapplable: true, points: rect(1300, 20)},
            {id: 'c-broad', x: 1700, y: y0 - 60, role: 'bounce', grapplable: true, points: rect(1500, 420)},
            {id: 'c-sloped', x: 3500, y: y0 - 80, role: 'bounce', grapplable: true,
                points: [{x: 0, y: 0}, {x: 1300, y: 160}, {x: 1300, y: 400}, {x: 0, y: 240}]},
            {id: 'c-irregular', x: 120, y: y0 + 640, role: 'bounce', grapplable: true,
                points: [{x: 0, y: 140}, {x: 360, y: 0}, {x: 1300, y: 0}, {x: 1620, y: 130},
                    {x: 1620, y: 520}, {x: 0, y: 480}]},
            {id: 'c-large', x: 5100, y: y0 - 60, role: 'bounce', grapplable: true, points: rect(3000, 840)},
            {id: 'c-huge', x: 120, y: y0 + 1500, role: 'bounce', grapplable: true, points: rect(6000, 1680)},
            {id: 'c-strip', x: 120, y: y0 - 400, role: 'bounce', grapplable: true, points: rect(8000, 64)},
            {id: 'c-solid', x: 2050, y: y0 + 700, role: 'solid', grapplable: true, points: rect(800, 200)},
            {id: 'c-mover', x: 3100, y: y0 + 700, role: 'solid', grapplable: true, points: rect(700, 140)},
            {id: 'c-hazard', x: 4100, y: y0 + 700, role: 'hazard', grapplable: false, points: rect(700, 180)},
            {id: 'c-drag', x: 2050, y: y0 + 1100, role: 'drag', grapplable: false, points: rect(2600, 260)}],
        movers: [{id: 'c-mover-x', element: 'c-mover', axis: 'x', min: 3000, max: 3200, periodMs: 4000, phase: 0.25}]}
    // A real clock for build timings only; the game sees the fixed one
    window.T664_NOW = performance.now.bind(performance)
    performance.now = () => 4321
    // Particles left by the title screen and the start (their count depends
    // on real frame timing) go, in both revisions alike
    Object.assign(visualEffects.particles, {particles: [], pool: [], lastTime: 0,
        lastWorldEmitTime: 0, trailSparkBudget: 0, sparkSeed: 181})
    floors = [loadFixedLevel(level)]
    ROLE_DETAIL.enabled = true
    for (let i = 0; i < 40; i++) floors[0].moveElements()
    screen.x = width / scale[version] / 2 - 4120
    screen.y = height / scale[version] / 2 - (y0 + 1390)
    Object.assign(ninja, {x: -100000, y: y0 - 3000, speedX: 0, speedY: 0})
    return true
}'''

# Shared page helpers, installed once per page
HELPERS = '''() => {
    window.T664 = {}
    T664.s = () => canvas.width / (width / scale[version])
    T664.byId = id => [...floors[0].elements, ...floors[0].dragZones].find(e => e.id === 'c-' + id)
    T664.box = e => {
        const b = e.writeBounds({}), s = T664.s()
        return [Math.floor((b.left + screen.x) * s), Math.floor((b.top + screen.y) * s),
            Math.ceil((b.right + screen.x) * s), Math.ceil((b.bottom + screen.y) * s)]
    }
    T664.poly = e => e.getPoints().map(p => [(p.x + screen.x) * T664.s(), (p.y + screen.y) * T664.s()])
    // A probe canvas with the world layer's transform; fn draws into it
    T664.probe = fn => {
        const probe = document.createElement('canvas')
        probe.width = canvas.width; probe.height = canvas.height
        const c = probe.getContext('2d'), main = ctx, s = T664.s()
        c.setTransform(s, 0, 0, s, 0, 0)
        ctx = c
        try { fn() } finally { ctx = main }
        return c.getImageData(0, 0, probe.width, probe.height).data
    }
    // Device-px mask of an element's polygon (antialiased edge pixels count as inside)
    T664.mask = e => T664.probe(() => { ctx.beginPath(); traceRoleDetailPath(e); ctx.fillStyle = '#fff'; ctx.fill() })
    T664.hash = data => { let h = 2166136261; for (let i = 0; i < data.length; i++) h = Math.imul(h ^ data[i], 16777619) >>> 0; return h }
    T664.frame = () => { draw(); return ctx.getImageData(0, 0, canvas.width, canvas.height).data }
    return true
}'''

# Per bounce panel: the cached board (motif scale, counts, geometry), the
# production material draw alone into a probe and its painted pixels outside
# the panel polygon mask
BOARDS = '''(ids) => {
    const world = floors[0], clockMs = world.elapsedSteps * physicsStepMs / cyclesPerTick
    const m = ctx.getTransform()
    const result = {}
    for (const id of ids) {
        const e = T664.byId(id)
        const unit = 1 / scale[version]
        ctx.save(); ctx.setTransform(T664.s(), 0, 0, T664.s(), 0, 0)
        const sprite = bounceMaterialSprite(e, world, glowSpriteScale(T664.s()), glowSpriteScale(T664.s()), unit)
        ctx.restore()
        const board = sprite.board
        const detail = T664.probe(() => drawBounceMaterial(e, world, clockMs))
        const mask = T664.mask(e)
        let painted = 0, outside = 0
        for (let i = 3; i < detail.length; i += 4) if (detail[i]) { painted++; if (!mask[i]) outside++ }
        const s = board.scale ?? unit
        // Geometric containment of every motif in local polygon coordinates
        const origin = e.points[0]
        const pts = e.points.map(p => ({x: p.x - origin.x, y: p.y - origin.y}))
        const edgeGap = p => Math.min(...pts.map((a, i) => {
            const b = pts[(i + 1) % pts.length], dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy
            const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2))
            return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy)
        }))
        const inPoly = p => pointInPolygon(pts, p.x, p.y)
        const vertices = board.traces.flatMap(t => t.points)
        const vias = board.traces.flatMap(t => t.vias)
        const padCorners = board.pads.flatMap(p => [[-3, -1], [3, -1], [-3, 1], [3, 1]].map(([x, y]) => ({x: p.x + x * s, y: p.y + y * s})))
        const segLengths = board.traces.flatMap(t => t.points.slice(1).map((p, i) => Math.hypot(p.x - t.points[i].x, p.y - t.points[i].y)))
        // Self-overlap: turns sharper than 90 degrees (incl. doubling back) and the gap between
        // non-adjacent segments of the same trace
        let sharpTurns = 0, minSelfGap = Infinity, minPathGap = Infinity
        const traceSegs = board.traces.map(t => t.points.slice(1).map((p, i) => [t.points[i], p]))
        for (let i = 0; i < traceSegs.length; i++)
            for (let j = i + 1; j < traceSegs.length; j++)
                for (const [a, b] of traceSegs[i])
                    for (const [c, d] of traceSegs[j]) minPathGap = Math.min(minPathGap, circuitSegmentGap(a, b, c, d))
        for (const t of board.traces) {
            const P = t.points
            for (let i = 2; i < P.length; i++)
                if ((P[i - 1].x - P[i - 2].x) * (P[i].x - P[i - 1].x) + (P[i - 1].y - P[i - 2].y) * (P[i].y - P[i - 1].y) < 0) sharpTurns++
            for (let i = 1; i < P.length; i++)
                for (let j = i + 2; j < P.length; j++)
                    minSelfGap = Math.min(minSelfGap, circuitSegmentGap(P[i - 1], P[i], P[j - 1], P[j]))
        }
        result[id] = {
            unit: +unit.toFixed(4), motifUnit: +s.toFixed(4), circuitScale: +(s / unit).toFixed(3),
            thin: board.thin, traces: board.traces.length, segments: segLengths.length,
            vias: vias.length, pads: board.pads.length, label: !!board.label,
            traceWidthPx: +(0.8 * s / unit).toFixed(2), viaRadiusPx: +(1.2 * s / unit).toFixed(2),
            viaStrokePx: +(0.5 * s / unit).toFixed(2), padSizePx: +(2 * s / unit).toFixed(2),
            gridPx: +(3 * s / unit).toFixed(2), meanSegmentPx: segLengths.length ? +(segLengths.reduce((a, b) => a + b, 0) / segLengths.length / unit).toFixed(1) : 0,
            areaPx2: Math.round(roleDetailLayout(e).area / unit / unit),
            minVertexEdgeGapPx: vertices.length ? +(Math.min(...vertices.map(edgeGap)) / unit).toFixed(2) : null,
            minViaEdgeGapPx: vias.length ? +(Math.min(...vias.map(edgeGap)) / unit).toFixed(2) : null,
            allVerticesInside: vertices.every(inPoly), allPadCornersInside: padCorners.every(inPoly),
            viaRingsFit: vias.every(p => inPoly(p) && edgeGap(p) >= 1.45 * s),
            sharpTurns, minSelfGapPx: minSelfGap === Infinity ? null : +(minSelfGap / unit).toFixed(2),
            pathGapPx: +(4.5 * s / unit).toFixed(2),
            minPathGapPx: minPathGap === Infinity ? null : +(minPathGap / unit).toFixed(2),
            traceLengthPx: +(segLengths.reduce((a, b) => a + b, 0) / unit).toFixed(1),
            painted, paintedOutsidePolygon: outside,
            boardSha: T664.hash(new TextEncoder().encode(JSON.stringify(board.traces.map(t => t.points)) + JSON.stringify(board.pads))),
            materialPixelHash: T664.hash(detail),
        }
    }
    return result
}'''


class LargePanelCircuitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get('LARGE_CIRCUITS_EVIDENCE_DIR')
        if root:
            cls.out = Path(root).resolve()
            if not cls.out.is_relative_to((ROOT / 'artifacts').resolve()):
                raise ValueError('Evidence must stay inside artifacts/')
        else:
            scratch = tempfile.TemporaryDirectory(prefix='task664-')
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
        page.evaluate(SETUP, Y0)
        page.evaluate(HELPERS)
        return page

    def frame(self, page):
        import numpy as np
        data = page.evaluate('''() => { const d = T664.frame();
            return Array.from(d, v => String.fromCharCode(v)).join('') }''')
        h, w = VIEWPORT['height'], VIEWPORT['width']
        return np.frombuffer(data.encode('latin-1'), np.uint8).reshape(h, w, 4)[..., :3].copy()

    def layout(self, page):
        return page.evaluate('''(ids) => Object.fromEntries(ids.map(id => [id,
            {box: T664.box(T664.byId(id)), poly: T664.poly(T664.byId(id))}]))''', list(SHAPES + CONTROLS))

    def write(self, name, value):
        (self.out / name).write_text(json.dumps(value, separators=(',', ':')) + '\n')

    def test_01_before_after_comparison(self):
        import numpy as np
        from PIL import Image, ImageDraw
        # Two baseline loads: headless Chromium rasterizes a few backdrop edge
        # pixels +-2 levels differently between page loads of the same
        # revision. A pixel counts as changed only if it differs from both.
        before_page, before2_page, after_page = self.open(self.baseline_url), self.open(self.baseline_url), self.open(self.url)
        before, before2, after = self.frame(before_page), self.frame(before2_page), self.frame(after_page)
        layout = self.layout(after_page)
        self.assertEqual(layout, self.layout(before_page))
        noise = np.abs(before.astype(int) - before2).max(2)
        # Masks of every bounce panel and of every control element (polygon raster)
        def poly_mask(ids):
            img = Image.new('L', (VIEWPORT['width'], VIEWPORT['height']), 0)
            d = ImageDraw.Draw(img)
            for k in ids:
                d.polygon([tuple(p) for p in layout[k]['poly']], fill=255)
            return np.array(img) > 0
        bounce = poly_mask(SHAPES)
        # Detail is clipped strictly inside the polygons; one device px of the
        # antialiased edge may differ
        from PIL import ImageFilter
        grown = np.array(Image.fromarray((bounce * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
        # Sometimes both baseline loads match each other and the after load is the other
        # backdrop variant, off by 1-2 levels nearly everywhere; so a pixel counts as
        # changed only if it is more than 2 levels off both loads (raw counts kept too)
        delta = np.minimum(np.abs(before.astype(int) - after).max(2), np.abs(before2.astype(int) - after).max(2))
        raw = delta > 0
        diff = delta > 2
        changed_outside = int((diff & ~grown).sum())
        changed_inside = int((diff & bounce).sum())
        controls = {}
        for k in CONTROLS:
            l, t, r, b = layout[k]['box']
            region = (slice(max(0, t - 6), b + 6), slice(max(0, l - 6), r + 6))
            controls[k] = dict(box=layout[k]['box'], differing_pixels=int(diff[region].sum()))
        # Panel border band: pixels just outside each bounce polygon (the neon stroke and glow)
        border = grown & ~bounce
        ring = np.array(Image.fromarray((bounce * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(15))) > 0
        border_band = ring & ~grown
        checks = dict(viewport=VIEWPORT, dpr=1, clock_ms=4321, baseline=self.baseline_sha,
                      baseline_outline_draw='Trampoline.draw of this tree (TASK-667)',
                      baseline_load_noise=dict(pixels=int((noise > 0).sum()), max_level=int(noise.max())),
                      changed_rule='more than 2 levels off both baseline loads',
                      raw_changed_pixels_outside_bounce_polygons_grown_1px=int((raw & ~grown).sum()),
                      max_level_outside_bounce_polygons_grown_1px=int(delta[~grown].max()),
                      changed_pixels_inside_bounce_polygons=changed_inside,
                      changed_pixels_outside_bounce_polygons_grown_1px=changed_outside,
                      border_band_pixels=int(border_band.sum()),
                      border_band_changed=int((diff & border_band).sum()),
                      edge_px_changed=int((diff & border).sum()), controls=controls)
        self._merge('render-checks.json', dict(spill=checks))
        self.assertGreater(changed_inside, 1000)
        self.assertEqual(changed_outside, 0)
        self.assertEqual(checks['border_band_changed'], 0)
        for k, v in controls.items():
            self.assertEqual(v['differing_pixels'], 0, k)
        # before-after.png: per panel, the BEFORE crop above the AFTER crop, production frames at
        # the same camera and the same 2x nearest-neighbour zoom for every panel and both revisions
        rows = []
        for k in COMPARED:
            l, t, r, b = layout[k]['box']
            l, t, r, b = max(0, l - 24), max(0, t - 24), min(VIEWPORT['width'], r + 24), min(VIEWPORT['height'], b + 24)
            crop = lambda a: Image.fromarray(a[t:b, l:r]).resize(((r - l) * 2, (b - t) * 2), Image.NEAREST)
            rows.append((k, crop(before), crop(after)))
        sheet = Image.new('RGB', (max(im.width for _, im, _ in rows) + 20, 40 + sum(2 * im.height + 52 for _, im, _ in rows) + 10), (16, 16, 24))
        d = ImageDraw.Draw(sheet)
        d.text((10, 12), f'PRODUCTION GAME CAPTURES  {VIEWPORT["width"]}x{VIEWPORT["height"]} dpr1, clock 4321 ms, same camera, all 2x zoom.  '
                         f'Per panel: BEFORE ({self.baseline_sha[:7]}) above AFTER (size-proportional circuits, same motif scale)', fill=(255, 255, 255))
        y = 40
        for k, b, a in rows:
            d.text((10, y), f'{SHAPE_CLASS[k]} panel ({k}) BEFORE', fill=(255, 200, 200))
            sheet.paste(b, (10, y + 14))
            y += b.height + 18
            d.text((10, y), f'{SHAPE_CLASS[k]} panel ({k}) AFTER', fill=(200, 255, 200))
            sheet.paste(a, (10, y + 14))
            y += a.height + 34
        sheet.save(self.out / 'before-after.png')
        print(f'PASS before/after: {changed_inside} px changed inside bounce polygons, 0 outside, '
              f'0 in border band, controls unchanged')

    def test_02_density_scale_and_clipping(self):
        old = self.open(self.baseline_url).evaluate(BOARDS, list(SHAPES))
        page = self.open(self.url)
        new = page.evaluate(BOARDS, list(SHAPES))
        rows = {}
        same = ('motifUnit', 'circuitScale', 'traceWidthPx', 'viaRadiusPx', 'viaStrokePx', 'padSizePx', 'gridPx', 'pathGapPx')
        for k in SHAPES:
            o, n = old[k], new[k]
            rows[k] = dict(shapeClass=SHAPE_CLASS[k], old=o, new=n,
                           traceRatio=round(n['traces'] / max(1, o['traces']), 3),
                           traceLengthRatio=round(n['traceLengthPx'] / max(1, o['traceLengthPx']), 3),
                           tracesPer100kPx2=dict(old=round(o['traces'] / o['areaPx2'] * 1e5, 2),
                                                 new=round(n['traces'] / n['areaPx2'] * 1e5, 2)),
                           motifUnchanged={f: n[f] == o[f] for f in same})
            # Motif scale and line thickness are unchanged
            for f in same:
                self.assertEqual(n[f], o[f], (k, f))
            self.assertAlmostEqual(n['circuitScale'], 3, places=2)
            self.assertEqual(n['areaPx2'], o['areaPx2'], k)
            # Clipping and containment
            self.assertEqual(n['paintedOutsidePolygon'], 0, k)
            self.assertTrue(n['allVerticesInside'] and n['allPadCornersInside'] and n['viaRingsFit'], k)
            # No trace doubles back; separate paths and non-adjacent segments keep the clear gap
            self.assertEqual(n['sharpTurns'], 0, k)
            for g in ('minSelfGapPx', 'minPathGapPx'):
                if n[g] is not None:
                    self.assertGreaterEqual(n[g], n['pathGapPx'] - 0.01, (k, g))
        for k in SMALL:
            # Boards at or below the old cap are byte-identical to the baseline
            self.assertEqual(new[k]['boardSha'], old[k]['boardSha'], k)
        for k in BIG:
            # Past the old 18 (8 thin) path plateau: more paths, length and vias than the baseline
            self.assertGreater(new[k]['traces'], old[k]['traces'], k)
            self.assertGreater(new[k]['traceLengthPx'], old[k]['traceLengthPx'], k)
            self.assertGreater(new[k]['vias'], old[k]['vias'], k)
        for k in ('broad', 'sloped', 'irregular', 'large', 'huge'):
            # Paths keep 2.5 motif units off the neon border
            self.assertGreaterEqual(new[k]['minVertexEdgeGapPx'], 2.5 * new[k]['circuitScale'] - 0.01, k)
        self.assertEqual(new['very-thin']['vias'], 0)
        self.assertGreater(new['thin']['vias'], 0)
        # Size scaling: paths per area stay flat from broad (1x) to large (4x) to huge (16x area);
        # no plateau (the baseline stopped at 18-20 paths however big the panel)
        per_area = {k: new[k]['traces'] / new[k]['areaPx2'] for k in ('broad', 'large', 'huge')}
        scaling = dict(rule='traces/area of large and huge within 0.75-1.25x broad; huge > 18 traces; strip > 8 traces',
                       tracesPer100kPx2={k: round(v * 1e5, 3) for k, v in per_area.items()},
                       ratioToBroad={k: round(per_area[k] / per_area['broad'], 3) for k in ('large', 'huge')},
                       areaRatioToBroad={k: round(new[k]['areaPx2'] / new['broad']['areaPx2'], 3) for k in ('large', 'huge')},
                       traces={k: dict(old=old[k]['traces'], new=new[k]['traces']) for k in ('broad', 'large', 'huge', 'strip')},
                       baselinePlateauRatioToBroad={k: round(old[k]['traces'] / old[k]['areaPx2'] / (old['broad']['traces'] / old['broad']['areaPx2']), 3)
                                                    for k in ('large', 'huge')})
        for k in ('large', 'huge'):
            self.assertGreaterEqual(scaling['ratioToBroad'][k], 0.75, k)
            self.assertLessEqual(scaling['ratioToBroad'][k], 1.25, k)
        self.assertGreater(new['huge']['traces'], 18)
        self.assertGreater(new['huge']['traces'], new['large']['traces'])
        self.assertGreater(new['strip']['traces'], 8)
        scaling['pass'] = True
        density = dict(fixed_camera=dict(viewport=VIEWPORT, dpr=1, cameraScale=page.evaluate('scale[version]'), clock_ms=4321), baseline=self.baseline_sha,
                       sizeScaling=scaling,
                       config=page.evaluate('GRAPPLE_OVER_ROLE_DETAIL.bounce.circuitScale'), panels=rows,
                       notes='px = logical screen px at the fixed camera; same page setup for both revisions')
        self.write('density.json', density)
        self._merge('render-checks.json', dict(clipping={k: dict(painted=new[k]['painted'], paintedOutsidePolygon=new[k]['paintedOutsidePolygon'],
            allVerticesInside=new[k]['allVerticesInside'], allPadCornersInside=new[k]['allPadCornersInside'],
            viaRingsFit=new[k]['viaRingsFit'], minVertexEdgeGapPx=new[k]['minVertexEdgeGapPx'], sharpTurns=new[k]['sharpTurns'], minPathGapPx=new[k]['minPathGapPx'],
            minSelfGapPx=new[k]['minSelfGapPx'], pathGapPx=new[k]['pathGapPx']) for k in SHAPES}))
        print('PASS density: ' + ', '.join(f'{k} traces {old[k]["traces"]}->{new[k]["traces"]} '
                                            f'length x{rows[k]["traceLengthRatio"]}' for k in SHAPES) + '; motif sizes unchanged; '
              f'traces/area vs broad: large x{scaling["ratioToBroad"]["large"]}, huge x{scaling["ratioToBroad"]["huge"]} (no plateau)')

    def test_03_determinism_cache_and_invalidation(self):
        pages = [self.open(self.url), self.open(self.url)]
        boards = [p.evaluate(BOARDS, list(SHAPES)) for p in pages]
        # Production frame pixels inside the bounce panels (the backdrop has
        # +-2 level page-load raster noise, see test_01)
        frames = [p.evaluate('''(ids) => { const f = T664.frame()
            const masks = ids.map(id => T664.mask(T664.byId(id)))
            return Array.from(f.filter((v, i) => masks.some(m => m[i - i % 4 + 3]))) }''', list(SHAPES)) for p in pages]
        # The drawn material itself is compared exactly (boards[*].materialPixelHash);
        # the composited first frames may differ by a level or two in a few channels
        frameDiff = [abs(a - b) for a, b in zip(*frames)]
        frameCompare = dict(panelChannels=len(frameDiff), lengthsEqual=len(frames[0]) == len(frames[1]), channelsDiffering=sum(1 for d in frameDiff if d),
                            channelsDifferingOver2=sum(1 for d in frameDiff if d > 2),
                            channelsDifferingOver4=sum(1 for d in frameDiff if d > 4), maxDiff=max(frameDiff, default=0))
        frames = [hashlib.sha256(bytes(f)).hexdigest()[:16] for f in frames]
        page = pages[0]
        cache = page.evaluate('''(ids) => {
            const world = floors[0]
            let builds = 0
            const original = bounceBoardDetail
            bounceBoardDetail = (...args) => { builds++; return original(...args) }
            const spriteFor = id => { const s = T664.s()
                return bounceMaterialSprite(T664.byId(id), world, glowSpriteScale(s), glowSpriteScale(s), 1 / scale[version]) }
            const first = ids.map(spriteFor)
            const size0 = BOUNCE_MATERIAL.sprites.size
            const keys0 = [...BOUNCE_MATERIAL.sprites.keys()].filter(k => k.startsWith('bounce|'))
            builds = 0
            for (let i = 0; i < 30; i++) { world.elapsedSteps += cyclesPerTick; draw() }
            const framesBuilds = builds
            const reused = ids.map(spriteFor).every((s, i) => s === first[i])
            const size1 = BOUNCE_MATERIAL.sprites.size
            BOUNCE_MATERIAL.circuitScale = 2
            builds = 0
            const scaled = ids.map(spriteFor)
            const changedBuilds = builds
            const scaledDistinct = scaled.every((s, i) => s !== first[i] && s.circuit === 2)
            const scale2 = +(scaled[2].board.scale * scale[version]).toFixed(3)
            draw()
            BOUNCE_MATERIAL.circuitScale = 3
            builds = 0
            const back = ids.map(spriteFor)
            const backBuilds = builds
            bounceBoardDetail = original
            const restoreReusesCached = back.every((s, i) => s === first[i])
            // Fresh material sprite build of the huge panel (board + raster), real clock
            const hi = ids.indexOf('huge'), timesMs = []
            for (let i = 0; i < 5; i++) {
                for (const [k, v] of [...BOUNCE_MATERIAL.sprites]) if (v === first[hi]) BOUNCE_MATERIAL.sprites.delete(k)
                const t0 = T664_NOW(), fresh = spriteFor('huge')
                timesMs.push(+(T664_NOW() - t0).toFixed(2))
                first[hi] = fresh
            }
            const hugeSpriteBuild = {runs: timesMs.length, timesMs, medianMs: [...timesMs].sort((a, b) => a - b)[2],
                traces: first[hi].board.traces.length, spritePx: [first[hi].image.width, first[hi].image.height]}
            return {hugeSpriteBuild, repeatedDrawFrames: 30, boardBuildsDuringFrames: framesBuilds, spritesReusedAfterFrames: reused,
                cacheSizeBefore: size0, cacheSizeAfter: size1, keysIncludeCircuitScale: keys0.every(k => k.split('|')[2].endsWith(',3')),
                sampleKeyTail: keys0[0].split('|')[2], scaleChangeBuilds: changedBuilds, scaleChangeNewSprites: scaledDistinct,
                motifUnitAtScale2: scale2, restoreScale3Builds: backBuilds,
                restoreReusesCached}
        }''', list(SHAPES))
        determinism = dict(boardsEqualAcrossPages=boards[0] == boards[1], frameHashes=frames, frameCompare=frameCompare,
                           boardShas={k: boards[0][k]['boardSha'] for k in SHAPES},
                           materialPixelHashes={k: boards[0][k]['materialPixelHash'] for k in SHAPES})
        self._merge('render-checks.json', dict(determinism=determinism, cache=cache))
        self.assertEqual(boards[0], boards[1])
        self.assertTrue(frameCompare['lengthsEqual'] and frameCompare['panelChannels'] > 0)
        # Some page-load pairs get the other backdrop raster variant (up to 3 levels in a few
        # dozen channels seen through the panel glow); the boards and drawn material above are exact
        self.assertEqual(frameCompare['channelsDifferingOver4'], 0)
        self.assertLess(frameCompare['channelsDiffering'], frameCompare['panelChannels'] / 1000)
        self.assertEqual(cache['boardBuildsDuringFrames'], 0)
        self.assertTrue(cache['spritesReusedAfterFrames'])
        self.assertEqual(cache['cacheSizeBefore'], cache['cacheSizeAfter'])
        self.assertTrue(cache['keysIncludeCircuitScale'])
        self.assertEqual(cache['scaleChangeBuilds'], len(SHAPES))
        self.assertTrue(cache['scaleChangeNewSprites'])
        self.assertEqual(cache['motifUnitAtScale2'], 2)
        self.assertEqual(cache['restoreScale3Builds'], 0)
        self.assertTrue(cache['restoreReusesCached'])
        self.assertEqual(cache['hugeSpriteBuild']['runs'], 5)
        self.assertGreater(cache['hugeSpriteBuild']['medianMs'], 0)
        self.assertGreater(cache['hugeSpriteBuild']['traces'], 18)
        print(f'PASS cache: 0 board builds over 30 frames; scale 3->2 rebuilt {cache["scaleChangeBuilds"]}, '
              f'back to 3 reused cached; huge sprite build median {cache["hugeSpriteBuild"]["medianMs"]} ms; two pages identical (boards/material; frame channels differing {frameCompare["channelsDiffering"]}, '
              f'max {frameCompare["maxDiff"]})')

    def test_04_pulse_alignment_and_timing(self):
        phases = (0.05, 0.3, 0.55, 0.8)
        script = '''([ids, phases]) => {
            const world = floors[0], config = GRAPPLE_OVER_ROLE_DETAIL.bounce
            const out = {pulseMs: config.pulseMs, phases: []}
            const unit = 1 / scale[version], s = T664.s()
            for (const t of phases) {
                const row = {t, panels: {}}
                for (const id of ids) {
                    const e = T664.byId(id)
                    const sprite = bounceMaterialSprite(e, world, glowSpriteScale(s), glowSpriteScale(s), unit)
                    const board = sprite.board, ms = board.scale ?? unit
                    // Contact at the panel's local centroid, t * pulseMs ago
                    const c = e.points.reduce((a, p) => ({x: a.x + p.x / e.points.length, y: a.y + p.y / e.points.length}), {x: 0, y: 0})
                    const steps = Math.round(t * config.pulseMs * cyclesPerTick / physicsStepMs)
                    ROLE_DETAIL.contacts.set(e, {step: world.elapsedSteps - steps, strength: 1, point: c})
                    const pulse = ROLE_DETAIL.pulse(e, world)
                    // Bright parts must be exactly the board's segments and vias
                    const segs = board.traces.flatMap(tr => tr.points.slice(1).map((p, i) => [tr.points[i], p]))
                    const vias = board.traces.flatMap(tr => tr.vias)
                    const parts = sprite.bright.parts
                    const aligned = parts.filter(p => !p.via).length === segs.length && parts.filter(p => p.via).length === vias.length &&
                        parts.filter(p => !p.via).every((p, i) => p.a === segs[i][0] && p.b === segs[i][1]) &&
                        parts.filter(p => p.via).every((p, i) => p.a === vias[i])
                    const wave = bounceContactWave(e, world, sprite, unit)
                    const lit = T664.probe(() => drawBounceContact(e, world))
                    // Every lit pulse pixel lies on an enlarged trace (half width) or via ring, or in the contact dot
                    const origin = e.points[0], ox = e.x + origin.x + screen.x, oy = e.y + origin.y + screen.y
                    const segDist = (p, a, b) => { const dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy
                        const f = l2 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2)) : 0
                        return Math.hypot(p.x - a.x - f * dx, p.y - a.y - f * dy) }
                    let litPx = 0, off = 0, onTrace = 0
                    const tol = 1.5 / s
                    for (let i = 3, n = 0; i < lit.length; i += 4, n++) {
                        if (lit[i] < 8) continue
                        litPx++
                        const x = n % canvas.width, y = Math.floor(n / canvas.width)
                        const p = {x: (x + 0.5) / s - ox, y: (y + 0.5) / s - oy}
                        const nearSeg = segs.some(([a, b]) => segDist(p, a, b) <= 0.4 * ms + tol)
                        const nearVia = vias.some(v => Math.abs(Math.hypot(p.x - v.x, p.y - v.y) - 1.2 * ms) <= 0.25 * ms + tol)
                        const inDot = wave.dot > 0 && Math.hypot(p.x - wave.point.x, p.y - wave.point.y) <= 8 * ms + tol
                        if (nearSeg) onTrace++
                        if (!nearSeg && !nearVia && !inDot) off++
                    }
                    row.panels[id] = {pulse: +pulse.toFixed(4), ageMs: +wave.ageMs.toFixed(2), partsAligned: aligned,
                        parts: parts.length, glowingParts: wave.parts.filter(p => p.glow > 0).length,
                        waveRadiusPx: +(wave.radius / unit).toFixed(1), dot: +wave.dot.toFixed(3),
                        dotRadiusPx: +(8 * ms / unit).toFixed(1), litPx, litOnTracePx: onTrace, litOffMotifPx: off}
                    ROLE_DETAIL.contacts.delete(e)
                }
                out.phases.push(row)
            }
            return out
        }'''
        new = self.open(self.url).evaluate(script, [list(SHAPES), list(phases)])
        old = self.open(self.baseline_url).evaluate(script, [list(SHAPES), list(phases)])
        lit = 0
        for row_new, row_old in zip(new['phases'], old['phases']):
            for k in SHAPES:
                n = row_new['panels'][k]
                self.assertTrue(n['partsAligned'], (row_new['t'], k))
                self.assertEqual(n['litOffMotifPx'], 0, (row_new['t'], k))
                # Same timing: pulse value and age identical to the baseline at every phase
                self.assertEqual(n['pulse'], row_old['panels'][k]['pulse'])
                self.assertEqual(n['ageMs'], row_old['panels'][k]['ageMs'])
                lit += n['litPx']
        self.assertEqual(new['pulseMs'], old['pulseMs'])
        self.assertGreater(lit, 0)
        pulse = dict(phases=phases, pulseMs=new['pulseMs'], new=new['phases'],
                     baselineTiming={r['t']: {k: [v['pulse'], v['ageMs'], v['dotRadiusPx']] for k, v in r['panels'].items()}
                                     for r in old['phases']})
        self._merge('render-checks.json', dict(pulse=pulse))
        print(f'PASS pulse: parts aligned with enlarged traces at phases {phases}; {lit} lit px, 0 off-motif; '
              f'timing identical to baseline (pulseMs {new["pulseMs"]})')

    def test_05_isolation(self):
        geometry = '''() => { const level = validateMountainManifest(GRAPPLE_OVER_MOUNTAIN);
            return JSON.stringify({elements: level.elements.map(e => ({id: e.id, role: e.role,
                grapplable: e.grapplable, x: e.x, y: e.y, points: e.points})), movers: level.movers}) }'''
        state = '''() => JSON.stringify({climb: captureClimbState(),
            fixture: floors[0].elements.map(e => ({id: e.id, role: e.surfaceRole, x: e.x, y: e.y, points: e.getPoints()})),
            zones: floors[0].dragZones.map(z => ({id: z.id, points: z.getPoints()}))})'''
        result = {}
        for label, url in (('before', self.baseline_url), ('after', self.url)):
            page = self.open(url)
            g = page.evaluate(geometry)
            s0 = page.evaluate(state)
            page.evaluate('() => { for (let i = 0; i < 20; i++) draw() }')
            s1 = page.evaluate(state)
            roles = page.evaluate('''(ids) => Object.fromEntries(ids.map(id => { const e = T664.byId(id)
                return [id, {role: e.surfaceRole ?? e.role ?? 'drag', grapplable: e.grapplable ?? false}] }))''', list(SHAPES + CONTROLS))
            result[label] = dict(levelGeometrySha=hashlib.sha256(g.encode()).hexdigest(),
                                 elements=len(json.loads(g)['elements']),
                                 stateSha=hashlib.sha256(s0.encode()).hexdigest(),
                                 stateUnchangedBy20Draws=s0 == s1, roles=roles)
        rc = self.out / 'render-checks.json'
        fd = json.loads(rc.read_text()).get('spill') if rc.exists() else None
        iso = dict(baseline=self.baseline_sha, **result,
                   geometryEqual=result['before']['levelGeometrySha'] == result['after']['levelGeometrySha'],
                   stateEqual=result['before']['stateSha'] == result['after']['stateSha'],
                   controlRolesUnchanged=result['before']['roles'] == result['after']['roles'],
                   stateFields='captureClimbState() + fixture element/drag-zone id, role, x, y, points',
                   controlsFixedPhase=fd and fd['controls'],
                   pageErrors=[e for errs in self.page_errors for e in errs])
        self._merge('render-checks.json', dict(isolation=iso))
        self.assertTrue(iso['geometryEqual'])
        self.assertTrue(iso['controlRolesUnchanged'])
        self.assertEqual({k: result['after']['roles'][k]['role'] for k in CONTROLS},
                         {'solid': 'solid', 'mover': 'solid', 'hazard': 'hazard', 'drag': 'drag'})
        self.assertTrue(iso['stateEqual'])
        self.assertTrue(result['before']['stateUnchangedBy20Draws'] and result['after']['stateUnchangedBy20Draws'])
        self.assertGreater(result['after']['elements'], 0)
        self.assertEqual(iso['pageErrors'], [])
        print(f'PASS isolation: level geometry {result["after"]["levelGeometrySha"][:12]} '
              f'({result["after"]["elements"]} elements) and state equal before/after; draws change no state')

    def _merge(self, name, value):
        path = self.out / name
        data = json.loads(path.read_text()) if path.exists() else {}
        data.update(value)
        path.write_text(json.dumps(data, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    unittest.main()
