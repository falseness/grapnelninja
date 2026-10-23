"""TASK-673: purple no-grapple zone gameplay.

Boots the real index.html, freezes the frame loop and drives the production
physics()/calcPhysics() and the real mouse handlers on small fixture levels.
The player is inside a zone while its circle overlaps it, edge and corner
tangency included. Inside, attached and in-flight ropes are dropped in the
step of entry, before that step's rope pull or acquisition, and no press
grapples. Position, momentum, gravity and bounces are untouched.

Input semantics (unchanged from fall recovery, TASK-662): a press whose rope
was dropped, or that was made inside a zone, stays stale until released. Held
input therefore never attaches after exit either: a fresh press is required.

Fixtures set the initial state only; trajectories run unmodified. Membership
is checked every step against an independent circle/rectangle distance.

NO_GRAPPLE_EVIDENCE_DIR=DIR writes compact transitions.json and physics.json.

    python3 -m unittest discover -s tools -p test_no_grapple_physics.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot, select_mode

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 1e-6  # NO_GRAPPLE_TANGENCY_TOLERANCE in fixedlevel.js
SOURCES = ('fixedlevel.js', 'physics.js', 'events.js', 'sprites/grapnel.js', 'sprites/ninja.js',
           'tools/test_no_grapple_physics.py')

HELPERS = '''() => {
    window.requestAnimationFrame = () => 0
    menu.unPause()
    cancelAnimationFrame(game)
    const rect = (id, x, y, w, h, role) => ({id, x, y, role, grapplable: role === 'solid' || role === 'bounce',
        points: [{x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}]})
    window.NG = {
        // spec: {zones, panels, drags}: lists of [id, x, y, w, h(, role)] in world units.
        world(spec) {
            const d = structuredClone(GRAPPLE_OVER_LEVEL)
            d.bounds = {left: -5000, top: -5000, right: 8000, bottom: 8000}
            d.spawn = {x: 0, y: 4000}
            d.finish = null
            const panels = (spec.panels || []).map(([id, x, y, w, h, role = 'solid']) => rect(id, x, y, w, h, role))
            d.elements = [...panels,
                ...(spec.zones || []).map(([id, x, y, w, h]) => rect(id, x, y, w, h, 'no-grapple')),
                ...(spec.drags || []).map(([id, x, y, w, h]) => rect(id, x, y, w, h, 'drag'))]
            d.encounters[0].elements = d.elements.map(e => e.id)
            floors = [loadFixedLevel(d)]
            screen.leftWall = null
            Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null,
                clip: null, traveled: 0, speedX: 0, speedY: 0})
            pressHeld = stalePress = gameplayPressOwned = false
            NG.log = []
            return {zones: floors[0].noGrappleZones.length, elements: floors[0].elements.length,
                drags: floors[0].dragZones.length}
        },
        place(x, y, vx, vy) {
            ninja.x = x; ninja.y = y; ninja.speedX = vx; ninja.speedY = vy
            ninja.track.pos = []
            screen.trackGrappleOver(true)
        },
        attach(id) {
            const e = floors[0].byId.get(id)
            Object.assign(grapnel, {throwed: true, grappled: true, shotStep: null, aim: null, clip: null,
                pos: [[e.x, e.y + e.getPoints()[2].y / 2, e]]})
        },
        fly() {
            Object.assign(grapnel, {throwed: true, grappled: false, shotStep: null, clip: null, traveled: 100,
                aim: {x: 0, y: -1}, speedX: 0, speedY: -grapnelSpeed, pos: [[ninja.x, ninja.y - 100, new Empty()]]})
        },
        snap() {
            const g = grapnel
            return {x: ninja.x, y: ninja.y, vx: ninja.speedX, vy: ninja.speedY,
                inside: floors[0].playerInNoGrapple === true, thrown: g.throwed, attached: g.grappled,
                anchor: g.grappled ? g.pos[g.pos.length - 1][2].id : null,
                held: pressHeld, stale: stalePress, owned: gameplayPressOwned}
        },
        // Record every production calcPhysics() step of the next `ticks` physics() ticks.
        ticks(n, stop) {
            const calc = calcPhysics
            calcPhysics = function() {
                const before = NG.snap(), r = calc()
                NG.log.push({step: floors[0].elapsedSteps, before, after: NG.snap()})
                return r
            }
            try { for (let i = 0; i < n && !(stop && stop()); i++) physics() } finally { calcPhysics = calc }
            return NG.snap()
        },
        // One production step with the position held: gravity is cancelled for this step only.
        still() {
            ninja.speedX = 0; ninja.speedY = -GRAVITY
            const before = NG.snap()
            calcPhysics()
            return {before, after: NG.snap()}
        }
    }
    return {radius: ninja.radius, gravity: GRAVITY, pull: grappleSpeed, range: grappleOverAcquisitionRadius(),
        cyclesPerTick, version}
}'''


def rect_distance(x, y, zone):
    _, zx, zy, w, h = zone[:5]
    dx = max(zx - x, 0, x - (zx + w))
    dy = max(zy - y, 0, y - (zy + h))
    return math.hypot(dx, dy)


def zones_containing(x, y, radius, zones):
    return [z[0] for z in zones if rect_distance(x, y, z) <= radius + TOLERANCE]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


class NoGrapplePhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.proof = {'revision': git('rev-parse', 'HEAD'),
                     'sourceHashes': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in SOURCES},
                     'browser': cls.browser.version, 'viewport': [1280, 720]}
        cls.transitions = dict(cls.proof)
        cls.physics = dict(cls.proof)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        out = os.environ.get('NO_GRAPPLE_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            for name, data in (('transitions.json', cls.transitions), ('physics.json', cls.physics)):
                Path(out, name).write_text(json.dumps(data, separators=(',', ':'), sort_keys=True) + '\n')

    def open(self, mode='grapple_over'):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate('m => { startGame(m); cancelAnimationFrame(game) }', mode)
        page.wait_for_function('!unTouch')
        self.constants = page.evaluate(HELPERS)
        self.radius = self.constants['radius']
        self.addCleanup(lambda: self.assertEqual(page.errors, []))
        return page

    def press(self, page, x, y):
        """Real mousedown at world point (x, y)."""
        p = page.evaluate('''([x, y]) => canvasCoordsToViewportCoords({
            x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})''', [x, y])
        self.assertTrue(0 < p['x'] < 1280 and 0 < p['y'] < 720, p)
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()

    def snap(self, page):
        return page.evaluate('NG.snap()')

    def check_membership(self, steps, zones):
        """Production membership equals the independent circle test on every step."""
        for row in steps:
            a = row['after']
            self.assertEqual(a['inside'], bool(zones_containing(a['x'], a['y'], self.radius, zones)), row)
            if a['inside']:
                self.assertFalse(a['thrown'] or a['attached'], row)

    # ---- transitions.json -------------------------------------------------

    def test_01_chronological_transitions(self):
        """outside -> boundary -> inside -> exit -> re-entry, overlapping zones, real input."""
        page = self.open()
        r = self.radius
        zones = [['A', 1000, -1500, 400, 3000], ['B', 1800, -1500, 400, 3000], ['C', 2100, -1500, 500, 3000]]
        panels = [['inner', 1180, -300, 80, 20], ['anchor', 1560, -330, 80, 20]]
        page.evaluate('s => NG.world(s)', {'zones': zones, 'panels': panels})
        x0 = page.evaluate('r => 1000 - r - 4 * 40', r)
        page.evaluate('x0 => NG.place(x0, 0, 4, 0)', x0)
        events = []

        # Outside: a real press into empty air flies and parks while held.
        self.press(page, x0 - 180, -240)
        page.evaluate('NG.ticks(2)')
        start = self.snap(page)
        self.assertTrue(start['thrown'] and not start['attached'] and start['held'] and start['owned'])
        self.assertFalse(start['inside'])
        events.append({'event': 'outside, held press in flight/parked', 'state': start})

        # Boundary: the first step whose circle touches A is the step the rope is dropped.
        page.evaluate("NG.ticks(40, () => floors[0].playerInNoGrapple)")
        log = page.evaluate('NG.log')
        self.check_membership(log, zones)
        entry = next(i for i, row in enumerate(log) if row['after']['inside'])
        prev, at = log[entry - 1], log[entry]
        gap = rect_distance(at['after']['x'], at['after']['y'], zones[0]) - r
        self.assertLess(abs(gap), TOLERANCE)
        self.assertLess(at['after']['x'], 1000)  # centre outside, circle tangent
        self.assertTrue(prev['after']['thrown'] and not prev['after']['inside'])
        self.assertTrue(at['before']['thrown'])
        self.assertFalse(at['after']['thrown'])
        self.assertEqual((at['after']['vx'], at['after']['vy']), (at['before']['vx'], at['before']['vy'] + self.constants['gravity']))
        self.assertTrue(at['after']['held'] and at['after']['stale'] and not at['after']['owned'])
        events.append({'event': 'boundary: edge tangency, in-flight rope dropped this step', 'step': at['step'],
                       'distanceMinusRadius': gap, 'previous': prev['after'], 'before': at['before'], 'after': at['after']})

        # Centre outside, circle overlapping: still inside, nothing thrown.
        page.evaluate('NG.log = []; NG.ticks(1)')
        log = page.evaluate('NG.log')
        self.check_membership(log, zones)
        overlap = next(row for row in log if row['after']['x'] < 1000 and
                       rect_distance(row['after']['x'], 0, zones[0]) < r - 1)
        events.append({'event': 'centre outside, circle overlaps', 'step': overlap['step'], 'after': overlap['after'],
                       'centreToEdge': 1000 - overlap['after']['x']})

        # Inside, still held: steering the held pointer at a panel in range never attaches.
        page.mouse.move(*self.viewport(page, 1220, -290).values())
        page.evaluate('NG.log = []; NG.ticks(3)')
        held = page.evaluate('NG.log')
        self.check_membership(held, zones)
        self.assertTrue(all(row['after']['inside'] and not row['after']['thrown'] for row in held))
        # Repeated input inside: release and a new press aimed straight at the panel.
        page.mouse.up()
        released = self.snap(page)
        self.assertFalse(released['stale'] or released['held'])
        center = self.snap(page)
        self.assertGreater(center['x'], 1000)
        distance_to_inner = math.hypot(1220 - center['x'], -290 - center['y'])
        self.assertLess(distance_to_inner, self.constants['range'])
        self.press(page, 1220, -290)
        repress = self.snap(page)
        self.assertFalse(repress['thrown'])
        self.assertTrue(repress['held'] and repress['stale'] and not repress['owned'])
        page.evaluate('NG.log = []; NG.ticks(4)')
        inside_rows = page.evaluate('NG.log')
        self.check_membership(inside_rows, zones)
        self.assertTrue(all(row['after']['inside'] and not row['after']['thrown'] for row in inside_rows))
        events.append({'event': 'inside: held input and a repeated press aimed at a panel in range never throw',
                       'heldSteps': len(held), 'repressAt': repress, 'pressTargetDistance': distance_to_inner,
                       'stepsAfterRepress': len(inside_rows), 'thrownAnyStep': False})

        # Exit A while the press made inside is still held: no rope after exit either.
        page.evaluate('NG.log = []; NG.ticks(30, () => !floors[0].playerInNoGrapple)')
        log = page.evaluate('NG.log')
        self.check_membership(log, zones)
        exit_row = next(row for row in log if not row['after']['inside'])
        self.assertGreater(rect_distance(exit_row['after']['x'], exit_row['after']['y'], zones[0]), r + TOLERANCE)
        self.assertTrue(exit_row['before']['inside'])
        page.mouse.move(*self.viewport(page, 1600, -320).values())
        page.evaluate('NG.log = []; NG.ticks(2)')
        after_exit = page.evaluate('NG.log')
        self.check_membership(after_exit, zones)
        self.assertTrue(all(not row['after']['thrown'] and not row['after']['inside'] for row in after_exit))
        events.append({'event': 'exit A; press made inside still held: no rope (needs a fresh press)',
                       'exitStep': exit_row['step'], 'before': exit_row['before'], 'after': exit_row['after'],
                       'heldStepsAfterExit': len(after_exit), 'thrownAnyStep': False})

        # A valid fresh press after exit attaches to the anchor between the zones.
        page.mouse.up()
        self.press(page, 1600, -320)
        page.evaluate("NG.log = []; NG.ticks(10, () => grapnel.grappled)")
        log = page.evaluate('NG.log')
        self.check_membership(log, zones)
        fresh = self.snap(page)
        self.assertTrue(fresh['attached'] and fresh['owned'] and not fresh['inside'])
        self.assertEqual(fresh['anchor'], 'anchor')
        events.append({'event': 'fresh press after exit attaches', 'state': fresh, 'stepsToAttach': len(log)})

        # Re-entry into B with an attached rope: dropped in the entry step, before its pull.
        page.evaluate("NG.log = []; NG.ticks(60, () => floors[0].playerInNoGrapple)")
        log = page.evaluate('NG.log')
        self.check_membership(log, zones)
        entry = next(i for i, row in enumerate(log) if row['after']['inside'])
        prev, at = log[entry - 1], log[entry]
        g, pull = self.constants['gravity'], self.constants['pull']
        pulled = (prev['after']['vx'] - prev['before']['vx'], prev['after']['vy'] - prev['before']['vy'] - g)
        self.assertTrue(prev['after']['attached'] and at['before']['attached'])
        self.assertAlmostEqual(math.hypot(*pulled), pull, places=12)
        self.assertFalse(at['after']['thrown'] or at['after']['attached'])
        self.assertEqual(at['after']['vx'], at['before']['vx'])
        self.assertEqual(at['after']['vy'], at['before']['vy'] + g)
        self.assertEqual(zones_containing(at['after']['x'], at['after']['y'], r, zones), ['B'])
        events.append({'event': 're-entry (B) with attached rope: dropped before rope pull',
                       'step': at['step'], 'previousStepPull': pulled, 'pullMagnitude': pull,
                       'entryStepVelocityDelta': [at['after']['vx'] - at['before']['vx'], at['after']['vy'] - at['before']['vy']],
                       'gravity': g, 'before': at['before'], 'after': at['after']})

        # Overlapping zones: B -> B and C -> only C -> outside all. Inside until clear of every zone.
        page.evaluate('NG.log = []; NG.ticks(40, () => !floors[0].playerInNoGrapple)')
        log = page.evaluate('NG.log')
        self.check_membership(log, zones)
        sets = [zones_containing(row['after']['x'], row['after']['y'], r, zones) for row in log]
        self.assertIn(['B', 'C'], sets)
        self.assertIn(['C'], sets)
        self.assertEqual(sets[-1], [])
        self.assertTrue(all(row['after']['inside'] for row, s in zip(log, sets) if s))
        last_c = max(i for i, s in enumerate(sets) if s)
        self.assertLess(abs(rect_distance(log[last_c]['after']['x'], 0, zones[2]) - r), 4.01)
        first = {}
        for row, s in zip(log, sets):
            first.setdefault('+'.join(s) or 'outside', {'step': row['step'], 'x': row['after']['x'],
                                                        'inside': row['after']['inside'], 'thrown': row['after']['thrown']})
        events.append({'event': 'overlapping zones B/C: inside until outside every zone', 'firstStepPerZoneSet': first,
                       'stepsChecked': len(log)})
        self.transitions['chronological'] = {'radius': r, 'zones': zones, 'panels': panels, 'startX': x0,
                                             'startVelocity': [4, 0], 'events': events}
        print('PASS chronological: outside -> tangent entry -> inside (held/repeat blocked) -> exit -> fresh attach -> '
              're-entry dropped before pull -> overlapping B/C -> outside')

    def viewport(self, page, x, y):
        return page.evaluate('''([x, y]) => canvasCoordsToViewportCoords({
            x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})''', [x, y])

    def test_02_boundary_cases(self):
        """One production step per case with the position held still; ropes set as initial state."""
        page = self.open()
        r = self.radius
        zones = [['Z', 1000, -200, 400, 400], ['Y', 1300, 100, 400, 400]]
        page.evaluate('s => NG.world(s)', {'zones': zones, 'panels': [['anchor', 600, -600, 80, 20]]})
        d = r + 1e-3
        cases = [
            ('edge tangent', 1000 - r, 0, True),
            ('edge just outside', 1000 - d, 0, False),
            ('centre outside, circle overlaps', 1000 - r / 2, 0, True),
            ('corner tangent', 1000 - 0.6 * r, -200 - 0.8 * r, True),
            ('corner just outside', 1000 - 0.6 * d, -200 - 0.8 * d, False),
            ('corner bounding box overlaps, circle outside', 1000 - 0.75 * r, -200 - 0.75 * r, False),
            ('centre inside', 1200, 0, True),
            ('overlap of Z and Y', 1350, 150, True),
            ('only Y', 1600, 400, True),
            ('Y corner tangent', 1700 + 0.8 * r, 500 + 0.6 * r, True),
        ]
        rows = []
        for name, x, y, expected in cases:
            for rope in ('attach', 'fly'):
                page.evaluate('([x, y]) => NG.place(x, y, 0, 0)', [x, y])
                page.evaluate("NG.%s('anchor')" % rope if rope == 'attach' else 'NG.fly()')
                res = page.evaluate('NG.still()')
                b, a = res['before'], res['after']
                inside = zones_containing(x, y, r, zones)
                self.assertEqual(bool(inside), expected, name)
                self.assertEqual(a['inside'], expected, name)
                self.assertEqual((a['x'], a['y']), (x, y))
                self.assertTrue(b['thrown'])
                self.assertEqual(a['thrown'], not expected, (name, rope))
                if rope == 'attach':
                    self.assertEqual(a['attached'], not expected)
                    if expected:  # no pull in the entry step
                        self.assertEqual((a['vx'], a['vy']), (0, 0))
                    else:
                        self.assertNotEqual((a['vx'], a['vy']), (0, 0))
                rows.append({'case': name, 'rope': rope, 'centre': [x, y], 'zones': inside,
                             'distanceMinusRadius': min(rect_distance(x, y, z) for z in zones) - r,
                             'inside': a['inside'], 'ropeBefore': b['thrown'], 'ropeAfter': a['thrown'],
                             'velocityAfter': [a['vx'], a['vy']]})
        self.transitions['boundary'] = {'radius': r, 'tolerance': TOLERANCE, 'zones': zones, 'cases': rows}
        print('PASS boundary: %d cases (edge/corner tangency, centre-outside overlap, overlapping zones, attached+in-flight)'
              % len(rows))

    def test_03_held_through_zone(self):
        """A press held from outside through entry and exit never re-attaches; a fresh press does."""
        page = self.open()
        zones = [['A', 1000, -1500, 300, 3000]]
        page.evaluate('s => NG.world(s)', {'zones': zones, 'panels': [['anchor', 1500, -330, 80, 20]]})
        page.evaluate('NG.place(800, 0, 4, 0)')
        self.press(page, 1540, -320)
        page.evaluate("NG.ticks(10, () => grapnel.grappled)")
        self.assertTrue(self.snap(page)['attached'])
        page.evaluate('NG.log = []; NG.ticks(40, () => floors[0].playerInNoGrapple)')
        page.evaluate('NG.ticks(40, () => !floors[0].playerInNoGrapple)')
        page.evaluate('NG.ticks(3)')
        log = page.evaluate('NG.log')
        self.check_membership(log, zones)
        entered = next(row for row in log if row['after']['inside'])
        self.assertTrue(entered['before']['attached'] and not entered['after']['thrown'])
        after = [row for row in log if row['step'] > entered['step'] and not row['after']['inside']]
        self.assertTrue(after)
        self.assertTrue(all(not row['after']['thrown'] and row['after']['held'] and row['after']['stale'] for row in after))
        page.mouse.up()
        self.press(page, 1540, -320)
        page.evaluate("NG.ticks(10, () => grapnel.grappled)")
        fresh = self.snap(page)
        self.assertTrue(fresh['attached'] and fresh['anchor'] == 'anchor')
        self.transitions['heldThroughZone'] = {
            'zones': zones, 'entry': {'step': entered['step'], 'before': entered['before'], 'after': entered['after']},
            'stepsOutsideAfterExitWhileHeld': len(after), 'thrownWhileHeldAfterExit': False,
            'heldAndStaleAfterExit': True, 'freshPress': fresh,
            'semantics': 'unchanged input ownership: a dropped/blocked press stays stale until released; '
                         'held input needs a fresh press after exit'}
        print('PASS held through zone: no re-attach while held after exit (%d steps); fresh press attaches' % len(after))

    # ---- physics.json -----------------------------------------------------

    def trajectory(self, page, spec, start, ticks, attach=None):
        page.evaluate('s => NG.world(s)', spec)
        page.evaluate('([x, y, vx, vy]) => NG.place(x, y, vx, vy)', start)
        if attach:
            page.evaluate('id => NG.attach(id)', attach)
        page.evaluate('n => NG.ticks(n)', ticks)
        return page.evaluate('NG.log')

    def test_04_matched_trajectories(self):
        page = self.open()
        zone = ['P', 1000, -400, 400, 1000]
        cases = {
            'freeFlightThroughZone': ({'panels': []}, [700, 0, 4, -1], 40),
            'bounceInsideZone': ({'panels': [['pad', 1100, 300, 200, 20, 'bounce']]}, [1200, 0, 0.5, 2], 60),
            'solidInsideZone': ({'panels': [['floor', 1050, 300, 300, 20, 'solid']]}, [1200, 0, -0.1, 2], 60),
        }
        out = {}
        for name, (spec, start, ticks) in cases.items():
            runs = {}
            for variant in ('none', 'purple', 'drag'):
                s = dict(spec)
                if variant == 'purple':
                    s['zones'] = [zone]
                if variant == 'drag':
                    s['drags'] = [zone]
                runs[variant] = [[row['after'][k] for k in ('x', 'y', 'vx', 'vy')] for row in
                                 self.trajectory(page, s, start, ticks)]
            inside = [bool(zones_containing(x, y, self.radius, [zone])) for x, y, _, _ in runs['purple']]
            self.assertTrue(any(inside))
            self.assertEqual(runs['purple'], runs['none'], name)
            self.assertNotEqual(runs['drag'], runs['none'], name)
            vy = [v[3] for v in runs['purple']]
            flips = sum(1 for a, b in zip(vy, vy[1:]) if a > 0 and b < 0)
            contacts = None
            if name == 'bounceInsideZone':
                self.assertGreaterEqual(flips, 1)
                contacts = flips
            if name == 'solidInsideZone':  # rests on the floor, never passes through it
                self.assertLess(max(y for _, y, _, _ in runs['purple']), 300 - self.radius + 1)
                self.assertLess(abs(runs['purple'][-1][1] - (300 - self.radius)), 1)
                contacts = max(y for _, y, _, _ in runs['purple'])
            max_delta = max(abs(a - b) for p, n in zip(runs['purple'], runs['none']) for a, b in zip(p, n))
            drag_delta = max(abs(a - b) for p, n in zip(runs['drag'], runs['none']) for a, b in zip(p, n))
            out[name] = {'start': start, 'ticks': ticks, 'steps': len(runs['purple']), 'stepsInsidePurple': sum(inside),
                         'maxAbsDeltaPurpleVsNone': max_delta, 'identicalPurpleVsNone': True,
                         'maxAbsDeltaDragVsNone': drag_delta, 'bounceFlipsOrSolidMaxY': contacts,
                         'final': {v: runs[v][-1] for v in runs}}
        self.physics['matchedNoRope'] = {'zone': zone, 'compare': '[x, y, vx, vy] after every calcPhysics step',
                                         'cases': out}
        print('PASS matched no-rope trajectories: purple == none bit-for-bit (%d cases); drag control differs'
              % len(out))

    def test_05_entry_keeps_momentum(self):
        page = self.open()
        zone = ['P', 1000, -1500, 400, 3000]
        spec = {'panels': [['anchor', 1560, -420, 80, 20]]}
        start = [700, 0, 4, 0]
        none = self.trajectory(page, spec, start, 30, attach='anchor')
        purple = self.trajectory(page, dict(spec, zones=[zone]), start, 30, attach='anchor')
        entry = next(i for i, row in enumerate(purple) if row['after']['inside'])
        key = lambda row: [row['after'][k] for k in ('x', 'y', 'vx', 'vy', 'attached')]
        self.assertEqual([key(r) for r in purple[:entry]], [key(r) for r in none[:entry]])
        at = purple[entry]
        g = self.constants['gravity']
        self.assertTrue(at['before']['attached'] and not at['after']['attached'])
        self.assertEqual(at['after']['vx'], at['before']['vx'])
        self.assertEqual(at['after']['vy'], at['before']['vy'] + g)
        self.assertNotEqual(none[entry]['after']['vx'], none[entry]['before']['vx'])
        later = [row for row in purple[entry + 1:] if row['after']['inside']]
        self.assertTrue(later)
        for row in later:
            self.assertEqual(row['after']['vx'], row['before']['vx'])
            self.assertEqual(row['after']['vy'], min(row['before']['vy'] + g, 21.6))
        self.physics['entryMomentum'] = {
            'zone': zone, 'start': start, 'anchor': 'anchor', 'entryStepIndex': entry, 'identicalBeforeEntry': True,
            'entry': {'before': at['before'], 'after': at['after'],
                      'velocityDelta': [at['after']['vx'] - at['before']['vx'], at['after']['vy'] - at['before']['vy']],
                      'gravity': g},
            'noZoneSameStepVelocityDelta': [none[entry]['after']['vx'] - none[entry]['before']['vx'],
                                            none[entry]['after']['vy'] - none[entry]['before']['vy']],
            'insideStepsAfterEntryGravityOnly': len(later)}
        print('PASS entry: rope dropped, velocity kept (delta = gravity only), %d later inside steps unbraked' % len(later))

    def test_06_rope_across_zone(self):
        page = self.open()
        zone = ['P', 900, -300, 200, 600]
        panels = [['far', 1200, -60, 40, 120], ['zoned', 1000, 150, 40, 100]]
        spec = {'zones': [zone], 'panels': panels}
        g, pull = self.constants['gravity'], self.constants['pull']
        # Attached rope crossing the zone, player outside: stays attached and pulls every step.
        rows = {}
        for variant, s in (('purple', spec), ('none', {'panels': panels})):
            rows[variant] = self.trajectory(page, s, [700, 0, -1, 0], 20, attach='far')
        log = rows['purple']
        self.check_membership(log, [zone])
        for row in log:
            b, a = row['before'], row['after']
            self.assertTrue(a['attached'] and a['anchor'] == 'far' and not a['inside'])
            self.assertAlmostEqual(math.hypot(a['vx'] - b['vx'], a['vy'] - b['vy'] - g), pull, places=12)
        self.assertEqual([r['after'] for r in rows['purple']], [r['after'] for r in rows['none']])
        # Real presses from outside across the zone acquire the panel behind it and one inside it.
        acquired = {}
        for target, aim in (('far', [1200, 0]), ('zoned', [1000, 200])):
            page.evaluate('s => NG.world(s)', spec)
            page.evaluate('NG.place(700, 0, 0, 0)')
            self.press(page, *aim)
            page.evaluate("NG.log = []; NG.ticks(10, () => grapnel.grappled)")
            steps = page.evaluate('NG.log')
            self.check_membership(steps, [zone])
            s = self.snap(page)
            self.assertTrue(s['attached'] and not s['inside'])
            self.assertEqual(s['anchor'], target)
            line = page.evaluate('''() => { const [ax, ay] = grapnel.pos[0]; const z = floors[0].noGrappleZones[0]
                const p = z.getPoints(); let crosses = false
                for (let t = 0; t <= 1; t += 1 / 512) if (pointInPolygon(p, ninja.x + (ax - ninja.x) * t,
                    ninja.y + (ay - ninja.y) * t)) crosses = true
                return {anchor: [ax, ay], crossesZone: crosses} }''')
            self.assertTrue(line['crossesZone'])
            page.mouse.up()
            acquired[target] = {'aim': aim, 'state': s, 'steps': len(steps), **line}
        self.physics['ropeAcrossZone'] = {
            'zone': zone, 'panels': panels,
            'attached': {'steps': len(log), 'attachedEveryStep': True, 'insideAnyStep': False,
                         'pullEveryStep': pull, 'identicalToNoZone': True, 'first': log[0], 'last': log[-1]},
            'acquired': acquired}
        print('PASS rope across purple: attached %d steps with pull, identical to no-zone; acquired far and in-zone panels'
              % len(log))

    def test_07_mode_and_reset_isolation(self):
        page = self.open()
        zones = [['A', 1000, -1500, 400, 3000]]
        page.evaluate('s => NG.world(s)', {'zones': zones, 'panels': [['inner', 1180, -300, 80, 20]]})
        page.evaluate('NG.place(1200, 0, 0, 0)')
        self.press(page, 1220, -290)
        page.evaluate('NG.ticks(2)')
        blocked = self.snap(page)
        self.assertTrue(blocked['inside'] and not blocked['thrown'] and blocked['stale'])
        page.mouse.up()
        # Reset: a fresh grapple_over run on the shipped level has no zones and grapples normally.
        page.evaluate("() => { startGame('grapple_over'); menu.unPause(); cancelAnimationFrame(game) }")
        page.wait_for_function('!unTouch')
        reset = page.evaluate('''() => { for (let i = 0; i < 3; i++) physics()
            return {zones: floors[0].noGrappleZones.length, inside: floors[0].playerInNoGrapple,
                    elements: floors[0].elements.length, layout: floors[0].level.layoutId || null, stale: stalePress} }''')
        self.assertEqual(reset['zones'], 0)
        self.assertFalse(reset['inside'])
        self.assertFalse(reset['stale'])
        p = page.evaluate('''() => canvasCoordsToViewportCoords({x: (ninja.x + 0.6 * 300 + screen.x) * scale[version],
            y: (ninja.y - 0.8 * 300 + screen.y) * scale[version]})''')
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        reset['pressThrows'] = page.evaluate('grapnel.throwed')
        self.assertTrue(reset['pressThrows'])
        page.mouse.up()
        modes = {'grapple_over_reset': reset, 'blockedBeforeReset': blocked}
        for mode in ('classic', 'bad'):
            select_mode(page, mode)
            page.evaluate('() => { menu.unPause(); window.requestAnimationFrame = () => 0; cancelAnimationFrame(game) }')
            page.wait_for_function('!unTouch')
            r = page.evaluate('''() => { const out = {version, hasZones: 'noGrappleZones' in floors[0]}
                const before = {x: ninja.x, y: ninja.y}
                for (let i = 0; i < 5; i++) physics()
                out.moved = ninja.x !== before.x || ninja.y !== before.y
                return out }''')
            p = page.evaluate('''() => canvasCoordsToViewportCoords({x: (ninja.x + 200 + screen.x) * scale[version],
                y: (ninja.y - 200 + screen.y) * scale[version]})''')
            page.mouse.move(p['x'], p['y'])
            page.mouse.down()
            r['pressThrows'] = page.evaluate('grapnel.throwed')
            page.evaluate('() => { for (let i = 0; i < 3; i++) physics() }')
            page.mouse.up()
            self.assertEqual(r['version'], mode)
            self.assertFalse(r['hasZones'])
            self.assertTrue(r['moved'])
            self.assertTrue(r['pressThrows'])
            modes[mode] = r
        self.transitions['modeAndReset'] = modes
        print('PASS mode/reset isolation: reset run has no zones and throws; classic/bad unaffected (3 checks)')


if __name__ == '__main__':
    unittest.main()
