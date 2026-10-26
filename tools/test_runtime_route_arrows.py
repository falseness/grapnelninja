"""TASK-659: the production game draws the imported transfer guide arrows (render/routearrows.js).

Boots the real index.html. The guided cases serve leveldata.js as the shipped
extended-mountain-v16 SVG imported with a `guide` on every gn:transfer (the
TASK-657 injection of convert_extended_mountain_svg.guide()), which since
TASK-660 is byte-identical to the shipped leveldata.js; the unguided cases
serve the same SVG with every guide stripped. Draw calls are recorded from the
production drawRouteArrows() through the canvas transform and compared with
the SVG arrow geometry (convert_extended_mountain_svg.arrow_geometry: the guide
up to the parameter where its arc length reaches min(0.5 * G, L), TASK-671).
Since TASK-712 the sub-curve is drawn as a static run of open chevrons; the
recorded chevron apexes are compared with the arc positions on the SVG-side
sub-curve and their sizes with the ROUTE_ARROWS screen-pixel ramps.
FIXTURES from test_level_route_arrows (short, long, curved, capped, degenerate)
are drawn by the production drawRouteArrows() on a synthetic level object.

    python3 -m unittest discover -s tools -p test_runtime_route_arrows.py -v

ROUTE_ARROWS_RUNTIME_EVIDENCE_DIR=DIR writes runtime-arrows.json, game-examples.png,
the "runtime" part of arrow-lengths.json, arrows.png and the "runtime" part of
physics-unchanged.json there.
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
from test_level_route_arrows import FIXTURES, WORLD_TOL, arc_length  # noqa: E402

SVG = ROOT / 'artifacts' / 'levels' / 'extended-mountain.svg'
MEASUREMENTS = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'
LEVELDATA = ROOT / 'leveldata.js'
EVIDENCE = os.environ.get('ROUTE_ARROWS_RUNTIME_EVIDENCE_DIR')
VIEWPORT = {'width': 1280, 'height': 720}
COLOR = '#8bdde8'
# TASK-712 chevron run: spacing, and first -> last half-size, stroke width and alpha (screen px)
GAP_PX, HALF_PX, STROKE_PX, ALPHA, GLOW_PX = 16, (4, 7), (1.6, 2.6), (0.25, 0.95), 6
ARC_SAMPLES = 1024
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
            path.shadow = c.shadowColor; path.cap = c.lineCap; path.join = c.lineJoin
            return saved[3].apply(c, arguments) }
        c.fill = function() { path.op = 'fill'; path.style = c.fillStyle; path.alpha = c.globalAlpha; path.blur = c.shadowBlur
            return saved[4].apply(c, arguments) }
        try { if (!T659.off) production(world) }
        finally { names.forEach((n, i) => c[n] = saved[i]); T659.rec = rec }
        rec.drawn = ROUTE_ARROWS.drawn.slice()
        rec.chevrons = ROUTE_ARROWS.drawnChevrons.slice()
    }
    for (const [object, name] of [[grapnel, 'draw'], [grapnel, 'drawHook'], [floors[0], 'draw']])
    {
        const f = object[name]
        object[name] = function() { mark(name); return f.apply(this, arguments) }
    }
    // A synthetic level drawn alone on a cleared canvas: its fragment polygons in grey, then the arrows
    window.T659.fixture = (level, wx, wy, k) => {
        scale[version] = k * width / canvas.width
        screen.x = -wx
        screen.y = -wy
        T659.off = false
        ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
        ctx.save()
        ctx.setTransform(1, 0, 0, 1, 0, 0)
        ctx.fillStyle = '#10161c'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.restore()
        // The world scale draw() applies around drawWorldLayer()
        ctx.save()
        ctx.scale(scale[version], scale[version])
        ctx.fillStyle = '#3c4a52'
        for (const e of level.elements)
        {
            ctx.beginPath()
            e.points.forEach((p, i) => ctx[i ? 'lineTo' : 'moveTo'](e.x + p.x - wx, e.y + p.y - wy))
            ctx.fill()
        }
        drawRouteArrows({level})
        ctx.restore()
        return {rec: T659.rec, cssWidth: getCanvasCssRect().width, canvas: [canvas.width, canvas.height]}
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

# Same input on both levels: grapple the starting panel, release, then shoot again.
TRACE = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    const shoot = (x, y, type) => {
        const p = canvasCoordsToViewportCoords({x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})
        document.dispatchEvent(new MouseEvent(type, {clientX: p.x, clientY: p.y}))
    }
    ninja.speedX = 0.6; ninja.speedY = -2.5
    const actions = {1: ['mousedown', 500, 0], 120: ['mouseup', 300, 0], 150: ['mousedown', 500, 0], 240: ['mouseup', 500, 0]}
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


def arc_table(p):
    """routeArrowTable: cumulative chord lengths at ARC_SAMPLES + 1 even parameters."""
    table, prev = [0.0], p[0]
    for i in range(1, ARC_SAMPLES + 1):
        q = cubic(p, i / ARC_SAMPLES)
        table.append(table[-1] + math.hypot(q[0] - prev[0], q[1] - prev[1]))
        prev = q
    return table


def arc_invert(table, s):
    """routeArrowInvert: the parameter where the table reaches arc length s."""
    n = len(table) - 1
    lo, hi = 0, n
    while hi - lo > 1:
        mid = (lo + hi) >> 1
        lo, hi = (mid, hi) if table[mid] < s else (lo, mid)
    span = table[hi] - table[lo]
    return (lo + ((s - table[lo]) / span if span > 0 else 0)) / n


def chevron_layout(curve, tangent, target, px):
    """Expected chevrons of a sub-curve at px world units per screen px: apex, unit direction and the
    half-size / stroke (screen px) and alpha ramps over the run fraction."""
    table = arc_table(curve)
    gap = GAP_PX * px
    count = math.floor(target / gap + 1e-6) + 1
    out = []
    for i in range(count):
        last, f = i == count - 1, i / (count - 1) if count > 1 else 1
        s = table[-1] - (count - 1 - i) * gap
        t = 1 if last else 0 if s <= 0 else arc_invert(table, s)
        if last:
            apex, u = list(curve[3]), list(tangent)
        else:
            apex = cubic(curve, t)
            d = next(v for v in (conv.bezier_tangent(curve, t), [curve[3][0] - curve[0][0], curve[3][1] - curve[0][1]], [1, 0])
                     if math.hypot(*v) > 1e-9)
            u = unit(d)
        out.append({'apex': apex, 'u': u, 'half': HALF_PX[0] + (HALF_PX[1] - HALF_PX[0]) * f,
                    'stroke': STROKE_PX[0] + (STROKE_PX[1] - STROKE_PX[0]) * f, 'alpha': ALPHA[0] + (ALPHA[1] - ALPHA[0]) * f})
    return out


def overlaps(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def fixture_level(offsets=None):
    """FIXTURES as a runtime level object (svgFormat fragments/transfers + elements), each fixture shifted by offsets[name]."""
    elements, fragments, transfers = [], [], []
    for i, (name, fx) in enumerate(FIXTURES.items()):
        ox, oy = (offsets or {}).get(name, (0, 0))
        for side in ('from', 'to'):
            ids = []
            for j, poly in enumerate(fx[side]):
                x0, y0 = poly[0][0] + ox, poly[0][1] + oy
                ids.append('%s-%s%d' % (name, side, j))
                elements.append({'id': ids[-1], 'x': x0, 'y': y0, 'role': 'solid', 'grapplable': True,
                                 'points': [{'x': x + ox - x0, 'y': y + oy - y0} for x, y in poly]})
            fragments.append({'id': '%s-%s' % (name, side), 'elements': ids})
        transfers.append({'id': name, 'from': name + '-from', 'to': name + '-to',
                          'guide': [[x + ox, y + oy] for x, y in fx['guide']]})
    return {'elements': elements, 'svgFormat': {'fragments': fragments, 'transfers': transfers}}


def level_polygons(level, fragment):
    els = {e['id']: e for e in level['elements']}
    frag = next(f for f in level['svgFormat']['fragments'] if f['id'] == fragment)
    return [[(els[e]['x'] + p['x'], els[e]['y'] + p['y']) for p in els[e]['points']] for e in frag['elements']]


def finite(values):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


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
                        'style': {'gapFraction': conv.ARROW_GAP_FRACTION, 'color': COLOR, 'chevronGapPx': GAP_PX, 'halfSizePx': HALF_PX,
                                  'strokePx': STROKE_PX, 'alpha': ALPHA, 'glowPx': GLOW_PX},
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
            for name, key in (('arrow-lengths.json', 'lengths'), ('physics-unchanged.json', 'physics')):
                if key not in cls.evidence:
                    continue
                path = Path(EVIDENCE, name)
                prior = json.loads(path.read_text()) if path.exists() else {}
                prior['runtime'] = dict(cls.evidence[key], inputs=cls.evidence['inputs'], browserErrors=cls.errors)
                path.write_text(json.dumps(prior, indent=1, sort_keys=True) + '\n')

    def open(self, js=None, arrows_js=None):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(context.close)
        if js is not None:
            context.route('**/leveldata.js', lambda route: route.fulfill(body=js, content_type='application/javascript'))
        if arrows_js is not None:
            context.route('**/render/routearrows.js', lambda route: route.fulfill(body=arrows_js, content_type='application/javascript'))
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

    def expected(self, tid, level=None):
        """The SVG side (converter arrow_geometry) for a guided transfer of the shipped or a fixture level."""
        level = level or self.level
        t = next(x for x in level['svgFormat']['transfers'] if x['id'] == tid)
        g = t['guide']
        geo = conv.arrow_geometry(g, level_polygons(level, t['from']), level_polygons(level, t['to']))
        return {'curve': [list(p) for p in geo['curve']], 'tangent': list(geo['tangent']), 'G': geo['G'], 'L': geo['L'],
                'target': geo['target'], 't': geo['t'], 'endpoint': list(geo['endpoint']),
                'samples': [cubic(g, geo['t'] * s / 10) for s in range(11)]}

    def arrows(self, out, wx, wy, k, info, level=None):
        """Decode the recorded draw calls into world-space chevron runs, checking each against the metadata:
        one open stroked chevron (M L L) per arc position chevronGapPx apart, the last at the tip."""
        rec = out['rec']
        paths = rec['paths']
        self.assertEqual(len(rec['chevrons']), len(rec['drawn']))
        self.assertEqual(len(paths), sum(rec['chevrons']))
        world = lambda p: [p[0] / k + wx, p[1] / k + wy]
        dev_per_css = out['canvas'][0] / out['cssWidth']
        px = dev_per_css / k
        result, worst = [], {'apex': 0, 'tangent': 0, 'stroke': 0, 'half': 0, 'alpha': 0}
        start = 0
        for tid, n in zip(rec['drawn'], rec['chevrons']):
            run, start = paths[start:start + n], start + n
            exp = self.expected(tid, level)
            layout = chevron_layout(exp['curve'], exp['tangent'], exp['target'], px)
            self.assertEqual(n, len(layout), tid)
            self.assertEqual(n, math.floor(exp['target'] / (GAP_PX * px) + 1e-6) + 1, tid)
            chevrons = []
            for p, e in zip(run, layout):
                self.assertEqual((p['kinds'], p['op'], p['style'], p['shadow'], p['cap'], p['join'], p['composite']),
                                 (['M', 'L', 'L'], 'stroke', COLOR, COLOR, 'round', 'round', 'source-over'))
                self.assertAlmostEqual(p['blur'], GLOW_PX * dev_per_css, places=6)
                a1, apex, a2 = p['points']
                base = lerp(a1, a2, .5)
                u = unit([apex[0] - base[0], apex[1] - base[1]])
                # Arms at apex - h u +- h n: each arm is h * sqrt(2) long, the base h behind the apex
                half = math.dist(apex, base) / dev_per_css
                spread = math.dist(a1, a2) / 2 / dev_per_css
                stroke = p['width'] / dev_per_css
                errs = {'apex': math.dist(world(apex), e['apex']), 'tangent': math.dist(u, e['u']),
                        'stroke': abs(stroke - e['stroke']), 'half': max(abs(half - e['half']), abs(spread - e['half'])),
                        'alpha': abs(p['alpha'] - e['alpha'])}
                self.assertLess(errs['apex'], DEVICE_EPS / k, tid)
                self.assertLess(errs['tangent'], 1e-3, tid)
                self.assertLess(errs['stroke'], 1e-4, tid)
                self.assertLess(errs['half'], 1e-3, tid)
                self.assertLess(errs['alpha'], 1e-6, tid)
                worst = {key: max(worst[key], v) for key, v in errs.items()}
                chevrons.append({'apexWorld': world(apex), 'tangent': u, 'halfPx': half, 'strokePx': stroke, 'alpha': p['alpha']})
            tip = chevrons[-1]['apexWorld']
            self.assertLess(math.dist(tip, exp['curve'][3]), DEVICE_EPS / k)
            self.assertLess(math.dist(chevrons[-1]['tangent'], exp['tangent']), 1e-3)
            # The run spans (n - 1) gaps of arc; consecutive apex chords never exceed the gap
            span = sum(math.dist(chevrons[i]['apexWorld'], chevrons[i + 1]['apexWorld']) for i in range(n - 1))
            self.assertLessEqual(span, (n - 1) * GAP_PX * px + n * DEVICE_EPS / k)
            device = [q for p in run for q in p['points']]
            result.append({'id': tid, 'tipWorld': tip, 'tangent': chevrons[-1]['tangent'], 'count': n, 'gapWorld': GAP_PX * px,
                           'expected': exp, 'chevrons': chevrons, 'firstHalfPx': chevrons[0]['halfPx'],
                           'lastHalfPx': chevrons[-1]['halfPx'], 'firstStrokePx': chevrons[0]['strokePx'],
                           'lastStrokePx': chevrons[-1]['strokePx'], 'firstAlpha': chevrons[0]['alpha'],
                           'lastAlpha': chevrons[-1]['alpha'], 'runChordLength': span, 'device': device})
        return result, worst

    def test_01_all_guides_loaded_and_drawn_match_metadata(self):
        page = self.open(self.js)
        info = self.setup(page)
        loaded = page.evaluate('() => ({layoutId: floors[0].level.layoutId, transfers: floors[0].level.svgFormat.transfers,'
                               ' arrows: routeArrowsFor(floors[0].level).map(a => ({id: a.id, curve: a.curve, tangent: a.tangent,'
                               ' gap: a.gap, length: a.length, target: a.target, t: a.t}))})')
        self.assertEqual(loaded['layoutId'], 'extended-mountain-v18')
        meas = json.loads((ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json').read_text())
        self.assertEqual(len(self.level['svgFormat']['fragments']), len(meas['fragments']))
        self.assertEqual(loaded['transfers'], self.level['svgFormat']['transfers'])
        self.assertEqual(len(loaded['arrows']), len(meas['encounters']))
        for a in loaded['arrows']:
            exp = self.expected(a['id'])
            self.assertLess(max(math.dist(p, q) for p, q in zip(a['curve'], exp['curve'])), 1e-9)
            self.assertLess(math.dist(a['tangent'], exp['tangent']), 1e-9)
            for key, py in (('gap', 'G'), ('length', 'L'), ('target', 'target')):
                self.assertLess(abs(a[key] - exp[py]), 1e-6, (a['id'], key))
            self.assertLess(abs(a['t'] - exp['t']), 1e-9)
        # Whole level in one frame: every guide drawn.
        wx, wy, k = self.overview(info)
        out = self.frame(page, wx, wy, k)
        self.assertEqual(sorted(out['rec']['drawn']), sorted(self.guides))
        overview, worst = self.arrows(out, wx, wy, k, info)
        self.assertEqual(len(overview), len(meas['encounters']))
        loaded_by = {a['id']: a for a in loaded['arrows']}
        lengths = {}
        for a in overview:
            exp = a['expected']
            # The drawn tip chevron, from the recorded draw calls, against the SVG-side endpoint; its arc
            # positions were checked against the SVG-side sub-curve and target by arrows().
            self.assertLess(math.dist(a['tipWorld'], exp['endpoint']), WORLD_TOL, a['id'])
            lengths[a['id']] = {'runtimeG': loaded_by[a['id']]['gap'], 'runtimeL': loaded_by[a['id']]['length'],
                                'runtimeTarget': loaded_by[a['id']]['target'], 'runtimeT': loaded_by[a['id']]['t'],
                                'svgG': exp['G'], 'svgL': exp['L'], 'svgTarget': exp['target'], 'svgT': exp['t'],
                                'chevrons': a['count'], 'gapWorld': a['gapWorld'], 'runChordLength': a['runChordLength'],
                                'drawnEndpoint': a['tipWorld'], 'svgEndpoint': exp['endpoint'],
                                'endpointError': math.dist(a['tipWorld'], exp['endpoint']), 'lastHalfPx': a['lastHalfPx']}
        self.evidence['lengths'] = {'shipped': lengths}
        self.evidence['cases']['allGuides'] = {
            'fragments': len(self.level['svgFormat']['fragments']), 'loadedTransfers': len(loaded['transfers']),
            'loadedGuides': sum('guide' in t for t in loaded['transfers']), 'runtimeArrows': len(loaded['arrows']),
            'loadedEqualsImported': True, 'overviewCamera': {'wx': wx, 'wy': wy, 'k': k}, 'drawn': len(overview),
            'worstError': worst, 'arrows': [{'id': a['id'], 'guide': self.guides[a['id']], 'expected': a['expected'],
                                             'drawnChevronsWorld': [c['apexWorld'] for c in a['chevrons']], 'drawnTangent': a['tangent'],
                                             'lastStrokePx': a['lastStrokePx'], 'lastHalfPx': a['lastHalfPx']} for a in overview]}

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
        # The same guide ends at the same world tip under every camera, with the same screen sizes; the
        # chevron spacing is in screen px, so a closer zoom puts more chevrons on the same world curve.
        base = frames['normal']['arrows']['T09']
        comparison = {}
        for name, f in frames.items():
            a = f['arrows']['T09']
            d = math.dist(a['tipWorld'], base['tipWorld'])
            self.assertLess(d, DEVICE_EPS / f['camera']['k'] + DEVICE_EPS / k0)
            self.assertAlmostEqual(a['firstStrokePx'], STROKE_PX[0] if a['count'] > 1 else STROKE_PX[1], delta=1e-4)
            self.assertAlmostEqual(a['lastStrokePx'], STROKE_PX[1], delta=1e-4)
            self.assertAlmostEqual(a['firstHalfPx'], HALF_PX[0] if a['count'] > 1 else HALF_PX[1], delta=1e-3)
            self.assertAlmostEqual(a['lastHalfPx'], HALF_PX[1], delta=1e-3)
            comparison[name] = {'worldDeltaVsNormal': d, 'count': a['count'], 'firstHalfPx': a['firstHalfPx'],
                                'lastHalfPx': a['lastHalfPx'], 'firstStrokePx': a['firstStrokePx'], 'lastStrokePx': a['lastStrokePx'],
                                'tipDevice': a['device'][-2], 'gapWorld': a['gapWorld'],
                                'lastHalfWorld': HALF_PX[1] / f['camera']['screenPxPerWorld']}
        tx = [comparison['translated']['tipDevice'][i] - comparison['normal']['tipDevice'][i] for i in (0, 1)]
        self.assertAlmostEqual(tx[0], -137.5 * k0, delta=2 * DEVICE_EPS)
        self.assertAlmostEqual(tx[1], 91.25 * k0, delta=2 * DEVICE_EPS)
        self.assertNotAlmostEqual(comparison['zoom1.6']['lastHalfWorld'], comparison['normal']['lastHalfWorld'])
        self.assertGreater(comparison['zoom1.6']['count'], comparison['zoom0.6']['count'])
        for f in frames.values():
            f['arrows'] = {t: {k: v for k, v in a.items() if k in ('tipWorld', 'tangent', 'count', 'firstHalfPx', 'lastHalfPx',
                                                                   'firstStrokePx', 'lastStrokePx', 'firstAlpha', 'lastAlpha')}
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
        on = [p for p in a['device'] if 0 <= p[0] < info['canvas'][0] and 0 <= p[1] < info['canvas'][1]]
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
            pts = arrow['device']
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
        # drawn over it, the 0.95 cyan tip chevron would move it far more.
        under_delta = max(delta(under_on, under_off, d) for d in near)
        # TASK-712: the 0.95 tip chevron (was a 0.4 head, bound 4) shows through by up to 0.95 / 0.4 * 4 levels.
        self.assertLessEqual(under_delta, 10)
        # Without the player there, the same pixels show the arrow head.
        page.evaluate('() => { ninja.x += 3000 }')
        away_on = image(page.evaluate(SHOT, [wx, wy, kz, False]))
        away_off = image(page.evaluate(SHOT, [wx, wy, kz, True]))
        away_delta = max(delta(away_on, away_off, d) for d in near)
        self.assertGreaterEqual(away_delta, 20)
        self.assertLess(4 * under_delta, away_delta)
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
        self.assertEqual(state, {'layoutId': 'extended-mountain-v18', 'guides': 0, 'arrows': 0})
        out = self.frame(page, wx, wy, k)
        self.assertEqual((out['rec']['drawn'], out['rec']['paths']), ([], []))
        partial = import_svg(guided_svg({'T01', 'T09', 'T17'}).encode())
        page2 = self.open(leveldata(partial))
        self.setup(page2)
        out2 = self.frame(page2, wx, wy, k)
        self.assertEqual(sorted(out2['rec']['drawn']), ['T01', 'T09', 'T17'])
        self.assertEqual(len(out2['rec']['paths']), sum(out2['rec']['chevrons']))
        self.assertEqual(len(out2['rec']['chevrons']), 3)
        # A legacy level object with no svgFormat at all draws nothing and throws nothing.
        legacy = page2.evaluate('() => { const l = {...floors[0].level}; delete l.svgFormat; return routeArrowsFor(l).length }')
        self.assertEqual(legacy, 0)
        self.evidence['cases']['absentMetadata'] = {'shipped': dict(state, drawn=out['rec']['drawn'], drawCalls=len(out['rec']['paths'])),
                                                   'partial': {'guided': ['T01', 'T09', 'T17'], 'drawn': out2['rec']['drawn'],
                                                               'drawCalls': len(out2['rec']['paths'])},
                                                   'noSvgFormatArrows': legacy}

    def test_05_collections_save_state_and_physics_unchanged(self):
        # Shipped guides with the distance-based renderer, no guides, and the shipped guides with the
        # pre-TASK-671 t=0.25 renderer (git HEAD~ version of render/routearrows.js, recorded by hash).
        import subprocess
        old_js = subprocess.run(['git', 'show', 'HEAD:render/routearrows.js'], cwd=ROOT, check=True, capture_output=True, text=True).stdout
        if 'ROUTE_ARROWS.t' not in old_js and 't: 0.25' not in old_js:
            old_js = subprocess.run(['git', 'show', '6c7fcc0:render/routearrows.js'], cwd=ROOT, check=True, capture_output=True, text=True).stdout
        self.assertIn('t: 0.25', old_js)
        pages = {'guidedDistanceArrows': self.open(self.js), 'noGuides': self.open(self.plain_js),
                 'guidedOldFixedTArrows': self.open(self.js, old_js)}
        for p in pages.values():
            p.evaluate(FREEZE_RESTART)
        names = list(pages)
        worlds = [pages[n].evaluate(WORLD) for n in names]
        for key in ('elements', 'dragZones', 'byId', 'grappleGroups', 'movers', 'floors', 'saveSchema', 'save',
                    'worldKeys', 'ninjaKeys', 'grapnelKeys', 'storageKeys'):
            for w in worlds[1:]:
                self.assertEqual(worlds[0][key], w[key], key)
        self.assertNotIn('guide', json.dumps(worlds[0]['save']))
        all_traces = [pages[n].evaluate(TRACE) for n in names]
        for tr in all_traces[2:]:
            self.assertEqual(all_traces[0]['trace'], tr['trace'])
            self.assertEqual(all_traces[0]['save'], tr['save'])
        traces = all_traces[:2]
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
        self.evidence['physics'] = {
            'cases': names, 'oldRenderer': {'source': 'git show of render/routearrows.js before TASK-671', 'sha256': sha(old_js)},
            'collectionsEqual': {k: True for k in ('elements', 'dragZones', 'byId', 'grappleGroups', 'movers', 'floors',
                                                   'saveSchema', 'save', 'worldKeys', 'ninjaKeys', 'grapnelKeys', 'storageKeys')},
            'collisionRoleSha256': {n: sha(json.dumps(w['elements'])) for n, w in zip(names, worlds)},
            'dragZoneSha256': {n: sha(json.dumps(w['dragZones'])) for n, w in zip(names, worlds)},
            'elementCount': len(worlds[0]['elements']),
            'traceTicks': len(traces[0]['trace']), 'traceFields': self.evidence['cases']['unchanged']['physics']['fields'],
            'traceSha256': {n: sha(json.dumps(t['trace'])) for n, t in zip(names, all_traces)},
            'finalSaveSha256': {n: sha(json.dumps(t['save'], sort_keys=True)) for n, t in zip(names, all_traces)},
            'tracesIdentical': True, 'grappledTicks': sum(1 for t in traces[0]['trace'] if t[6]), 'playerMovedWorld': moved,
            'arrowsDrawnLastFrame': {n: t['arrowsLastFrame'] for n, t in zip(names, all_traces)}}

    def fixture_frame(self, page, level, wx, wy, k, info):
        out = page.evaluate('a => T659.fixture(...a)', [level, wx, wy, k])
        return out, self.arrows(out, wx, wy, k, info, level)[0]

    def test_06_fixtures_match_svg_and_keep_head_size_across_zooms(self):
        page = self.open(self.js)
        info = self.setup(page)
        level = fixture_level()
        loaded = page.evaluate('l => routeArrowsFor(l).map(a => ({id: a.id, gap: a.gap, length: a.length, target: a.target,'
                               ' t: a.t, curve: a.curve, tangent: a.tangent}))', level)
        self.assertEqual([a['id'] for a in loaded], list(FIXTURES))
        records = {}
        for a in loaded:
            exp = self.expected(a['id'], level)
            self.assertTrue(finite([a['gap'], a['length'], a['target'], a['t'], *a['tangent'], *sum(a['curve'], [])]), a['id'])
            self.assertLess(abs(a['gap'] - exp['G']), 1e-9, a['id'])
            self.assertLess(abs(a['length'] - exp['L']), 1e-6, a['id'])
            self.assertLess(abs(a['target'] - exp['target']), 1e-6, a['id'])
            self.assertLess(abs(a['t'] - exp['t']), 1e-9, a['id'])
            self.assertLess(math.dist(a['curve'][3], exp['endpoint']), 1e-6, a['id'])
            records[a['id']] = {'runtimeG': a['gap'], 'runtimeL': a['length'], 'runtimeTarget': a['target'], 'runtimeT': a['t'],
                                'runtimeEndpoint': a['curve'][3], 'runtimeTangent': a['tangent'], 'svgG': exp['G'],
                                'svgL': exp['L'], 'svgTarget': exp['target'], 'svgT': exp['t'], 'svgEndpoint': exp['endpoint'],
                                'finite': True, 'zooms': {}}
        # Each fixture centred at three zooms: same world tip, same 4 -> 7 px chevrons and 1.6 -> 2.6 px strokes.
        k0 = info['k0']
        for a in loaded:
            g = FIXTURES[a['id']]['guide']
            cx, cy = (min(p[0] for p in g) + max(p[0] for p in g)) / 2, (min(p[1] for p in g) + max(p[1] for p in g)) / 2
            for zoom in (0.6, 1.0, 1.6):
                k = k0 * zoom
                wx, wy = cx - info['canvas'][0] / k / 2, cy - info['canvas'][1] / k / 2
                out, drawn = self.fixture_frame(page, level, wx, wy, k, info)
                self.assertIn(a['id'], out['rec']['drawn'])
                d = {x['id']: x for x in drawn}[a['id']]
                self.assertLess(math.dist(d['tipWorld'], d['expected']['endpoint']), WORLD_TOL, a['id'])
                self.assertTrue(finite(sum((c['apexWorld'] for c in d['chevrons']), []) + d['tipWorld']), a['id'])
                records[a['id']]['zooms'][str(zoom)] = {'k': k, 'chevrons': d['count'], 'drawnEndpoint': d['tipWorld'],
                                                        'firstHalfPx': d['firstHalfPx'], 'lastHalfPx': d['lastHalfPx'],
                                                        'firstStrokePx': d['firstStrokePx'], 'lastStrokePx': d['lastStrokePx']}
        self.evidence.setdefault('lengths', {})['fixtures'] = records
        self.evidence['lengths']['toleranceWorldUnits'] = WORLD_TOL
        heads = [z['lastHalfPx'] for r in records.values() for z in r['zooms'].values()]
        self.assertLess(max(heads) - min(heads), 2e-3)
        self.assertAlmostEqual(heads[0], HALF_PX[1], delta=1e-3)
        self.evidence['cases']['fixtureZooms'] = {'zooms': [0.6, 1.0, 1.6], 'lastHalfPxRange': [min(heads), max(heads)]}

    def test_07_arrows_png_short_and_long_at_matched_zoom(self):
        from PIL import Image, ImageDraw
        page = self.open(self.js)
        info = self.setup(page)
        k0 = info['k0']
        # Fixtures short, long, curved and capped, each in its own frame at one matched zoom k.
        names = ['short', 'long', 'curved', 'capped']
        k = 0.5 * k0
        tiles, drawn_by = [], {}
        for n in names:
            level = fixture_level()
            level['svgFormat']['transfers'] = [t for t in level['svgFormat']['transfers'] if t['id'] == n]
            level['elements'] = [e for e in level['elements'] if e['id'].startswith(n + '-')]
            pts = [p for poly in FIXTURES[n]['from'] + FIXTURES[n]['to'] for p in poly] + list(FIXTURES[n]['guide'])
            x0, y0, x1, y1 = box(pts)
            wx, wy = (x0 + x1) / 2 - info['canvas'][0] / k / 2, (y0 + y1) / 2 - info['canvas'][1] / k / 2
            out, drawn = self.fixture_frame(page, level, wx, wy, k, info)
            self.assertEqual(out['rec']['drawn'], [n])
            drawn_by[n] = drawn[0]
            shot = image(page.evaluate('() => canvas.toDataURL("image/png")'))
            pad = 30
            tiles.append((n, shot.crop((max(0, int((x0 - wx) * k) - pad), max(0, int((y0 - wy) * k) - pad),
                                        min(shot.width, int((x1 - wx) * k) + pad), min(shot.height, int((y1 - wy) * k) + pad)))))
        by = drawn_by
        heads = {n: (by[n]['lastHalfPx'], by[n]['lastStrokePx']) for n in names}
        self.assertLess(max(h[0] for h in heads.values()) - min(h[0] for h in heads.values()), 2e-3)
        self.assertGreater(by['long']['expected']['target'], 10 * by['short']['expected']['target'])
        self.assertGreater(by['long']['count'], by['short']['count'])
        # Shipped level: its shortest and longest shafts in production frames at the game zoom.
        lengths = {a['id']: a['target'] for a in page.evaluate('() => routeArrowsFor(floors[0].level).map(a => ({id: a.id, target: a.target}))')}
        short, long_ = min(lengths, key=lengths.get), max(lengths, key=lengths.get)
        crops, game = [], {}
        for tid in (short, long_):
            exp = self.expected(tid)
            mid = cubic(exp['curve'], .5)
            gx, gy = mid[0] - info['canvas'][0] / k0 / 2, mid[1] - info['canvas'][1] / k0 / 2
            shot = image(page.evaluate(SHOT, [gx, gy, k0, False]))
            fo = self.frame(page, gx, gy, k0)
            a = {x['id']: x for x in self.arrows(fo, gx, gy, k0, info)[0]}[tid]
            game[tid] = {'target': exp['target'], 'chevrons': a['count'], 'lastHalfPx': a['lastHalfPx'],
                         'lastStrokePx': a['lastStrokePx'], 'k': k0}
            x0, y0, x1, y1 = box(a['device'])
            pad = 40
            crops.append((tid, shot.crop((max(0, int(x0) - pad), max(0, int(y0) - pad),
                                          min(shot.width, int(x1) + pad), min(shot.height, int(y1) + pad)))))
        self.assertLess(abs(game[short]['lastHalfPx'] - game[long_]['lastHalfPx']), 2e-3)
        self.assertGreater(game[long_]['target'], 2 * game[short]['target'])
        self.assertGreater(game[long_]['chevrons'], game[short]['chevrons'])
        rows = [[(n, c, '%s: G=%.0f run=%.0fu %d chevrons, tip %.2fpx (k=%.4f)' % (n, by[n]['expected']['G'], by[n]['expected']['target'],
                                                                                  by[n]['count'], heads[n][0], k)) for n, c in tiles],
                [(tid, c, 'game %s: %s run=%.0fu %d chevrons, tip %.2fpx (k=%.4f)' % ('shortest' if tid == short else 'longest', tid,
                                                                                    game[tid]['target'], game[tid]['chevrons'],
                                                                                    game[tid]['lastHalfPx'], k0)) for tid, c in crops]]
        widths = [sum(max(c.width, 8 * len(t)) + 16 for _, c, t in r) for r in rows]
        heights = [max(c.height for _, c, _ in r) + 30 for r in rows]
        sheet = Image.new('RGB', (max(widths) + 16, sum(heights) + 40), (12, 12, 16))
        dr = ImageDraw.Draw(sheet)
        dr.text((8, 6), 'Distance-based chevron runs: run = min(0.5 G, L); one chevron per 16 CSS px, 4 -> 7 px at any zoom', fill=(240, 240, 240))
        y = 28
        for r, h in zip(rows, heights):
            x = 8
            for _, c, t in r:
                dr.text((x, y), t, fill=(230, 230, 230))
                sheet.paste(c, (x, y + 18))
                x += max(c.width, 8 * len(t)) + 16
            y += h
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            sheet.save(Path(EVIDENCE, 'arrows.png'))
        self.evidence['cases']['arrowsPng'] = {
            'fixtureZoomK': k, 'fixtureHeadsPx': heads,
            'fixtureChevrons': {n: by[n]['count'] for n in names},
            'fixtureTargets': {n: by[n]['expected']['target'] for n in names},
            'gameShortest': short, 'gameLongest': long_, 'game': game}

    def test_08_culling_and_cache_reuse(self):
        page = self.open(self.js)
        info = self.setup(page)
        before = page.evaluate('() => ({builds: ROUTE_ARROWS.builds, same: routeArrowsFor(floors[0].level) === routeArrowsFor(floors[0].level)})')
        self.assertTrue(before['same'])
        k0 = info['k0']
        culled = {}
        for zoom in (0.6, 1.0, 1.6):
            k = k0 * zoom
            for tid in ('T01', 'T25'):
                exp = self.expected(tid)
                tip = exp['curve'][3]
                wx, wy = tip[0] - info['canvas'][0] / k / 2, tip[1] - info['canvas'][1] / k / 2
                out = self.frame(page, wx, wy, k)
                view = [wx, wy, wx + info['canvas'][0] / k, wy + info['canvas'][1] / k]
                must = sorted(t for t in self.guides if overlaps(box(self.expected(t)['curve']), view))
                far = [t for t in self.guides if not overlaps(box(self.expected(t)['curve']),
                                                               [view[0] - 3000, view[1] - 3000, view[2] + 3000, view[3] + 3000])]
                drawn = out['rec']['drawn']
                self.assertIn(tid, drawn)
                self.assertTrue(set(must) <= set(drawn), (zoom, tid))
                self.assertFalse(set(far) & set(drawn), (zoom, tid))
                self.assertGreater(len(far), 0)
                culled['%s@%s' % (tid, zoom)] = {'drawn': len(drawn), 'mustDraw': len(must), 'farCulled': len(far)}
        after = page.evaluate('() => ({builds: ROUTE_ARROWS.builds, same: routeArrowsFor(floors[0].level) === routeArrowsFor(floors[0].level)})')
        self.assertEqual(after['builds'], before['builds'])
        # Chevron layouts are kept with the arrow: repeated frames at one zoom compute none.
        tip = self.expected('T09')['curve'][3]
        wx, wy = tip[0] - info['canvas'][0] / k0 / 2, tip[1] - info['canvas'][1] / k0 / 2
        self.frame(page, wx, wy, k0)
        layouts = page.evaluate('() => ROUTE_ARROWS.layouts')
        for _ in range(5):
            self.frame(page, wx, wy, k0)
        self.assertEqual(page.evaluate('() => ROUTE_ARROWS.layouts'), layouts)
        # A different level object is computed once, then reused.
        fresh = page.evaluate('l => { const b = ROUTE_ARROWS.builds; const a = routeArrowsFor(l); routeArrowsFor(l);'
                              ' return {added: ROUTE_ARROWS.builds - b, same: a === routeArrowsFor(l)} }', fixture_level())
        self.assertEqual(fresh, {'added': 1, 'same': True})
        self.evidence['cases']['cullingAndCache'] = {'frames': len(culled), 'culling': culled, 'buildsBefore': before['builds'],
                                                    'buildsAfterFrames': after['builds'], 'cacheIdentity': True,
                                                    'newLevelBuildsOnce': fresh, 'chevronLayoutsReusedOver5Frames': True}

    def test_09_zero_browser_errors(self):
        page = self.open(self.js)
        page.evaluate('() => new Promise(r => setTimeout(r, 1500))')
        self.assertEqual(self.errors, [])
        self.evidence['cases']['browserErrors'] = {'count': len(self.errors), 'errors': self.errors}


if __name__ == '__main__':
    unittest.main()
