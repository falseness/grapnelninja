"""TASK-659: the production game draws the imported transfer guide arrows (render/routearrows.js).

Boots the real index.html. The guided cases serve leveldata.js as the shipped
extended-mountain-v9 SVG imported with a `guide` on every gn:transfer (the
TASK-657 injection of convert_extended_mountain_svg.guide()), which since
TASK-660 is byte-identical to the shipped leveldata.js; the unguided cases
serve the same SVG with every guide stripped. Draw calls are recorded from the
production drawRouteArrows() through the canvas transform and compared with
the SVG arrow geometry (head_of / bezier_tangent at t = 0.25).

    python3 -m unittest discover -s tools -p test_runtime_route_arrows.py -v

ROUTE_ARROWS_RUNTIME_EVIDENCE_DIR=DIR writes runtime-arrows.json, game-examples.png,
examples.json and physics.json there.
"""
import base64
from contextlib import ExitStack
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402
import convert_extended_mountain_svg as conv  # noqa: E402
from import_level_svg import dumps, import_svg  # noqa: E402

SVG = ROOT / 'artifacts' / 'levels' / 'extended-mountain.svg'
MEASUREMENTS = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'
LEVELDATA = ROOT / 'leveldata.js'
EVIDENCE = os.environ.get('ROUTE_ARROWS_RUNTIME_EVIDENCE_DIR')
VIEWPORT = {'width': 1280, 'height': 720}
T = 0.25
COLOR, OPACITY, STROKE_PX, HEAD_PX = '#8bdde8', 0.4, 1.5, 6
# The canvas keeps its transform in float32: compare to 0.002 device pixels.
DEVICE_EPS = 2e-3
EXAMPLES = [('T03', 'opening (rightward)'), ('T09', 'leftward'), ('T17', 'ceiling catch'), ('T18', 'descending onto bounce')]

# Fixed-camera production frames, and a recorder around the production drawRouteArrows().
# Canvas pixel = (world - (wx, wy)) * k.
SETUP = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    // Frozen clock: two frames of the same camera differ only by what the test toggles
    const now = performance.now()
    performance.now = () => now
    // The first-run control hint (drawn over the world) is dismissed, as after a player's first press
    TUTORIAL_HINT.visible = false
    const production = drawRouteArrows
    window.T659 = {order: [], rec: null, off: false}
    const mark = name => T659.order.push(name)
    for (const name of ['drawAcquisitionCircle', 'drawPlayerLayer'])
    {
        const f = window[name]
        window[name] = function() { mark(name); return f.apply(this, arguments) }
    }
    drawRouteArrows = function(world)
    {
        mark('drawRouteArrows')
        const c = ctx, rec = {paths: [], ops: []}
        const names = ['moveTo', 'lineTo', 'bezierCurveTo', 'stroke', 'fill']
        const saved = names.map(n => c[n])
        const pt = (x, y) => { const p = c.getTransform().transformPoint({x, y}); return [p.x, p.y] }
        let path = null
        c.moveTo = function(x, y) { path = {points: [pt(x, y)], kinds: ['M']}; rec.paths.push(path); return saved[0].apply(c, arguments) }
        c.lineTo = function(x, y) { path.points.push(pt(x, y)); path.kinds.push('L'); return saved[1].apply(c, arguments) }
        c.bezierCurveTo = function(a, b, d, e, x, y) { path.points.push(pt(a, b), pt(d, e), pt(x, y)); path.kinds.push('C'); return saved[2].apply(c, arguments) }
        c.stroke = function() { const m = c.getTransform(); path.op = 'stroke'; path.style = c.strokeStyle; path.alpha = c.globalAlpha
            path.width = c.lineWidth * Math.hypot(m.a, m.b); path.composite = c.globalCompositeOperation; path.blur = c.shadowBlur
            return saved[3].apply(c, arguments) }
        c.fill = function() { path.op = 'fill'; path.style = c.fillStyle; path.alpha = c.globalAlpha; path.blur = c.shadowBlur
            return saved[4].apply(c, arguments) }
        try { if (!T659.off) production(world) }
        finally { names.forEach((n, i) => c[n] = saved[i]); T659.rec = rec }
        rec.drawn = ROUTE_ARROWS.drawn.slice()
    }
    for (const [object, name] of [[grapnel, 'draw'], [grapnel, 'drawHook'], [floors[0], 'draw']])
    {
        const f = object[name]
        object[name] = function() { mark(name); return f.apply(this, arguments) }
    }
    window.T659.frame = (wx, wy, k, off = false) => {
        scale[version] = k * width / canvas.width
        screen.x = -wx
        screen.y = -wy
        T659.off = off
        T659.order = []
        ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
        draw()
        return {rec: T659.rec, order: T659.order, cssWidth: getCanvasCssRect().width, canvas: [canvas.width, canvas.height]}
    }
    return {canvas: [canvas.width, canvas.height], logical: [width, height], cssWidth: getCanvasCssRect().width,
            gameScale: MODE_DEFINITIONS.grapple_over.cameraScale}
}'''

SHOT = '''([wx, wy, k, off]) => { T659.frame(wx, wy, k, off); return canvas.toDataURL('image/png') }'''

# Every collection the physics, rope, collision and render code reads, and the save schema.
WORLD = '''() => {
    const w = floors[0]
    const shape = e => ({id: e.id, role: e.surfaceRole, grapplable: e.grapplable, cls: e.constructor.name,
        points: e.getPoints().map(p => [p.x, p.y])})
    const schema = v => Array.isArray(v) ? [v.length ? schema(v[0]) : null]
        : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k => [k, schema(v[k])])) : typeof v
    const save = captureClimbState()
    return {elements: w.elements.map(shape), dragZones: w.dragZones.map(shape), byId: [...w.byId.keys()],
        grappleGroups: floors.flatMap(f => f.elements).map(e => e.id), movers: w.level.movers,
        floors: floors.length, saveSchema: schema(save), save,
        worldKeys: Object.keys(w).sort(), ninjaKeys: Object.keys(ninja).sort(), grapnelKeys: Object.keys(grapnel).sort(),
        storageKeys: Object.keys(localStorage).sort()}
}'''

# Stop the loop and take the "Restart climb" action: both levels start from tick 0.
FREEZE_RESTART = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    CLIMB_UI.restart()
    cancelAnimationFrame(game)
}'''

