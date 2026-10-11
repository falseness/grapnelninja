"""Cheap harness checks for tools/y8_feature_cost.py (TASK-271).

Timestamp arithmetic, inactive-gap exclusion, backing-size equality, rejected
mismatched settings, deterministic bounded replay, no hooks in the shipped
runtime, and one short browser run proving that disabling a draw-only hook
leaves the simulation (physics steps and world state) unchanged.
"""
from contextlib import ExitStack
import copy
import subprocess
import unittest

import y8_feature_cost as fc


def frames(intervals, start=1000.0, canvas=(1280, 720)):
    result = [{'t': start, 'dt': None, 'canvas': list(canvas), 'state': {'menu': False}}]
    for dt in intervals:
        result.append({'t': result[-1]['t'] + dt, 'dt': dt, 'canvas': list(canvas), 'state': {'menu': False}})
    return result


def raw(case, intervals, **settings):
    base = {'mode': 'bad', 'profile': 'desktop', 'viewport': [1280, 720], 'dpr': 1, 'cpu_throttle': 1,
            'seed': 4, 'warmup_ms': 100, 'window_ms': 200, 'windows': 1, 'replay_sha256': 'r', 'diagnostic': False}
    base.update(settings)
    r = {'case': case, 'settings': base, 'frames': frames(intervals), 'excluded': [], 'deaths': [], 'dispatched': [],
         'dimensions': {'canvas': [1280, 720]}}
    r['summary'] = fc.summarize(r)
    return r


class MetricsTests(unittest.TestCase):
    def test_timestamp_arithmetic(self):
        m = fc.metrics(frames([20.0] * 100))
        self.assertEqual(m['intervals'], 100)
        self.assertAlmostEqual(m['active_ms'], 2000.0)
        self.assertAlmostEqual(m['wall_ms'], 2000.0)
        self.assertAlmostEqual(m['average_fps'], 50.0)
        self.assertEqual(m['frame_ms'], {'p50': 20.0, 'p95': 20.0, 'p99': 20.0, 'max': 20.0})
        m = fc.metrics(frames([10.0] * 90 + [100.0] * 10))
        self.assertAlmostEqual(m['active_ms'], 1900.0)
        self.assertAlmostEqual(m['average_fps'], 100 * 1000 / 1900.0)
        self.assertEqual(m['frame_ms']['p50'], 10.0)
        self.assertEqual(m['frame_ms']['p95'], 100.0)
        self.assertEqual(m['frame_ms']['max'], 100.0)

    def test_inconsistent_or_inactive_rejected(self):
        for defect in ('inconsistent', 'inactive', 'negative', 'single'):
            with self.subTest(defect=defect):
                f = frames([20.0] * 10)
                if defect == 'inconsistent':
                    f[3]['dt'] = 25.0
                if defect == 'inactive':
                    f[3]['state']['menu'] = True
                if defect == 'negative':
                    f[3]['t'] = f[2]['t'] - 1
                if defect == 'single':
                    f = f[:1]
                with self.assertRaises(fc.EvidenceError):
                    fc.metrics(f)

    def test_inactive_gap_excluded(self):
        f = frames([20.0] * 50)
        # Menu/pause gap of 3000 ms: the next active frame has dt=None.
        f += [{'t': f[-1]['t'] + 3000.0, 'dt': None, 'canvas': [1280, 720], 'state': {'menu': False}}]
        f += frames([20.0] * 50, start=f[-1]['t'])[1:]
        m = fc.metrics(f)
        self.assertEqual(m['gaps'], 1)
        self.assertEqual(m['intervals'], 100)
        self.assertAlmostEqual(m['active_ms'], 2000.0)
        self.assertAlmostEqual(m['wall_ms'], 5000.0)
        self.assertAlmostEqual(m['average_fps'], 50.0)
        self.assertEqual(m['frame_ms']['max'], 20.0)

    def test_split_windows_on_active_time(self):
        f = frames([10.0] * 100)  # 1000 active ms
        warm, *_ = windows = fc.split_windows(f, 200, 300, 2)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0][0]['t'], 1200.0)
        self.assertIsNone(windows[0][0]['dt'])
        self.assertAlmostEqual(fc.metrics(windows[0])['active_ms'], 300.0)
        self.assertEqual(windows[1][0]['t'], windows[0][-1]['t'])
        self.assertAlmostEqual(fc.metrics(windows[1])['active_ms'], 300.0)
        with self.assertRaises(fc.EvidenceError):
            fc.split_windows(f, 200, 300, 3)
        # A gap inside the window neither counts as active time nor ends the window.
        g = frames([10.0] * 30)
        g.append({'t': g[-1]['t'] + 5000.0, 'dt': None, 'canvas': [1280, 720], 'state': {'menu': False}})
        g += frames([10.0] * 40, start=g[-1]['t'])[1:]
        w = fc.split_windows(g, 100, 300, 1)[0]
        m = fc.metrics(w)
        self.assertEqual(m['gaps'], 1)
        self.assertAlmostEqual(m['active_ms'], 300.0)
        self.assertGreater(m['wall_ms'], 5000.0)


