"""TASK-650: normal Grapple Over starts load the imported SVG level.

Boots the real index.html (no fixture injection) and checks the level the game
builds against artifacts/levels/extended-mountain.level.json and the SVG it was generated
from. Covers fresh start, restart, an incompatible old save, a current-layout
save, the boot asset fetch and unchanged classic/bad selection.

TASK650_EVIDENCE_DIR=DIR writes DIR/runtime.json with the observed values.

Task651Tests (TASK-651) render the default level through the production draw()
with a fixed camera, compare it with the concept artifacts/level/extended-mountain.svg
under the same world-to-image mapping, check the loaded objects against the
imported data and the concept measurements, and probe the yellow drag zones.
TASK651_EVIDENCE_DIR=DIR writes the images, runtime-fidelity.json,
capture.json and behavior.log there (default: a temporary directory).

    python3 -m unittest discover -s tools -p test_imported_level_runtime.py -v
    TASK651_EVIDENCE_DIR=artifacts/TASK-651 python3 -m unittest discover -s tools \
        -p test_imported_level_runtime.py -k Task651Tests -v
"""
import base64
from contextlib import ExitStack
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from browser_test_support import start_browser_test, wait_for_boot, wait_for_boot_run, select_mode

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / 'artifacts' / 'levels' / 'extended-mountain.svg'
LEVEL = ROOT / 'artifacts' / 'levels' / 'extended-mountain.level.json'
LAYOUT_ID = 'extended-mountain-v18'
CLIMB_KEY = 'grapnelninja.grappleOver'
# Tree before TASK-650: physics, collision and sprite sources must match it.
BASE_REV = '8b9bbf6'
UNCHANGED = ['physics.js', 'fixedlevel.js', 'collision', 'sprites', 'elements', 'respawn.js', 'moveScreen.js', 'render']

# TASK-667: the only sprites/trampoline.js change (git diff -U0 lines): closePath
# before fill/stroke in the ordinary draw path; vertices, curves and the bad branch untouched.
TRAMPOLINE_CLOSE_DIFF = [
    '+        // Closed before painting, so the stroke joins the closing corner',
    '+        // (the last vertex) instead of ending there with two line caps',
    '+        ctx.closePath()',
    '+',
    '-        ctx.closePath()',
]

# TASK-662: the only physics.js change since BASE_REV (git diff -U0 lines), plus
# TASK-665's two long-fall detector calls (longfall.js; no physics change).
PHYSICS_FALL_RECOVERY_DIFF = [
    '+// Grapple Over: falling strictly below this many world units under the spawn',
    '+// returns the player to the spawn without restarting the run.',
    '+const CLIMB_FALL_RECOVERY_DEPTH = 1500',
    '-    for (cycle = 0; cycle < cyclesPerTick - 1; ++cycle)',
    '+    // A fall recovery ends the tick at the spawn, so the recovery step is observable.',
    '+    let recovered = false',
    '+    for (cycle = 0; cycle < cyclesPerTick - 1 && !recovered; ++cycle)',
    '-        calcPhysics()',
    '+        recovered = calcPhysics()',
    '-    calcPhysics()',
    '+    if (!recovered) calcPhysics()',
    # TASK-673: the no-grapple release hook (fixedlevel.js applyNoGrappleZones).
    "+    // Release in the step of entry, before this step's rope pull or acquisition.",
    "+    if (version === 'grapple_over') floors[0].applyNoGrappleZones(ninja)",
    '+        LONG_FALL.step()',
    '+        if (stats.currentHeight < -CLIMB_FALL_RECOVERY_DEPTH)',
    '+        {',
    '+            recoverClimbFall()',
    '+            return true',
    '+        }',
    '+',
    # TASK-717: the recovery launches like a fresh start (comment and speedY below).
    '+// Teleport a fallen Grapple Over player to the spawn and launch it upward',
    '+// like a fresh start. Time, best height, upgrades and the world (movers',
    '+// included) are kept; only the player, grapple, gameplay input ownership and',
    '+// camera are reset.',
    '+function recoverClimbFall()',
    '+{',
    '+    const world = floors[0], spawn = world.level.spawn',
    '+    ninja.x = spawn.x',
    '+    ninja.y = spawn.y',
    '+    ninja.speedX = 0',
    '+    ninja.speedY = -getSpawnLaunchSpeed()',
    '+    ninja.track.pos = []',
    '+    ninja.track.addPos(ninja.x, ninja.y, true)',
    '+    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,',
    '+        aim: null, clip: null, traveled: 0, speedX: 0, speedY: 0})',
    '+    // A press held through the fall cannot grapple again until it is released.',
    '+    gameplayPressOwned = false',
    '+    stalePress = pressHeld',
    '+    world.climbStats.currentHeight = 0',
    '+    LONG_FALL.restartTracking()',
    '+    screen.trackGrappleOver(true)',
    # TASK-721: the run's first recovery in single mode opens the double grapnel offer.
    "+    // The run's first recovery in single mode pauses on the double grapnel",
    '+    // offer; the launch above plays once it is answered.',
    "+    const offer = !world.doubleOfferShown && world.grapnelMode !== 'double'",
    '+    world.doubleOfferShown = true',
    '+    PROGRESS.flushClimb()',
    '+    if (offer) CLIMB_UI.offerDouble()',
    '+}',
]

