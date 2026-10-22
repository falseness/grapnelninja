"""TASK-650: normal Grapple Over starts load the imported SVG level.

Boots the real index.html (no fixture injection) and checks the level the game
builds against levels/extended-mountain.level.json and the SVG it was generated
from. Covers fresh start, restart, an incompatible old save, a current-layout
save, the boot asset fetch and unchanged classic/bad selection.

TASK650_EVIDENCE_DIR=DIR writes DIR/runtime.json with the observed values.

    python3 -m unittest discover -s tools -p test_imported_level_runtime.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET

from browser_test_support import start_browser_test, wait_for_boot, wait_for_boot_run, select_mode

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / 'levels' / 'extended-mountain.svg'
LEVEL = ROOT / 'levels' / 'extended-mountain.level.json'
LAYOUT_ID = 'extended-mountain-v1'
CLIMB_KEY = 'grapnelninja.grappleOver'
# Tree before TASK-650: physics, collision and sprite sources must match it.
BASE_REV = '8b9bbf6'
UNCHANGED = ['physics.js', 'fixedlevel.js', 'collision', 'sprites', 'elements', 'respawn.js', 'moveScreen.js', 'render']

SNAPSHOT = '''() => {
    const w = floors[0], l = w.level
    return {
        version, world: w.constructor.name, layoutId: l.layoutId,
        fragments: l.svgFormat ? l.svgFormat.fragments.length : null,
        transfers: l.svgFormat ? l.svgFormat.transfers.length : null,
        elementCount: w.elements.length, dragZones: w.dragZones.map(z => z.id),
        spawn: l.spawn, finish: l.finish, bounds: l.bounds,
        ninja: {x: ninja.x, y: ninja.y, speedX: ninja.speedX, speedY: ninja.speedY},
        tick: w.elapsedSteps, stats: w.climbStats,
        range: grappleOverAcquisitionRadius(),
        levelElements: l.elements.map(e => ({id: e.id, x: e.x, y: e.y, role: e.role,
            grapplable: e.grapplable, points: e.points})),
        live: w.elements.concat(w.dragZones).map(e => ({id: e.id, x: e.x, y: e.y,
            role: e.surfaceRole, grapplable: e.grapplable})),
        notice: document.getElementById('climb-save-notice')?.textContent ?? null,
        paused: menu.gamePaused
    }
}'''

# Freeze the loop, then take the confirmed "Restart climb" action.
RESTART = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    ninja.x += 777; ninja.y -= 333; ninja.speedX = 3
    for (let i = 0; i < 5; i++) physics()
    CLIMB_UI.restart()
    cancelAnimationFrame(game)
}'''


def svg_source():
    """Spawn, finish and fragment count read straight from the authoring SVG."""
    root = ET.parse(SVG).getroot()
    ns = '{http://www.w3.org/2000/svg}'
    spawn = root.find('.//%scircle[@data-marker="spawn"]' % ns)
    finish = root.find('.//%srect[@data-marker="finish"]' % ns)
    x, y = float(finish.get('x')), float(finish.get('y'))
    return {
        'layoutId': root.get('data-layout-id'),
        'fragments': len(root.findall('.//*[@data-fragment="true"]')),
        'drag': sorted(e.get('id') for e in root.iter() if e.get('data-role') == 'drag'),
        'spawn': {'x': float(spawn.get('cx')), 'y': float(spawn.get('cy'))},
        'finish': {'left': x, 'top': y, 'right': x + float(finish.get('width')),
                   'bottom': y + float(finish.get('height'))},
    }


class ImportedLevelRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        cls.level = json.loads(LEVEL.read_text())
        cls.svg = svg_source()
        cls.evidence = {'level': str(LEVEL.relative_to(ROOT)), 'svg': str(SVG.relative_to(ROOT)), 'cases': {}}

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        out = os.environ.get('TASK650_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            Path(out, 'runtime.json').write_text(json.dumps(cls.evidence, separators=(',', ':'), sort_keys=True))

    def open(self, seed=None, query='', route=None, boot_run=True):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors, requests = [], []
        page.on('pageerror', lambda e: errors.append('pageerror: %s' % e))
        page.on('console', lambda m: m.type == 'error' and errors.append('console: %s' % m.text))
        page.on('response', lambda r: 'levels/' in r.url and requests.append({'url': r.url.split('/', 3)[3], 'status': r.status}))
        if seed is not None:
            page.add_init_script('for (const [k, v] of Object.entries(%s)) localStorage.setItem(k, v)' % json.dumps(seed))
        if route:
            page.route('**/levels/extended-mountain.level.json', route)
        page.goto(self.url + query)
        if boot_run:
            wait_for_boot_run(page)
        page.errors, page.requests = errors, requests
        return page

    def record(self, name, page, snap, **extra):
        keep = {k: snap[k] for k in ('version', 'world', 'layoutId', 'fragments', 'transfers', 'elementCount',
                                     'dragZones', 'spawn', 'finish', 'ninja', 'tick', 'notice', 'paused', 'range')}
        self.evidence['cases'][name] = dict(keep, browserErrors=page.errors, levelRequests=page.requests, **extra)

    def assert_imported(self, snap):
        self.assertEqual(snap['version'], 'grapple_over')
        self.assertEqual(snap['world'], 'PersistentWorld')
        self.assertEqual(snap['layoutId'], LAYOUT_ID)
        self.assertEqual(snap['layoutId'], self.svg['layoutId'])
        self.assertEqual(snap['fragments'], 25)
        self.assertEqual(snap['fragments'], self.svg['fragments'])
        self.assertEqual(snap['transfers'], 24)
        self.assertEqual(len(snap['dragZones']), 6)
        self.assertEqual(sorted(snap['dragZones']), self.svg['drag'])
        self.assertEqual(snap['spawn'], self.svg['spawn'])
        self.assertEqual(snap['finish'], self.svg['finish'])
        self.assertEqual(snap['spawn'], self.level['spawn'])
        self.assertEqual(snap['finish'], self.level['finish'])
        self.assertEqual(snap['bounds'], self.level['bounds'])
        # Every authored element, unchanged, with no extra or missing ids.
        self.assertEqual(snap['levelElements'], self.level['elements'])
        source = {e['id']: e for e in self.level['elements']}
        self.assertEqual(sorted(e['id'] for e in snap['live']), sorted(source))
        for e in snap['live']:
            s = source[e['id']]
            self.assertEqual((e['x'], e['y'], e['role'], e['grapplable']), (s['x'], s['y'], s['role'], s['grapplable']), e['id'])
        self.assertEqual(snap['range'], 540)

    def test_01_fresh_start(self):
        page = self.open()
        snap = page.evaluate(SNAPSHOT)
        self.assert_imported(snap)
        self.assertIsNone(snap['notice'])
        self.assertEqual(page.requests, [{'url': 'levels/extended-mountain.level.json', 'status': 200}])
        # A fresh start began at the spawn; a few gameplay frames may have run since.
        self.assertLess(abs(snap['ninja']['x'] - snap['spawn']['x']), 1)
        self.assertLess(abs(snap['ninja']['y'] - snap['spawn']['y']), 40)
        self.assertEqual(page.errors, [])
        self.record('fresh_start', page, snap, coordinatesMatchSource=True, elementsCompared=len(snap['live']))

    def test_02_restart(self):
        page = self.open()
        page.evaluate(RESTART)
        snap = page.evaluate(SNAPSHOT)
        self.assert_imported(snap)
        self.assertEqual((snap['ninja']['x'], snap['ninja']['y']), (snap['spawn']['x'], snap['spawn']['y']))
        self.assertEqual(snap['tick'], 0)
        self.assertEqual(page.errors, [])
        self.record('restart', page, snap, coordinatesMatchSource=True, elementsCompared=len(snap['live']))

    def test_03_incompatible_old_save(self):
        # A real save from the previous normal layout (replacement-v1), plus a
        # legacy save without a layout id.
        old = self.open(query='?grappleFixture=replacement-v1')
        saved = old.evaluate('''() => {
            window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
            ninja.x += 500; for (let i = 0; i < 30; i++) physics()
            return {layoutId: floors[0].level.layoutId, save: JSON.stringify(captureClimbState())}
        }''')
        self.assertEqual(saved['layoutId'], 'grapple-over-replacement-v1')
        self.assertEqual(old.errors, [])
        legacy = json.loads(saved['save'])
        del legacy['layoutId']
        results = {}
        for name, raw in (('replacement-v1', saved['save']), ('no-layout-id', json.dumps(legacy))):
            page = self.open(seed={CLIMB_KEY: raw})
            snap = page.evaluate(SNAPSHOT)
            self.assert_imported(snap)
            self.assertEqual(snap['notice'], 'Climb save unavailable. Starting at the base.')
            self.assertLess(abs(snap['ninja']['x'] - snap['spawn']['x']), 1)
            self.assertLess(abs(snap['ninja']['y'] - snap['spawn']['y']), 40)
            self.assertFalse(snap['paused'])
            # The next write replaces the rejected save with the new layout.
            page.evaluate('PROGRESS.flushClimb(true)')
            page.wait_for_function('k => JSON.parse(localStorage.getItem(k)).layoutId === "%s"' % LAYOUT_ID, arg=CLIMB_KEY)
            self.assertEqual(page.errors, [])
            self.record('incompatible_save_' + name, page, snap, seededLayoutId=json.loads(raw).get('layoutId'),
                        rewrittenLayoutId=LAYOUT_ID)
            results[name] = snap['notice']
        self.assertEqual(len(results), 2)

    def test_04_current_layout_save(self):
        first = self.open()
        save = first.evaluate('''() => {
            window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
            ninja.x += 600; ninja.y -= 200; ninja.speedX = 2
            for (let i = 0; i < 20; i++) physics()
            return JSON.stringify(captureClimbState())
        }''')
        state = json.loads(save)
        self.assertEqual(state['layoutId'], LAYOUT_ID)
        page = self.open(seed={CLIMB_KEY: save})
        snap = page.evaluate(SNAPSHOT)
        self.assert_imported(snap)
        self.assertIsNone(snap['notice'])
        self.assertTrue(snap['paused'])
        self.assertEqual(snap['tick'], state['simulationTick'])
        self.assertEqual((snap['ninja']['x'], snap['ninja']['y']), (state['player']['x'], state['player']['y']))
        self.assertEqual(first.errors + page.errors, [])
        self.record('current_layout_save', page, snap, savedTick=state['simulationTick'], savedPlayer=state['player'])

    def test_05_level_ready_before_world(self):
        # A slow asset still arrives before the world is built.
        import time

        def slow(route):
            time.sleep(1.0)
            route.continue_()
        page = self.open(route=slow)
        snap = page.evaluate(SNAPSHOT)
        self.assert_imported(snap)
        self.assertEqual(page.errors, [])
        self.record('slow_asset', page, snap)
        # A missing asset takes the existing boot failure/retry path; no world.
        failed = self.open(route=lambda r: r.fulfill(status=404, body='missing'), boot_run=False)
        failed.wait_for_selector('#boot-retry:not([hidden])')
        world = failed.evaluate('typeof floors === "undefined" ? null : (floors && floors[0] ? floors[0].constructor.name : null)')
        self.assertIsNone(world)
        expected = [e for e in failed.errors if 'Application boot failed' in e or '404' in e]
        self.assertTrue(expected and len(expected) == len(failed.errors), failed.errors)
        self.evidence['cases']['missing_asset'] = {'bootRetryVisible': True, 'world': world,
                                                   'expectedErrors': failed.errors, 'levelRequests': failed.requests}

    def test_06_classic_bad_unchanged(self):
        page = self.open()
        seen = {}
        for mode in ('classic', 'bad', 'grapple_over'):
            select_mode(page, mode)
            seen[mode] = page.evaluate('() => ({version, world: floors.map(f => f.constructor.name), '
                                       'layoutId: floors[0].level ? floors[0].level.layoutId : null})')
        self.assertEqual(seen['classic']['version'], 'classic')
        self.assertEqual(seen['classic']['world'], ['SideFloor', 'Floor', 'SideFloor'])
        self.assertEqual(seen['bad']['version'], 'bad')
        self.assertEqual(seen['bad']['world'], ['SideFloor', 'Floor', 'SideFloor'])
        self.assertIsNone(seen['classic']['layoutId'])
        self.assertIsNone(seen['bad']['layoutId'])
        self.assertEqual(seen['grapple_over']['layoutId'], LAYOUT_ID)
        self.assertEqual(page.errors, [])
        # Physics, collision, bounce and level-loader sources match the pre-task tree,
        # and index.html only gained the boot fetch.
        diff = subprocess.run(['git', 'diff', '--stat', BASE_REV, '--'] + UNCHANGED, cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
        self.assertEqual(diff, '')
        index = subprocess.run(['git', 'diff', '-U0', BASE_REV, '--', 'index.html'], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout
        changed = [l for l in index.splitlines() if l[:1] in '+-' and not l.startswith(('+++', '---'))]
        self.assertEqual(changed, ['+                await loadGrappleOverLevelAsset()'])
        self.evidence['cases']['modes'] = dict(seen, browserErrors=page.errors, unchangedSources=UNCHANGED,
                                               baseRev=BASE_REV, unchangedDiff=diff, indexHtmlChanges=changed)


if __name__ == '__main__':
    unittest.main()