class PairingTests(unittest.TestCase):
    def test_backing_size_equality_required(self):
        a, b = raw('control', [10.0] * 40), raw('candidate', [12.0] * 40)
        self.assertEqual(fc.compare(a, b)['backing'], [1280, 720])
        c = copy.deepcopy(b)
        c['frames'][5]['canvas'] = [960, 540]
        with self.assertRaises(fc.EvidenceError):
            fc.compare(a, c)
        d = copy.deepcopy(b)
        for f in d['frames']:
            f['canvas'] = [960, 540]
        d['dimensions']['canvas'] = [960, 540]
        with self.assertRaises(fc.EvidenceError):
            fc.compare(a, d)

    def test_mismatched_settings_rejected(self):
        a = raw('control', [10.0] * 40)
        for key, value in (('seed', 1), ('dpr', 2), ('mode', 'classic'), ('replay_sha256', 'other'),
                           ('cpu_throttle', 4), ('window_ms', 300), ('profile', 'touch'), ('diagnostic', True)):
            with self.subTest(key=key):
                with self.assertRaises(fc.EvidenceError):
                    fc.compare(a, raw('candidate', [10.0] * 40, **{key: value}))
        self.assertAlmostEqual(fc.compare(a, raw('candidate', [20.0] * 20))['delta_average_fps'], -50.0)


class ReplayTests(unittest.TestCase):
    def test_bounded_deterministic_replay(self):
        a, b = fc.replay_script(4, 'desktop', 15000), fc.replay_script(4, 'desktop', 15000)
        self.assertEqual(a, b)
        self.assertNotEqual(a, fc.replay_script(1, 'desktop', 15000))
        self.assertEqual(fc.replay_sha256(a), fc.replay_sha256(b))
        self.assertTrue(all(e['t_ms'] <= 15000 for e in a))
        self.assertTrue(all(0.4 * 1280 <= e['x'] <= 0.85 * 1280 and 0.15 * 720 <= e['y'] <= 0.6 * 720 for e in a))
        self.assertEqual([e['type'] for e in a[:2]], ['start', 'end'])


class ShippedRuntimeTests(unittest.TestCase):
    def test_no_diagnostic_hooks_in_shipped_runtime(self):
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=fc.ROOT, text=True).splitlines()
        runtime = [n for n in tracked if n.endswith(fc.RUNTIME_SUFFIXES) and not n.startswith('tools/')]
        self.assertGreater(len(runtime), 20)
        for name in runtime:
            text = (fc.ROOT / name).read_text(errors='replace')
            self.assertNotIn(fc.MARKER, text, name)
            self.assertNotIn(fc.ALL_DRAW, text, name)


SIMULATION = '''(cfg) => {
    cancelAnimationFrame(game)
    startGame(cfg.mode)
    cancelAnimationFrame(game)
    for (let i = 0; i < cfg.frames; i++) { gameLoop(1000 + i * 1000 / 60); cancelAnimationFrame(game) }
    const FC = window.__featureCost
    return {steps: FC.physicsSteps, frames: FC.frames.length, dispatched: FC.dispatched.length,
        ablated: FC.ablated, deaths: FC.deaths.length,
        ninja: [ninja.x, ninja.y, ninja.speedX, ninja.speedY], screen: [screen.x, screen.y],
        grapnel: [grapnel.throwed, grapnel.isGrappled(), grapnel.pos.length],
        score: scoreText.count[version], elements: floors.map(f => f.elements.length),
        accumulator: physicsTiming.accumulatorMs}
}'''


class DrawOnlyHookTests(unittest.TestCase):
    def run_simulation(self, ablate):
        from browser_test_support import start_browser_test
        cfg = {'dpr': 1, 'input': 'mouse', 'ablate': ablate, 'diagnostic': True,
               'replay': fc.replay_script(4, 'desktop', 4000), 'warmup_ms': 0, 'window_ms': 100000, 'windows': 1}
        with ExitStack() as stack:
            url, browser = start_browser_test(fc.ROOT, stack.callback)
            network = []
            ctx = fc.new_context(browser, 'desktop', 4, network)
            stack.callback(ctx.close)
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + 'index.html', wait_until='domcontentloaded')
            page.wait_for_function(fc.BOOTED, timeout=60000)
            page.evaluate(fc.INSTRUMENT, cfg)
            result = page.evaluate(SIMULATION, {'mode': 'bad', 'frames': 240})
            self.assertEqual(errors, [])
            return result

    def test_disabled_draw_only_hook_keeps_simulation_unchanged(self):
        reference = self.run_simulation([])
        self.assertEqual(reference['ablated'], [])
        self.assertGreaterEqual(reference['steps'], 200)
        self.assertEqual(reference['frames'], 240)
        self.assertGreater(reference['dispatched'], 4)
        for ablate in (['drawWorldLayer'], [fc.ALL_DRAW]):
            with self.subTest(ablate=ablate):
                ablated = self.run_simulation(ablate)
                self.assertNotEqual(ablated['ablated'], [])
                for key in ('steps', 'frames', 'dispatched', 'deaths', 'ninja', 'screen', 'grapnel',
                            'score', 'elements', 'accumulator'):
                    self.assertEqual(ablated[key], reference[key], key)
                print(f'PASS draw-only hook {ablate} disabled: physics steps={ablated["steps"]} '
                      f'ninja={ablated["ninja"]} screen={ablated["screen"]} score={ablated["score"]} '
                      f'elements={ablated["elements"]} unchanged versus full drawing', flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
