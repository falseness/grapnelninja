"""TASK-674: purple no-grapple zone presentation.

Boots the real index.html in Grapple Over, stops the frame loop and loads a
small fixture level (the shipped level has no zones yet) with two purple
zones, a far-away zone for culling, solid and bounce panels, a yellow drag
zone and one route-arrow transfer whose guide crosses a zone. Frames are the
production draw() of that state:

- render/nograpplezones.js draws the zones first in the world layer, under
  the route arrows, the rope, the panels and the player (call order, and
  pixels of opaque panels and the player unchanged by the zones);
- the wash is translucent (base fill alpha from STYLE.colors.noGrapple.fill,
  measured from the pixels between lattice lines), adds no yellow and changes
  nothing outside the zones and their edge/bracket margin;
- Ion lattice (TASK-782): a frame is a pure function of world.elapsedSteps and
  the camera (sha of two renders), the pulse changes pixels inside a zone and
  none outside, and the hex lattice period in device px scales with the camera
  scale (world-unit hexes);
- zones are culled by their own box (only visible ones are drawn) and a level
  without zones draws nothing;
- zones stay pass-through: not in elements or dragZones, no drag motes, and a
  fall through a zone keeps the trajectory of the same level without zones;
- the tutorial legend (render/tutorialhint.js) adds '= NO GRAPPLE' /
  '= БЕЗ ЗАЦЕПА' after the unchanged bounce and drag entries, inside the
  desktop and touch views, and follows the hint's lifecycle.

NO_GRAPPLE_EVIDENCE_DIR=DIR writes purple-desktop.png and purple-touch.png
(top: English, rope crossing a zone; bottom: Russian, the player inside a
zone after its rope was dropped) and presentation.json.

    python3 -m unittest discover -s tools -p test_no_grapple_render.py -v
"""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import unittest

from PIL import Image

from browser_test_support import start_browser_test, wait_for_boot

ROOT = Path(__file__).resolve().parent.parent
BASE_COMMIT = '54305c2'  # before TASK-674: the legend entries it must keep
SOURCES = ('render/nograpplezones.js', 'render/draw.js', 'render/tutorialhint.js', 'style.js', 'i18n.js',
           'index.html', 'fixedlevel.js', 'tools/test_no_grapple_render.py')
VIEWPORTS = {'desktop': dict(viewport={'width': 1280, 'height': 720}, device_scale_factor=1),
             'touch': dict(viewport={'width': 844, 'height': 390}, device_scale_factor=2,
                           is_mobile=True, has_touch=True)}
LEGEND = {'en': ['BOUNCE', 'LOSE SPEED', 'NO GRAPPLE'], 'ru': ['ОТСКОК', 'ЗАМЕДЛЕНИЕ', 'БЕЗ ЗАЦЕПА']}

