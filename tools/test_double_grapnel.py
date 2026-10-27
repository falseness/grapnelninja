"""TASK-718: Grapple Over double grapnel mode (x2 range).

setGrapnelMode('double') doubles grappleOverAcquisitionRadius() before and
after the range upgrade; the range circle, shot travel and acquisition all use
it. grapnelMode and usedDouble round-trip through captureClimbState /
restoreClimbState; older saves load as single/false. Double mode shows the
'x2 RANGE' HUD row.

DOUBLE_GRAPNEL_EVIDENCE_DIR=DIR writes range.json, save.json, badge.png and,
when DOUBLE_GRAPNEL_BASELINE_ROOT names a checkout of the previous commit,
single-identical.json (a scripted single-mode physics trace from both trees).
When the commit ships a new layout, copy its leveldata.js and mountain.js into
that checkout: the level bounds set the camera scale, so the scripted clicks
(and the trace) differ between layouts even with identical code (TASK-725).

    python3 -m unittest discover -s tools -p test_double_grapnel.py -v
"""
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
import hashlib
import io
import json
import os
from pathlib import Path
from threading import Thread
import unittest

from browser_test_support import QuietHandler, start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
OUT = os.environ.get('DOUBLE_GRAPNEL_EVIDENCE_DIR')
BASELINE = os.environ.get('DOUBLE_GRAPNEL_BASELINE_ROOT')

FREEZE = '''{ const raf = window.requestAnimationFrame.bind(window)
    window.requestAnimationFrame = cb => cb && cb.name === 'gameLoop' ? 0 : raf(cb) }'''

# The radius drawRangeCircle passes to ctx.arc in one real frame.
CIRCLE = '''() => { const arc = ctx.arc, radii = []
    ctx.arc = function(x, y, r) { if (this.strokeStyle === '#00ffff') radii.push(r); return arc.apply(this, arguments) }
    try { drawAcquisitionCircle() } finally { ctx.arc = arc }
    return radii }'''

# A ceiling bar whose underside is `distance` straight above a resting ninja;
# a held press aimed at it either attaches or parks at the range edge.
SHOT = '''([distance, mode, upgraded]) => {
    const rect = (id, x, y, w, h) => ({id, x, y, role: 'bounce', grapplable: true,
        points: [{x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}]})
    const m = structuredClone(GRAPPLE_OVER_REPLACEMENT)
    m.sections = [{id: 'S01', status: 'built', encounters: ['probe']}]; m.finish = null; m.movers = []
    const floorY = 1000, x = 500
    m.elements = [rect('floor', 0, floorY, 1000, 40), rect('target', 300, floorY - ninja.radius - 1 - distance - 40, 400, 40)]
    m.encounters = [{id: 'probe', elements: m.elements.map(e => e.id)}]
    m.bounds = {left: -4000, right: 6000, top: -6000, bottom: 8000}
    floors = [loadMountainLevel(m)]; floors[0].rangeUpgraded = upgraded; setGrapnelMode(mode)
    Object.assign(ninja, {x, y: floorY - ninja.radius - 1, speedX: 0, speedY: 0})
    grapnel.endShot(); pressHeld = stalePress = gameplayPressOwned = false
    screen.leftWall = null; screen.trackGrappleOver(true)
    const q = canvasCoordsToViewportCoords({x: (x + screen.x) * scale[version],
        y: (floorY - ninja.radius - 1 - distance - 20 + screen.y) * scale[version]})
    document.dispatchEvent(new MouseEvent('mousedown', {clientX: q.x, clientY: q.y, bubbles: true}))
    let attachedTick = null
    for (let t = 1; t <= 120 && attachedTick === null; t++) { physics(); if (grapnel.grappled) attachedTick = t }
    const out = {mode, upgraded, distance, range: grappleOverAcquisitionRadius(), attachedTick,
        grappled: grapnel.grappled, throwed: grapnel.throwed, traveled: grapnel.traveled,
        anchor: grapnel.grappled ? grapnel.pos[0][2].id : null}
    document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))
    return out }'''

# Fixed scripted input on the shipped level: press/release at fixed world
# offsets from the ninja on fixed ticks; per-tick state hashed.
SCRIPT = '''() => {
    const presses = [[5, 40, 400, -700], [60, 0, null], [70, -380, -650], [150, 0, null], [160, 300, -900],
        [260, 0, null], [270, -200, -500], [330, 0, null]]
    const rows = []
    const fire = (dx, dy) => {
        if (dx === 0 && dy === null) return document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))
        const q = canvasCoordsToViewportCoords({x: (ninja.x + dx + screen.x) * scale[version],
            y: (ninja.y + dy + screen.y) * scale[version]})
        document.dispatchEvent(new MouseEvent('mousedown', {clientX: q.x, clientY: q.y, bubbles: true}))
    }
    for (let t = 0; t < 400; t++) {
        for (const [tick, dx, dy] of presses) if (tick === t) fire(dx, dy)
        physics()
        rows.push([ninja.x, ninja.y, ninja.speedX, ninja.speedY, grapnel.throwed, grapnel.grappled,
            grapnel.traveled, grapnel.pos.length])
    }
    return rows }'''

