"""TASK-689: browser proof of the fixed Grapple Over camera scale 0.25 on the shipped level.

The same player states are framed at the previous scale 0.375 (a test-only override of the
runtime scale table, shipped files untouched) and at the shipped 0.25. Input goes through the
production document listeners (CDP mouse and touch events) before and after a live viewport
resize at DPR 1 and 2. Evidence JSON/PNG goes to CAMERA_SCALE_EVIDENCE_DIR (a temporary
directory when unset, never an earlier ticket's directory).
"""
import hashlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
SHIPPED_SCALE = 0.25
PREVIOUS_SCALE = 0.375
SCALES = (PREVIOUS_SCALE, SHIPPED_SCALE)
# Pre-jump poses: the player rests 30 units above the source panel's top centre.
POSES = (
    dict(name='opening', encounter='S06-03', source='P0', target='P1'),
    dict(name='first-leftward', encounter='OPEN-L1-L2', source='P18', target='P19'),
    dict(name='purple-NG1-entry', encounter='NG-ENTRY', source='P21', target='P22'),
)
# name, viewport, touch (coarse pointer + mobile), DPR used for the captures
FRAMING_VIEWS = (
    dict(name='desktop-1280x720', width=1280, height=720, touch=False, dpr=1),
    dict(name='narrow-390x844', width=390, height=844, touch=False, dpr=2),
    # A touch-first phone held upright: the stage is turned 90 degrees behind the rotate
    # prompt and the run is paused, so only the camera bounds are recorded (no capture).
    dict(name='phone-portrait-390x844', width=390, height=844, touch=True, dpr=2, capture=False),
)
SOURCES = ('gameoptions.js', 'events.js', 'moveScreen.js', 'physics.js', 'index.html', 'leveldata.js',
           'mountain.js', 'fixedlevel.js', 'menu.js', 'sprites/grapnel.js', 'sprites/ninja.js',
           'render/draw.js', 'tools/test_camera_scale_browser.py', 'tools/browser_test_support.py')

HELPER = r'''
window.T689 = (() => {
  const top = (e, f) => {
    const pts = e.getPoints(), lo = Math.min(...pts.map(p => p.x)), hi = Math.max(...pts.map(p => p.x));
    const x = lo + (hi - lo) * f, ys = [];
    for (const l of e.getLines()) if (x >= Math.min(l.x1, l.x2) && x <= Math.max(l.x1, l.x2) && l.x1 !== l.x2)
      ys.push(l.y1 + (x - l.x1) * (l.y2 - l.y1) / (l.x2 - l.x1));
    return {x, y: Math.min(...ys)};
  };
  const body = id => floors[0].byId.get(id + '-body0');
  const bbox = e => {const p = e.getPoints(), xs = p.map(q => q.x), ys = p.map(q => q.y);
    return {left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys)}};
  const aims = [];
  const api = {
    aims,
    freeze() {
      window.requestAnimationFrame = () => 0; cancelAnimationFrame(game);
      const original = grapnel.setAim.bind(grapnel);
      // Records the world target that events.js resolved from the press (production path).
      grapnel.setAim = target => {aims.push({x: target.x, y: target.y}); original(target)};
    },
    setScale(s) {
      scale.grapple_over = s; screen.updateWidthLayout(); layoutHud(); TUTORIAL_HINT.invalidate();
    },
    top, body, bbox,
    pose(source, fraction = 0.5, drop = 30) {
      const p = top(body(source), fraction);
      ninja.x = p.x; ninja.y = p.y - drop; ninja.speedX = ninja.speedY = 0;
      grapnel.endShot(); pressHeld = stalePress = gameplayPressOwned = false; unTouch = false;
      screen.trackGrappleOver(true);
      return {x: ninja.x, y: ninja.y};
    },
    camera() {
      const s = scale[version];
      return {scale: s, logical: [width, height], left: -screen.x, top: -screen.y,
              right: -screen.x + width / s, bottom: -screen.y + height / s, width: width / s, height: height / s};
    },
    cssPerLogical() {return getCanvasCssRect().width / width},
    client(p) {const s = scale[version]; return canvasCoordsToViewportCoords({x: (p.x + screen.x) * s, y: (p.y + screen.y) * s})},
    world(c) {const s = scale[version], q = viewportCoordsToCanvasCoords(c); return {x: q.x / s - screen.x, y: q.y / s - screen.y}},
    ninjaScreen() {
      const s = scale[version], x = (ninja.x + screen.x) * s, y = (ninja.y + screen.y) * s, r = ninja.radius * s;
      return {x, y, r, inside: x - r >= -1e-6 && x + r <= width + 1e-6 && y - r >= -1e-6 && y + r <= height + 1e-6};
    },
    attached() {return grapnel.grappled ? grapnel.pos.at(-1)?.[2]?.id ?? null : null},
    nearest(id) {
      let best = null;
      for (const l of body(id).getLines()) {
        const dx = l.x2 - l.x1, dy = l.y2 - l.y1;
        const t = Math.max(0, Math.min(1, ((ninja.x - l.x1) * dx + (ninja.y - l.y1) * dy) / (dx * dx + dy * dy)));
        const q = {x: l.x1 + t * dx, y: l.y1 + t * dy}; q.d = Math.hypot(q.x - ninja.x, q.y - ninja.y);
        if (!best || q.d < best.d) best = q;
      }
      return best;
    },
  };
  return api;
})();
'''