# Fixture scene in fractions of the view (world units = view * W/H, camera at 0, 0)
SCENE = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    menu.unPause()
    // Frozen wall clock: animated motes stay put between compared frames
    const now = performance.now(), date = Date.now()
    performance.now = () => now
    Date.now = () => date
    const W = width / scale[version], H = height / scale[version]
    const r = ninja.radius
    const rect = (id, fx, fy, fw, fh, role) => ({id, x: fx * W, y: fy * H, role,
        grapplable: role === 'solid' || role === 'bounce',
        points: [{x: 0, y: 0}, {x: fw * W, y: 0}, {x: fw * W, y: fh * H}, {x: 0, y: fh * H}]})
    const els = [rect('zoneA', 0.06, 0.08, 0.34, 0.42, 'no-grapple'), rect('zoneB', 0.58, 0.06, 0.36, 0.30, 'no-grapple'),
        rect('zoneFar', 6, 0.1, 0.3, 0.3, 'no-grapple'),
        rect('P1', 0.22, 0.14, 0.12, 0.05, 'solid'), rect('P2', 0.03, 0.62, 0.10, 0.05, 'bounce'),
        rect('P3', 0.52, 0.20, 0.16, 0.05, 'bounce'), rect('D1', 0.70, 0.44, 0.22, 0.06, 'drag')]
    const d = structuredClone(GRAPPLE_OVER_LEVEL)
    d.bounds = {left: -5 * W, top: -5 * H, right: 12 * W, bottom: 8 * H}
    d.spawn = {x: 0.5 * W, y: 4 * H}
    d.finish = null
    d.elements = els
    d.encounters = [{id: 'E1', elements: els.map(e => e.id)}]
    d.sections = [{id: 'SEC-fixture', encounters: ['E1']}]
    d.movers = []
    const p1 = els[3], p2 = els[4]
    d.svgFormat = {version: 1, grappleRange: 540,
        fragments: [{id: 'F1', elements: ['P1']}, {id: 'F2', elements: ['P2']}],
        transfers: [{id: 'T1', from: 'F2', to: 'F1', encounter: 'E1', guide: [
            [p2.x + 0.05 * W, p2.y - r], [0.10 * W, 0.30 * H], [0.20 * W, 0.24 * H], [p1.x + 0.06 * W, p1.y + 0.05 * H]]}]}
    floors = [loadFixedLevel(d)]
    screen.leftWall = null
    screen.x = 0; screen.y = 0
    window.PG = {W, H, d,
        // device px of a world point (no rotation: k from the canvas backing store)
        dev(x, y) { const k = canvas.width / width * scale[version]
            return [Math.round((x + screen.x) * k), Math.round((y + screen.y) * k)] },
        pixel(x, y) { const [px, py] = PG.dev(x, y)
            return Array.from(ctx.getImageData(px, py, 1, 1).data) },
        frame() { PG.base(); draw(); PG.base() },
        // The game's base transform (gameoptions.js)
        base() { ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0) },
        image() { return ctx.getImageData(0, 0, canvas.width, canvas.height).data },
        ropeScene() {
            ninja.x = 0.06 * W - r - 1.5; ninja.y = 0.40 * H; ninja.speedX = ninja.speedY = 0
            ninja.track.pos = []
            const e = floors[0].byId.get('P1')
            Object.assign(grapnel, {throwed: true, grappled: true, shotStep: null, aim: null, clip: null,
                traveled: 0, pos: [[e.x + 0.06 * W, e.y + 0.05 * H, e]]})
            floors[0].applyNoGrappleZones(ninja)
            screen.x = 0; screen.y = 0
            return {inside: floors[0].playerInNoGrapple, attached: grapnel.grappled}
        },
        insideScene() {
            PG.ropeScene()
            ninja.x = 0.14 * W; ninja.y = 0.36 * H
            ninja.track.pos = []
            floors[0].applyNoGrappleZones(ninja)
            screen.x = 0; screen.y = 0
            return {inside: floors[0].playerInNoGrapple, attached: grapnel.grappled, thrown: grapnel.throwed}
        },
        // Frame with the zones hidden from the renderer only
        withoutZones(fn) { const w = floors[0], z = w.noGrappleZones
            w.noGrappleZones = []
            try { return fn() } finally { w.noGrappleZones = z } }
    }
    return {W, H, zones: floors[0].noGrappleZones.map(z => z.id), elements: floors[0].elements.map(e => e.id),
        dragZones: floors[0].dragZones.map(z => z.id), radius: r, scale: scale[version],
        canvas: [canvas.width, canvas.height]}
}'''

# Draw order of one production frame
ORDER = '''() => {
    const log = [], wrap = (obj, name, label) => { const f = obj[name]
        obj[name] = function(...a) { log.push(label); return f.apply(this, a) }
        return () => { obj[name] = f } }
    const undo = [wrap(window, 'drawNoGrappleZones', 'noGrappleZones'), wrap(window, 'drawRouteArrows', 'routeArrows'),
        wrap(grapnel, 'draw', 'rope'), wrap(floors[0], 'draw', 'panels'),
        wrap(window, 'drawGrappleOverRoleDetail', 'roleDetail'), wrap(ninja, 'draw', 'player'),
        wrap(TUTORIAL_HINT, 'draw', 'tutorialHint')]
    try { PG.frame() } finally { undo.reverse().forEach(u => u()); delete ninja.draw; delete floors[0].draw; delete grapnel.draw }
    return {order: log, drawn: NO_GRAPPLE_ZONES.drawn.slice(), arrows: ROUTE_ARROWS.drawn.slice(),
        dragCount: ROLE_DETAIL.frame && ROLE_DETAIL.frame.counts.drag}
}'''

# Pixel comparison of the same state with and without the zones: changed
# pixels inside / outside the zone boxes, and their colour shift
DIFF = '''(pad) => {
    const W = canvas.width, H = canvas.height
    const boxes = floors[0].noGrappleZones.map(z => { const b = getElementCullBox(z)
        const a = PG.dev(b.left, b.top), c = PG.dev(b.right, b.bottom)
        return [a[0] - pad, a[1] - pad, c[0] + pad, c[1] + pad] })
    PG.frame(); const again = PG.image()
    PG.frame(); const zoned = PG.image()
    const plain = PG.withoutZones(() => { PG.frame(); return PG.image() })
    let changedIn = 0, changedOut = 0, unstable = 0, yellowShift = 0, sum = [0, 0, 0], maxOut = 0
    for (let y = 0; y < H; ++y)
        for (let x = 0; x < W; ++x) {
            const i = (y * W + x) * 4
            if (again[i] !== zoned[i] || again[i + 1] !== zoned[i + 1] || again[i + 2] !== zoned[i + 2]) ++unstable
            const dr = zoned[i] - plain[i], dg = zoned[i + 1] - plain[i + 1], db = zoned[i + 2] - plain[i + 2]
            if (!dr && !dg && !db) continue
            const inside = boxes.some(b => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3])
            if (!inside) { ++changedOut; maxOut = Math.max(maxOut, Math.abs(dr), Math.abs(dg), Math.abs(db)); continue }
            ++changedIn; sum[0] += dr; sum[1] += dg; sum[2] += db
            if (dr > 2 && dg > 2 && db < -2) ++yellowShift
        }
    return {changedIn, changedOut, maxOut, unstable, yellowShift, meanShift: sum.map(s => changedIn ? +(s / changedIn).toFixed(2) : 0),
        boxes}
}'''

# TASK-782: sha-256 of the canvas at given elapsedSteps and camera, and the pixels a
# change of elapsedSteps changes inside / outside the zone boxes (pad in device px).
# Other layers also run on elapsedSteps (role detail, drag motes), so outside the
# boxes each zoned frame is compared with the same step without zones: zoneOut counts
# outside pixels where a zoned frame differs from its plain twin (expected 0), and
# changedOut those the step change moves in zoned frames but not in plain ones.
PULSE = '''async ([s1, s2, pad]) => {
    const W = canvas.width, H = canvas.height, world = floors[0]
    const boxes = world.noGrappleZones.map(z => { const b = getElementCullBox(z)
        const a = PG.dev(b.left, b.top), c = PG.dev(b.right, b.bottom)
        return [a[0] - pad, a[1] - pad, c[0] + pad, c[1] + pad] })
    const at = async steps => { world.elapsedSteps = steps; PG.frame(); const img = PG.image()
        const sha = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', img)), b => b.toString(16).padStart(2, '0')).join('')
        return {img, sha} }
    const steps0 = world.elapsedSteps
    const a = await at(s1), b = await at(s2), again = await at(s1)
    const pa = PG.withoutZones(() => { world.elapsedSteps = s1; PG.frame(); return PG.image() })
    const pb = PG.withoutZones(() => { world.elapsedSteps = s2; PG.frame(); return PG.image() })
    world.elapsedSteps = steps0
    const same = (u, v, i) => u[i] === v[i] && u[i + 1] === v[i + 1] && u[i + 2] === v[i + 2]
    let changedIn = 0, changedOut = 0, zoneOut = 0, otherLayersOut = 0
    for (let y = 0; y < H; ++y)
        for (let x = 0; x < W; ++x) {
            const i = (y * W + x) * 4
            if (boxes.some(q => x >= q[0] && x <= q[2] && y >= q[1] && y <= q[3])) {
                if (!same(a.img, b.img, i)) ++changedIn
                continue
            }
            if (!same(a.img, pa, i) || !same(b.img, pb, i)) ++zoneOut
            const moved = !same(a.img, b.img, i), plainMoved = !same(pa, pb, i)
            if (moved && !plainMoved) ++changedOut
            if (plainMoved) ++otherLayersOut
        }
    return {s1, s2, sha1: a.sha, sha1Again: again.sha, sha2: b.sha, changedIn, changedOut, zoneOut, otherLayersOut}
}'''

# Simulated steps that put the pulse centre at u = p . dir of a zone's centre (+ du)
PULSE_STEPS = '''([id, du]) => { const c = STYLE.colors.noGrapple, d = c.pulseDirection, l = Math.hypot(d[0], d[1])
    const b = getElementCullBox(floors[0].byId.get(id) || floors[0].noGrappleZones.find(z => z.id === id))
    const u = (((b.left + b.right) / 2 * d[0] + (b.top + b.bottom) / 2 * d[1]) / l + du) % c.pulsePeriodWorld
    return Math.round((u + c.pulsePeriodWorld) % c.pulsePeriodWorld / c.pulseSpeed * 1000 / (physicsStepMs / cyclesPerTick)) }'''

# Zone-only luminance (zoned - plain) of rows across zoneA's interior at camera scale s
LATTICE_ROWS = '''([s, steps]) => { const s0 = scale[version], world = floors[0], st0 = world.elapsedSteps
    scale[version] = s; screen.x = 0; screen.y = 0; world.elapsedSteps = steps
    try {
        const z = world.noGrappleZones.find(z => z.id === 'zoneA'), b = getElementCullBox(z), m = STYLE.colors.noGrapple.glowWorld * 1.2
        const a = PG.dev(b.left + m, (b.top + b.bottom) / 2), c = PG.dev(b.right - m, (b.top + b.bottom) / 2)
        const rows = Math.round(3 * STYLE.colors.noGrapple.hexRadius * s * canvas.width / width)
        PG.frame(); const zoned = ctx.getImageData(a[0], a[1], c[0] - a[0], rows).data
        const plain = PG.withoutZones(() => { PG.frame(); return ctx.getImageData(a[0], a[1], c[0] - a[0], rows).data })
        const lum = d => { const out = []; for (let i = 0; i < d.length; i += 4) out.push(0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]); return out }
        const zl = lum(zoned), pl = lum(plain)
        return {width: c[0] - a[0], rows, k: canvas.width / width * s, delta: zl.map((v, i) => +(v - pl[i]).toFixed(2))}
    } finally { scale[version] = s0; screen.x = 0; screen.y = 0; world.elapsedSteps = st0; PG.frame() } }'''


def lattice_period(rec):
    """Horizontal period (device px) of the zone-only luminance: the power spectrum summed over
    the rows (each detrended, Hann-windowed and zero-padded to 16384), whose lowest-frequency
    local maximum with >= 25% of the strongest power, above 3 cycles per row, is the
    fundamental (refined by a parabola on log power). The period is rarely a whole pixel."""
    import numpy as np
    w, rows = rec['width'], rec['rows']
    d = np.array(rec['delta'], dtype=float).reshape(rows, w)
    xs = np.arange(w)
    d = np.array([row - np.polyval(np.polyfit(xs, row, 1), xs) for row in d]) * np.hanning(w)
    n = 16384
    power = (np.abs(np.fft.rfft(d, n, axis=1)) ** 2).sum(axis=0)
    lo = int(np.ceil(3 * n / w))
    top = power[lo:].max()
    i = next(i for i in range(lo + 1, len(power) - 1)
             if power[i] >= 0.25 * top and power[i] >= power[i - 1] and power[i] >= power[i + 1])
    y0, y1, y2 = np.log(power[i - 1:i + 2])
    den = y0 - 2 * y1 + y2
    f = (i + (0.5 * (y0 - y2) / den if den else 0)) / n
    return float(1 / f), float(power[i] / top)


# Pixels at named world points with and without the zones
SAMPLES = '''(points) => {
    PG.frame()
    const zoned = Object.fromEntries(Object.entries(points).map(([k, [x, y]]) => [k, PG.pixel(x, y)]))
    const plain = PG.withoutZones(() => { PG.frame()
        return Object.fromEntries(Object.entries(points).map(([k, [x, y]]) => [k, PG.pixel(x, y)])) })
    return {zoned, plain}
}'''

LEGEND_STATE = '''() => { PG.frame()
    const c = ctx.canvas, k = c.width / width, b = menu.constButton
    return {lines: TUTORIAL_HINT.lines, legend: TUTORIAL_HINT.legendBoxes, key: TUTORIAL_HINT.spriteKey,
        canvas: [c.width, c.height], menuButton: {x: b.x * k, y: b.y * k, w: b.width * k, h: b.height * k}}
}'''
SPRITE_PIXEL = '''([x, y]) => Array.from(TUTORIAL_HINT.sprite.getContext('2d').getImageData(Math.round(x), Math.round(y), 1, 1).data)'''


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def overlaps(a, b):
    return a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']


def method_source(text, name):
    """The source of an object-literal method `name(...)` up to its closing brace at 4 spaces."""
    m = re.search(r'\n    ' + name + r'\(.*?\n    \}', text, re.S)
    return m.group(0) if m else None


class NoGrappleRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.out = os.environ.get('NO_GRAPPLE_EVIDENCE_DIR')
        cls.proof = {'revision': git('rev-parse', 'HEAD'),
                     'trackedChangesOutsideArtifacts': len([l for l in git('status', '--porcelain', '--untracked-files=no').splitlines()
                                                            if 'artifacts' not in l]),
                     'sourceHashes': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in SOURCES},
                     'browser': cls.browser.version}

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            Path(cls.out, 'presentation.json').write_text(
                json.dumps(cls.proof, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n')

    def open(self, kind):
        context = self.browser.new_context(locale='en-US', **VIEWPORTS[kind])
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'index.html')
        wait_for_boot(page)
        page.wait_for_function('bootComplete && runInProgress')
        self.assertEqual(page.evaluate('[version, I18N.language, isTouchFirstDevice(), TUTORIAL_HINT.visible]'),
                         ['grapple_over', 'en', kind != 'desktop', True])
        # The shipped level's zones (v16: NG1, NGM, NGU) are far from the spawn view: culled, not drawn
        page.evaluate('draw()')
        shipped = page.evaluate('({zones: floors[0].noGrappleZones.length, drawn: NO_GRAPPLE_ZONES.drawn.length})')
        zones = [e['id'] for e in json.loads((ROOT / 'artifacts' / 'levels' / 'extended-mountain.level.json').read_text())
                 ['elements'] if e['role'] == 'no-grapple']
        self.assertGreaterEqual(len(zones), 1)
        self.assertEqual(shipped, {'zones': len(zones), 'drawn': 0})
        scene = page.evaluate(SCENE)
        self.assertEqual(scene['zones'], ['zoneA', 'zoneB', 'zoneFar'])
        self.assertEqual(scene['dragZones'], ['D1'])
        self.assertEqual(scene['elements'], ['P1', 'P2', 'P3'])
        return page, dict(scene, shippedLevel=shipped)

    def screenshot(self, page):
        return Image.open(io.BytesIO(page.screenshot()))

    def legend(self, page, lang):
        state = page.evaluate(LEGEND_STATE)
        self.assertEqual(state['lines'][3:], LEGEND[lang])
        self.assertTrue(state['key'].startswith(lang + '|grapple_over|'))
        W, H = state['canvas']
        legend = state['legend']
        self.assertEqual([b['label'] for b in legend], LEGEND[lang])
        boxes = []
        for b in legend:
            icon = b['icon']
            text = {'x': b['text']['x'], 'y': icon['y'] + icon['h'] / 2 - H * 0.015, 'w': b['text']['width'], 'h': H * 0.03}
            self.assertGreater(icon['x'], 0)
            self.assertLess(text['x'] + text['w'], W)
            self.assertLessEqual(icon['x'] + icon['w'], text['x'])
            boxes += [icon, text]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(overlaps(a, b), (a, b))
            self.assertFalse(overlaps(a, state['menuButton']), (a, state['menuButton']))
        bounce, drag, purple = (b['icon'] for b in legend)
        self.assertAlmostEqual(bounce['w'] / bounce['h'], 1, places=6)
        self.assertAlmostEqual(drag['w'] / drag['h'], 3.2, places=6)
        # 'Ion lattice' icon (TASK-783), probed at its bottom centre (clear of the
        # label's shadow and the bracket): the faint outer line, the bright edge
        # 0.45 s inside it, the lattice between; the bracket on the top-left
        # corner's left arm
        s = purple['h'] / 2.8
        mid = purple['y'] + purple['h'] / 2
        cx, bottom = purple['x'] + purple['w'] / 2, purple['y'] + purple['h']
        # Strongest of the pixels within 2 px (the 0.25 s stroke is antialiased at touch size)
        edge = max((page.evaluate(SPRITE_PIXEL, [cx, bottom - 0.45 * s + d]) for d in range(-2, 3)),
                   key=lambda p: (p[3], p[2]))
        self.assertTrue(edge[2] > 200 and edge[2] > edge[0] > edge[1] + 30, edge)
        outer = page.evaluate(SPRITE_PIXEL, [cx, bottom - 0.05 * s])
        self.assertTrue(outer[2] > 100 and outer[2] > outer[0] > outer[1] + 30 and outer[3] < edge[3], (outer, edge))
        bracket = page.evaluate(SPRITE_PIXEL, [purple['x'] + 0.15 * s, purple['y'] + 0.6 * s])
        self.assertTrue(min(bracket[:3]) > 200, bracket)
        row = [page.evaluate(SPRITE_PIXEL, [purple['x'] + 0.6 * s + i * (purple['w'] - 1.2 * s) / 40, mid])
               for i in range(41)]
        lattice = max(p[0] for p in row) - min(p[0] for p in row)
        self.assertGreater(lattice, 25, row)
        left, right = boxes[0]['x'], boxes[-1]['x'] + boxes[-1]['w']
        return {'labels': [b['label'] for b in legend], 'canvas': state['canvas'],
                'icons': [{k: round(v, 1) for k, v in b['icon'].items()} for b in legend],
                'textRight': round(right, 1), 'textLeft': round(left, 1), 'insideView': True, 'noOverlap': True,
                'clearOfMenuButton': True, 'noGrappleEdgePixel': edge, 'noGrappleOuterPixel': outer,
                'noGrappleBracketPixel': bracket, 'noGrappleLatticeRedRange': lattice,
                'iconAspect': {'bounce': round(bounce['w'] / bounce['h'], 3), 'drag': round(drag['w'] / drag['h'], 3),
                               'noGrapple': round(purple['w'] / purple['h'], 3)}}

    def run_viewport(self, kind):
        page, scene = self.open(kind)
        W, H, r = scene['W'], scene['H'], scene['radius']
        rec = {'scene': scene}

        # Rope scene: the player just outside zone A, roped to P1 inside it
        self.assertEqual(page.evaluate('PG.ropeScene()'), {'inside': False, 'attached': True})
        order = page.evaluate(ORDER)
        o = order['order']
        self.assertEqual(o[0], 'noGrappleZones', o)
        for later in ('routeArrows', 'rope', 'panels', 'roleDetail', 'player', 'tutorialHint'):
            self.assertIn(later, o)
            self.assertLess(o.index('noGrappleZones'), o.index(later), o)
        self.assertEqual(order['drawn'], ['zoneA', 'zoneB'])          # zoneFar culled
        self.assertEqual(order['arrows'], ['T1'])
        self.assertEqual(order['dragCount'], 1)
        rec['layerOrder'] = order

        # Pixels: opaque panels and the player hide the wash; rope and arrow stand out of it
        p1 = page.evaluate("(() => { const e = floors[0].byId.get('P1'); return [e.x, e.y] })()")
        # Player and rope pixels are measured on frames without the hint's vignette
        page.evaluate('TUTORIAL_HINT.visible = false')
        pts = {'zoneOnly': [0.10 * W, 0.20 * H], 'outside': [0.50 * W, 0.92 * H],
               'panelP1': [p1[0] + 0.03 * W, p1[1] + 0.025 * H],
               'player': page.evaluate('[ninja.x, ninja.y]'),
               'ropeMid': page.evaluate('[(ninja.x + grapnel.pos[0][0]) / 2, (ninja.y + grapnel.pos[0][1]) / 2]')}
        samples = page.evaluate(SAMPLES, pts)
        z, p = samples['zoned'], samples['plain']
        self.assertNotEqual(z['zoneOnly'][:3], p['zoneOnly'][:3])
        self.assertGreater(z['zoneOnly'][2] - p['zoneOnly'][2], z['zoneOnly'][1] - p['zoneOnly'][1])
        self.assertEqual(z['outside'], p['outside'])
        for name in ('panelP1', 'player'):
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(z[name], p[name])), (name, z[name], p[name]))
        # Estimated base-fill alpha from base -> zoned toward the fill colour (least squares over the
        # three channels), the median over interior points past the glow band: most fall between
        # lattice lines where only the base fill covers the backdrop (a lattice line adds to it, a
        # bright mote or panel edge drawn over it takes it toward 0)
        fill = page.evaluate('STYLE.colors.noGrapple.fill')
        m = re.match(r'rgba\((\d+), (\d+), (\d+), ([\d.]+)\)', fill)
        target, alpha = [int(m.group(i)) for i in (1, 2, 3)], float(m.group(4))
        grid = {f'g{i}_{j}': [(0.15 + 0.03 * i) * W, (0.20 + 0.03 * j) * H] for i in range(6) for j in range(6)}
        gs = page.evaluate(SAMPLES, grid)
        def fit(n):
            zc, pc = gs['zoned'][n], gs['plain'][n]
            den = sum((target[c] - pc[c]) ** 2 for c in range(3))
            return sum((zc[c] - pc[c]) * (target[c] - pc[c]) for c in range(3)) / den, den
        # Points covered by an opaque panel, the player or a mote read the same with and without zones
        usable = {n: fit(n)[0] for n in grid if fit(n)[1] >= 40 ** 2 and gs['zoned'][n] != gs['plain'][n]}
        self.assertGreaterEqual(len(usable), 12, gs)
        base = sorted(usable, key=usable.get)[len(usable) // 2]
        bz, bp = gs['zoned'][base], gs['plain'][base]
        est = [usable[base]]
        self.assertTrue(abs(est[0] - alpha) < 0.03, (est, alpha, bz, bp, usable))
        self.assertTrue(0 < alpha < 0.35)
        lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        # Brightest rope pixel near its midpoint against the wash. The Grapple Over helix strands
        # swing up to 6 px off the rope line with a clock-driven phase, so search +-7 screen px.
        near = page.evaluate('''([x, y]) => { PG.frame(); const out = []
            const u = 1 / scale[version]
            for (let dx = -7; dx <= 7; ++dx) for (let dy = -7; dy <= 7; ++dy) out.push(PG.pixel(x + dx * u, y + dy * u)); return out }''', pts['ropeMid'])
        rope_contrast = max(lum(c) for c in near) - lum(z['zoneOnly'])
        self.assertGreater(rope_contrast, 40, (near, z['zoneOnly']))
        rec['pixels'] = {'points': {k: [round(v, 1) for v in xy] for k, xy in pts.items()}, 'zoned': z, 'plain': p,
                         'fill': fill, 'fillAlpha': alpha, 'measuredAlpha': [round(e, 3) for e in est],
                         'baseFillPixel': {'point': base, 'zoned': bz, 'plain': bp, 'usablePoints': len(usable)},
                         'ropeLuminanceContrastOverWash': round(rope_contrast, 1)}
        # Edge, outer line and corner brackets reach bracketGapPx + bracketPx CSS px outside the polygon
        k = page.evaluate('canvas.width / getCanvasCssRect().width')
        pad = int(page.evaluate('STYLE.colors.noGrapple.bracketGapPx + STYLE.colors.noGrapple.bracketPx') * k + 0.999) + 2
        diff = page.evaluate(DIFF, pad)
        self.assertEqual(diff['unstable'], 0, diff)
        self.assertGreater(diff['changedIn'], 1000, diff)
        self.assertEqual(diff['changedOut'], 0, diff)
        self.assertEqual(diff['yellowShift'], 0, diff)
        self.assertGreater(diff['meanShift'][2], diff['meanShift'][1], diff)
        rec['zoneDiff'] = dict(diff, pad=pad)

        # TASK-782 (a) determinism, (b) pulse: two elapsedSteps whose pulse centres cross zoneA
        s1 = page.evaluate(PULSE_STEPS, ['zoneA', 0])
        s2 = page.evaluate(PULSE_STEPS, ['zoneA', 600])
        pulse = page.evaluate(PULSE, [s1, s2, pad])
        self.assertEqual(pulse['sha1'], pulse['sha1Again'], pulse)
        self.assertNotEqual(pulse['sha1'], pulse['sha2'], pulse)
        self.assertGreater(pulse['changedIn'], 500, pulse)
        self.assertEqual(pulse['changedOut'], 0, pulse)
        self.assertEqual(pulse['zoneOut'], 0, pulse)
        rec['determinism'] = {'elapsedSteps': s1, 'sha': pulse['sha1'], 'shaAgain': pulse['sha1Again'], 'identical': True}
        rec['pulse'] = pulse
        # (c) world-size hexes: the lattice period in device px follows the camera scale, with the pulse away
        quiet = page.evaluate(PULSE_STEPS, ['zoneA', 3600])
        scales = [scene['scale'], scene['scale'] * 1.5]
        periods = []
        for sc in scales:
            per, peak = lattice_period(page.evaluate(LATTICE_ROWS, [sc, quiet]))
            periods.append({'scale': sc, 'periodPx': round(per, 3), 'peak': round(peak, 3)})
        ratio = periods[1]['periodPx'] / periods[0]['periodPx']
        expect = scales[1] / scales[0]
        hex_px = [3 ** 0.5 * page.evaluate('STYLE.colors.noGrapple.hexRadius') * sc * k * page.evaluate('getCanvasCssRect().width / width')
                  for sc in scales]
        self.assertLess(abs(ratio / expect - 1), 0.10, (periods, ratio, expect))
        for pr, hp in zip(periods, hex_px):
            self.assertLess(abs(pr['periodPx'] / hp - 1), 0.10, (periods, hex_px))
        rec['latticePeriod'] = {'periods': periods, 'expectedHexPeriodPx': [round(h, 3) for h in hex_px],
                                'ratio': round(ratio, 4), 'scaleRatio': expect, 'withinTenPercent': True}
        page.evaluate('TUTORIAL_HINT.visible = true')

        # Culling by each zone's own box as the camera moves (view left edge at world x = sx)
        cull = page.evaluate('''([W, H]) => { const out = {}
            for (const [name, sx] of [['zoneAPartlyLeft', 0.3 * W], ['zoneAOffLeft', 0.5 * W], ['farZoneInView', 5.9 * W]]) {
                screen.x = -sx; screen.y = 0; PG.frame(); out[name] = NO_GRAPPLE_ZONES.drawn.slice() }
            screen.x = 0; screen.y = 0; return out }''', [W, H])
        self.assertIn('zoneA', cull['zoneAPartlyLeft'])
        self.assertNotIn('zoneA', cull['zoneAOffLeft'])
        self.assertEqual(cull['farZoneInView'], ['zoneFar'])
        rec['culling'] = cull

        # Pass-through: a ropeless glide out of zone A matches the same glide without zones
        fall = page.evaluate('''([W, H]) => {
            const run = () => { PG.ropeScene(); Object.assign(grapnel, {throwed: false, grappled: false, pos: []})
                ninja.x = 0.39 * W; ninja.y = 0.30 * H; ninja.speedX = 3; ninja.speedY = 0
                const path = []
                for (let i = 0; i < 40; ++i) { calcPhysics(); path.push([ninja.x, ninja.y, ninja.speedX, ninja.speedY, !!floors[0].playerInNoGrapple]) }
                return path }
            const zoned = run(), plain = PG.withoutZones(run)
            return {steps: zoned.length, insideSteps: zoned.filter(s => s[4]).length, exited: !zoned[39][4],
                samePath: zoned.every((s, i) => s.slice(0, 4).every((v, j) => v === plain[i][j])),
                first: zoned[0].slice(0, 4), last: zoned[39].slice(0, 4)} }''', [W, H])
        self.assertTrue(fall['samePath'], fall)
        self.assertTrue(fall['insideSteps'] > 0 and fall['exited'], fall)
        rec['passThrough'] = dict(fall, notInElements=True, notInDragZones=True, dragMotesOnlyInDragZones=order['dragCount'] == 1)

        # Screenshots: English rope scene, Russian player-inside scene, each with the legend
        page.evaluate('PG.ropeScene(); PG.frame()')
        rec['legend'] = {'en': self.legend(page, 'en')}
        page.evaluate('PG.ropeScene(); PG.frame()')
        top = self.screenshot(page)
        page.evaluate("I18N.language = 'ru'")
        inside = page.evaluate('PG.insideScene()')
        self.assertEqual(inside, {'inside': True, 'attached': False, 'thrown': False})
        page.evaluate('PG.frame()')
        rec['legend']['ru'] = self.legend(page, 'ru')
        page.evaluate('PG.insideScene(); PG.frame()')
        player = page.evaluate('''() => { const s = PG.pixel(ninja.x, ninja.y)
            const z = PG.withoutZones(() => { PG.frame(); return PG.pixel(ninja.x, ninja.y) }); PG.frame(); return [s, z] }''')
        self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(*player)), player)
        rec['playerInsideZone'] = {'state': inside, 'centrePixel': player[0], 'centrePixelWithoutZones': player[1]}
        bottom = self.screenshot(page)
        if self.out:
            Path(self.out).mkdir(parents=True, exist_ok=True)
            sheet = Image.new('RGB', (top.width, top.height + bottom.height))
            sheet.paste(top.convert('RGB'), (0, 0))
            sheet.paste(bottom.convert('RGB'), (0, top.height))
            path = Path(self.out, f'purple-{kind}.png')
            sheet.save(path)
            rec['screenshot'] = {'file': path.name, 'size': list(sheet.size), 'top': 'en rope scene', 'bottom': 'ru player inside zoneA'}

        # Lifecycle: the legend goes with the hint (press, fade, hidden, not drawn)
        life = page.evaluate('''() => { const before = TUTORIAL_HINT.visible
            TUTORIAL_HINT.press('test'); TUTORIAL_HINT.advance(1000)
            const mid = {visible: TUTORIAL_HINT.visible, alpha: TUTORIAL_HINT.alpha}
            TUTORIAL_HINT.advance(2000)
            let draws = 0; const d0 = TUTORIAL_HINT.draw; TUTORIAL_HINT.draw = function(...a) { ++draws; return d0.apply(this, a) }
            try { PG.frame() } finally { delete TUTORIAL_HINT.draw }
            return {before, mid, after: {visible: TUTORIAL_HINT.visible, alpha: TUTORIAL_HINT.alpha, done: TUTORIAL_HINT.done},
                drawsAfterFade: draws} }''')
        self.assertTrue(life['before'] and life['mid']['visible'] and 0 < life['mid']['alpha'] < 1, life)
        self.assertEqual(life['after'], {'visible': False, 'alpha': 0, 'done': True})
        self.assertEqual(life['drawsAfterFade'], 0)
        rec['lifecycle'] = life
        self.proof.setdefault('viewports', {})[kind] = rec
        print(f"PASS {kind}: pulse in={pulse['changedIn']} out={pulse['changedOut']} sha stable, lattice period "
              f"{[p['periodPx'] for p in periods]} px ratio {ratio:.3f} (scale ratio {expect})", flush=True)
        print(f"PASS {kind}: order {o}, drawn {order['drawn']}, diff in={diff['changedIn']} out={diff['changedOut']} "
              f"yellow={diff['yellowShift']}, alpha {rec['pixels']['measuredAlpha']}, cull {cull}, legend en/ru ok", flush=True)

    def test_01_desktop(self):
        self.run_viewport('desktop')

    def test_02_touch(self):
        self.run_viewport('touch')

    def test_03_existing_legend_entries_unchanged(self):
        """Bounce and drag entries: same labels, sizes and drawing code as before this ticket."""
        old = git('show', f'{BASE_COMMIT}:render/tutorialhint.js')
        new = (ROOT / 'render/tutorialhint.js').read_text(encoding='utf-8')
        same = {}
        for name in ('drawBounce', 'drawDrag', 'press', 'advance', 'runStarted', 'draw'):
            a, b = method_source(old, name), method_source(new, name)
            self.assertIsNotNone(a, name)
            self.assertEqual(a, b, name)
            same[name] = hashlib.sha256(b.encode()).hexdigest()[:16]
        items = "{label: I18N.t('tutorial.legend.bounce'), w: 3.2, h: 3.2, draw: this.drawBounce}"
        drag = "{label: I18N.t('tutorial.legend.drag'), w: 6.4, h: 2, draw: this.drawDrag}"
        self.assertIn(items, old)
        self.assertIn(items, new)
        self.assertIn(drag, old)
        self.assertIn(drag, new)
        i18n_old = git('show', f'{BASE_COMMIT}:i18n.js')
        i18n_new = (ROOT / 'i18n.js').read_text(encoding='utf-8')
        keys = {}
        for key in ('tutorial.legend.bounce', 'tutorial.legend.drag'):
            o, n = re.findall(rf"'{re.escape(key)}'\s*:\s*'([^']*)'", i18n_old), re.findall(rf"'{re.escape(key)}'\s*:\s*'([^']*)'", i18n_new)
            self.assertEqual(o, n)
            keys[key] = n
        keys['tutorial.legend.noGrapple'] = re.findall(r"'tutorial\.legend\.noGrapple'\s*:\s*'([^']*)'", i18n_new)
        self.assertEqual(keys['tutorial.legend.noGrapple'], ['NO GRAPPLE', 'БЕЗ ЗАЦЕПА'])
        self.proof['existingLegend'] = {'baseCommit': BASE_COMMIT, 'unchangedMethods': same,
                                        'entries': {'bounce': items, 'drag': drag}, 'translations': keys}
        print('PASS existing legend entries and lifecycle methods unchanged since', BASE_COMMIT, flush=True)


if __name__ == '__main__':
    unittest.main()