# TASK-704: the Grapple Over spawn launch, added right after CLIMB_FALL_RECOVERY_DEPTH.
SPAWN_LAUNCH_DIFF = [
    '+// Grapple Over: a fresh start (first run or restart) launches the ninja',
    '+// upward from the spawn so its no-input free-flight apex is this high.',
    '+const SPAWN_LAUNCH_RISE = 270',
    '+',
    '+// Apex rise of a no-input flight starting at speedY = -speed, integrated',
    '+// exactly as calcPhysics/Ninja.move do it (gravity, speed cap, then move).',
    '+function spawnLaunchRise(speed)',
    '+{',
    '+    const maxSpeed = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)',
    '+    let speedY = -speed, rise = 0',
    '+    for (;;)',
    '+    {',
    '+        speedY = Math.max(-maxSpeed, Math.min(maxSpeed, speedY + GRAVITY))',
    '+        if (speedY >= 0) return rise',
    '+        rise -= speedY',
    '+    }',
    '+}',
    '+// Upward speed whose no-input apex is SPAWN_LAUNCH_RISE above the spawn.',
    '+function getSpawnLaunchSpeed()',
    '+{',
    '+    let low = 0, high = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)',
    '+    for (let i = 0; i < 60; ++i)',
    '+    {',
    '+        const mid = (low + high) / 2',
    '+        if (spawnLaunchRise(mid) < SPAWN_LAUNCH_RISE) low = mid',
    '+        else high = mid',
    '+    }',
    '+    return (low + high) / 2',
    '+}',
]

