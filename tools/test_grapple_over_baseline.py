"""TASK-444: observable, pre-change classic/bad behavior and immutable provenance."""
import json
import math
import subprocess
import unittest

from browser_test_support import start_browser_test
from grapple_over_test_support import (ROOT, VIEWPORT, EvidenceWriter, STATE,
                                       open_fixture, screenshot, source_hashes, step)


class Task444Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter()
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.baseline = {'revision': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'source_hashes': source_hashes(), 'seed': 1, 'modes': {},
            'browser': cls.browser.version, 'viewport': VIEWPORT,
            'device_scale_factor': 1, 'rendering': 'rAF cancelled; explicit physics() steps'}
        cls.behaviour = {}
        cls.evidence.log('CONFIG ' + json.dumps(cls.baseline, sort_keys=True))

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('baseline.json', cls.baseline)
        cls.evidence.write('behaviour.json', cls.behaviour)

    def open(self, mode):
        page, errors = open_fixture(self.browser, self.url, mode, self.addCleanup)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def test_seeded_movement_and_constants(self):
        for mode in ('classic', 'bad'):
            with self.subTest(mode=mode):
                page = self.open(mode)
                initial = page.evaluate(STATE)
                constants = page.evaluate('''() => ({gravity: GRAVITY, pull: grappleSpeed,
                    throwSpeed: grapnelSpeed, cyclesPerTick, physicsStepMs, gameplay: GAMEPLAY})''')
                trace = step(page, 12)
                replay = self.open(mode)
                self.assertEqual(initial, replay.evaluate(STATE))
                self.assertEqual(trace, step(replay, 12))
                self.assertAlmostEqual(initial['radius'], 10.8)
                self.assertEqual(initial['mode'], mode)
                self.assertNotEqual(trace[-1]['y'], initial['y'])
                self.assertGreater(constants['gravity'], 0)
                self.assertGreater(constants['pull'], 0)
                self.baseline['modes'][mode] = {'initial': initial, 'constants': constants,
                                               'movement_trace': trace, 'seeded_replay_equal': True}
                screenshot(page, self.evidence, mode + '-movement')
                print(f'PASS {mode} seeded movement: 12 steps, identical replay, radius=10.8')

    def test_grapple_pause_and_mode_switch(self):
        for mode in ('classic', 'bad'):
            with self.subTest(mode=mode):
                page = self.open(mode)
                before = page.evaluate(STATE)
                page.mouse.move(900, 200)
                page.mouse.down()
                thrown = page.evaluate(STATE)
                self.assertTrue(thrown['throwed'])
                trace = step(page, 3)
                self.assertNotEqual(trace[-1]['rope'], thrown['rope'])
                screenshot(page, self.evidence, mode + '-throw')
                page.mouse.up()
                released = page.evaluate(STATE)
                self.assertFalse(released['throwed'])
                self.assertFalse(released['grappled'])
                page.keyboard.press('p')
                paused = page.evaluate(STATE)
                self.assertTrue(paused['paused'])
                # Run the real loop with elapsed time; pause must suppress physics.
                page.evaluate('''() => {for(let i=0;i<10;i++) {
                    gameLoop(performance.now()+i*20); cancelAnimationFrame(game)}}''')
                self.assertEqual(paused, page.evaluate(STATE))
                page.screenshot(path=str(self.evidence.path('screenshots/' + mode + '-pause.png')))
                page.keyboard.press('p')
                self.assertFalse(page.evaluate(STATE)['paused'])
                resumed = step(page, 1)[0]
                self.assertNotEqual(resumed['y'], paused['y'])
                page.keyboard.press('p')
                page.wait_for_function('!unTouch')
                point = page.evaluate('''() => {const b=menu.backToMenu.background,
                    r=canvas.getBoundingClientRect(); return {
                    x:r.x+(b.x+b.width/2)*r.width/width,
                    y:r.y+(b.y+b.height/2)*r.height/height}}''')
                page.mouse.click(**point)
                other = 'bad' if mode == 'classic' else 'classic'
                page.wait_for_function('mode => version === mode && !menu.gamePaused', arg=other)
                page.evaluate('cancelAnimationFrame(game)')
                switched = page.evaluate(STATE)
                self.behaviour.setdefault(mode, {})['input'] = {
                    'events': ['mousedown(900,200)', 'physics x3', 'mouseup', 'p',
                               'gameLoop x10', 'p', 'physics x1', 'p', 'click mode switch'],
                    'before': before, 'thrown': thrown, 'trace': trace, 'released': released,
                    'paused': paused, 'pause_unchanged': True, 'resumed': resumed,
                    'switched': switched}
                print(f'PASS {mode} real input throw/release, pause frozen, resume, switch -> {other}')

    def test_flat_and_sloped_collisions(self):
        for mode in ('classic', 'bad'):
            page = self.open(mode)
            rows = {}
            for slope in (0, -0.5):
                row = page.evaluate('''slope => {
                    for(const floor of floors) floor.elements=[];
                    const x=width*0.4, y=height*0.6, w=width*0.2;
                    const t=new Trampoline({x,y,points:[{x:0,y:120},{x:0,y:0},
                        {x:w,y:slope*w},{x:w,y:slope*w+120}]});
                    floors[1].elements=[t];
                    const norm=Math.hypot(slope,1), nx=slope/norm, ny=-1/norm;
                    ninja.x=x+w/2+nx*(ninja.radius-2);
                    ninja.y=y+slope*w/2+ny*(ninja.radius-2);
                    ninja.speedX=-nx*9; ninja.speedY=-ny*9;
                    const before=(STATE)();
                    ninja.collision();
                    const after=(STATE)();
                    return {slope,before,after,normal:{x:nx,y:ny},
                        incoming:before.speedX*nx+before.speedY*ny,
                        outgoing:after.speedX*nx+after.speedY*ny,
                        contact:!!ninja.bounce,
                        distance:Math.sqrt(segmentDistanceSquared(t.getLines()[1],ninja.x,ninja.y))};
                }'''.replace('STATE', STATE), slope)
                self.assertTrue(row['contact'])
                self.assertLess(row['incoming'], 0)
                self.assertGreater(row['outgoing'], 0)
                self.assertGreaterEqual(row['distance'], row['after']['radius'])
                self.assertTrue(all(math.isfinite(row['after'][k]) for k in ('x','y','speedX','speedY')))
                kind = 'flat' if slope == 0 else 'sloped'
                rows[kind] = row
                screenshot(page, self.evidence, mode + '-' + kind)
                print(f"PASS {mode} {kind} collision: incoming={row['incoming']} "
                      f"outgoing={row['outgoing']} separation={row['distance']}")
            self.behaviour.setdefault(mode, {})['collisions'] = rows
        loaded = page.evaluate('Array.from(document.scripts, s => s.src)')
        self.assertFalse(any('grapple_over' in s for s in loaded))
        self.behaviour['fixtures_not_loaded_by_index'] = True
        print('PASS test fixtures not loaded by index.html')


if __name__ == '__main__':
    unittest.main()