def sha256(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


class CameraScaleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cleanups = []
        env = os.environ.get('CAMERA_SCALE_EVIDENCE_DIR')
        if env:
            cls.out = Path(env)
        else:
            cls._tmp = tempfile.TemporaryDirectory()
            cls._cleanups.append(cls._tmp.cleanup)
            cls.out = Path(cls._tmp.name)
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.hashes = {path: sha256(path) for path in SOURCES}
        cls.url, cls.browser = start_browser_test(ROOT, cls._cleanups.append)

    @classmethod
    def tearDownClass(cls):
        while cls._cleanups:
            cls._cleanups.pop()()

    def write(self, name, data):
        data = dict(data, sourceSha256=self.hashes)
        (self.out / name).write_text(json.dumps(data, indent=1) + '\n')

    def open(self, width, height, touch=False, dpr=1):
        context = self.browser.new_context(viewport=dict(width=width, height=height), device_scale_factor=dpr,
                                           has_touch=touch, is_mobile=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(HELPER)
        page.evaluate('T689.freeze()')
        state = page.evaluate('({version, scale: scale[version], layout: floors[0].level.layoutId ?? null,'
                              ' touchFirst: isTouchFirstDevice(), rotated: isViewRotated(), dpr: devicePixelRatio})')
        self.assertEqual(state['version'], 'grapple_over')
        self.assertEqual(state['scale'], SHIPPED_SCALE)
        self.assertEqual(state['touchFirst'], touch)
        self.assertEqual(state['dpr'], dpr)
        return page, context, state

    def resize(self, page, width, height):
        before = page.evaluate('width')
        page.set_viewport_size(dict(width=width, height=height))
        page.wait_for_function('([w, h, before]) => innerWidth === w && innerHeight === h && width !== before',
                               arg=[width, height, before])
        page.wait_for_timeout(50)

    # ---------------------------------------------------------------- framing

    def test_01_framing_previous_vs_shipped_scale(self):
        from PIL import Image, ImageDraw
        rows, tiles = [], {}
        for view in FRAMING_VIEWS:
            page, _, state = self.open(view['width'], view['height'], view['touch'], view['dpr'])
            if view['touch']:
                self.assertTrue(state['rotated'])
            for pose in POSES:
                per_scale = {}
                # Past the opening the hold-to-grapple hint was dismissed by the first press.
                page.evaluate('v => {TUTORIAL_HINT.visible = v}', pose['name'] == 'opening')
                for s in SCALES:
                    page.evaluate('s => T689.setScale(s)', s)
                    player = page.evaluate('p => T689.pose(p)', pose['source'])
                    camera = page.evaluate('T689.camera()')
                    landing = page.evaluate('id => T689.top(T689.body(id), 0.5)', pose['target'])
                    ninja = page.evaluate('T689.ninjaScreen()')
                    self.assertTrue(ninja['inside'], (view['name'], pose['name'], s, ninja))
                    rect = page.evaluate('getCanvasCssRect()')
                    per_scale[str(s)] = dict(player=player, camera=camera, landing=landing,
                                             landingVisible=camera['left'] <= landing['x'] <= camera['right'] and
                                             camera['top'] <= landing['y'] <= camera['bottom'],
                                             playerScreenLogical=ninja, canvasCss=rect)
                    if view.get('capture', True):
                        page.evaluate('draw()')
                        path = self.out / 'frames' / ('%s_%s_%s.png' % (view['name'], pose['name'], s))
                        path.parent.mkdir(exist_ok=True)
                        clip = dict(x=rect['left'], y=rect['top'], width=rect['width'], height=rect['height'])
                        page.screenshot(path=str(path), clip=clip)
                        marks = [page.evaluate('p => T689.client(p)', p) for p in (player, landing)]
                        tiles[(view['name'], pose['name'], s)] = (path, rect, marks, view['dpr'])
                old, new = per_scale[str(PREVIOUS_SCALE)], per_scale[str(SHIPPED_SCALE)]
                self.assertEqual(old['player'], new['player'])
                ratio_w = new['camera']['width'] / old['camera']['width']
                ratio_h = new['camera']['height'] / old['camera']['height']
                self.assertAlmostEqual(ratio_w, 1.5, places=9)
                self.assertAlmostEqual(ratio_h, 1.5, places=9)
                self.assertAlmostEqual(new['camera']['right'] - new['camera']['left'], new['camera']['width'], places=6)
                # The larger view contains the player at the same state and is inside the level bounds when they allow it.
                rows.append(dict(view=view['name'], viewport=[view['width'], view['height']], dpr=view['dpr'],
                                 touch=view['touch'], rotated=state['rotated'], pose=pose,
                                 widthRatio=ratio_w, heightRatio=ratio_h, scales=per_scale))
            page.evaluate('s => T689.setScale(s)', SHIPPED_SCALE)
            page.context.close()
        bounds = json.loads((ROOT / 'artifacts/levels/extended-mountain.level.json').read_text())['bounds']
        self.write('framing.json', dict(
            level='extended-mountain-v17', levelBounds=bounds, scales=SCALES,
            override='test-only: scale.grapple_over set in the page, then screen.updateWidthLayout() and layoutHud();'
                     ' shipped gameoptions.js stays 0.25',
            playerState='rest 30 units above the source panel top centre, speed 0, camera snapped by screen.trackGrappleOver(true)',
            tolerance=1e-9, allRatiosOk=all(abs(r['widthRatio'] - 1.5) < 1e-9 and abs(r['heightRatio'] - 1.5) < 1e-9 for r in rows),
            cases=len(rows), rows=rows))
        # comparison.png: one row per view/pose, previous scale left, shipped scale right; rings mark
        # the player (cyan) and the next landing's top centre (yellow) as a test overlay.
        blocks = []
        for view in FRAMING_VIEWS:
            if not view.get('capture', True):
                continue
            for pose in POSES:
                row = []
                for s in SCALES:
                    path, rect, marks, dpr = tiles[(view['name'], pose['name'], s)]
                    img = Image.open(path).convert('RGB')
                    k = 960 / img.width if img.width > 960 else 1
                    img = img.resize((round(img.width * k), round(img.height * k)))
                    d = ImageDraw.Draw(img)
                    px = img.width / rect['width']
                    for (c, color) in zip(marks, ((0, 255, 255), (255, 230, 0))):
                        x, y = (c['x'] - rect['left']) * px, (c['y'] - rect['top']) * px
                        d.ellipse((x - 14, y - 14, x + 14, y + 14), outline=color, width=3)
                    d.rectangle((0, 0, img.width, 22), fill=(0, 0, 0))
                    d.text((6, 5), '%s | %s | scale %s' % (view['name'], pose['name'], s), fill=(255, 255, 255))
                    row.append(img)
                blocks.append(row)
        total_w = max(sum(i.width for i in r) + 10 for r in blocks)
        total_h = sum(max(i.height for i in r) + 10 for r in blocks)
        sheet = Image.new('RGB', (total_w, total_h), (40, 40, 40))
        y = 0
        for r in blocks:
            x = 0
            for img in r:
                sheet.paste(img, (x, y))
                x += img.width + 10
            y += max(i.height for i in r) + 10
        sheet.save(self.out / 'comparison.png', optimize=True)
        print('PASS framing: %d view/pose cases, width and height ratios 1.5 (tol 1e-9)' % len(rows), flush=True)

    # ------------------------------------------------------------------ input

    INPUT_RUNS = (
        dict(name='mouse-dpr1', touch=False, dpr=1, before=(1280, 720), after=(390, 844)),
        dict(name='mouse-dpr2', touch=False, dpr=2, before=(1280, 720), after=(390, 844)),
        dict(name='touch-dpr1', touch=True, dpr=1, before=(844, 390), after=(667, 375)),
        dict(name='touch-dpr2', touch=True, dpr=2, before=(844, 390), after=(667, 375)),
    )

    def press(self, page, cdp, touch, client, release=True):
        if touch:
            cdp.send('Input.dispatchTouchEvent', dict(type='touchStart', touchPoints=[dict(x=client['x'], y=client['y'], id=1)]))
            if release:
                cdp.send('Input.dispatchTouchEvent', dict(type='touchEnd', touchPoints=[]))
        else:
            for kind in ('mouseMoved', 'mousePressed') + (('mouseReleased',) if release else ()):
                cdp.send('Input.dispatchMouseEvent', dict(type=kind, x=client['x'], y=client['y'], button='left', clickCount=1))

    def release(self, cdp, touch, client):
        if touch:
            cdp.send('Input.dispatchTouchEvent', dict(type='touchEnd', touchPoints=[]))
        else:
            cdp.send('Input.dispatchMouseEvent', dict(type='mouseReleased', x=client['x'], y=client['y'], button='left', clickCount=1))

    def input_phase(self, page, cdp, touch, label):
        """Known world points -> client -> production press -> resolved world target; then a real grapple."""
        rows, pose = [], POSES[0]
        page.evaluate('p => T689.pose(p)', pose['source'])
        css = page.evaluate('T689.cssPerLogical()')
        camera = page.evaluate('T689.camera()')
        points = page.evaluate('''([s, t]) => [
            ['source-top-0.2', T689.top(T689.body(s), 0.2)], ['source-top-0.8', T689.top(T689.body(s), 0.8)],
            ['target-top-centre', T689.top(T689.body(t), 0.5)], ['target-top-0.9', T689.top(T689.body(t), 0.9)],
            ['above-player', {x: ninja.x + 37.3, y: ninja.y - 611.7}]]''', [pose['source'], pose['target']])
        for name, world in points:
            exact = page.evaluate('p => T689.client(p)', world)
            back = page.evaluate('c => T689.world(c)', exact)
            # Chrome delivers mouse clientX/Y in whole CSS px (fractional CDP positions are truncated),
            # so the press goes to the nearest whole pixel as a real mouse would; touches keep fractions.
            client = exact if touch else dict(x=round(exact['x']), y=round(exact['y']))
            expected = page.evaluate('c => T689.world(c)', client)
            count = page.evaluate('T689.aims.length')
            page.wait_for_function('!unTouch')
            self.press(page, cdp, touch, client)
            resolved = page.evaluate('n => T689.aims.slice(n)', count)
            self.assertEqual(len(resolved), 1, (label, name, resolved))
            s = camera['scale']
            to_css = lambda a, b: math.hypot(a['x'] - b['x'], a['y'] - b['y']) * s * css
            dispatch_err = to_css(resolved[0], world)
            conversion_err = to_css(resolved[0], expected)
            roundtrip_err = to_css(back, world)
            self.assertLessEqual(dispatch_err, 1.0, (label, name))
            # CDP carries touch points as floats: allow 1e-3 CSS px for that encoding.
            self.assertLessEqual(conversion_err, 1e-3, (label, name))
            self.assertLessEqual(roundtrip_err, 1.0, (label, name))
            rows.append(dict(point=name, world=world, exactClient=exact, client=client, functionRoundTripWorld=back,
                             dispatchedWorld=resolved[0], dispatchErrorCssPx=dispatch_err,
                             conversionErrorVsDeliveredPixelCssPx=conversion_err, roundTripErrorCssPx=roundtrip_err))
            page.evaluate('p => T689.pose(p)', pose['source'])
        # Intended reachable grapple target: the next panel when it is in range of the rest pose,
        # otherwise the pumping surface of the source panel (how every route starts).
        reach = page.evaluate('''([s, t]) => {const q = T689.nearest(t); return {range: grappleOverAcquisitionRadius(),
            next: {x: q.x, y: q.y, d: q.d}, pump: T689.top(T689.body(s), 0.7)}}''', [pose['source'], pose['target']])
        if reach['next']['d'] <= reach['range'] - 5:
            intended, aim = pose['target'] + '-body0', reach['next']
        else:
            intended, aim = pose['source'] + '-body0', reach['pump']
        grapples = [self.grapple(page, cdp, touch, label, intended, aim,
                                 'pre-jump %s: next panel %s at %.0f units vs range %s' % (
                                     pose['source'], pose['target'], reach['next']['d'], reach['range']))]
        # And the next panel itself. No rest pose has its next panel in range (routes pump first), so the
        # player is moved from the first leftward rest pose toward L2 to 60% of the range, as mid-route.
        lead = POSES[1]
        near = page.evaluate('''([s, t]) => {T689.pose(s); const q = T689.nearest(t), d = q.d, k = 0.6 * grappleOverAcquisitionRadius() / d;
            ninja.x = q.x + (ninja.x - q.x) * k; ninja.y = q.y + (ninja.y - q.y) * k; screen.trackGrappleOver(true);
            const r = T689.nearest(t);
            return {encounter: null, source: s, target: t, aim: {x: r.x, y: r.y}, d: r.d,
                    noGrappleZone: floors[0].playerInNoGrappleZone(ninja)}}''', [lead['source'], lead['target']])
        near['encounter'] = lead['encounter']
        self.assertFalse(near['noGrappleZone'])
        self.assertIsNotNone(near)
        grapples.append(self.grapple(page, cdp, touch, label, near['target'] + '-body0', near['aim'],
                                     'toward %s (%s): next panel %s at %.0f units, in range' % (
                                         near['source'], near['encounter'], near['target'], near['d'])))
        return dict(label=label, camera=camera, cssPerLogical=css, points=rows, grapples=grapples)

    def grapple(self, page, cdp, touch, label, intended, aim, note):
        """Hold a production press on aim until the grapnel attaches; the attached element must be intended."""
        client = page.evaluate('p => T689.client(p)', aim)
        if not touch:
            client = dict(x=round(client['x']), y=round(client['y']))
        page.wait_for_function('!unTouch')
        start = page.evaluate('[ninja.x, ninja.y]')
        self.press(page, cdp, touch, client, release=False)
        ticks = page.evaluate('''() => {for (let i = 0; i < 180; ++i) {physics(); if (T689.attached()) return i + 1} return null}''')
        attached = page.evaluate('T689.attached()')
        self.release(cdp, touch, client)
        self.assertEqual(attached, intended, (label, note))
        return dict(label=label, note=note, player=start, intended=intended, aimWorld=aim, client=client,
                    attached=attached, ticks=ticks)

    def test_02_input_conversion_and_dispatch(self):
        runs = []
        for run in self.INPUT_RUNS:
            page, context, state = self.open(*run['before'], touch=run['touch'], dpr=run['dpr'])
            cdp = context.new_cdp_session(page)
            phases = [self.input_phase(page, cdp, run['touch'], '%s before %dx%d' % ((run['name'],) + run['before']))]
            self.resize(page, *run['after'])
            after = page.evaluate('({rotated: isViewRotated(), width, dpr: devicePixelRatio})')
            self.assertFalse(after['rotated'])
            phases.append(self.input_phase(page, cdp, run['touch'], '%s after %dx%d' % ((run['name'],) + run['after'])))
            self.assertNotEqual(phases[0]['camera']['logical'], phases[1]['camera']['logical'])
            runs.append(dict(run, state=state, after_state=after, phases=phases))
        # Upright touch phone: the turned stage still converts exactly, but a tap there never throws.
        page, context, state = self.open(390, 844, touch=True, dpr=2)
        cdp = context.new_cdp_session(page)
        self.assertTrue(state['rotated'])
        page.evaluate('p => T689.pose(p)', POSES[0]['source'])
        world = page.evaluate('T689.top(T689.body("P0"), 0.8)')
        client = page.evaluate('p => T689.client(p)', world)
        back = page.evaluate('c => T689.world(c)', client)
        s, css = page.evaluate('[scale[version], T689.cssPerLogical()]')
        err = math.hypot(back['x'] - world['x'], back['y'] - world['y']) * s * css
        self.assertLessEqual(err, 1.0)
        count = page.evaluate('T689.aims.length')
        self.press(page, cdp, True, client)
        self.assertEqual(page.evaluate('T689.aims.length'), count)
        portrait = dict(viewport=[390, 844], dpr=2, rotated=True, world=world, client=client, roundTripWorld=back,
                        roundTripErrorCssPx=err, throwsOnTap=False, note='upright phone: rotate prompt, run paused, input ignored by design')
        errors = [p['dispatchErrorCssPx'] for r in runs for ph in r['phases'] for p in ph['points']] + \
                 [p['roundTripErrorCssPx'] for r in runs for ph in r['phases'] for p in ph['points']] + [err]
        self.write('input.json', dict(maxErrorCssPx=max(errors), limitCssPx=1.0, conversions=len(errors),
                                      grapples=[g for r in runs for ph in r['phases'] for g in ph['grapples']],
                                      runs=runs, portraitPhone=portrait))
        print('PASS input: %d conversions, max error %.4f CSS px, %d production grapples reached the intended target'
              % (len(errors), max(errors), 4 * len(runs)), flush=True)

    # --------------------------------------------------------------------- ui

    def track(self, page, label):
        """Production physics and tracking through ascent, fall and direction changes; ninja on screen every tick."""
        return page.evaluate('''label => {
            const rows = [], out = [], outOfLevel = [];
            const max = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent);
            const phases = [
              // A strong release (15% of the speed cap), its apex and a long fall.
              ['ascent', 60, () => {ninja.speedY = -max * 0.15; ninja.speedX = 0}],
              ['apex-and-fall', 150, () => {}],
              ['right', 30, () => {ninja.speedX = max * 0.4}],
              ['reverse-left', 30, () => {ninja.speedX = -max * 0.4}],
              ['reverse-right-fall', 60, () => {ninja.speedX = max * 0.4; ninja.speedY = max * 0.5}],
            ];
            let worst = Infinity, tick = 0;
            for (const [name, ticks, kick] of phases) {
              kick();
              for (let i = 0; i < ticks; ++i, ++tick) {
                physics();
                const n = T689.ninjaScreen();
                // The camera is clamped to the level bounds: a player below the bottom bound has left the
                // level (fall recovery follows) and is reported apart, not as a tracking failure.
                const lb = floors[0].level.bounds;
                const inLevel = ninja.x >= lb.left && ninja.x <= lb.right && ninja.y >= lb.top && ninja.y <= lb.bottom;
                if (!inLevel) outOfLevel.push({name, tick, inView: n.inside, ninja: [ninja.x, ninja.y]});
                else {
                  worst = Math.min(worst, n.x - n.r, width - n.x - n.r, n.y - n.r, height - n.y - n.r);
                  if (!n.inside) out.push({name, tick, n, ninja: [ninja.x, ninja.y]});
                }
                if (i === 0 || i === ticks - 1) rows.push({phase: name, tick, x: ninja.x, y: ninja.y,
                    vx: ninja.speedX, vy: ninja.speedY, screen: [n.x, n.y]});
              }
            }
            const b = floors[0].level.bounds;
            return {label, ticks: tick, outside: out, outOfLevel, minMarginLogical: worst, samples: rows,
                    insideLevelBounds: rows.every(r => r.x >= b.left && r.x <= b.right && r.y >= b.top && r.y <= b.bottom),
                    minY: Math.min(...rows.map(r => r.y)), maxY: Math.max(...rows.map(r => r.y))};
        }''', label)

    def hud(self, page):
        return page.evaluate('''() => {
            const s = scale[version], css = T689.cssPerLogical(), b = menu.button.background;
            return {scale: s, menuButtonCss: [b.width * s * css, b.height * s * css],
                    menuButtonClient: canvasCoordsToViewportCoords({x: (b.x + b.width / 2) * s, y: (b.y + b.height / 2) * s}),
                    hudFontCss: scoreText.fontSize * s * css}}''')

    def pause_buttons(self, page):
        return page.evaluate('''() => {const css = T689.cssPerLogical();
            return CLIMB_UI.buttons.map(b => ({text: b.text?.text ?? null, css: [b.background.width * css, b.background.height * css],
                client: canvasCoordsToViewportCoords({x: b.background.x + b.background.width / 2,
                    y: b.background.y + b.background.height / 2})}))}''')

    def test_03_ui_tracking_and_hud(self):
        views = []
        for view in (dict(name='desktop-1280x720', size=(1280, 720), touch=False),
                     dict(name='narrow-390x844', size=(390, 844), touch=False),
                     dict(name='phone-844x390', size=(844, 390), touch=True)):
            page, context, _ = self.open(*view['size'], touch=view['touch'], dpr=2 if view['touch'] else 1)
            cdp = context.new_cdp_session(page)
            row = dict(view=view, tracking=[], hud={}, clicks=[])
            for s in SCALES:
                page.evaluate('s => T689.setScale(s)', s)
                for pose in POSES:
                    page.evaluate('p => T689.pose(p)', pose['source'])
                    result = self.track(page, '%s %s scale %s' % (view['name'], pose['name'], s))
                    self.assertEqual(result['outside'], [], result['label'])
                    row['tracking'].append(result)
                page.evaluate('p => T689.pose(p)', POSES[0]['source'])
                row['hud'][str(s)] = self.hud(page)
                # HUD menu button: a real press pauses; the pause menu's Resume resumes.
                page.wait_for_function('!unTouch')
                page.evaluate('draw()')
                self.press(page, cdp, view['touch'], row['hud'][str(s)]['menuButtonClient'])
                paused = page.evaluate('menu.gamePaused')
                self.assertTrue(paused, (view['name'], s))
                buttons = self.pause_buttons(page)
                self.assertGreaterEqual(len(buttons), 4)
                row['hud'][str(s)]['pauseButtons'] = buttons
                page.wait_for_function('!unTouch')
                self.press(page, cdp, view['touch'], buttons[0]['client'])
                resumed = not page.evaluate('menu.gamePaused')
                self.assertTrue(resumed, (view['name'], s))
                row['clicks'].append(dict(scale=s, menuButtonPaused=paused, resumeResumed=resumed))
            old, new = row['hud'][str(PREVIOUS_SCALE)], row['hud'][str(SHIPPED_SCALE)]
            row['sizeDiffCss'] = dict(
                menuButton=max(abs(a - b) for a, b in zip(old['menuButtonCss'], new['menuButtonCss'])),
                hudFont=abs(old['hudFontCss'] - new['hudFontCss']),
                pauseButtons=max(abs(a - b) for x, y in zip(old['pauseButtons'], new['pauseButtons'])
                                 for a, b in zip(x['css'], y['css'])))
            for key, diff in row['sizeDiffCss'].items():
                self.assertLessEqual(diff, 1.0, (view['name'], key))
            if view['touch']:
                self.assertGreaterEqual(min(new['menuButtonCss']) + 1e-6, 44)
            views.append(row)
            context.close()
        self.write('ui.json', dict(
            allTrackingInside=all(t['outside'] == [] for v in views for t in v['tracking']),
            trackingRuns=sum(len(v['tracking']) for v in views),
            trackedTicks=sum(t['ticks'] for v in views for t in v['tracking']),
            maxSizeDiffCss=max(d for v in views for d in v['sizeDiffCss'].values()), views=views))
        print('PASS ui: %d tracking runs, player inside every tick; HUD/pause controls within 1 CSS px and clickable'
              % sum(len(v['tracking']) for v in views), flush=True)

    # ------------------------------------------------------------- visibility

    def test_04_landing_visibility(self):
        views = []
        for view in (dict(name='desktop-1280x720', size=(1280, 720), touch=False),
                     dict(name='narrow-390x844', size=(390, 844), touch=False),
                     dict(name='phone-844x390', size=(844, 390), touch=True)):
            page, context, _ = self.open(*view['size'], touch=view['touch'], dpr=1)
            per_scale = {}
            for s in SCALES:
                page.evaluate('s => T689.setScale(s)', s)
                rows = page.evaluate('''() => floors[0].level.encounters.map(e => {
                    const panels = [...new Set(e.elements.map(id => id.split('-')[0]))];
                    const source = panels[0], target = panels[panels.length - 1];
                    const player = T689.pose(source), c = T689.camera(), b = T689.bbox(T689.body(target));
                    const land = T689.top(T689.body(target), 0.5);
                    const ix = Math.max(0, Math.min(c.right, b.right) - Math.max(c.left, b.left));
                    const iy = Math.max(0, Math.min(c.bottom, b.bottom) - Math.max(c.top, b.top));
                    return {encounter: e.id, source, target, player, landing: land,
                        landingVisible: land.x >= c.left && land.x <= c.right && land.y >= c.top && land.y <= c.bottom,
                        targetBoxVisibleFraction: ix * iy / ((b.right - b.left) * (b.bottom - b.top)),
                        camera: [c.left, c.top, c.right, c.bottom]}})''')
                per_scale[str(s)] = dict(visible=sum(r['landingVisible'] for r in rows), sampled=len(rows),
                                         offScreen=[r['encounter'] for r in rows if not r['landingVisible']], rows=rows)
            old, new = per_scale[str(PREVIOUS_SCALE)], per_scale[str(SHIPPED_SCALE)]
            self.assertEqual(new['sampled'], 61)
            # The larger view never loses a landing the previous one showed.
            self.assertTrue(set(new['offScreen']) <= set(old['offScreen']), view['name'])
            views.append(dict(view=view, newlyVisible=sorted(set(old['offScreen']) - set(new['offScreen'])), scales=per_scale))
            context.close()
        self.write('visibility.json', dict(
            definition='pre-jump view: player at rest 30 units above the source panel top centre, camera snapped;'
                       ' landing = top centre of the encounter\'s last panel',
            summary={v['view']['name']: {s: dict(visible=v['scales'][s]['visible'], sampled=v['scales'][s]['sampled'],
                                                offScreen=v['scales'][s]['offScreen']) for s in v['scales']} for v in views},
            views=views))
        print('PASS visibility: ' + '; '.join('%s %s' % (v['view']['name'], {s: '%d/%d' % (v['scales'][s]['visible'], v['scales'][s]['sampled'])
                                                                          for s in v['scales']}) for v in views), flush=True)


if __name__ == '__main__':
    unittest.main()
