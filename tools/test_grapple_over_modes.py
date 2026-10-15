"""TASK-445 internal third-mode initialization and fixed climb proof."""
import hashlib
import json
import math
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, STATE, source_hashes, step
from perf_mobile import SEED_SCRIPT


class Task445Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-445')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_modes.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=ROOT, text=True).strip(), 'source_hashes': hashes,
            'browser': cls.browser.version, 'viewports': [[1280, 720], [960, 720]],
            'device_scale_factor': 1, 'seed': 1, 'modes': {},
            'baseline_path': 'artifacts/TASK-444/baseline.json'}
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    @classmethod
    def tearDownClass(cls):
        cls.evidence.write('modes.json', cls.proof)

    def open(self, mode, width=1280):
        context = self.browser.new_context(viewport={'width': width, 'height': 720},
                                           device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        self.assertEqual(page.evaluate('version'), 'bad')
        page.evaluate(SEED_SCRIPT % 1)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page, errors

    def test_three_modes_and_baseline_traces(self):
        baseline = json.loads((ROOT / self.proof['baseline_path']).read_text())
        for mode in ('classic', 'bad', 'grapple_over'):
            with self.subTest(mode=mode):
                page, errors = self.open(mode)
                initial = page.evaluate(STATE)
                state = page.evaluate('''() => ({player:[ninja.x,ninja.y,ninja.radius],
                    camera:[screen.x,screen.y,screen.borderX,scale[version]],
                    hud:[scoreText.x,scoreText.y,scoreText.fontSize,
                         scoreText.count[version],scoreText.record[version]],
                    constants:{gravity:GRAVITY,pull:grappleSpeed,throwSpeed:grapnelSpeed,
                               cyclesPerTick,physicsStepMs,gameplay:GAMEPLAY},
                    definition:MODE_DEFINITIONS[version]})''')
                for key in ('player', 'camera', 'hud'):
                    self.assertTrue(all(isinstance(v, (int, float)) and math.isfinite(v)
                                        for v in state[key]), (mode, key, state[key]))
                self.assertEqual(initial['radius'], 10.8)
                self.assertEqual(state['constants'], baseline['modes']['bad']['constants'])
                trace = step(page, 12)
                if mode != 'grapple_over':
                    self.assertEqual(initial, baseline['modes'][mode]['initial'])
                    self.assertEqual(trace, baseline['modes'][mode]['movement_trace'])
                else:
                    self.assertEqual(state['definition']['cameraScale'], 0.75)
                    self.assertEqual(state['definition']['acquisitionRadius'], 540)
                page.evaluate('draw()')
                self.assertEqual(errors, [])
                self.proof['modes'][mode] = dict(state, initial=initial, movement_trace=trace,
                    finite=True, browser_errors=errors, baseline_trace_equal=mode != 'grapple_over')
                print(f'PASS {mode}: finite player/camera/HUD; browser_errors=0; '
                      f'baseline_trace_equal={mode != "grapple_over"}')

    def test_fixture_geometry_and_rendering(self):
        observations = []
        for width in (1280, 960):
            page, errors = self.open('grapple_over', width)
            geometry = page.evaluate('''() => floors.map(f => f.elements.map(e =>
                ({x:e.x,y:e.y,points:e.points,fill:e.fill,stroke:e.stroke})))''')
            self.assertEqual(len(geometry[0]), 4)
            self.assertEqual([(e['x'], e['y']) for e in geometry[0]],
                             [(120,1100),(600,800),(240,500),(650,200)])
            self.assertEqual([e['points'][2] for e in geometry[0]],
                             [dict(x=w,y=h) for w,h in [(1000,60),(300,40),(280,40),(300,40)]])
            page.evaluate('draw()')
            page.screenshot(path=str(self.evidence.path('fixture.png' if width == 1280
                                                     else 'fixture-960.png')))
            self.assertEqual(errors, [])
            observations.append({'viewport': [width,720], 'geometry': geometry,
                                 'browser_errors': errors})
        self.assertEqual(observations[0]['geometry'], observations[1]['geometry'])
        self.proof['fixture'] = {'observations': observations, 'identical_geometry': True,
                                'rendered_with_existing_trampolines': True}
        print('PASS fixture: 4 existing neon Trampolines; identical geometry/dimensions at 1280x720 and 960x720')
