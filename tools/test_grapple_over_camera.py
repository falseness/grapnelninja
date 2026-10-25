"""TASK-449/TASK-692: centered runtime camera and fixed-clock regression proof."""
from functools import partial
from http.server import ThreadingHTTPServer
import hashlib
import io
import json
import math
import os
import subprocess
import tarfile
import tempfile
from threading import Thread
import unittest

import test_grapple_over_world as world
from browser_test_support import QuietHandler, wait_for_boot
from grapple_over_test_support import ROOT
from perf_mobile import SEED_SCRIPT

# The commit just before TASK-692 centered the camera; classic and bad must
# replay byte for byte against it.
LEGACY_BASELINE = os.environ.get('GRAPPLE_OVER_CAMERA_BASELINE', '77906ff')
ALPHA = -math.expm1(-(1 / 60) / .18)
LEGACY_TRACE = '''() => {
    const rows = [];
    // Scripted input: keep pushing right and bounce the player in the air.
    for (let i = 0; i < 150; i++) {
        ninja.speedX = 6;
        if (ninja.speedY > 2) ninja.speedY = -3;
        physics();
        rows.push([screen.x, screen.y, screen.speedX, screen.speedY, ninja.x, ninja.y]);
    }
    return rows;
}'''


class Task449Tests(unittest.TestCase):
    TASK = 'TASK-449'
    setUpClass = classmethod(world.Task446Tests.setUpClass.__func__)
    open = world.Task446Tests.open

    def setUp(self):
        self.proof['source_hashes']['tools/test_grapple_over_camera.py'] = hashlib.sha256(
            (ROOT / 'tools/test_grapple_over_camera.py').read_bytes()).hexdigest()

    def centered_page(self):
        page = self.open()
        page.evaluate('''() => {
            window.view = () => [width/scale[version], height/scale[version]];
            // Offset of the view center from the player, in world units.
            window.offset = () => {const [w,h]=view(); return [w/2-ninja.x-screen.x, h/2-ninja.y-screen.y]};
            window.tick = () => {screen.trackGrappleOver(); return offset()};
        }''')
        return page

    # Worlds much larger than the 7680x4320 view, so no axis is small-world centered.
    def test_centering_stationary(self):
        page = self.centered_page()
        result = page.evaluate('''([fraction, big]) => {
            floors[0].level.bounds = big;
            ninja.x = 1000; ninja.y = -500; ninja.speedX = ninja.speedY = 0;
            screen.trackGrappleOver(true);
            const [w,h] = view();
            screen.x -= fraction*w; screen.y -= fraction*h;
            const rows = [offset()];
            for (let i = 0; i < 150; i++) rows.push(tick());
            return {view: view(), rows};
        }''', [.3, {'left': -40000, 'right': 40000, 'top': -40000, 'bottom': 40000}])
        w, h = result['view']
        dist = [math.hypot(*r) for r in result['rows']]
        self.assertAlmostEqual(result['rows'][0][0], .3 * w)
        self.assertAlmostEqual(result['rows'][0][1], .3 * h)
        self.assertTrue(all(b < a for a, b in zip(dist, dist[1:]) if a > 1e-9))
        # Pure exponential easing toward the center.
        for n, (x, y) in enumerate(result['rows']):
            self.assertAlmostEqual(x, .3 * w * (1 - ALPHA) ** n, delta=1e-6)
            self.assertAlmostEqual(y, .3 * h * (1 - ALPHA) ** n, delta=1e-6)
        first = next(i for i, d in enumerate(dist) if max(map(abs, result['rows'][i])) <= 1)
        self.assertLessEqual(first, 90)
        self.assertTrue(all(max(map(abs, r)) <= 1 for r in result['rows'][first:first + 61]))
        small = page.evaluate('''big => {
            floors[0].level.bounds = big;
            ninja.x = 1000; ninja.y = -500; screen.trackGrappleOver(true);
            const [w,h] = view(); screen.x -= .1*w; screen.y -= .1*h;
            const rows = [offset()];
            for (let i = 0; i < 120; i++) rows.push(tick());
            return rows;
        }''', {'left': -40000, 'right': 40000, 'top': -40000, 'bottom': 40000})
        sfirst = next(i for i, r in enumerate(small) if max(map(abs, r)) <= 1)
        sdist = [math.hypot(*r) for r in small]
        self.assertTrue(all(b < a for a, b in zip(sdist, sdist[1:]) if a > 1e-9))
        self.assertTrue(all(max(map(abs, r)) <= 1 for r in small[sfirst:]))
        self.write('stationary', {
            'view': [w, h], 'alpha': ALPHA,
            'start30': {'startOffset': result['rows'][0], 'monotonic': True,
                'firstTickWithin1': first, 'secondsWithin1': first / 60,
                'maxAbsNext60': max(max(map(abs, r)) for r in result['rows'][first:first + 61]),
                'offsets': [[round(v, 4) for v in r] for r in result['rows'][:first + 61:5]]},
            'start10InsideOldDeadZone': {'startOffset': small[0], 'monotonic': True,
                'firstTickWithin1': sfirst, 'secondsWithin1': sfirst / 60,
                'finalOffset': small[-1]}})
        print(f'PASS centering: 30% start within 1 unit at tick {first} ({first/60:.3f} s), '
              f'stays 60 ticks; 10% start within 1 unit at tick {sfirst}')

    def test_centering_moving_and_fast_fall(self):
        page = self.centered_page()
        result = page.evaluate('''big => {
            floors[0].level.bounds = big;
            const out = {};
            for (const [name, vx, vy] of [['right',1.5,0],['left',-1.5,0],['down',0,2],['up',0,-2],['diagonal',1,-1]]) {
                ninja.x = -20000*Math.sign(vx); ninja.y = -20000*Math.sign(vy);
                ninja.speedX = vx; ninja.speedY = vy; screen.trackGrappleOver(true);
                const rows = [];
                for (let i = 0; i < 400; i++) {
                    ninja.x += vx*cyclesPerTick; ninja.y += vy*cyclesPerTick;
                    rows.push(tick());
                }
                out[name] = {perTick: [vx*cyclesPerTick, vy*cyclesPerTick], rows};
            }
            // Fast fall: the eased lag would exceed half the view; the
            // visibility clamp must keep the whole circle on screen.
            ninja.x = 0; ninja.y = -30000; ninja.speedX = 0; ninja.speedY = 90;
            screen.trackGrappleOver(true);
            const fall = [];
            for (let i = 0; i < 80; i++) {
                ninja.y += ninja.speedY*cyclesPerTick; screen.trackGrappleOver();
                fall.push([ninja.y + screen.y, ninja.x + screen.x]);
            }
            out.fall = {perTick: ninja.speedY*cyclesPerTick, radius: ninja.radius, view: view(), rows: fall};
            return out;
        }''', {'left': -40000, 'right': 40000, 'top': -40000, 'bottom': 40000})
        summary = {}
        for name in ('right', 'left', 'down', 'up', 'diagonal'):
            row = result[name]
            for axis in (0, 1):
                d = row['perTick'][axis]
                expected = -d * (1 - ALPHA) / ALPHA
                values = [r[axis] for r in row['rows']]
                if d == 0:
                    self.assertTrue(all(abs(v) < 1e-9 for v in values))
                    continue
                # Camera center is never ahead of the player along the motion.
                self.assertTrue(all(v * d <= 1e-9 for v in values))
                self.assertAlmostEqual(values[-1], expected, delta=1e-6)
                summary.setdefault(name, {})['xy'[axis]] = {'perTick': d,
                    'steadyOffset': values[-1], 'expectedEasedLag': expected,
                    'oppositeSignToVelocity': values[-1] * d < 0,
                    'aheadTicks': sum(v * d > 1e-9 for v in values)}
        fall = result['fall']
        h, r = fall['view'][1], fall['radius']
        clamped = 0
        for y, x in fall['rows']:
            self.assertGreaterEqual(y, r - 1e-8)
            self.assertLessEqual(y, h - r + 1e-8)
            clamped += abs(y - (h - r)) < 1e-6
        self.assertGreater(clamped, 0)
        self.write('moving', {'alpha': ALPHA, 'axes': summary,
            'fastFall': {'perTick': fall['perTick'], 'radius': r, 'viewHeight': h,
                'ticks': len(fall['rows']), 'circleInsideEveryTick': True,
                'visibilityClampedTicks': clamped,
                'minScreenY': min(y for y, _ in fall['rows']),
                'maxScreenY': max(y for y, _ in fall['rows'])}})
        print(f'PASS moving: steady offset trails by the eased lag on 5 paths, never ahead; '
              f'fast fall circle inside view on 80 ticks ({clamped} visibility-clamped)')

    def test_centering_level_edges(self):
        page = self.centered_page()
        result = page.evaluate('''() => {
            floors[0].level.bounds = {left:0, right:30000, top:-30000, bottom:0};
            const [w,h] = view(), rows = [];
            ninja.x = 12000; ninja.y = -12000; ninja.speedX = ninja.speedY = 0;
            screen.trackGrappleOver(true);
            // Walk toward the bottom-left corner, then rest there.
            for (let i = 0; i < 360; i++) {
                if (i < 240) {ninja.x -= 48; ninja.y += 48}
                const before = [screen.x, screen.y];
                screen.trackGrappleOver();
                rows.push({before, player:[ninja.x, ninja.y], camera:[screen.x, screen.y]});
            }
            return {view:[w,h], bounds:{...floors[0].level.bounds}, rows};
        }''')
        w, h = result['view']
        b = result['bounds']
        free = {'x': 0, 'y': 0}
        clamped = {'x': 0, 'y': 0}
        for row in result['rows']:
            for axis, size, low, high in ((0, w, b['left'], b['right']), (1, h, b['top'], b['bottom'])):
                p, c, prev = row['player'][axis], row['camera'][axis], row['before'][axis]
                eased = prev + (size / 2 - p - prev) * ALPHA
                bound = min(max(eased, size - high), -low)
                self.assertGreaterEqual(c, size - high - 1e-8)
                self.assertLessEqual(c, -low + 1e-8)
                self.assertAlmostEqual(c, bound, delta=1e-6)
                key = 'xy'[axis]
                if bound != eased:
                    clamped[key] += 1
                else:
                    free[key] += 1
        last = result['rows'][-1]['camera']
        self.assertEqual(last, [-b['left'], h - b['bottom']])
        self.assertGreater(min(clamped.values()), 0)
        self.assertGreater(min(free.values()), 0)
        self.write('edges', {'bounds': b, 'view': [w, h], 'ticks': len(result['rows']),
            'clampedTicks': clamped, 'freeTicks': free, 'finalCamera': last,
            'onBoundAtRest': True, 'finalPlayerScreen': [result['rows'][-1]['player'][0] + last[0],
                result['rows'][-1]['player'][1] + last[1]]})
        # Small worlds stay centered.
        small = page.evaluate('''() => {
            floors[0].level.bounds = {left:0,right:100,top:-100,bottom:100};
            screen.trackGrappleOver(); return [screen.x, screen.y, ...view()];
        }''')
        self.assertEqual(small[:2], [(small[2] - 100) / 2, small[3] / 2])
        print(f'PASS edges: camera on bound when clamped ({clamped}), eased when free ({free}); small world centered')

    def write(self, key, value):
        path = self.evidence.path('centering.json')
        data = json.loads(path.read_text()) if path.exists() else {}
        data.update({'revision': self.proof['revision'],
            'moveScreenSha256': self.proof['source_hashes']['moveScreen.js'], key: value})
        self.evidence.write('centering.json', data)

    def legacy_baseline(self):
        directory = tempfile.TemporaryDirectory(prefix='task692-baseline-')
        self.addCleanup(directory.cleanup)
        archive = subprocess.check_output(['git', 'archive', LEGACY_BASELINE], cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(directory.name, filter='data')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=directory.name))
        self.addCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}/'

    def legacy_traces(self, url):
        traces = {}
        for mode in ('classic', 'bad'):
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, device_scale_factor=1)
            self.addCleanup(context.close)
            page = context.new_page()
            page.add_init_script(SEED_SCRIPT % 1)
            page.goto(url)
            wait_for_boot(page)
            page.evaluate(SEED_SCRIPT % 1)
            page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
            page.wait_for_function('!unTouch')
            traces[mode] = json.dumps(page.evaluate(LEGACY_TRACE), separators=(',', ':'))
        return traces

    def test_fixed_cadence_and_legacy(self):
        page=self.open()
        results=page.evaluate('''() => [30,60,120].map(hz=>{
            startGame('grapple_over');cancelAnimationFrame(game);resetPhysicsTiming();
            ninja.x=1500;ninja.y=-800;ninja.speedX=-.2;ninja.speedY=0;
            screen.trackGrappleOver(true);
            let ticks=0;const states=[];
            for(let i=0;i<=hz*2;i++) {
                ticks+=runFixedPhysics(1000+i*1000/hz);
            }
            return {hz,ticks,player:[ninja.x,ninja.y,ninja.speedX,ninja.speedY],camera:[screen.x,screen.y]};
        })''')
        for row in results[1:]:
            self.assertEqual(row['ticks'],results[0]['ticks'])
            self.assertEqual(row['player'],results[0]['player'])
            self.assertEqual(row['camera'],results[0]['camera'])
        world.Task446Tests.test_classic_bad_baseline(self)
        # Classic and bad camera traces against the pre-TASK-692 commit.
        current = self.legacy_traces(self.url)
        baseline = self.legacy_traces(self.legacy_baseline())
        legacy = {'baselineRevision': subprocess.check_output(['git', 'rev-parse', LEGACY_BASELINE],
            cwd=ROOT, text=True).strip(), 'revision': self.proof['revision'], 'ticks': 150}
        for mode in ('classic', 'bad'):
            rows = json.loads(current[mode])
            cameras = {tuple(r[:2]) for r in rows}
            self.assertGreater(len(cameras), 1, mode + ' camera never moved')
            self.assertEqual(current[mode], baseline[mode])
            legacy[mode] = {'sha256': hashlib.sha256(current[mode].encode()).hexdigest(),
                'baselineSha256': hashlib.sha256(baseline[mode].encode()).hexdigest(),
                'bytes': len(current[mode]), 'byteIdentical': current[mode] == baseline[mode],
                'distinctCameraPositions': len(cameras), 'first': rows[0], 'last': rows[-1]}
        self.evidence.write('legacy.json', legacy)
        self.evidence.write('cadence.json', dict(self.proof, cadence=results,
            frame_cadence_identical=True, legacy_baseline_equal=True))
        print('PASS cadence: 30/60/120 Hz identical physics and camera; classic/bad baseline equal; '
              f'classic/bad 150-tick camera traces byte-identical to {LEGACY_BASELINE}')
