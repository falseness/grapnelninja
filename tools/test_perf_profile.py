"""Opt-in frame profiler (render/perfprofile.js, TASK-414).

With ?perf=1 the game runs under real requestAnimationFrame until at least
150 frames; window.PERF_PROFILE.snapshot() must list every draw() layer and
the physics update with finite, non-negative meanMs/p95Ms, sorted by meanMs
descending. Every request of that run is recorded: only the local server and
the stubbed Bridge SDK URL. Without the flag PERF_PROFILE is undefined and
no layer is wrapped. A fixed-seed frozen-clock render (render_snapshot.py)
with and without ?perf=1 must have 0 differing pixels.
Set PERF_PROFILE_EVIDENCE_DIR=<absolute dir> to write snapshot.json,
network.log and pixels.log there.
"""
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import unittest
from urllib.parse import urlparse

import numpy as np

from browser_test_support import SDK_URL, start_browser_test
from perf_mobile import SEED_SCRIPT
from render_snapshot import (ADVANCE_SCRIPT, CLOCK_SCRIPT, SEED, SETUP_SCRIPT, boot_frozen,
                             input_script, pixels, png_bytes)

ROOT = Path(__file__).resolve().parent.parent
LAYERS = ['background', 'lights', 'behindForegroundParticles', 'playerTrail', 'world',
          'particlesAndTrails', 'bloom', 'playerGlow', 'colorGrade', 'player',
          'tutorialHint', 'ui', 'fpsCounter']
MIN_FRAMES = 150
VIEWPORT = {'width': 844, 'height': 390}
PIXEL_TICKS = [60, 300]


def evidence_dir():
    path = os.environ.get('PERF_PROFILE_EVIDENCE_DIR')
    if not path:
        return None
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


class PerfProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.evidence = evidence_dir()

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def open(self, query, requests=None, errors=None):
        context = self.browser.new_context(viewport=VIEWPORT)
        self.addCleanup(context.close)
        page = context.new_page()
        if requests is not None:
            page.on('request', lambda r: requests.append(r.url))
        page.on('pageerror', lambda e: (errors if errors is not None else []).append(str(e)))
        page.goto(self.url + 'index.html' + query, wait_until='load')
        return page

    def test_snapshot_with_flag(self):
        requests, errors = [], []
        page = self.open('?perf=1', requests, errors)
        page.wait_for_function(f'() => window.PERF_PROFILE && PERF_PROFILE.snapshot().frames >= {MIN_FRAMES}',
                               timeout=300000, polling=500)
        snap = page.evaluate('() => PERF_PROFILE.snapshot()')
        print('SNAPSHOT', json.dumps(snap), flush=True)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(snap['frames'], MIN_FRAMES)
        self.assertTrue(math.isfinite(snap['rafFps']) and snap['rafFps'] > 0)
        names = [e['name'] for e in snap['entries']]
        self.assertEqual(sorted(names), sorted(LAYERS + ['update']))
        for e in snap['entries']:
            for key in ('meanMs', 'p95Ms'):
                self.assertTrue(math.isfinite(e[key]) and e[key] >= 0, (e['name'], key, e[key]))
            self.assertTrue(0 <= e['samples'] <= 120, e)
        means = [e['meanMs'] for e in snap['entries']]
        self.assertEqual(means, sorted(means, reverse=True))
        drawn = {e['name'] for e in snap['entries'] if e['samples']}
        bloom_on = page.evaluate('() => STYLE.features.bloom')
        self.assertEqual(drawn, set(LAYERS + ['update']) - (set() if bloom_on else {'bloom'}))
        print(f'bloom feature={bloom_on}; entries with samples: {sorted(drawn)}', flush=True)
        print(f'PASS flag: frames={snap["frames"]} rafFps={snap["rafFps"]:.2f} '
              f'entries={len(names)} names={names} sorted desc', flush=True)

        local = f'http://{urlparse(self.url).netloc}/'
        foreign = [u for u in requests if not u.startswith(local) and u != SDK_URL]
        if self.evidence:
            (self.evidence / 'snapshot.json').write_text(json.dumps(snap, indent=1) + '\n')
            hosts = sorted({urlparse(u).netloc for u in requests})
            (self.evidence / 'network.log').write_text(
                '\n'.join(requests) + f'\n--- {len(requests)} requests; hosts: {hosts}; '
                f'foreign (not local, not stubbed SDK): {len(foreign)}\n')
        self.assertIn(SDK_URL, requests)
        self.assertEqual(foreign, [])
        print(f'PASS network: {len(requests)} requests, only {local} and the stubbed SDK', flush=True)

    def test_no_flag_is_untouched(self):
        page = self.open('')
        page.wait_for_function('() => typeof bootComplete !== "undefined" && bootComplete')
        page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        state = page.evaluate('''() => ({
            profile: typeof window.PERF_PROFILE,
            wrapped: ["drawBackgroundLayer", "drawWorldLayer", "drawUILayer", "runFixedPhysics", "gameLoop"]
                .filter(n => window[n].toString().includes("performance.now()"))})''')
        self.assertEqual(state, {'profile': 'undefined', 'wrapped': []})
        print('PASS no flag: window.PERF_PROFILE is undefined, nothing wrapped', flush=True)

    def frozen_captures(self, query):
        context = self.browser.new_context(viewport=VIEWPORT)
        self.addCleanup(context.close)
        context.add_init_script(SEED_SCRIPT % SEED)
        context.add_init_script(CLOCK_SCRIPT)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url + 'index.html' + query, wait_until='load')
        boot_frozen(page)
        page.evaluate(SETUP_SCRIPT, [input_script(SEED, PIXEL_TICKS[-1], VIEWPORT['width'],
                                                  VIEWPORT['height']), False])
        page.evaluate('() => draw()')
        shots = {'boot': png_bytes(page.evaluate('() => __snap.capture()'))}
        page.evaluate('mode => startGame(mode)', 'bad')
        for tick in PIXEL_TICKS:
            page.evaluate(ADVANCE_SCRIPT, tick)
            shots[f'bad-tick{tick:04d}'] = png_bytes(page.evaluate('() => __snap.capture()'))
        profiled = page.evaluate('() => window.PERF_PROFILE ? PERF_PROFILE.snapshot().entries'
                                 '.filter(e => e.name === "world").length : 0')
        self.assertEqual(errors, [])
        return shots, profiled

    def test_pixels_identical(self):
        plain, plain_profiled = self.frozen_captures('')
        perf, perf_profiled = self.frozen_captures('?perf=1')
        self.assertEqual((plain_profiled, perf_profiled), (0, 1))
        lines, total = [], 0
        out = self.evidence or Path(os.environ.get('TMPDIR', '/tmp'))
        for name in plain:
            a_path, b_path = out / f'pixels-{name}-plain.png', out / f'pixels-{name}-perf.png'
            a_path.write_bytes(plain[name])
            b_path.write_bytes(perf[name])
            a, b = pixels(a_path), pixels(b_path)
            self.assertEqual(a.shape, b.shape)
            diff = int((np.abs(a - b).max(axis=2) > 0).sum())
            total += diff
            lines.append(f'{name}: {a.shape[1]}x{a.shape[0]} differing_pixels={diff}')
            if not self.evidence:
                a_path.unlink()
                b_path.unlink()
        lines.append(f'seed={SEED} viewport={VIEWPORT} total differing_pixels={total}')
        print('\n'.join(lines), flush=True)
        if self.evidence:
            (self.evidence / 'pixels.log').write_text('\n'.join(lines) + '\n')
        self.assertEqual(total, 0)
        print('PASS pixels: plain vs ?perf=1 identical', flush=True)


if __name__ == '__main__':
    unittest.main()