EVIDENCE = {'range': {}, 'save': {}}


def tearDownModule():
    if not OUT:
        return
    Path(OUT).mkdir(parents=True, exist_ok=True)
    for name in ('range', 'save', 'singleIdentical'):
        if EVIDENCE.get(name):
            file = 'single-identical.json' if name == 'singleIdentical' else name + '.json'
            Path(OUT, file).write_text(json.dumps(EVIDENCE[name], separators=(',', ':'), sort_keys=True) + '\n')


class DoubleGrapnelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def open(self, url=None, query='', freeze=True):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
        self.addCleanup(context.close)
        if freeze:
            context.add_init_script(FREEZE)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto((url or self.url) + query)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        return page

    def test_01_effective_range_and_circle(self):
        out = EVIDENCE['range']
        for name, query in (('imported', ''), ('replacement', '?grappleFixture=replacement-v1')):
            page = self.open(query=query)
            rows = {}
            for upgraded in (False, True):
                for mode in ('single', 'double'):
                    page.evaluate('([u, m]) => { floors[0].rangeUpgraded = u; setGrapnelMode(m) }', [upgraded, mode])
                    rows[('upgraded-' if upgraded else 'base-') + mode] = {
                        'range': page.evaluate('grappleOverAcquisitionRadius()'),
                        'circleRadii': page.evaluate(CIRCLE)}
            for key, row in rows.items():
                self.assertEqual(row['circleRadii'], [row['range']], key)
            for stage in ('base', 'upgraded'):
                self.assertEqual(rows[stage + '-double']['range'], 2 * rows[stage + '-single']['range'])
            self.assertEqual(page.errors, [])
            out[name] = rows
        self.assertEqual((out['imported']['base-single']['range'], out['imported']['base-double']['range']), (540, 1080))
        self.assertEqual((out['replacement']['base-single']['range'], out['replacement']['upgraded-single']['range'],
                          out['replacement']['upgraded-double']['range']), (360, 540, 1080))
        out['ratio'] = {f'{n}-{s}': out[n][s + '-double']['range'] / out[n][s + '-single']['range']
                        for n in ('imported', 'replacement') for s in ('base', 'upgraded')}

    def test_02_target_800_attaches_only_in_double(self):
        page = self.open()
        shots = {mode: page.evaluate(SHOT, [800, mode, True]) for mode in ('single', 'double')}
        self.assertEqual(shots['single']['range'], 540)
        self.assertFalse(shots['single']['grappled'])
        self.assertIsNone(shots['single']['attachedTick'])
        self.assertEqual(shots['single']['traveled'], 540)
        self.assertEqual(shots['double']['range'], 1080)
        self.assertTrue(shots['double']['grappled'])
        self.assertEqual(shots['double']['anchor'], 'target')
        self.assertEqual(page.errors, [])
        EVIDENCE['range']['shot800'] = shots

    def test_03_save_round_trip_and_old_save(self):
        page = self.open()
        out = EVIDENCE['save']
        self.assertEqual(page.evaluate('[floors[0].grapnelMode, floors[0].usedDouble]'), ['single', False])
        page.evaluate("setGrapnelMode('double')")
        save = page.evaluate('captureClimbState()')
        self.assertEqual((save['grapnelMode'], save['usedDouble']), ('double', True))
        page.evaluate('s => { CLIMB_UI.restart(); restoreClimbState(s) }', save)
        out['doubleRoundTrip'] = page.evaluate('({mode: floors[0].grapnelMode, usedDouble: floors[0].usedDouble,'
                                               ' range: grappleOverAcquisitionRadius()})')
        self.assertEqual(out['doubleRoundTrip'], {'mode': 'double', 'usedDouble': True, 'range': 1080})
        # Switching back to single keeps usedDouble for the run, and through a save.
        page.evaluate("setGrapnelMode('single')")
        save = page.evaluate('captureClimbState()')
        page.evaluate('s => { CLIMB_UI.restart(); restoreClimbState(s) }', save)
        out['singleAfterDouble'] = page.evaluate('({mode: floors[0].grapnelMode, usedDouble: floors[0].usedDouble,'
                                                 ' range: grappleOverAcquisitionRadius()})')
        self.assertEqual(out['singleAfterDouble'], {'mode': 'single', 'usedDouble': True, 'range': 540})
        # A save from before TASK-718 has neither field.
        page.evaluate("setGrapnelMode('double')")
        old = page.evaluate('captureClimbState()')
        del old['grapnelMode'], old['usedDouble']
        page.evaluate('s => restoreClimbState(s)', old)
        out['oldSave'] = page.evaluate('({keys: [], mode: floors[0].grapnelMode, usedDouble: floors[0].usedDouble,'
                                       ' range: grappleOverAcquisitionRadius()})')
        out['oldSave']['keys'] = sorted(old)
        self.assertEqual((out['oldSave']['mode'], out['oldSave']['usedDouble'], out['oldSave']['range']),
                         ('single', False, 540))
        bad = page.evaluate('''s => { try { restoreClimbState({...s, grapnelMode: 'triple'}); return 'accepted' }
            catch (e) { return e.message } }''', old)
        self.assertEqual(bad, 'InvalidClimbState')
        out['invalidMode'] = bad
        # A restart is a new run: single and not used.
        page.evaluate("setGrapnelMode('double'); CLIMB_UI.restart()")
        out['afterRestart'] = page.evaluate('[floors[0].grapnelMode, floors[0].usedDouble]')
        self.assertEqual(out['afterRestart'], ['single', False])
        self.assertEqual(page.errors, [])

    def test_04_hud_badge(self):
        from PIL import Image
        page = self.open(freeze=False)
        page.evaluate("I18N.language = 'en'")
        self.assertEqual(page.evaluate("I18N.t('climb.doubleRange')"), 'x2 RANGE')
        texts, crops = {}, {}
        for mode in ('single', 'double'):
            page.evaluate('m => setGrapnelMode(m)', mode)
            page.evaluate('''() => new Promise(r => { window.__texts = []; const f = CLIMB_UI.text
                CLIMB_UI.text = function(t) { window.__texts.push(String(t)); return f.apply(this, arguments) }
                requestAnimationFrame(() => requestAnimationFrame(() => { CLIMB_UI.text = f; r() })) })''')
            texts[mode] = page.evaluate('window.__texts')
            crops[mode] = page.screenshot(clip={'x': 0, 'y': 0, 'width': 260, 'height': 175})
        self.assertNotIn('x2 RANGE', texts['single'])
        self.assertIn('x2 RANGE', texts['double'])
        self.assertNotEqual(crops['single'], crops['double'])
        self.assertEqual(page.errors, [])
        EVIDENCE['range']['badge'] = {m: {'x2RangeDrawn': 'x2 RANGE' in texts[m]} for m in texts}
        if OUT:
            Path(OUT).mkdir(parents=True, exist_ok=True)
            a, b = (Image.open(io.BytesIO(crops[m])) for m in ('double', 'single'))
            sheet = Image.new('RGB', (a.width + b.width + 10, a.height), 'white')
            sheet.paste(a, (0, 0)); sheet.paste(b, (a.width + 10, 0))
            sheet.save(Path(OUT, 'badge.png'))
            EVIDENCE['range']['badge']['png'] = 'left: double (en), right: single'

    @unittest.skipUnless(BASELINE, 'DOUBLE_GRAPNEL_BASELINE_ROOT not set')
    def test_05_single_trace_identical_to_baseline(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=BASELINE))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        traces = {}
        for name, url in (('head', self.url), ('baseline', f'http://127.0.0.1:{server.server_port}/')):
            page = self.open(url)
            traces[name] = page.evaluate(SCRIPT)
            self.assertEqual(page.errors, [])
        digest = {k: hashlib.sha256(json.dumps(v, separators=(',', ':')).encode()).hexdigest() for k, v in traces.items()}
        events = traces['head']
        EVIDENCE['singleIdentical'] = {
            'ticks': len(events), 'sha256': digest, 'identical': traces['head'] == traces['baseline'],
            'baselineRoot': BASELINE, 'grappledTicks': sum(1 for r in events if r[5]),
            'throwedTicks': sum(1 for r in events if r[4]), 'last': events[-1]}
        # Digests first: a full list diff of two 400-row traces takes difflib minutes.
        first = next((i for i, (h, b) in enumerate(zip(traces['head'], traces['baseline'])) if h != b), None)
        self.assertEqual(digest['head'], digest['baseline'], 'first differing tick %s' % first)
        # The script really grapples, so the comparison covers rope physics.
        self.assertGreater(EVIDENCE['singleIdentical']['grappledTicks'], 0)


if __name__ == '__main__':
    unittest.main()