SNAPSHOT = '''() => {
    const w = floors[0], l = w.level
    return {
        version, world: w.constructor.name, layoutId: l.layoutId,
        fragments: l.svgFormat ? l.svgFormat.fragments.length : null,
        transfers: l.svgFormat ? l.svgFormat.transfers.length : null,
        elementCount: w.elements.length, dragZones: w.dragZones.map(z => z.id),
        noGrappleZones: (w.noGrappleZones || []).map(z => z.id),
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
        page.on('response', lambda r: 'leveldata.js' in r.url and requests.append({'url': r.url.split('/', 3)[3], 'status': r.status}))
        if seed is not None:
            page.add_init_script('for (const [k, v] of Object.entries(%s)) localStorage.setItem(k, v)' % json.dumps(seed))
        if route:
            page.route('**/leveldata.js', route)
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
        # Counts come from the shipped measurements (v18: 104 panels, 103 transfers), not fixed numbers.
        meas = json.loads((ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json').read_text())
        self.assertEqual(snap['fragments'], len(meas['fragments']))
        self.assertEqual(snap['fragments'], self.svg['fragments'])
        self.assertEqual(snap['transfers'], len(meas['encounters']))
        self.assertEqual(len(snap['dragZones']), len(self.svg['drag']))
        self.assertEqual(sorted(snap['dragZones']), self.svg['drag'])
        self.assertEqual(snap['spawn'], self.svg['spawn'])
        self.assertEqual(snap['finish'], self.svg['finish'])
        self.assertEqual(snap['spawn'], self.level['spawn'])
        self.assertEqual(snap['finish'], self.level['finish'])
        self.assertEqual(snap['bounds'], self.level['bounds'])
        # Every authored element, unchanged, with no extra or missing ids.
        self.assertEqual(snap['levelElements'], self.level['elements'])
        # No-grapple zones (NG1 since v13) live in world.noGrappleZones, not in elements/dragZones.
        source = {e['id']: e for e in self.level['elements'] if e['role'] != 'no-grapple'}
        self.assertEqual(snap['noGrappleZones'], [e['id'] for e in self.level['elements'] if e['role'] == 'no-grapple'])
        # Purple encounters, then the SEC-ext-summit big zones (v18), counted from the measurements.
        self.assertEqual(snap['noGrappleZones'], [p['zone'] for p in meas['purpleExtensions']] + meas.get('extSummit', {}).get('zones', []))
        self.assertEqual(snap['noGrappleZones'], [z['id'] for z in meas['noGrappleZones']])
        self.assertEqual(sorted(e['id'] for e in snap['live']), sorted(source))
        for e in snap['live']:
            s = source[e['id']]
            self.assertEqual((e['x'], e['y'], e['role'], e['grapplable']), (s['x'], s['y'], s['role'], s['grapplable']), e['id'])
        self.assertEqual(snap['range'], 540)

    def test_02_restart(self):
        page = self.open()
        page.evaluate(RESTART)
        snap = page.evaluate(SNAPSHOT)
        self.assert_imported(snap)
        self.assertEqual((snap['ninja']['x'], snap['ninja']['y']), (snap['spawn']['x'], snap['spawn']['y']))
        self.assertEqual(snap['tick'], 0)
        self.assertEqual(page.errors, [])
        self.record('restart', page, snap, coordinatesMatchSource=True, elementsCompared=len(snap['live']))

    def test_starting_platform_is_green_bounce(self):
        page = self.open()
        roles = page.evaluate("""() => floors[0].elements
            .filter(e => e.id.startsWith('P0-body'))
            .map(e => ({id: e.id, role: e.surfaceRole, grapplable: e.grapplable}))""")
        self.assertEqual(len(roles), 1)
        self.assertTrue(all(e['role'] == 'bounce' and e['grapplable'] for e in roles))
        self.assertEqual(page.errors, [])

    def test_local_file_start(self):
        # Windows double-click / file:// startup cannot fetch the JSON asset.
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.goto((ROOT / 'index.html').as_uri())
        wait_for_boot_run(page)
        self.assert_imported(page.evaluate(SNAPSHOT))
        self.assertEqual(errors, [])
        self.assertFalse(page.locator('#boot-retry').is_visible())
        self.assertEqual(page.evaluate('window.GRAPPLE_OVER_BUNDLED_LEVEL'), self.level)

    def test_local_script_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'level.js'
            result = subprocess.run([
                'python3', str(ROOT / 'tools/import_level_svg.py'),
                '--input', str(SVG), '--output', str(output), '--format', 'javascript'
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), (ROOT / 'leveldata.js').read_bytes())

    def test_03_incompatible_previous_layout_save(self):
        # TASK-711: saves from v17 (and earlier imported layouts) restart at the spawn. The save is a real current one
        # with the old layout id. A fresh start launches upward (TASK-704), so y may be up to the launch apex above.
        first = self.open()
        save = json.loads(first.evaluate('''() => {
            window.requestAnimationFrame = () => 0; cancelAnimationFrame(game)
            ninja.x += 600; ninja.y -= 200; for (let i = 0; i < 20; i++) physics()
            return JSON.stringify(captureClimbState())
        }'''))
        self.assertEqual(save['layoutId'], LAYOUT_ID)
        results = {}
        for old in ('extended-mountain-v17', 'extended-mountain-v16', 'extended-mountain-v15'):
            page = self.open(seed={CLIMB_KEY: json.dumps(dict(save, layoutId=old))})
            snap = page.evaluate(SNAPSHOT)
            self.assert_imported(snap)
            self.assertEqual(snap['notice'], 'Climb save unavailable. Starting at the base.')
            self.assertLess(abs(snap['ninja']['x'] - snap['spawn']['x']), 1)
            self.assertTrue(snap['spawn']['y'] - 280 < snap['ninja']['y'] <= snap['spawn']['y'] + 1, snap['ninja'])
            self.assertLess(snap['stats']['maxHeight'], 300)
            self.assertFalse(snap['paused'])
            # The next write replaces the rejected save with the new layout.
            page.evaluate('PROGRESS.flushClimb(true)')
            page.wait_for_function('k => JSON.parse(localStorage.getItem(k)).layoutId === "%s"' % LAYOUT_ID, arg=CLIMB_KEY)
            self.assertEqual(first.errors + page.errors, [])
            self.record('incompatible_save_' + old, page, snap, seededLayoutId=old, rewrittenLayoutId=LAYOUT_ID,
                        savedPlayer={'x': save['player']['x'], 'y': save['player']['y']})
            results[old] = snap['notice']
        self.assertEqual(len(results), 3)

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
        expected = [e for e in failed.errors if 'Application boot failed' in e or '404' in e or 'MIME type' in e]
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
        # The only later change is TASK-659's display-only guide arrows: a new render file, its
        # script tag and the call in drawWorldLayer(). TASK-662 added only the Grapple Over
        # fall recovery to physics.js (PHYSICS_FALL_RECOVERY_DIFF below). TASK-663 changed only
        # the tutorial sprite (render/tutorialhint.js), which builds no world objects.
        # TASK-664 changed only the panel circuits (render/roledetail.js). TASK-666 added the
        # screen-space long-fall message (render/fallmessage.js): its script tag, the call in
        # draw() and its fade advance next to the tutorial hint's in the game loop. TASK-667
        # moved Trampoline.draw's closePath before its fill/stroke (TRAMPOLINE_CLOSE_DIFF).
        # TASK-672/673 added the no-grapple zone role to fixedlevel.js (validation, world.noGrappleZones,
        # applyNoGrappleZones) and its physics hook; TASK-674 added render/nograpplezones.js, its
        # script tag and the call in drawWorldLayer(). These are covered by test_no_grapple_*.
        # TASK-692 centered the Grapple Over camera on the ninja (moveScreen.js only; covered by the camera tests).
        # TASK-699/701 changed only display code (render/effects.js glow, render/parallax.js tiles). TASK-704 added
        # the Grapple Over spawn launch (SPAWN_LAUNCH_DIFF in physics.js, one assignment in startGrappleOverVersion);
        # TASK-717 applied it to recoverClimbFall too; TASK-721 opens the first-death offer from it. TASK-714/715/716 changed only display code
        # (render/glowsprites.js bakes, render/landmarks.js, the sprites/grapnel.js rope and claw drawing).
        diff = subprocess.run(['git', 'diff', '--stat', BASE_REV, '--'] + UNCHANGED + [':!render/routearrows.js', ':!render/draw.js', ':!physics.js',
                                                                                      ':!render/tutorialhint.js', ':!render/roledetail.js',
                                                                                      ':!render/fallmessage.js', ':!sprites/trampoline.js',
                                                                                      ':!fixedlevel.js', ':!render/nograpplezones.js', ':!moveScreen.js',
                                                                                      ':!render/effects.js', ':!render/parallax.js',
                                                                                      ':!render/glowsprites.js', ':!render/landmarks.js',
                                                                                      ':!sprites/grapnel.js'],
                              cwd=ROOT, capture_output=True, text=True, check=True).stdout
        self.assertEqual(diff, '')
        lines = lambda path: [l for l in subprocess.run(['git', 'diff', '-U0', BASE_REV, '--', path], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.splitlines() if l[:1] in '+-' and not l.startswith(('+++', '---'))]
        # TASK-714 also rewrote the palette wash in render/draw.js (display only, baked via float16), so the
        # layer-order lines are checked as an ordered subsequence of the draw.js diff.
        draw_lines = iter(lines('render/draw.js'))
        self.assertTrue(all(l in draw_lines for l in ['+    // Purple no-grapple zones under everything else in the world',
                                                   '+    drawNoGrappleZones(floors[0])',
                                                   '+    // Transfer guide arrows under the range circle, grapnel, terrain and player',
                                                   '+    drawRouteArrows(floors[0])',
                                                   '+// Long-fall reaction: screen space, over the hint and under the HUD it avoids',
                                                   '+function drawFallMessageLayer()', '+{', '+    FALL_MESSAGE.draw(ctx)', '+}', '+',
                                                   "+    if (version === 'grapple_over')", '+        drawFallMessageLayer()']))
        self.assertEqual(lines('physics.js'), PHYSICS_FALL_RECOVERY_DIFF[:3] + SPAWN_LAUNCH_DIFF + PHYSICS_FALL_RECOVERY_DIFF[3:])
        self.assertEqual(lines('sprites/trampoline.js'), TRAMPOLINE_CLOSE_DIFF)
        changed = lines('index.html')
        self.assertEqual(changed, ['+        <script src = "longfall.js"></script>',
                                   '+        <script src = "render/fallmessage.js"></script>',
                                   '+        <script src = "render/nograpplezones.js"></script>',
                                   '+        <script src = "render/routearrows.js"></script>',
                                   '+                await loadGrappleOverLevelAsset()',
                                   '+                // A fresh start (first run or restart) launches upward, as',
                                   '+                // does a fall recovery; a continue or save restore does not.',
                                   '+                ninja.speedY = -getSpawnLaunchSpeed()',
                                   '-                    if (activelyPlaying) TUTORIAL_HINT.advance(steps * physicsStepMs)',
                                   '+                    if (activelyPlaying)', '+                    {',
                                   '+                        TUTORIAL_HINT.advance(steps * physicsStepMs)',
                                   '+                        FALL_MESSAGE.advance(steps * physicsStepMs)', '+                    }',
                                   # TASK-721: a step can open the first-death offer's pause screen.
                                   '+                    // A step can open a pause screen (the first-death offer): keep it on top',
                                   '+                    if (menu.gamePaused) menu.drawPauseScreen()'])
        self.evidence['cases']['modes'] = dict(seen, browserErrors=page.errors, unchangedSources=UNCHANGED,
                                               baseRev=BASE_REV, unchangedDiff=diff, indexHtmlChanges=changed)


CONCEPT = SVG
MEASUREMENTS = ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json'
TOLERANCE = 0.01
TILE = (1280, 720)
KIND_ROLE = {'platform': 'solid', 'ceiling': 'solid', 'summit': 'solid', 'bounce': 'bounce', 'chute': 'bounce'}

# Freeze the loop and expose a fixed-camera production draw(). The HUD, tutorial
# hint and FPS counter are screen-space overlays: hide them so tiles stitch.
CAPTURE_SETUP = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    drawUILayer = () => {}
    drawTutorialHintLayer = () => {}
    drawFpsCounterLayer = () => {}
    // Canvas pixel = (world + screen) * scale * canvas.width / width: k pixels per world unit.
    window.TASK651_CAPTURE = (wx, wy, k, world) => {
        scale[version] = k * width / canvas.width
        screen.x = -wx
        screen.y = -wy
        if (!world) floors[0].draw = () => {}
        ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
        try { draw() } finally { delete floors[0].draw }
        return canvas.toDataURL('image/png')
    }
    return {canvas: [canvas.width, canvas.height], logical: [width, height], dpr: devicePixelRatio}
}'''

