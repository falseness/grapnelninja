"""TASK-674: purple no-grapple zone presentation.

Boots the real index.html in Grapple Over, stops the frame loop and loads a
small fixture level (the shipped level has no zones yet) with two purple
zones, a far-away zone for culling, solid and bounce panels, a yellow drag
zone and one route-arrow transfer whose guide crosses a zone. Frames are the
production draw() of that state:

- render/nograpplezones.js draws the zones first in the world layer, under
  the route arrows, the rope, the panels and the player (call order, and
  pixels of opaque panels and the player unchanged by the zones);
- the wash is translucent (alpha from STYLE.colors.noGrapple, measured from
  pixels), adds no yellow and changes nothing outside the zones;
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
        edge = page.evaluate(SPRITE_PIXEL, [purple['x'] + 1, purple['y'] + purple['h'] / 2])
        self.assertTrue(edge[2] > 100 and edge[2] > edge[0] > edge[1] + 30, edge)
        left, right = boxes[0]['x'], boxes[-1]['x'] + boxes[-1]['w']
        return {'labels': [b['label'] for b in legend], 'canvas': state['canvas'],
                'icons': [{k: round(v, 1) for k, v in b['icon'].items()} for b in legend],
                'textRight': round(right, 1), 'textLeft': round(left, 1), 'insideView': True, 'noOverlap': True,
                'clearOfMenuButton': True, 'noGrappleEdgePixel': edge,
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
        # Estimated wash alpha per channel from base -> zoned toward the fill colour
        fill = page.evaluate('STYLE.colors.noGrapple.fill')
        m = re.match(r'rgba\((\d+), (\d+), (\d+), ([\d.]+)\)', fill)
        target, alpha = [int(m.group(i)) for i in (1, 2, 3)], float(m.group(4))
        est = [(z['zoneOnly'][i] - p['zoneOnly'][i]) / (target[i] - p['zoneOnly'][i]) for i in range(3)
               if abs(target[i] - p['zoneOnly'][i]) > 40]
        self.assertTrue(est and all(0 < e < 0.35 for e in est), est)
        self.assertTrue(0 < alpha < 0.35)
        lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        # Brightest rope pixel near its midpoint against the wash
        near = page.evaluate('''([x, y]) => { PG.frame(); const out = []
            for (const dx of [-1, 0, 1]) for (const dy of [-1, 0, 1]) out.push(PG.pixel(x + dx, y + dy)); return out }''', pts['ropeMid'])
        rope_contrast = max(lum(c) for c in near) - lum(z['zoneOnly'])
        self.assertGreater(rope_contrast, 40, (near, z['zoneOnly']))
        rec['pixels'] = {'points': {k: [round(v, 1) for v in xy] for k, xy in pts.items()}, 'zoned': z, 'plain': p,
                         'fill': fill, 'fillAlpha': alpha, 'measuredAlpha': [round(e, 3) for e in est],
                         'ropeLuminanceContrastOverWash': round(rope_contrast, 1)}
        diff = page.evaluate(DIFF, 4)
        self.assertEqual(diff['unstable'], 0, diff)
        self.assertGreater(diff['changedIn'], 1000, diff)
        self.assertEqual(diff['changedOut'], 0, diff)
        self.assertEqual(diff['yellowShift'], 0, diff)
        self.assertGreater(diff['meanShift'][2], diff['meanShift'][1], diff)
        rec['zoneDiff'] = diff
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