# Same input on both levels: a held shot toward P1, release, a second shot; draw() runs every tick.
TRACE = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    const shoot = (x, y, type) => {
        const p = canvasCoordsToViewportCoords({x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})
        document.dispatchEvent(new MouseEvent(type, {clientX: p.x, clientY: p.y}))
    }
    ninja.speedX = 0.6; ninja.speedY = -2.5
    const actions = {20: ['mousedown', 1050, -330], 120: ['mouseup', 1050, -330], 150: ['mousedown', 1500, -700], 240: ['mouseup', 1500, -700]}
    const trace = []
    for (let tick = 0; tick < 300; tick++)
    {
        if (actions[tick]) shoot(actions[tick][1], actions[tick][2], actions[tick][0])
        physics()
        draw()
        trace.push([tick, ninja.x, ninja.y, ninja.speedX, ninja.speedY, grapnel.throwed, grapnel.isGrappled(),
            grapnel.pos.length ? grapnel.pos[0].slice(0, 2) : null, screen.x, screen.y, floors[0].elapsedSteps,
            floors[0].climbStats.bestHeight ?? null])
    }
    return {trace, arrowsLastFrame: ROUTE_ARROWS.drawn.length, save: captureClimbState()}
}'''


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def unguided_svg():
    """Shipped v6 SVG with every gn:transfer guide removed (the pre-TASK-660 legacy shape)."""
    return re.sub(r'(<gn:transfer id="T\d+"[^>]*?) guide="[^"]*"', r'\1', SVG.read_text())


def guided_svg(only=None):
    """Shipped v6 SVG with guides on every (or only the listed) gn:transfer."""
    meas = json.loads(MEASUREMENTS.read_text())
    rows, frags = {'T%02d' % r['number']: r for r in meas['encounters']}, meas['fragments']
    return re.sub(r'(<gn:transfer id="(T\d+)"[^>]*?)/>',
                  lambda m: m.group(0) if only and m.group(2) not in only else
                  '%s guide="%s"/>' % (m.group(1), conv.guide(rows[m.group(2)], frags)), unguided_svg())


def leveldata(level):
    return '// Generated by tools/import_level_svg.py; do not edit.\nwindow.GRAPPLE_OVER_BUNDLED_LEVEL = ' + dumps(level).rstrip() + ';\n'


def lerp(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def cubic(p, t):
    return list(conv.bezier(p, t))


def unit(v):
    n = math.hypot(*v)
    return [v[0] / n, v[1] / n]


def box(points):
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]


def overlaps(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def image(data_url):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(',', 1)[1]))).convert('RGB')


class RuntimeRouteArrowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.svg_text = guided_svg()
        cls.level = import_svg(cls.svg_text.encode())
        cls.js = leveldata(cls.level)
        cls.shipped_js = LEVELDATA.read_text()
        cls.plain_js = leveldata(import_svg(unguided_svg().encode()))
        cls.guides = {t['id']: t['guide'] for t in cls.level['svgFormat']['transfers']}
        cls.transfers = {t['id']: t for t in cls.level['svgFormat']['transfers']}
        cls.errors = []
        cls.evidence = {'inputs': {'svg': str(SVG.relative_to(ROOT)), 'svgSha256': sha(SVG.read_bytes()),
                                   'measurementsSha256': sha(MEASUREMENTS.read_bytes()), 'guidedSvgSha256': sha(cls.svg_text),
                                   'guidedLeveldataSha256': sha(cls.js), 'shippedLeveldataSha256': sha(cls.shipped_js),
                                   'unguidedLeveldataSha256': sha(cls.plain_js),
                                   'routearrowsJsSha256': sha((ROOT / 'render/routearrows.js').read_bytes()),
                                   'drawJsSha256': sha((ROOT / 'render/draw.js').read_bytes())},
                        'style': {'t': T, 'color': COLOR, 'opacity': OPACITY, 'strokePx': STROKE_PX, 'headPx': HEAD_PX},
                        'cases': {}}

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            path = Path(EVIDENCE, 'runtime-arrows.json')
            prior = json.loads(path.read_text()) if path.exists() else {'cases': {}}
            prior['cases'].update(cls.evidence['cases'])
            cls.evidence['cases'] = prior['cases']
            cls.evidence['browserErrors'] = cls.errors
            path.write_text(json.dumps(cls.evidence, separators=(',', ':'), sort_keys=True) + '\n')

    def open(self, js=None):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(context.close)
        if js is not None:
            context.route('**/leveldata.js', lambda route: route.fulfill(body=js, content_type='application/javascript'))
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append('pageerror: %s' % e))
        page.on('console', lambda m: m.type == 'error' and self.errors.append('console: %s' % m.text))
        page.goto(self.url)
        wait_for_boot_run(page)
        return page

    def setup(self, page):
        info = page.evaluate(SETUP)
        info['k0'] = info['gameScale'] * info['canvas'][0] / info['logical'][0]
        info['devPerCss'] = info['canvas'][0] / info['cssWidth']
        return info

    def frame(self, page, wx, wy, k, off=False):
        return page.evaluate('a => T659.frame(...a)', [wx, wy, k, off])

    def overview(self, info):
        b = self.level['bounds']
        k = 0.9 * min(info['canvas'][0] / (b['right'] - b['left']), info['canvas'][1] / (b['bottom'] - b['top']))
        return b['left'] - 100, b['top'] - 100, k

    def expected(self, tid):
        g = self.guides[tid]
        a = g[0]
        b, c, d = lerp(g[0], g[1], T), lerp(g[1], g[2], T), lerp(g[2], g[3], T)
        ab, bc = lerp(b, c, T), lerp(c, d, T)
        return {'curve': [a, b, ab, lerp(ab, bc, T)], 'tangent': unit(conv.bezier_tangent(g, T)),
                'samples': [cubic(g, T * s / 10) for s in range(11)]}

    def arrows(self, out, wx, wy, k, info):
        """Decode the recorded draw calls into world-space arrows, checking each against the metadata."""
        rec = out['rec']
        paths = rec['paths']
        self.assertEqual(len(paths), 2 * len(rec['drawn']))
        world = lambda p: [p[0] / k + wx, p[1] / k + wy]
        dev_per_css = out['canvas'][0] / out['cssWidth']
        result, worst = [], {'point': 0, 'sample': 0, 'tangent': 0, 'stroke': 0, 'head': 0}
        for i, tid in enumerate(rec['drawn']):
            shaft, head = paths[2 * i], paths[2 * i + 1]
            self.assertEqual((shaft['kinds'], shaft['op'], head['kinds'], head['op']), (['M', 'C'], 'stroke', ['M', 'L', 'L'], 'fill'))
            for p in (shaft, head):
                self.assertEqual((p['style'], p['blur']), (COLOR, 0))
                self.assertAlmostEqual(p['alpha'], OPACITY, places=6)
            curve = [world(p) for p in shaft['points']]
            exp = self.expected(tid)
            point_err = max(math.dist(a, b) for a, b in zip(curve, exp['curve']))
            sample_err = max(math.dist(cubic(curve, s / 10), e) for s, e in zip(range(11), exp['samples']))
            tip, b1, b2 = head['points']
            base = lerp(b1, b2, .5)
            tangent = unit([tip[0] - base[0], tip[1] - base[1]])
            tangent_err = math.dist(tangent, exp['tangent'])
            head_len = math.dist(tip, base) / dev_per_css
            head_width = math.dist(b1, b2) / dev_per_css
            stroke = shaft['width'] / dev_per_css
            self.assertLess(point_err, DEVICE_EPS / k)
            self.assertLess(sample_err, DEVICE_EPS / k)
            self.assertLess(math.dist(world(tip), exp['curve'][3]), DEVICE_EPS / k)
            self.assertLess(tangent_err, 1e-4)
            self.assertAlmostEqual(head_len, HEAD_PX, delta=1e-3)
            self.assertAlmostEqual(head_width, HEAD_PX, delta=1e-3)
            self.assertAlmostEqual(stroke, STROKE_PX, delta=1e-4)
            worst = {'point': max(worst['point'], point_err), 'sample': max(worst['sample'], sample_err),
                     'tangent': max(worst['tangent'], tangent_err),
                     'stroke': max(worst['stroke'], abs(stroke - STROKE_PX)),
                     'head': max(worst['head'], abs(head_len - HEAD_PX), abs(head_width - HEAD_PX))}
            result.append({'id': tid, 'curveWorld': curve, 'tipWorld': world(tip), 'tangent': tangent,
                           'strokePx': stroke, 'headLengthPx': head_len, 'headWidthPx': head_width,
                           'shaftDevice': shaft['points'], 'headDevice': head['points']})
        return result, worst

    def test_01_all_guides_loaded_and_drawn_match_metadata(self):
        page = self.open(self.js)
        info = self.setup(page)
        loaded = page.evaluate('() => ({layoutId: floors[0].level.layoutId, transfers: floors[0].level.svgFormat.transfers,'
                               ' arrows: routeArrowsFor(floors[0].level).map(a => ({id: a.id, curve: a.curve, tangent: a.tangent}))})')
        self.assertEqual(loaded['layoutId'], 'extended-mountain-v9')
        self.assertEqual(len(self.level['svgFormat']['fragments']), 31)
        self.assertEqual(loaded['transfers'], self.level['svgFormat']['transfers'])
        self.assertEqual(len(loaded['arrows']), 30)
        for a in loaded['arrows']:
            exp = self.expected(a['id'])
            self.assertLess(max(math.dist(p, q) for p, q in zip(a['curve'], exp['curve'])), 1e-9)
            self.assertLess(math.dist(a['tangent'], exp['tangent']), 1e-12)
        # Whole level in one frame: every guide drawn.
        wx, wy, k = self.overview(info)
        out = self.frame(page, wx, wy, k)
        self.assertEqual(sorted(out['rec']['drawn']), sorted(self.guides))
        overview, worst = self.arrows(out, wx, wy, k, info)
        self.assertEqual(len(overview), 30)
        self.evidence['cases']['allGuides'] = {
            'fragments': len(self.level['svgFormat']['fragments']), 'loadedTransfers': len(loaded['transfers']),
            'loadedGuides': sum('guide' in t for t in loaded['transfers']), 'runtimeArrows': len(loaded['arrows']),
            'loadedEqualsImported': True, 'overviewCamera': {'wx': wx, 'wy': wy, 'k': k}, 'drawn': len(overview),
            'worstError': worst, 'arrows': [{'id': a['id'], 'guide': self.guides[a['id']], 'expected': self.expected(a['id']),
                                             'drawnCurveWorld': a['curveWorld'], 'drawnTangent': a['tangent'],
                                             'strokePx': a['strokePx'], 'headLengthPx': a['headLengthPx']} for a in overview]}

    def test_02_translation_and_two_zooms_preserve_world_and_screen_sizes(self):
        page = self.open(self.js)
        info = self.setup(page)
        k0 = info['k0']
        tip = self.expected('T09')['curve'][3]
        cameras = {'normal': (k0, 0, 0), 'translated': (k0, 137.5, -91.25), 'zoom1.6': (k0 * 1.6, 0, 0), 'zoom0.6': (k0 * .6, 0, 0)}
        frames = {}
        for name, (k, dx, dy) in cameras.items():
            wx = tip[0] - info['canvas'][0] / k / 2 + dx
            wy = tip[1] - info['canvas'][1] / k / 2 + dy
            out = self.frame(page, wx, wy, k)
            arrows, worst = self.arrows(out, wx, wy, k, info)
            view = [wx, wy, wx + info['canvas'][0] / k, wy + info['canvas'][1] / k]
            # No guide whose curve box meets the view is culled; guides far outside are.
            must = sorted(t for t in self.guides if overlaps(box(self.expected(t)['curve']), view))
            far = [t for t in self.guides if not overlaps(box(self.expected(t)['curve']),
                                                           [view[0] - 3000, view[1] - 3000, view[2] + 3000, view[3] + 3000])]
            drawn = out['rec']['drawn']
            self.assertTrue(set(must) <= set(drawn), (name, must, drawn))
            self.assertFalse(set(far) & set(drawn), name)
            self.assertIn('T09', drawn)
            self.assertGreater(len(far), 0)
            frames[name] = {'camera': {'wx': wx, 'wy': wy, 'k': k, 'screenPxPerWorld': k / info['devPerCss']},
                            'drawn': drawn, 'mustDraw': must, 'farCulled': far, 'worstError': worst,
                            'arrows': {a['id']: a for a in arrows}}
        # The same guide sits at the same world points under every camera, with the same screen sizes.
        base = frames['normal']['arrows']['T09']
        comparison = {}
        for name, f in frames.items():
            a = f['arrows']['T09']
            d = max(math.dist(p, q) for p, q in zip(a['curveWorld'], base['curveWorld']))
            self.assertLess(d, DEVICE_EPS / f['camera']['k'] + DEVICE_EPS / k0)
            self.assertAlmostEqual(a['strokePx'], STROKE_PX, delta=1e-4)
            self.assertAlmostEqual(a['headLengthPx'], HEAD_PX, delta=1e-3)
            comparison[name] = {'worldDeltaVsNormal': d, 'strokePx': a['strokePx'], 'headLengthPx': a['headLengthPx'],
                                'headWidthPx': a['headWidthPx'], 'tipDevice': a['headDevice'][0],
                                'headWorldLength': HEAD_PX / f['camera']['screenPxPerWorld']}
        tx = [comparison['translated']['tipDevice'][i] - comparison['normal']['tipDevice'][i] for i in (0, 1)]
        self.assertAlmostEqual(tx[0], -137.5 * k0, delta=2 * DEVICE_EPS)
        self.assertAlmostEqual(tx[1], 91.25 * k0, delta=2 * DEVICE_EPS)
        self.assertNotAlmostEqual(comparison['zoom1.6']['headWorldLength'], comparison['normal']['headWorldLength'])
        for f in frames.values():
            f['arrows'] = {t: {k: v for k, v in a.items() if k in ('curveWorld', 'tangent', 'strokePx', 'headLengthPx', 'headWidthPx')}
                           for t, a in f['arrows'].items()}
        self.evidence['cases']['cameras'] = {'frames': frames, 'T09': comparison, 'translationDeviceShift': tx,
                                            'expectedTranslationDeviceShift': [-137.5 * k0, 91.25 * k0]}

    def boundary_case(self, info):
        """A camera at game zoom that shows part of a guide but none of its source panel."""
        k0 = info['k0']
        W, H = info['canvas'][0] / k0, info['canvas'][1] / k0
        elements = {e['id']: e for e in self.level['elements']}
        frag = {f['id']: f['elements'] for f in self.level['svgFormat']['fragments']}
        for tid in sorted(self.guides):
            exp = self.expected(tid)
            src = box([[elements[e]['x'] + p['x'], elements[e]['y'] + p['y']] for e in frag[self.transfers[tid]['from']]
                       for p in elements[e]['points']])
            mid = cubic(exp['curve'], .5)
            ux, uy = exp['tangent']
            if abs(ux) >= abs(uy):
                left = mid[0] if ux > 0 else mid[0] - W
                view = [left, mid[1] - H / 2, left + W, mid[1] + H / 2]
                edge = 'left' if ux > 0 else 'right'
            else:
                top = mid[1] if uy > 0 else mid[1] - H
                view = [mid[0] - W / 2, top, mid[0] + W / 2, top + H]
                edge = 'top' if uy > 0 else 'bottom'
            if not overlaps(src, view) and not overlaps(box([exp['curve'][0]]), view):
                return tid, view, src, edge
        self.fail('no boundary case')

    def test_03_boundary_guide_with_offscreen_source_is_drawn_and_examples(self):
        from PIL import Image, ImageChops, ImageDraw
        page = self.open(self.js)
        info = self.setup(page)
        k0 = info['k0']
        tid, view, src, edge = self.boundary_case(info)
        out = self.frame(page, view[0], view[1], k0)
        self.assertIn(tid, out['rec']['drawn'])
        arrows, _ = self.arrows(out, view[0], view[1], k0, info)
        a = {x['id']: x for x in arrows}[tid]
        on = [p for p in a['shaftDevice'] + a['headDevice'] if 0 <= p[0] < info['canvas'][0] and 0 <= p[1] < info['canvas'][1]]
        self.assertTrue(on)
        loaded_src = page.evaluate('''ids => floors[0].elements.filter(e => ids.includes(e.id)).map(e => e.getPoints().map(p => [p.x, p.y]))''',
                                   [e for f in self.level['svgFormat']['fragments'] if f['id'] == self.transfers[tid]['from'] for e in f['elements']])
        live_src = box([p for poly in loaded_src for p in poly])
        self.assertFalse(overlaps(live_src, view))
        shots, pixels = {}, {}

        def capture(name, wx, wy, tid):
            with_arrows = image(page.evaluate(SHOT, [wx, wy, k0, False]))
            without = image(page.evaluate(SHOT, [wx, wy, k0, True]))
            out = self.frame(page, wx, wy, k0)
            arrow = {x['id']: x for x in self.arrows(out, wx, wy, k0, info)[0]}[tid]
            pts = arrow['shaftDevice'] + arrow['headDevice']
            x0, y0, x1, y1 = box(pts)
            region = (max(0, int(x0) - 3), max(0, int(y0) - 3), min(with_arrows.width, int(x1) + 4), min(with_arrows.height, int(y1) + 4))
            diff = ImageChops.difference(with_arrows.crop(region), without.crop(region)).convert('L')
            changed = sum(1 for v in diff.getdata() if v > 6)
            cyan = 0
            for (r1, g1, b1), (r0, g0, b0) in zip(with_arrows.crop(region).getdata(), without.crop(region).getdata()):
                if (g1 - g0) > 6 and (b1 - b0) > 6 and (g1 - g0) >= (r1 - r0):
                    cyan += 1
            self.assertGreater(changed, 20, name)
            self.assertGreater(cyan, 20, name)
            pixels[name] = {'transfer': tid, 'camera': {'wx': wx, 'wy': wy, 'k': k0}, 'regionPx': region,
                            'changedPixels': changed, 'cyanShiftedPixels': cyan, 'drawn': out['rec']['drawn']}
            shots[name] = (with_arrows, pts)

        for tid_ex, label in EXAMPLES:
            mid = cubic(self.expected(tid_ex)['curve'], .5)
            capture(label, mid[0] - info['canvas'][0] / k0 / 2, mid[1] - info['canvas'][1] / k0 / 2, tid_ex)
        capture('crosses the %s viewport edge, source %s offscreen' % (edge, self.transfers[tid]['from']), view[0], view[1], tid)
        # Under the player: the ball covers the arrow's head, so its core pixels do not change. At 6x the
        # game zoom the ball (radius 10.8) is about 32 px wide; its 4 px core is compared, away from the rim.
        kz = 6 * k0
        tip = self.expected('T03')['curve'][3]
        page.evaluate('([x, y]) => { ninja.x = x; ninja.y = y }', tip)
        wx, wy = tip[0] - info['canvas'][0] / kz / 2, tip[1] - info['canvas'][1] / kz / 2
        under_on = image(page.evaluate(SHOT, [wx, wy, kz, False]))
        under_off = image(page.evaluate(SHOT, [wx, wy, kz, True]))
        order = self.frame(page, wx, wy, kz)['order']
        c = (round((tip[0] - wx) * kz), round((tip[1] - wy) * kz))
        near = [(dx, dy) for dx in range(-4, 5) for dy in range(-4, 5) if dx * dx + dy * dy <= 16]
        delta = lambda a, b, d: max(abs(u - v) for u, v in zip(a.getpixel((c[0] + d[0], c[1] + d[1])), b.getpixel((c[0] + d[0], c[1] + d[1]))))
        # The ball body is slightly translucent: drawn under it the arrow moves its core by a few levels at most;
        # drawn over it, the 0.4 cyan head would move it by about 0.4 * (arrow - ball), around 20 levels.
        under_delta = max(delta(under_on, under_off, d) for d in near)
        self.assertLessEqual(under_delta, 4)
        # Without the player there, the same pixels show the arrow head.
        page.evaluate('() => { ninja.x += 3000 }')
        away_on = image(page.evaluate(SHOT, [wx, wy, kz, False]))
        away_off = image(page.evaluate(SHOT, [wx, wy, kz, True]))
        away_delta = max(delta(away_on, away_off, d) for d in near)
        self.assertGreaterEqual(away_delta, 20)
        first = order.index('drawRouteArrows')
        for name in ('drawAcquisitionCircle', 'draw', 'drawHook', 'drawPlayerLayer'):
            self.assertLess(first, order.index(name), order)
        # Composite of the real production frames: crops around each arrow, magnified 2x (nearest).
        crop, tile = (280, 158), (560, 316)
        sheet = Image.new('RGB', (tile[0] * 3 + 40, (tile[1] + 30) * 2 + 10), (12, 12, 16))
        draw = ImageDraw.Draw(sheet)
        for i, (name, (img, pts)) in enumerate(shots.items()):
            x0, y0, x1, y1 = box(pts)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            left = int(min(max(cx - crop[0] / 2, 0), img.width - crop[0]))
            top = int(min(max(cy - crop[1] / 2, 0), img.height - crop[1]))
            ox, oy = 10 + (i % 3) * (tile[0] + 10), 10 + (i // 3) * (tile[1] + 30)
            sheet.paste(img.crop((left, top, left + crop[0], top + crop[1])).resize(tile, Image.NEAREST), (ox, oy + 20))
            pixels[name]['sheetCropPx'] = [left, top, left + crop[0], top + crop[1]]
            draw.text((ox, oy + 4), '%s: %s (production frame, 2x crop)' % (pixels[name]['transfer'], name), fill=(230, 230, 230))
            if name.startswith('crosses'):
                draw.rectangle((ox, oy + 20, ox + tile[0] - 1, oy + 20 + tile[1] - 1), outline=(255, 120, 60))
        under = under_on.crop((c[0] - crop[0] // 2, c[1] - crop[1] // 2, c[0] + crop[0] // 2, c[1] + crop[1] // 2)).resize(tile, Image.NEAREST)
        ox, oy = 10 + 2 * (tile[0] + 10), 10 + tile[1] + 30
        sheet.paste(under, (ox, oy + 20))
        draw.text((ox, oy + 4), 'T03 tip under the player (6x zoom; player drawn over the arrow head)', fill=(230, 230, 230))
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            sheet.save(Path(EVIDENCE, 'game-examples.png'))
        self.evidence['cases']['examples'] = {
            'pixels': pixels, 'boundary': {'transfer': tid, 'edge': edge, 'from': self.transfers[tid]['from'], 'viewWorld': view,
                                           'sourceBoxWorld': src, 'liveSourceBoxWorld': live_src, 'sourceOffscreen': True,
                                           'arrowDrawn': True, 'onscreenDevicePoints': on},
            'underPlayer': {'tipWorld': tip, 'k': kz, 'centerPx': c, 'pixels': near, 'coreMaxChannelDeltaWithPlayer': under_delta,
                            'coreMaxChannelDeltaWithoutPlayer': away_delta, 'drawOrder': order}}

    def test_04_absent_and_partial_metadata(self):
        # TASK-660 ships the guides: the shipped leveldata.js is exactly the all-guided level.
        self.assertEqual(self.shipped_js, self.js)
        page = self.open(self.plain_js)  # the same level with every guide removed
        info = self.setup(page)
        wx, wy, k = self.overview(info)
        state = page.evaluate('() => ({layoutId: floors[0].level.layoutId, guides: floors[0].level.svgFormat.transfers.filter(t => t.guide).length,'
                              ' arrows: routeArrowsFor(floors[0].level).length})')
        self.assertEqual(state, {'layoutId': 'extended-mountain-v9', 'guides': 0, 'arrows': 0})
        out = self.frame(page, wx, wy, k)
        self.assertEqual((out['rec']['drawn'], out['rec']['paths']), ([], []))
        partial = import_svg(guided_svg({'T01', 'T09', 'T17'}).encode())
        page2 = self.open(leveldata(partial))
        self.setup(page2)
        out2 = self.frame(page2, wx, wy, k)
        self.assertEqual(sorted(out2['rec']['drawn']), ['T01', 'T09', 'T17'])
        self.assertEqual(len(out2['rec']['paths']), 6)
        # A legacy level object with no svgFormat at all draws nothing and throws nothing.
        legacy = page2.evaluate('() => { const l = {...floors[0].level}; delete l.svgFormat; return routeArrowsFor(l).length }')
        self.assertEqual(legacy, 0)
        self.evidence['cases']['absentMetadata'] = {'shipped': dict(state, drawn=out['rec']['drawn'], drawCalls=len(out['rec']['paths'])),
                                                   'partial': {'guided': ['T01', 'T09', 'T17'], 'drawn': out2['rec']['drawn'],
                                                               'drawCalls': len(out2['rec']['paths'])},
                                                   'noSvgFormatArrows': legacy}

    def test_05_collections_save_state_and_physics_unchanged(self):
        guided, plain = self.open(self.js), self.open(self.plain_js)
        for p in (guided, plain):
            p.evaluate(FREEZE_RESTART)
        worlds = [p.evaluate(WORLD) for p in (guided, plain)]
        for key in ('elements', 'dragZones', 'byId', 'grappleGroups', 'movers', 'floors', 'saveSchema', 'save',
                    'worldKeys', 'ninjaKeys', 'grapnelKeys', 'storageKeys'):
            self.assertEqual(worlds[0][key], worlds[1][key], key)
        self.assertNotIn('guide', json.dumps(worlds[0]['save']))
        traces = [p.evaluate(TRACE) for p in (guided, plain)]
        self.assertEqual(traces[0]['trace'], traces[1]['trace'])
        self.assertEqual(traces[0]['save'], traces[1]['save'])
        moved = math.dist(traces[0]['trace'][0][1:3], traces[0]['trace'][-1][1:3])
        self.assertGreater(moved, 100)
        self.assertTrue(any(t[6] for t in traces[0]['trace']))
        self.assertGreater(traces[0]['arrowsLastFrame'], 0)
        self.assertEqual(traces[1]['arrowsLastFrame'], 0)
        self.evidence['cases']['unchanged'] = {
            'collections': {k: {'equal': True, 'count': len(worlds[0][k]) if isinstance(worlds[0][k], list) else worlds[0][k]}
                            for k in ('elements', 'dragZones', 'byId', 'grappleGroups', 'movers', 'floors')},
            'saveSchemaEqual': True, 'saveSchema': worlds[0]['saveSchema'], 'saveEqual': True,
            'objectKeysEqual': {k: True for k in ('worldKeys', 'ninjaKeys', 'grapnelKeys', 'storageKeys')},
            'physics': {'ticks': len(traces[0]['trace']), 'fields': ['tick', 'x', 'y', 'speedX', 'speedY', 'throwed', 'grappled',
                                                                   'tip', 'screenX', 'screenY', 'elapsedSteps', 'bestHeight'],
                        'guidedSha256': sha(json.dumps(traces[0]['trace'])), 'omittedSha256': sha(json.dumps(traces[1]['trace'])),
                        'identical': True, 'grappledTicks': sum(1 for t in traces[0]['trace'] if t[6]), 'playerMoved': moved,
                        'arrowsDrawnLastFrame': {'guided': traces[0]['arrowsLastFrame'], 'omitted': traces[1]['arrowsLastFrame']},
                        'finalSaveEqual': True, 'sampleEvery50': traces[0]['trace'][::50]}}

    def test_06_zero_browser_errors(self):
        page = self.open(self.js)
        page.evaluate('() => new Promise(r => setTimeout(r, 1500))')
        self.assertEqual(self.errors, [])
        self.evidence['cases']['browserErrors'] = {'count': len(self.errors), 'errors': self.errors}


if __name__ == '__main__':
    unittest.main()