# The loaded objects themselves, as every collision, rope and render consumer sees them.
RUNTIME = '''() => {
    const w = floors[0]
    const shape = (e, collection) => ({id: e.id, role: e.surfaceRole, grapplable: e.grapplable, collection,
        points: e.getPoints().map(p => [p.x, p.y])})
    return {version, query: location.search, imported: GRAPPLE_OVER_IMPORTED_ACTIVE, world: w.constructor.name,
        layoutId: w.level.layoutId, elements: w.elements.map(e => shape(e, 'elements')),
        dragZones: w.dragZones.map(e => shape(e, 'dragZones')), byId: [...w.byId.keys()],
        transfers: w.level.svgFormat.transfers, fragments: w.level.svgFormat.fragments}
}'''

# Yellow zones: collections, a free fall through each zone and a held shot aimed
# into each zone through production mouse input; then a held shot at a solid top.
BEHAVIOR = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    const w = floors[0], drag = new Set(w.dragZones.map(z => z.id))
    const out = {collections: {dragZones: w.dragZones.map(z => z.id),
        elementsWithDrag: w.elements.filter(e => drag.has(e.id) || e.surfaceRole === 'drag').map(e => e.id),
        byIdWithDrag: [...w.byId.keys()].filter(id => drag.has(id)),
        // Grapnel shots and rope wraps walk floors[*].elements (sprites/grapnel.js).
        grappleGroupsWithDrag: floors.flatMap(f => f.elements).filter(e => drag.has(e.id)).map(e => e.id),
        floors: floors.length}, passThrough: [], noAttach: []}
    let contacts = []
    for (const method of ['applySolidContact', 'applyBounce'])
    {
        const original = Ninja.prototype[method]
        Ninja.prototype[method] = function (c) { contacts.push(c.element ? c.element.id : null); return original.call(this, c) }
    }
    let damped = 0
    const applyDrag = w.applyDragZones
    w.applyDragZones = function (player) {
        const before = [player.speedX, player.speedY]
        applyDrag.call(this, player)
        if (player.speedX !== before[0] || player.speedY !== before[1]) damped++
    }
    const reset = (x, y) => {
        if (grapnel.throwed) grapnel.endShot()
        grapnel.throwed = false; grapnel.grappled = false
        ninja.x = x; ninja.y = y; ninja.speedX = 0; ninja.speedY = 0
        contacts = []; damped = 0
        screen.trackGrappleOver(true)
    }
    const client = p => canvasCoordsToViewportCoords({x: (p.x + screen.x) * scale[version], y: (p.y + screen.y) * scale[version]})
    const mouse = (type, p) => { const q = client(p)
        document.dispatchEvent(new MouseEvent(type, {clientX: q.x, clientY: q.y, bubbles: true, button: 0})) }
    const box = e => { const ps = e.getPoints(), xs = ps.map(p => p.x), ys = ps.map(p => p.y)
        return {left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys)} }
    const shot = (from, target, ticks) => {
        reset(from.x, from.y)
        mouse('mousedown', target)
        const states = [], thrown = grapnel.throwed
        for (let i = 0; i < ticks; i++) {
            physics()
            states.push({grappled: grapnel.grappled, element: grapnel.grappled ? grapnel.pos[0][2].id : null})
        }
        mouse('mouseup', target)
        const hit = states.find(s => s.grappled)
        return {from, target, ticks, thrown, grappled: !!hit, element: hit ? hit.element : null,
            firstGrappledTick: hit ? states.indexOf(hit) + 1 : null, range: grappleOverAcquisitionRadius()}
    }
    for (const zone of w.dragZones)
    {
        const b = box(zone), cx = (b.left + b.right) / 2
        reset(cx, b.top - 150)
        let entered = null, exited = null, inside = 0
        for (let tick = 1; tick <= 1200 && exited === null; tick++)
        {
            physics()
            const overlap = ninja.y + ninja.radius > b.top && ninja.y - ninja.radius < b.bottom
            if (overlap) { inside++; if (entered === null) entered = tick }
            if (ninja.y - ninja.radius > b.bottom) exited = tick
        }
        out.passThrough.push({id: zone.id, top: b.top, bottom: b.bottom, enteredTick: entered, exitedBelowTick: exited,
            ticksOverlapping: inside, dampedTicks: damped, contacts: contacts.slice(), y: ninja.y, radius: ninja.radius})
        out.noAttach.push({id: zone.id, ...shot({x: cx, y: b.top - 200}, {x: cx, y: b.top + 120}, 90)})
    }
    const solid = w.byId.get('P1-body0'), sb = box(solid), ps = solid.getPoints()
    const top = {x: (ps[0].x + ps[1].x) / 2, y: (ps[0].y + ps[1].y) / 2}
    out.control = {id: solid.id, ...shot({x: top.x, y: top.y - 200}, {x: top.x, y: top.y + 20}, 90)}
    return out
}'''


def concept_mapping():
    """Concept canvas -> world, from the annotation matrix TASK-647 wrote into the import SVG."""
    text = SVG.read_text()
    a, b, c, d, e, f = map(float, re.search(r'data-layer="annotations"[^>]*transform="matrix\(([^)]*)\)"', text).group(1).split())
    assert b == c == 0 and a == d
    return a, e, f


def image(data_url):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(',', 1)[1]))).convert('RGB')


def poly_distance(a, b):
    """Minimum edge-to-edge distance between two separated polygons."""
    return min(min(boundary_distance(p, b) for p in a), min(boundary_distance(p, a) for p in b))


def boundary_distance(p, poly):
    best = math.inf
    for q, r in zip(poly, poly[1:] + poly[:1]):
        dx, dy = r[0] - q[0], r[1] - q[1]
        t = max(0, min(1, ((p[0] - q[0]) * dx + (p[1] - q[1]) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(p[0] - q[0] - t * dx, p[1] - q[1] - t * dy))
    return best


def fit(points, box, pad):
    """jump-combinations.svg panel framing (artifacts/level/generate_extended.py fit())."""
    xmin = min(x for x, y in points) - pad
    xmax = max(x for x, y in points) + pad
    ymin = min(y for x, y in points) - pad
    ymax = max(y for x, y in points) + pad
    bx, by, bw, bh = box
    s = min(bw / (xmax - xmin), bh / (ymax - ymin))
    return s, bx + (bw - (xmax - xmin) * s) / 2 - xmin * s, by + (bh - (ymax - ymin) * s) / 2 - ymin * s


class Task651Tests(unittest.TestCase):
    """TASK-651: the default imported level as production renders and loads it."""

    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)
        out = os.environ.get('TASK651_EVIDENCE_DIR')
        if not out:
            out = cls.stack.enter_context(tempfile.TemporaryDirectory())
        cls.out = Path(out)
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.level = json.loads(LEVEL.read_text())
        cls.measurements = json.loads(MEASUREMENTS.read_text())
        cls.errors = []

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def open(self):
        """Normal default-level startup: no query, no fixture, no seeded save."""
        context = self.browser.new_context(viewport={'width': TILE[0], 'height': TILE[1]}, device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append('pageerror: %s' % e))
        page.on('console', lambda m: m.type == 'error' and self.errors.append('console: %s' % m.text))
        page.goto(self.url)
        wait_for_boot_run(page)
        state = page.evaluate('() => ({version, search: location.search, layoutId: floors[0].level.layoutId,'
                              ' imported: GRAPPLE_OVER_IMPORTED_ACTIVE, world: floors[0].constructor.name})')
        self.assertEqual(state, {'version': 'grapple_over', 'search': '', 'layoutId': LAYOUT_ID,
                                 'imported': True, 'world': 'PersistentWorld'})
        return page, state

    def game(self, page, left, top, k, size, world=True):
        """Stitch TILE-sized production frames into a size image of the world window at (left, top)."""
        from PIL import Image
        out = Image.new('RGB', size)
        for ty in range(0, size[1], TILE[1]):
            for tx in range(0, size[0], TILE[0]):
                out.paste(image(page.evaluate('a => TASK651_CAPTURE(...a)', [left + tx / k, top + ty / k, k, world])), (tx, ty))
        return out

    def concept(self, page, viewbox, size):
        """The concept SVG itself, rendered with its viewBox set to the same world window."""
        from PIL import Image
        text = CONCEPT.read_text()
        a, e, f = concept_mapping()
        viewbox = (viewbox[0]*a+e, viewbox[1]*a+f, viewbox[2]*a, viewbox[3]*a)
        svg = re.sub(r'<svg[^>]*?>', lambda m: re.sub(r' (width|height|viewBox)="[^"]*"', '', m.group(0))[:-1] +
                     ' width="%d" height="%d" viewBox="%s" preserveAspectRatio="none">' % (size[0], size[1], ' '.join(repr(v) for v in viewbox)),
                     text, count=1)
        page.set_viewport_size({'width': size[0], 'height': size[1]})
        page.set_content('<html><body style="margin:0;background:#000">%s</body></html>' % svg)
        return Image.open(io.BytesIO(page.screenshot(clip={'x': 0, 'y': 0, 'width': size[0], 'height': size[1]}))).convert('RGB')

    def runtime(self, page):
        return page.evaluate(RUNTIME)

    def test_01_captures(self):
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
        a, e, f = concept_mapping()
        # The mapping is the concept's own: every concept fragment polygon (measurement
        # world data) lands on a polygon drawn in extended-mountain.svg.
        drawn = [[tuple(map(float, p.split(','))) for p in m.split()]
                 for m in re.findall(r'<polygon id="P[^"]*" points="([^"]*)"', CONCEPT.read_text())]
        drawn = [[((x-e)/a, (y-f)/a) for x,y in poly] for poly in drawn]
        mapping_error = 0
        for m in self.measurements['fragments']:
            for poly in m['polys']:
                canvas = [((m['x'] + x - e) / a, (m['y'] + y - f) / a) for x, y in poly]
                errors = [max(max(abs(p[0] - q[0]), abs(p[1] - q[1])) for p, q in zip(canvas, d))
                          for d in drawn if len(d) == len(canvas)]
                mapping_error = max(mapping_error, min(errors))
        self.assertLess(mapping_error, 0.006)

        page, state = self.open()
        setup = page.evaluate(CAPTURE_SETUP)
        self.assertEqual(setup['canvas'], list(TILE))
        runtime = self.runtime(page)
        polys = runtime['elements'] + runtime['dragZones']
        svg_page = self.browser.new_page()
        self.addCleanup(svg_page.close)
        views = []

        def view(name, left, top, k, size):
            game = self.game(page, left, top, k, size)
            concept = self.concept(svg_page, ((left - e) / a, (top - f) / a, size[0] / k / a, size[1] / k / a), size)
            px = lambda p: ((p[0] - left) * k, (p[1] - top) * k)
            views.append({'name': name, 'worldLeft': left, 'worldTop': top, 'pixelsPerWorldUnit': k, 'sizePx': list(size),
                          'worldRight': left + size[0] / k, 'worldBottom': top + size[1] / k,
                          'conceptViewBox': [(left - e) / a, (top - f) / a, size[0] / k / a, size[1] / k / a]})
            return game, concept, px

        def label(img, text):
            img = img.copy()
            d = ImageDraw.Draw(img)
            d.rectangle([0, 0, img.width, 26], fill=(0, 0, 0))
            d.text((8, 7), text, fill=(255, 255, 0))
            return img

        def side(left, right, gap=16):
            out = Image.new('RGB', (left.width + right.width + gap, max(left.height, right.height)), (255, 255, 255))
            out.paste(left, (0, 0))
            out.paste(right, (left.width + gap, 0))
            return out

        def outline(img, px, measured=True):
            img = img.copy()
            d = ImageDraw.Draw(img)
            if measured:
                for m in self.measurements['fragments']:
                    for poly in m['polys']:
                        d.polygon([px((m['x'] + x, m['y'] + y)) for x, y in poly], outline=(255, 0, 255))
            for p in polys:
                colour = (255, 230, 0) if p['collection'] == 'dragZones' else (0, 255, 255)
                d.line([px(q) for q in p['points'] + p['points'][:1]], fill=colour, width=2)
            for enc in self.measurements['encounters']:
                (x0, y0), (x1, y1) = px(enc['witness'][0]), px(enc['witness'][1])
                d.line([(x0, y0), (x1, y1)], fill=(255, 255, 255), width=1)
                for x, y in ((x0, y0), (x1, y1)):
                    d.ellipse([x - 3, y - 3, x + 3, y + 3], outline=(255, 64, 64), width=2)
            return img

        # Overview: the concept's whole 2600x4300 canvas at half size.
        size = (1300, 2150)
        game, concept, px = view('overview', e, f, 1 / (2 * a), size)
        game.save(self.out / 'full-map-game.png')
        side(label(concept, 'AUTHORING artifacts/levels/extended-mountain.svg (world %.0f,%.0f; %.4f px/u)' % (e, f, 1 / (2 * a))),
             label(game, 'GAME production draw(), default start, same world window and scale')).save(self.out / 'full-map-comparison.png')
        side(label(outline(game, px), 'GAME + runtime polygons (cyan), runtime drag zones (yellow)'),
             label(outline(concept, px), 'CONCEPT + same; magenta = measurements, red = transfer endpoints')).save(self.out / 'geometry-overlay.png')

        # Close-ups: the jump-combinations.svg panel windows for chains 11-13, 14-16, 18-20, 22-24.
        rows, registration = [], []
        frags = self.measurements['fragments']
        for i, (first, middle, last) in enumerate(self.measurements['combinations']):
            bx, by, bw, bh = 70 + (i % 2) * 1260, 220 + (i // 2) * 1000, 1200, 930
            pts = [(m['x'] + x, m['y'] + y) for m in frags[first - 1:last + 1] for poly in m['polys'] for x, y in poly]
            pts += [tuple(q) for z in self.measurements['yellowBands'] if z['belowJump'] == middle for q in z['polygon']]
            s, ox, oy = fit(pts, (bx + 40, by + 130, bw - 80, bh - 240), 650)
            name = 'chain-%02d-%02d' % (first, last)
            game, concept, px = view(name, (bx - ox) / s, (by - oy) / s, s, (bw, bh))
            game.save(self.out / ('closeup-%s-game.png' % name))
            outline(game, px, measured=False).save(self.out / ('closeup-%s-overlay.png' % name))
            rows.append(side(label(concept, 'CONCEPT %s (%.4f px/u)' % (name, s)),
                             label(game, 'GAME %s: same world window' % name)))
            # Registration: pixels the world layer changes vs runtime polygons drawn at this mapping.
            bare = self.game(page, (bx - ox) / s, (by - oy) / s, s, (bw, bh), world=False)
            # Permit one pixel of anti-aliasing at the thin green neon outline.
            changed = ImageChops.difference(game, bare).convert('L').point(lambda v: 255 if v > 16 else 0).filter(ImageFilter.MaxFilter(3))

            # The outline strokes are bright on every role; the dark solid fill is not.
            def coverage(dx):
                mask = Image.new('L', (bw, bh))
                d = ImageDraw.Draw(mask)
                for p in polys:
                    d.line([(x + dx, y) for x, y in map(px, p['points'] + p['points'][:1])], fill=255, width=1)
                hit = ImageChops.multiply(mask, changed).histogram()[255]
                return hit / max(1, mask.histogram()[255])
            registration.append({'view': name, 'outlineCoverage': coverage(0), 'outlineCoverageShifted40px': coverage(40)})
        combo = Image.new('RGB', (rows[0].width, sum(r.height for r in rows) + 16 * (len(rows) - 1)), (255, 255, 255))
        y = 0
        for r in rows:
            combo.paste(r, (0, y))
            y += r.height + 16
        combo.resize((combo.width // 2, combo.height // 2), Image.LANCZOS).save(self.out / 'combinations-comparison.png')
        browser = self.browser.version
        capture = {'startup': state, 'setup': setup, 'browser': 'chromium ' + browser, 'viewport': list(TILE),
                   'deviceScaleFactor': 1, 'tile': list(TILE), 'conceptToWorld': {'scale': a, 'offset': [e, f]},
                   'conceptMappingMaxErrorPx': mapping_error, 'views': views, 'registration': registration,
                   'hiddenOverlays': ['drawUILayer', 'drawTutorialHintLayer', 'drawFpsCounterLayer'],
                   'inputs': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (CONCEPT, MEASUREMENTS, SVG, LEVEL)}}
        (self.out / 'capture.json').write_text(json.dumps(capture, separators=(',', ':')))
        for r in registration:
            self.assertGreater(r['outlineCoverage'], 0.9, r)
            self.assertLess(r['outlineCoverageShifted40px'], r['outlineCoverage'] - 0.3, r)
        self.assertEqual(self.errors, [])

    def test_02_runtime_fidelity(self):
        page, state = self.open()
        rt = self.runtime(page)
        report = {'startup': state, 'tolerance': TOLERANCE, 'checks': {}}
        # No-grapple zones are not live solids or drag zones (world.noGrappleZones).
        source = {e['id']: e for e in self.level['elements'] if e['role'] != 'no-grapple'}
        live = rt['elements'] + rt['dragZones']
        self.assertEqual(sorted(e['id'] for e in live), sorted(source))
        # Against the imported level data.
        worst = 0
        for e in live:
            s = source[e['id']]
            self.assertEqual((e['role'], e['grapplable']), (s['role'], s['grapplable']), e['id'])
            self.assertEqual(len(e['points']), len(s['points']), e['id'])
            for (x, y), p in zip(e['points'], s['points']):
                worst = max(worst, abs(x - s['x'] - p['x']), abs(y - s['y'] - p['y']))
        self.assertLessEqual(worst, TOLERANCE)
        report['checks']['importedData'] = {'objects': len(live), 'maxError': worst, 'rolesAndGrapplableMatch': True}
        # Against the concept measurements: fragment bodies and roles.
        worst, kinds = 0, {}
        by_id = {e['id']: e for e in live}
        for m in self.measurements['fragments']:
            for k, poly in enumerate(m['polys']):
                e = by_id['%s-body%d' % (m['id'], k)]
                self.assertEqual(e['role'], m.get('surfaceRole', KIND_ROLE[m['kind']]), e['id'])
                self.assertTrue(e['grapplable'], e['id'])
                self.assertEqual(e['collection'], 'elements')
                self.assertEqual(len(e['points']), len(poly), e['id'])
                for (x, y), (px, py) in zip(e['points'], poly):
                    worst = max(worst, abs(x - m['x'] - px), abs(y - m['y'] - py))
                kinds[m['kind']] = kinds.get(m['kind'], 0) + 1
        self.assertLessEqual(worst, TOLERANCE)
        self.assertEqual(len(rt['elements']), sum(kinds.values()))
        report['checks']['conceptFragments'] = {'fragments': len(self.measurements['fragments']), 'bodies': sum(kinds.values()),
                                                'bodiesByKind': kinds, 'maxError': worst}
        # Transfer endpoints: on the live fragment boundaries, at the measured distance.
        fragment = lambda fid: [e['points'] for e in rt['elements'] if e['id'].startswith(fid + '-body')]
        transfers = {t['encounter']: t for t in rt['transfers']}
        rows = []
        for enc in self.measurements['encounters']:
            src, dst = fragment(enc['fromFragment']), fragment(enc['toFragment'])
            endpoint = [min(boundary_distance(enc['witness'][0], p) for p in src),
                        min(boundary_distance(enc['witness'][1], p) for p in dst)]
            gap = min(poly_distance(p, q) for p in src for q in dst)
            t = transfers[enc['id']]
            row = {'transfer': t['id'], 'encounter': enc['id'], 'from': enc['fromFragment'], 'to': enc['toFragment'],
                   'endpointOffsets': endpoint, 'runtimeGap': gap, 'measuredGap': enc['distance'],
                   'runtimePercent': gap / 540 * 100, 'gapPercent': t['gapPercent']}
            self.assertEqual((t['from'], t['to']), (enc['fromFragment'], enc['toFragment']))
            self.assertEqual(t['id'], 'T%02d' % enc['number'])
            self.assertLessEqual(max(endpoint), TOLERANCE, row)
            self.assertLessEqual(abs(gap - enc['distance']), TOLERANCE, row)
            self.assertLessEqual(abs(gap / 540 * 100 - t['gapPercent']), TOLERANCE, row)
            rows.append(row)
        self.assertEqual(len(rows), len(json.loads((ROOT / 'artifacts' / 'levels' / 'extended-mountain-measurements.json').read_text())['encounters']))
        self.assertGreater(len(rows), 0)
        report['checks']['transfers'] = {'count': len(rows), 'endpointsChecked': 2 * len(rows),
                                         'maxEndpointOffset': max(max(r['endpointOffsets']) for r in rows),
                                         'maxGapError': max(abs(r['runtimeGap'] - r['measuredGap']) for r in rows),
                                         'rows': rows}
        # Six yellow rectangles: live drag zones vs measurements and the SVG rects.
        root = ET.parse(SVG).getroot()
        svg_rects = {r.get('id'): r for r in root.iter('{http://www.w3.org/2000/svg}rect') if r.get('data-role') == 'drag'}
        zones = {z['id']: z for z in rt['dragZones']}
        rects = []
        for band in self.measurements['yellowBands']:
            z = zones['%s-drag' % band['id']]
            xs, ys = [p[0] for p in z['points']], [p[1] for p in z['points']]
            box = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
            want = [band['x'], band['y'], band['width'], band['height']]
            r = svg_rects[z['id']]
            svg = [float(r.get(k)) for k in ('x', 'y', 'width', 'height')]
            aligned = len(xs) == 4 and len(set(round(x, 6) for x in xs)) == 2 and len(set(round(y, 6) for y in ys)) == 2
            err = max(max(abs(p - q) for p, q in zip(box, want)), max(abs(p - q) for p, q in zip(box, svg)))
            self.assertTrue(aligned, z['id'])
            self.assertLessEqual(err, TOLERANCE, z['id'])
            self.assertEqual((z['role'], z['grapplable'], z['collection']), ('drag', False, 'dragZones'))
            rects.append({'id': z['id'], 'band': band['id'], 'belowJump': band['belowJump'], 'runtime': box,
                          'measured': want, 'maxError': err, 'axisAligned': aligned})
        self.assertEqual(len(rects), len(self.measurements['yellowBands']))
        report['checks']['yellowRectangles'] = {'count': len(rects), 'rows': rects}
        self.assertEqual(self.errors, [])
        report['browserErrors'] = list(self.errors)
        report['result'] = 'PASS'
        (self.out / 'runtime-fidelity.json').write_text(json.dumps(report, separators=(',', ':')))

    def test_03_yellow_zone_behavior(self):
        page, state = self.open()
        out = page.evaluate(BEHAVIOR)
        c = out['collections']
        lines = ['STARTUP %s' % json.dumps(state, sort_keys=True),
                 'COLLECTION dragZones=%s' % ','.join(c['dragZones']),
                 'COLLECTION elements_with_drag=%d byId_with_drag=%d grapple_collision_groups_with_drag=%d floors=%d'
                 % (len(c['elementsWithDrag']), len(c['byIdWithDrag']), len(c['grappleGroupsWithDrag']), c['floors'])]
        self.assertEqual(sorted(c['dragZones']), sorted(z['id']+'-drag' for z in self.measurements['yellowBands']))
        self.assertEqual(c['elementsWithDrag'] + c['byIdWithDrag'] + c['grappleGroupsWithDrag'], [])
        for p in out['passThrough']:
            ok = (p['enteredTick'] is not None and p['exitedBelowTick'] is not None and p['contacts'] == []
                  and p['dampedTicks'] > 0)
            lines.append('PASS_THROUGH %s top=%.2f bottom=%.2f entered_tick=%s exited_below_tick=%s overlapping_ticks=%d '
                         'damped_ticks=%d contacts=%d RESULT %s' % (p['id'], p['top'], p['bottom'], p['enteredTick'],
                         p['exitedBelowTick'], p['ticksOverlapping'], p['dampedTicks'], len(p['contacts']), 'PASS' if ok else 'FAIL'))
            self.assertTrue(ok, p)
        for n in out['noAttach']:
            # The ray may pass through a brake and legitimately attach to a
            # platform behind it. It must never attach to any drag zone.
            ok = n['thrown'] and n['element'] not in c['dragZones']
            lines.append('NO_ATTACH %s from=(%.2f,%.2f) aim=(%.2f,%.2f) ticks=%d range=%d thrown=%s grappled=%s element=%s RESULT %s'
                         % (n['id'], n['from']['x'], n['from']['y'], n['target']['x'], n['target']['y'], n['ticks'],
                            n['range'], str(n['thrown']).lower(), str(n['grappled']).lower(), n['element'], 'PASS' if ok else 'FAIL'))
            self.assertTrue(ok, n)
        ctl = out['control']
        lines.append('CONTROL_ATTACH %s aim=(%.2f,%.2f) grappled=%s element=%s first_grappled_tick=%s RESULT %s'
                     % (ctl['id'], ctl['target']['x'], ctl['target']['y'], str(ctl['grappled']).lower(), ctl['element'],
                        ctl['firstGrappledTick'], 'PASS' if ctl['thrown'] and ctl['element'] == 'P1-body0' else 'FAIL'))
        self.assertTrue(ctl['thrown'])
        self.assertEqual(ctl['element'], 'P1-body0')
        lines.append('BROWSER_PAGE_ERRORS %d' % len(self.errors))
        lines.extend('BROWSER_ERROR %s' % e for e in self.errors)
        self.assertEqual(self.errors, [])
        lines.append('BEHAVIOR_RESULT PASS')
        (self.out / 'behavior.log').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    unittest.main()
