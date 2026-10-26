"""TASK-704: Grapple Over upward launch at the spawn.

Boots the real index.html with the frame loop frozen before boot, so the first
run is observed at the spawn, then drives production physics() ticks with no
input. A fresh start (the first run of a page load and every restart) leaves
the spawn with an upward speed whose free-flight apex is 270 +- 10 world units
above the spawn. A continue/respawn (respawnNinja), a fall recovery, a save
restore (restoreClimbState) and the classic/bad modes start at rest.

SPAWN_LAUNCH_EVIDENCE_DIR=DIR writes compact launch.json there.

    python3 -m unittest discover -s tools -p test_spawn_launch.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run, select_mode

ROOT = Path(__file__).resolve().parent.parent
CLIMB_KEY = 'grapnelninja.grappleOver'
RISE, TOLERANCE = 270, 10

# Block only the game loop (Playwright's own polling still needs requestAnimationFrame).
FREEZE = '''{ const raf = window.requestAnimationFrame.bind(window)
    window.requestAnimationFrame = cb => cb && cb.name === 'gameLoop' ? 0 : raf(cb) }'''

# No-input flight from the current state: per-tick y, until the ninja falls back below its start.
TRACE = '''ticks => {
    const spawn = floors[0].level.spawn, y0 = ninja.y, start = {x: ninja.x, y: ninja.y,
        speedX: ninja.speedX, speedY: ninja.speedY, atSpawn: ninja.x === spawn.x && ninja.y === spawn.y}
    const ys = []
    let minY = ninja.y
    for (let i = 0; i < ticks; i++) {
        physics()
        ys.push(ninja.y)
        minY = Math.min(minY, ninja.y)
        if (ninja.y > y0 + 1) break
    }
    return {start, spawnY: spawn.y, apexRise: spawn.y - minY, apexTick: ys.indexOf(minY) + 1, ys,
        grappled: grapnel.throwed, pressHeld}
}'''

EVIDENCE = {}


def tearDownModule():
    out = os.environ.get('SPAWN_LAUNCH_EVIDENCE_DIR')
    if out and EVIDENCE:
        Path(out).mkdir(parents=True, exist_ok=True)
        Path(out, 'launch.json').write_text(json.dumps(EVIDENCE, separators=(',', ':'), sort_keys=True) + '\n')


def brief(trace):
    """The fields the assertions use; the full y trace only as a hash and its length."""
    ys = trace['ys']
    return {'start': trace['start'], 'apexRise': trace['apexRise'], 'apexTick': trace['apexTick'],
            'ticks': len(ys), 'traceSha256': hashlib.sha256(json.dumps(ys).encode()).hexdigest(),
            'ysEvery10': ys[::10]}


class SpawnLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def open(self, context=None, mode=None):
        if context is None:
            context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
            self.addCleanup(context.close)
        context.add_init_script(FREEZE)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('version'), 'grapple_over')
        if mode:
            select_mode(page, mode)
            self.assertEqual(page.evaluate('version'), mode)
        return page

    def assert_launch(self, trace):
        self.assertTrue(trace['start']['atSpawn'])
        self.assertLess(trace['start']['speedY'], 0)
        self.assertEqual(trace['start']['speedX'], 0)
        self.assertFalse(trace['grappled'])
        self.assertLessEqual(abs(trace['apexRise'] - RISE), TOLERANCE)

    def test_01_first_run_and_restart_launch(self):
        traces = []
        for _ in range(2):
            page = self.open()
            first = page.evaluate(TRACE, 2000)
            self.assert_launch(first)
            page.evaluate('() => CLIMB_UI.restart()')
            restart = page.evaluate(TRACE, 2000)
            self.assert_launch(restart)
            self.assertEqual(page.errors, [])
            traces.append((first, restart))
        (a, ar), (b, br) = traces
        # Two identical runs give identical traces; a restart repeats the first run.
        self.assertEqual(a['ys'], b['ys'])
        self.assertEqual(ar['ys'], br['ys'])
        self.assertEqual(a['ys'], ar['ys'])
        EVIDENCE['firstRun'] = brief(a)
        EVIDENCE['restart'] = brief(ar)
        EVIDENCE['repeatRun'] = {'firstRun': brief(b), 'restart': brief(br),
                                 'identical': a['ys'] == b['ys'] and ar['ys'] == br['ys']}
        EVIDENCE['target'] = {'rise': RISE, 'tolerance': TOLERANCE,
                              'launchSpeed': page.evaluate('getSpawnLaunchSpeed()'),
                              'predictedRise': page.evaluate('spawnLaunchRise(getSpawnLaunchSpeed())')}

    def test_02_respawn_and_fall_recovery_at_rest(self):
        page = self.open()
        # Fall recovery teleports to the spawn without a launch.
        rec = page.evaluate('''() => { ninja.speedY = -5; recoverClimbFall()
            return {speedX: ninja.speedX, speedY: ninja.speedY, atSpawn: ninja.y === floors[0].level.spawn.y} }''')
        self.assertEqual((rec['speedX'], rec['speedY'], rec['atSpawn']), (0, 0, True))
        # Continue/respawn (respawn.js) in the mode it was built for.
        select_mode(page, 'classic')
        res = page.evaluate('''() => { ninja.speedX = 3; ninja.speedY = -5; const p = respawnNinja()
            return {speedX: ninja.speedX, speedY: ninja.speedY, x: p.x, y: p.y} }''')
        self.assertEqual((res['speedX'], res['speedY']), (0, 0))
        self.assertEqual(page.errors, [])
        EVIDENCE['fallRecovery'] = {'initialSpeedY': rec['speedY'], 'speedX': rec['speedX']}
        EVIDENCE['continueRespawn'] = {'initialSpeedY': res['speedY'], 'speedX': res['speedX']}

    def test_03_save_restore_at_rest(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = self.open(context)
        # A mid-air save at rest 100 above the spawn: restore keeps that speed, no launch.
        page.evaluate('''() => { ninja.y = floors[0].level.spawn.y - 100; ninja.speedX = ninja.speedY = 0
            PROGRESS.flushClimb() }''')
        page.wait_for_function('k => { const v = localStorage.getItem(k); return v && JSON.parse(v).player.y === ninja.y }',
                               arg=CLIMB_KEY)
        saved = json.loads(page.evaluate('k => localStorage.getItem(k)', CLIMB_KEY))
        page.close()
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.wait_for_function('y => ninja.y === y', arg=saved['player']['y'])
        got = page.evaluate('({speedX: ninja.speedX, speedY: ninja.speedY, y: ninja.y, spawnY: floors[0].level.spawn.y})')
        self.assertEqual((saved['player']['speedY'], got['speedY'], got['speedX']), (0, 0, 0))
        self.assertEqual(got['y'], got['spawnY'] - 100)
        self.assertEqual(page.errors, [])
        EVIDENCE['saveRestore'] = {'initialSpeedY': got['speedY'], 'speedX': got['speedX'], 'restoredY': got['y'],
                                   'spawnY': got['spawnY']}

    def test_04_classic_and_bad_at_rest(self):
        for mode in ('classic', 'bad'):
            page = self.open(mode=mode)
            v = page.evaluate('({speedX: ninja.speedX, speedY: ninja.speedY})')
            self.assertEqual((v['speedX'], v['speedY']), (0, 0))
            # A restart in that mode also starts at rest.
            page.evaluate('ninja.speedY = -5')
            select_mode(page, 'classic' if mode == 'bad' else 'bad')
            select_mode(page, mode)
            again = page.evaluate('({speedY: ninja.speedY, version})')
            self.assertEqual((again['speedY'], again['version']), (0, mode))
            self.assertEqual(page.errors, [])
            EVIDENCE[mode] = {'initialSpeedY': v['speedY'], 'speedX': v['speedX'], 'afterReselectSpeedY': again['speedY']}


if __name__ == '__main__':
    unittest.main()
