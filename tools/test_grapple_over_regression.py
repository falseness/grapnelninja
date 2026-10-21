"""TASK-498: shared-system and old-mode regression coverage after the Grapple Over work.

Task498Tests orchestrates child runs only; it never runs itself or any class after Task497Tests:
  * the nine existing shared-system suites (input, resize, pause/time, persistence, ninja bounce,
    broadphase collision, mode switch, camera left wall, boot), each a separate
    `python3 -m unittest discover -s tools -p <suite>.py -v`, logs under logs/;
  * the Grapple Over focused collection Task444Tests..Task497Tests, selected from
    unittest.TestLoader().discover('tools', pattern='test_grapple_over_*.py') by test ID, one child per class
    with GRAPPLE_OVER_EVIDENCE_DIR=<evidence>/new-suites/<Class>; passing runs keep only their logs;
  * a direct seeded classic/bad movement and bounce capture compared with artifacts/TASK-444.

Two kinds of earlier class no longer describe the current game (artifacts/TASK-498/diagnosis.md):
  * REPINNED: navigation/startup pins (two-mode backToMenu, boot not in Grapple Over). Each is a same-named
    subclass below whose methods are the original source with explicit, asserted text edits; the selection
    runs it instead of the original (test_grapple_over_baseline.py stays untouched: source_hashes() hashes it).
  * SUPERSEDED: classes a later design ticket invalidated. They still run and must fail with exactly the
    recorded signature (failing test, asserting source line, exception text), so new breakage is not hidden.

    python3 tools/test_grapple_over_regression.py list            # print the filtered collection, run nothing
    GRAPPLE_OVER_EVIDENCE_DIR=artifacts/... python3 tools/test_grapple_over_regression.py select Class   # one child
"""
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from browser_test_support import start_browser_test
from grapple_over_test_support import (ROOT, VIEWPORT, EvidenceWriter, STATE, open_fixture,
                                       source_hashes, step)
import test_grapple_over_baseline as _baseline
import test_grapple_over_modes as _modes
import test_grapple_over_save as _save
import test_grapple_over_world as _world

NEW_CLASS = re.compile(r'^Task(44[4-9]|4[5-8][0-9]|49[0-7])Tests$')
LEGACY = {
    # suite: (shared subsystem, evidence env var or None)
    'test_input': ('input', None),
    'test_resize': ('resize/layout', None),
    'test_pause_time': ('pause/time', None),
    'test_progress': ('persistence (save keys)', None),
    'test_ninja_bounce': ('ninja bounce', None),
    'test_collision_broadphase': ('broadphase collision', None),
    'test_mode_switch': ('mode switch/navigation', 'MODE_SWITCH_EVIDENCE_DIR'),
    'test_left_wall': ('camera left wall', 'LEFT_WALL_EVIDENCE_DIR'),
    'test_boot_main_mode': ('boot/startup', 'BOOT_EVIDENCE_DIR'),
}
# Which TASK-444..497 classes exercise each shared subsystem the Grapple Over work touched.
SUBSYSTEM_SUITES = {
    'input': ['Task455Tests', 'Task466Tests', 'Task487Tests', 'Task494Tests', 'Task497Tests'],
    'resize/layout': ['Task459Tests', 'Task494Tests', 'Task497Tests'],
    'pause/time': ['Task444Tests', 'Task456Tests', 'Task495Tests'],
    'persistence (save keys)': ['Task456Tests', 'Task459Tests', 'Task495Tests'],
    'ninja bounce': ['Task444Tests', 'Task447Tests', 'Task454Tests'],
    'broadphase collision': ['Task447Tests', 'Task452Tests', 'Task454Tests'],
    'mode switch/navigation': ['Task444Tests', 'Task459Tests', 'Task495Tests'],
    'camera left wall': ['Task462Tests', 'Task465Tests'],
    'boot/startup': ['Task459Tests', 'Task496Tests'],
}
# Classes a later design ticket superseded (artifacts/TASK-498/diagnosis.md, bisected first bad commits).
# failures: (test method, asserting source line, exception line regex), one per FAIL/ERROR block.
SUPERSEDED = {
    'Task445Tests': dict(commit='88fd0d9 / c493a2f', ticket='TASK-448 fixture growth; TASK-543 range 1080/0.375',
        failures=[('test_fixture_geometry_and_rendering', 'self.assertEqual(len(geometry[0]), 4)',
                   r'AssertionError: 91 != 4$'),
                  ('test_three_modes_and_baseline_traces',
                   "self.assertEqual(state['definition']['cameraScale'], 0.75)", r'AssertionError: 0\.375 != 0\.75$')]),
    'Task446Tests': dict(commit='9f6506b', ticket='TASK-465 mountain replaced the TEST-ONLY fixture',
        failures=[('test_camera_travel_preserves_world', "self.assertEqual(row['count'], 7)",
                   r'AssertionError: 91 != 7$')] * 2),
    'Task448Tests': dict(commit='bc2097f', ticket='TASK-451 fixture boundaries',
        failures=[('test_fixed_boundaries_camera_backtracking_and_landings',
                   "self.assertEqual(observed['anchorBefore'], [[360, 1100, 'base']])",
                   r"AssertionError: Lists differ: \[\[360, 1110, None\]\] != \[\[360, 1100, 'base'\]\]$")]),
    'Task449Tests': dict(commit='9f6506b', ticket='TASK-465 mountain replaced the TEST-ONLY fixture',
        failures=[('test_tracking_and_video', 'self.assertLessEqual(p+c, v-r+1e-8)',
                   r'AssertionError: [\d.]+ not less than or equal to [\d.]+$')]),
    'Task450Tests': dict(commit='97ea9d0', ticket='TASK-458 owned gameplay input on pause/restore',
        failures=[('test_aim_scroll_dpr_resize_rotation', "self.assertEqual(state['shots'],before+1)",
                   r'AssertionError: 0 != 1$'),
                  ('test_input_touch_mouse_cancel_camera_ui', "self.assertEqual(rows['touch_start']['shots'],1)",
                   r'AssertionError: 0 != 1$')]),
    'Task451Tests': dict(commit='c493a2f', ticket='TASK-543 range 1080/0.375',
        failures=[('test_range_occlusion_motion', "self.assertEqual(row['attached'], expected, name)",
                   r'AssertionError: True != False : range_541_angle_0$'),
                  ('test_zero_aim_and_fresh_press', "self.assertEqual(row['attached'], expected, name)",
                   r'AssertionError: True != False : expired$')]),
    # Keeping the boot run (as for 455/456) still fails: the invalid-save case expects the old fixture spawn
    # (360 != the mountain's 2160) and the delayed read targets an untouched fresh start
    # (artifacts/TASK-498/repin-attempts/Task457Tests-startup-repin.log).
    'Task457Tests': dict(commit='4f509ed / 9f6506b',
        ticket='TASK-459 Grapple Over at startup; TASK-465 mountain spawn replaced the fixture spawn',
        failures=[('test_delayed_read_and_failed_writes', "self.assertEqual(page.evaluate('ninja.y'),old['player']['y'])",
                   r'AssertionError: -?[\d.]+ != -?[\d.]+$'),
                  ('test_falling_throttle_pause_exit_pagehide_reload',
                   "self.assertGreater(current['player']['y'],first['player']['y'])",
                   r'AssertionError: 300 not greater than 300$'),
                  ('test_invalid_and_unavailable',
                   "self.assertEqual(notice.inner_text(),'Сохранение недоступно. Начинаем у подножия.')",
                   r'TimeoutError: Locator\.inner_text: Timeout 30000ms exceeded\.$')]),
    'Task458Tests': dict(commit='9f6506b', ticket='TASK-465 mountain replaced the TEST-ONLY fixture',
        failures=[('test_restore_resume_and_fresh_input', "page.evaluate('" "''kind=>{",
                   r"Error: Page\.evaluate: TypeError: Cannot read properties of undefined \(reading 'x'\)$")]),
    'Task460Tests': dict(commit='9f6506b', ticket='TASK-465 mountain replaced the TEST-ONLY fixture',
        failures=[('test_climb_flow_and_localized_layout', "self.assertTrue(completed['stats']['completed'])",
                   r'AssertionError: False is not true$')]),
    'Task463Tests': dict(commit='c493a2f', ticket='TASK-543 range 1080/0.375',
        failures=[('test_01_six_movement_families',
                   "self.assertEqual((constants['range'],constants['scale']),(540,0.75))",
                   r'AssertionError: Tuples differ: \(1080, 0\.375\) != \(540, 0\.75\)$'),
                  ('test_02_independent_evidence_audit',
                   "data=json.loads(self.evidence.path('calibration.json').read_text())",
                   r"FileNotFoundError: \[Errno 2\] No such file or directory: '.*/Task463Tests/calibration\.json'$")]),
    'Task464Tests': dict(commit='9f6506b', ticket='TASK-465 mountain replaced the TEST-ONLY fixture',
        failures=[('test_manifest_and_full_map',
                   "a=tasks[f'TASK-{465+i*3}']['description'];b=tasks[f'TASK-{466+i*3}']['description']",
                   r"KeyError: 'TASK-465'$"),
                  ('test_validator_and_partial_runtime', "result=page.evaluate('" "''() => {",
                   r'Error: Page\.evaluate: Error: InvalidBuildStatus: S01$')]),
}


def failure_blocks(text):
    """(test method, asserting source line, exception line) of every FAIL/ERROR block of one -v log."""
    out = []
    for block in re.split(r'^={70}\n', text, flags=re.M)[1:]:
        head = re.match(r'(?:FAIL|ERROR): (\w+) ', block)
        if not head:
            continue
        lines = block.split('\n')
        code = [lines[i + 1].strip() for i, line in enumerate(lines[:-1])
                if line.startswith(f'  File "{ROOT}/tools/')]
        error = next((line for line in lines if re.match(r'^[\w.]*(Error|Exception)\b', line)), None)
        out.append((head.group(1), code[-1] if code else None, error))
    return out


def signature_mismatch(cls, text):
    """None when the log fails exactly with SUPERSEDED[cls]'s recorded failures, else the difference."""
    observed = sorted(failure_blocks(text), key=lambda f: (f[0], f[1] or ''))
    expected = sorted(SUPERSEDED[cls]['failures'])
    if len(observed) != len(expected):
        return f'{len(observed)} failures, expected {len(expected)}: {observed}'
    for got, want in zip(observed, expected):
        if got[0] != want[0] or got[1] != want[1] or not got[2] or not re.search(want[2], got[2]):
            return f'observed {got}, expected {want}'
    return None


def repin(base, name, *edits):
    """base.name rebuilt from its own source after exact text edits; each edit must match exactly once."""
    func = getattr(base, name)
    source = textwrap.dedent(inspect.getsource(func))
    for old, new in edits:
        if source.count(old) != 1:
            raise AssertionError(f'{base.__name__}.{name}: re-pin edit no longer matches: {old!r}')
        source = source.replace(old, new)
    scope = dict(vars(sys.modules[func.__module__]))
    exec(compile(source, f'<{base.__name__}.{name} re-pinned by TASK-498>', 'exec'), scope)
    return scope[name]


class Repinned:
    """A re-pinned earlier class: refuses to run into the original task's own artifacts."""
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('GRAPPLE_OVER_EVIDENCE_DIR'):
            raise RuntimeError(f'{cls.__name__} re-pin needs GRAPPLE_OVER_EVIDENCE_DIR')
        super().setUpClass()


# Re-entering Grapple Over saves the climb and restores it paused (TASK-459). Boot already starts Grapple Over,
# so the old "startGame('grapple_over') after boot" fresh start now re-enters; the re-pins keep the boot run.
KEEP_BOOT_RUN = "if(version!=='grapple_over'||!runInProgress)startGame('grapple_over');"


class Task444Tests(Repinned, _baseline.Task444Tests):
    # The pause screen's two-mode backToMenu toggle became the three-mode menu.modeButtons (TASK-445/459)
    test_grapple_pause_and_mode_switch = repin(
        _baseline.Task444Tests, 'test_grapple_pause_and_mode_switch',
        ("'''() => {const b=menu.backToMenu.background,",
         "'''other => {const b=menu.modeButtons[['grapple_over', 'bad', 'classic'].indexOf(other)].background,"),
        ("y:r.y+(b.y+b.height/2)*r.height/height}}''')",
         "y:r.y+(b.y+b.height/2)*r.height/height}}''', 'bad' if mode == 'classic' else 'classic')"))


class Task455Tests(Repinned, _world.Task455Tests):
    test_input_attachment_reversal_release_video = repin(
        _world.Task455Tests, 'test_input_attachment_reversal_release_video',
        ('''"() => {startGame('grapple_over');cancelAnimationFrame(game)}"''',
         '"() => {' + KEEP_BOOT_RUN + 'cancelAnimationFrame(game)}"'))


class Task456Tests(Repinned, _save.Task456Tests):
    open = repin(_save.Task456Tests, 'open',
                 ("'m => {startGame(m);cancelAnimationFrame(game)}'",
                  "'m => {if(version!==m||!runInProgress)startGame(m);cancelAnimationFrame(game)}'"))


class Task459Tests(Repinned, _modes.Task459Tests):
    def tap(self, page, box):
        # A menu tap arms STYLE.timing.inputUntouchMs, during which the next tap is ignored (events.js unTouch);
        # the climb pause (TASK-460) put consecutive selector taps inside that window
        page.wait_for_function('!unTouch')
        super().tap(page, box)

    # The climb pause (CLIMB_UI, TASK-460) lists resume, restart and the two other modes, not Grapple Over itself
    test_boot_transitions_and_localized_touch_layout = repin(
        _modes.Task459Tests, 'test_boot_transitions_and_localized_touch_layout',
        ("self.tap(page,next(b for b in buttons if b['name']==label))\n",
         "self.assertNotIn(label,[b['name'] for b in buttons])\n"))


REPINNED = {cls.__name__: cls for cls in (Task444Tests, Task455Tests, Task456Tests, Task459Tests)}

KEEP_FROM_CHILD = {'tests.log', 'commands.log'}
WORKERS = int(os.environ.get('TASK498_WORKERS', '5'))
SELECT = ("unittest.TestLoader().discover('tools', pattern='test_grapple_over_*.py'), flattened, "
          "test IDs whose class matches ^Task(44[4-9]|4[5-8][0-9]|49[0-7])Tests$")


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def selected(only=None):
    tests = flatten(unittest.TestLoader().discover(str(TOOLS), pattern='test_grapple_over_*.py',
                                                   top_level_dir=str(TOOLS)))
    out = []
    for test in tests:
        cls = type(test).__name__
        if cls in REPINNED and type(test).__module__ != 'test_grapple_over_regression':
            continue  # replaced by its re-pinned subclass
        if NEW_CLASS.match(cls) and (only is None or cls == only):
            out.append(test)
        elif isinstance(test, unittest.loader._FailedTest):
            out.append(test)  # an import error must fail the run, not vanish
    return out


def file_hashes():
    names = dict(source_hashes())
    for path in sorted(TOOLS.glob('test_grapple_over_*.py')) + [TOOLS / (s + '.py') for s in LEGACY]:
        name = str(path.relative_to(ROOT))
        names[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for extra in ('tools/grapple_over_support.py', 'tools/grapple_over_verify.py'):
        names[extra] = hashlib.sha256((ROOT / extra).read_bytes()).hexdigest()
    return dict(sorted(names.items()))


def summarize(text):
    """Executed case names, counts and the unittest result line of one -v log."""
    cases = re.findall(r'^(test\w*) \(([\w.]+)\)', text, re.M)
    ran = re.search(r'^Ran (\d+) tests? in ([\d.]+)s$', text, re.M)
    result = re.findall(r'^(OK.*|FAILED.*)$', text, re.M)
    return dict(ran=int(ran.group(1)) if ran else 0, seconds=float(ran.group(2)) if ran else None,
                result=result[-1] if result else None,
                cases=[f'{cls.split(".")[-1]}.{name}' for name, cls in cases],
                skipped=len(re.findall(r'(?:\.\.\. |^)skipped ', text, re.M)) + len(re.findall(r'skipped=\d+', text)),
                failed=len(re.findall(r'^(?:FAIL|ERROR): ', text, re.M)),
                browser_errors=len(re.findall(r'pageerror|Uncaught |(?<!\s0 )console errors?\b', text, re.I)))


# TASK-444's collision fixture (tools/test_grapple_over_baseline.py test_flat_and_sloped_collisions), verbatim.
COLLISION = '''slope => {
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
}'''.replace('STATE', STATE)

STARTUP_NOTE = (
    'Expected startup/navigation changes (TASK-445 onward): the game boots into the Grapple Over climb instead of '
    'the old default; the title/pause menus offer three modes (Grapple Over, classic, bad) instead of the old '
    'two-mode toggle; Grapple Over adds its own save keys beside the untouched classic/bad progress keys. '
    'Preserved old-mode gameplay: explicitly selected classic and bad keep their initial state, constants, '
    '12-step seeded movement, flat/sloped bounce response, throw/release, pause freeze and resume exactly as '
    'captured by TASK-444 before any Grapple Over change, and the old shared-system suites still pass. '
    'Re-pinned startup/navigation assertions only: Task444 clicks the old mode through menu.modeButtons instead of '
    'backToMenu; Task455/456 keep the boot Grapple Over run instead of re-entering it (re-entry restores the save '
    'paused); Task459 waits out the menu tap debounce and expects no same-mode button in the climb pause. '
    'Classes a later design ticket superseded run unchanged and must fail with exactly their recorded signature '
    '(SUPERSEDED, artifacts/TASK-498/diagnosis.md).')


class Task498Tests(unittest.TestCase):
    TASK = 'TASK-498'

    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter(cls.TASK)
        cls.revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        cls.dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                            cwd=ROOT, text=True).splitlines()
        cls.hashes = file_hashes()
        cls.evidence.log(f'START {time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())} revision={cls.revision} '
                         f'tracked_changes={cls.dirty}')
        cls.evidence.log('SOURCE_HASHES ' + json.dumps(cls.hashes, separators=(',', ':')))

    def run_child(self, name, command, env, log):
        start = time.time()
        with log.open('w') as stream:
            stream.write(f'$ {" ".join(command)}\n')
            stream.flush()
            run = subprocess.run(command, cwd=ROOT, env=dict(os.environ, **env), stdout=stream,
                                 stderr=subprocess.STDOUT, timeout=4 * 3600)
        text = log.read_text()
        summary = dict(summarize(text), exit=run.returncode, wall_seconds=round(time.time() - start, 1),
                       env=env, command=' '.join(command), log=str(log.relative_to(self.evidence.root)))
        self.evidence.log(f'CHILD {name} exit={run.returncode} ran={summary["ran"]} skipped={summary["skipped"]} '
                          f'result={summary["result"]} wall={summary["wall_seconds"]}s')
        return summary

    def test_01_shared_system_suites(self):
        def one(suite):
            env = {}
            if LEGACY[suite][1]:
                env[LEGACY[suite][1]] = str(self.evidence.path(f'logs/{suite}-evidence/x').parent)
            command = ['python3', '-m', 'unittest', 'discover', '-s', 'tools', '-p', suite + '.py', '-v']
            self.evidence.log(f'COMMAND (cwd={ROOT}) {" ".join(f"{k}={v}" for k, v in env.items())} '
                              f'{" ".join(command)} > logs/{suite}.log 2>&1')
            return suite, self.run_child(suite, command, env, self.evidence.path(f'logs/{suite}.log'))
        # One at a time: several suites drive the real-time loop, so they share the CPU with nothing else
        results = dict(map(one, LEGACY))
        self.evidence.write('logs/legacy-summary.json', results)
        for suite, summary in results.items():
            with self.subTest(suite=suite):
                self.assertEqual(summary['exit'], 0, summary)
                self.assertGreater(summary['ran'], 0, summary)
                self.assertEqual(summary['skipped'], 0, summary)
                self.assertTrue(summary['result'].startswith('OK'), summary)
                self.assertEqual(summary['browser_errors'], 0, summary)
            print(f'PASS {suite}: {summary["ran"]} tests, exit 0, 0 skipped')

    def test_02_new_grapple_over_suites(self):
        tests = selected()
        classes = sorted({type(t).__name__ for t in tests})
        self.assertEqual(classes, [f'Task{n}Tests' for n in range(444, 498)])
        self.assertNotIn('Task498Tests', classes)
        root = self.evidence.path('new-suites/x').parent
        self.evidence.log(f'SELECT {SELECT}: {len(tests)} tests in {len(classes)} classes')
        (root / 'selected.txt').write_text('\n'.join(t.id() for t in tests) + '\n')

        def previous(cls):  # schedule longest first from the original ticket's own run
            log = ROOT / 'artifacts' / f'TASK-{cls[4:7]}' / 'tests.log'
            found = re.findall(r'^Ran \d+ tests? in ([\d.]+)s', log.read_text(errors='replace'), re.M) \
                if log.exists() else []
            return float(found[-1]) if found else 0.0

        def one(cls):
            out = root / cls
            env = {'GRAPPLE_OVER_EVIDENCE_DIR': str(out)}
            command = ['python3', 'tools/test_grapple_over_regression.py', 'select', cls]
            self.evidence.log(f'COMMAND (cwd={ROOT}) GRAPPLE_OVER_EVIDENCE_DIR={out.relative_to(ROOT)} '
                              f'{" ".join(command)} > new-suites/{cls}/tests.log 2>&1')
            out.mkdir(parents=True, exist_ok=True)
            summary = self.run_child(cls, command, env, out / 'tests.log')
            if cls in SUPERSEDED:
                text = (out / 'tests.log').read_text()
                summary.update(status='SUPERSEDED', **{k: SUPERSEDED[cls][k] for k in ('commit', 'ticket')},
                               observed_failures=failure_blocks(text),
                               signature_mismatch=signature_mismatch(cls, text))
                self.evidence.log(f'SUPERSEDED {cls} {SUPERSEDED[cls]["commit"]} ({SUPERSEDED[cls]["ticket"]}): '
                                  f'signature {"MATCH" if summary["signature_mismatch"] is None else "MISMATCH"}')
            else:
                summary['status'] = 'PASS' if summary['exit'] == 0 else 'FAIL'
                summary['repinned'] = cls in REPINNED
            if summary['exit'] == 0 or summary.get('signature_mismatch', 1) is None:
                removed = 0
                for path in sorted(out.rglob('*'), reverse=True):
                    keep = path.name in KEEP_FROM_CHILD or (cls == 'Task444Tests' and path.suffix == '.json')
                    if path.is_file() and not keep:
                        removed += path.stat().st_size
                        path.unlink()
                    elif path.is_dir() and not any(path.iterdir()):
                        path.rmdir()
                summary['pruned_bytes'] = removed
            return cls, summary

        order = sorted(classes, key=previous, reverse=True)
        with ThreadPoolExecutor(WORKERS) as pool:
            results = dict(sorted(pool.map(one, order)))
        self.evidence.write('new-suites/summary.json', results)
        for cls, summary in results.items():
            with self.subTest(cls=cls):
                self.assertEqual(summary['ran'], sum(type(t).__name__ == cls for t in tests), summary)
                self.assertEqual(summary['skipped'], 0, summary)
                if cls in SUPERSEDED:
                    self.assertEqual(summary['exit'], 1, summary)
                    self.assertIsNone(summary['signature_mismatch'], summary)
                    continue
                self.assertEqual(summary['exit'], 0, summary)
                self.assertTrue(summary['result'].startswith('OK'), summary)
                self.assertEqual(summary['browser_errors'], 0, summary)
                self.assertFalse(any('Task498Tests' in c or not NEW_CLASS.match(c.split('.')[0])
                                     for c in summary['cases']), summary['cases'])
        print(f'PASS {len(tests)} tests in {len(classes)} classes Task444..Task497: '
              f'{len(classes) - len(SUPERSEDED)} exit 0 ({len(REPINNED)} re-pinned), 0 skipped; '
              f'{len(SUPERSEDED)} SUPERSEDED fail with exactly their recorded signature')

    def capture(self):
        url, browser = start_browser_test(ROOT, self.addCleanup)
        out = dict(browser=browser.version, viewport=VIEWPORT, device_scale_factor=1, modes={})
        for mode in ('classic', 'bad'):
            page, errors = open_fixture(browser, url, mode, self.addCleanup)
            initial = page.evaluate(STATE)
            constants = page.evaluate('''() => ({gravity: GRAVITY, pull: grappleSpeed,
                throwSpeed: grapnelSpeed, cyclesPerTick, physicsStepMs, gameplay: GAMEPLAY})''')
            trace = step(page, 12)
            bounce = {}
            for slope, kind in ((0, 'flat'), (-0.5, 'sloped')):
                bounce[kind] = page.evaluate(COLLISION, slope)
            out['modes'][mode] = dict(initial=initial, constants=constants, movement_trace=trace,
                                      collisions=bounce, browser_errors=list(errors))
        return out

    def test_03_old_mode_traces_match_task444(self):
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())
        behaviour = json.loads((ROOT / 'artifacts/TASK-444/behaviour.json').read_text())
        self.evidence.log(f'CONFIG capture browser=chromium(start_browser_test) viewport={VIEWPORT} dpr=1 seed=1 '
                          f'rAF cancelled, explicit physics(); baseline=artifacts/TASK-444 revision {baseline["revision"]}')
        now = self.capture()
        self.evidence.log(f'CONFIG chromium {now["browser"]} (TASK-444 baseline {baseline["browser"]})')
        compare = {}
        for mode in ('classic', 'bad'):
            got, old = now['modes'][mode], baseline['modes'][mode]
            rows = dict(initial=got['initial'] == old['initial'], constants=got['constants'] == old['constants'],
                        movement_trace=got['movement_trace'] == old['movement_trace'],
                        flat_bounce=got['collisions']['flat'] == behaviour[mode]['collisions']['flat'],
                        sloped_bounce=got['collisions']['sloped'] == behaviour[mode]['collisions']['sloped'],
                        browser_errors=len(got['browser_errors']))
            compare[mode] = rows
            with self.subTest(mode=mode):
                self.assertEqual(got['initial'], old['initial'])
                self.assertEqual(got['constants'], old['constants'])
                self.assertEqual(got['movement_trace'], old['movement_trace'])
                self.assertEqual(got['collisions'], behaviour[mode]['collisions'])
                self.assertEqual(got['browser_errors'], [])
            print(f'PASS {mode}: initial, constants, 12-step trace, flat/sloped bounce equal TASK-444 '
                  f'(outgoing {got["collisions"]["flat"]["outgoing"]:.4f}/{got["collisions"]["sloped"]["outgoing"]:.4f})')
        # The rerun of Task444Tests itself (test_02) also recaptured its traces under new-suites/Task444Tests.
        child = self.evidence.root / 'new-suites/Task444Tests'
        if (child / 'baseline.json').exists():
            rerun_base = json.loads((child / 'baseline.json').read_text())
            rerun_beh = json.loads((child / 'behaviour.json').read_text())
            for mode in ('classic', 'bad'):
                self.assertEqual(rerun_base['modes'][mode], baseline['modes'][mode])
                self.assertEqual(rerun_beh[mode]['collisions'], behaviour[mode]['collisions'])
                # 'switched' is sampled after the real-time rAF loop runs the new mode, so it varies run to run
                # (artifacts/TASK-444/RESTORED.md); the rest of the input/pause trace is deterministic.
                strip = lambda d: {k: v for k, v in d.items() if k != 'switched'}
                self.assertEqual(strip(rerun_beh[mode]['input']), strip(behaviour[mode]['input']))
                self.assertEqual(rerun_beh[mode]['input']['switched']['mode'], behaviour[mode]['input']['switched']['mode'])
                compare[mode]['task444_rerun_traces_equal'] = True
            print('PASS Task444Tests rerun: movement, bounce and input/pause traces equal TASK-444')
        self.evidence.write('old-mode-traces.json', dict(
            baseline='artifacts/TASK-444/baseline.json', behaviour='artifacts/TASK-444/behaviour.json',
            baseline_revision=baseline['revision'], browser=now['browser'], viewport=VIEWPORT,
            comparison=compare, capture=now['modes']))

    def test_04_regression_map(self):
        legacy = self.evidence.root / 'logs/legacy-summary.json'
        new = self.evidence.root / 'new-suites/summary.json'
        traces = self.evidence.root / 'old-mode-traces.json'
        for path in (legacy, new, traces):
            self.assertTrue(path.exists(), path)
        legacy, new = json.loads(legacy.read_text()), json.loads(new.read_text())
        traces = json.loads(traces.read_text())
        self.assertEqual(file_hashes(), self.hashes, 'tested files changed during the run')
        subsystems = {}
        for suite, (subsystem, _) in LEGACY.items():
            subsystems[subsystem] = dict(
                existing_suite={suite: dict(exit=legacy[suite]['exit'], ran=legacy[suite]['ran'],
                                            skipped=legacy[suite]['skipped'], log=legacy[suite]['log'])},
                new_suites={c: dict(status=new[c]['status'], exit=new[c]['exit'], ran=new[c]['ran'],
                                    skipped=new[c]['skipped'], log=new[c]['log']) for c in SUBSYSTEM_SUITES[subsystem]})
        subsystems['ninja bounce']['baseline_traces'] = subsystems['broadphase collision']['baseline_traces'] = \
            dict(path='artifacts/TASK-444/behaviour.json collisions', equal=all(
                traces['comparison'][m][k] for m in ('classic', 'bad') for k in ('flat_bounce', 'sloped_bounce')))
        subsystems['input']['baseline_traces'] = dict(path='artifacts/TASK-444/baseline.json movement_trace',
            equal=all(traces['comparison'][m]['movement_trace'] for m in ('classic', 'bad')))
        live = [s for c, s in new.items() if c not in SUPERSEDED]
        errors = sum(s['browser_errors'] for s in list(legacy.values()) + live) + sum(
            traces['comparison'][m]['browser_errors'] for m in ('classic', 'bad'))
        report = dict(revision=self.revision, tracked_changes=self.dirty, source_hashes_unchanged=True,
                      subsystems=subsystems, old_mode_physics=traces['comparison'],
                      classes={c: dict(status=s['status'], exit=s['exit'], ran=s['ran'], skipped=s['skipped'],
                                       log=s['log'], **({'repinned': True} if s.get('repinned') else {}),
                                       **({k: s[k] for k in ('commit', 'ticket', 'observed_failures',
                                                              'signature_mismatch')} if c in SUPERSEDED else {}))
                               for c, s in new.items()},
                      superseded_source='artifacts/TASK-498/diagnosis.md',
                      old_mode_physics_match_baseline=all(all(v for k, v in row.items() if k != 'browser_errors')
                                                          for row in traces['comparison'].values()),
                      totals=dict(existing_suites=len(legacy), existing_tests=sum(s['ran'] for s in legacy.values()),
                                  new_classes=len(new), new_tests=sum(s['ran'] for s in new.values()),
                                  passed_classes=sum(s['status'] == 'PASS' for s in new.values()),
                                  superseded_classes=sum(s['status'] == 'SUPERSEDED' for s in new.values()),
                                  nonzero_exits=sum(s['exit'] != 0 for s in list(legacy.values()) + live),
                                  skipped=sum(s['skipped'] for s in list(legacy.values()) + list(new.values())),
                                  browser_errors=errors),
                      expected_changes_vs_preserved=STARTUP_NOTE)
        self.evidence.write('regression.json', report)
        self.evidence.path('logs/README.md').write_text(
            '# TASK-498 suite logs\n\n' + STARTUP_NOTE + '\n\nlogs/<suite>.log: complete output of each existing '
            'shared-system suite; logs/legacy-summary.json: exit/counts. new-suites/<Class>/tests.log: complete '
            'output of each Task444..Task497 child run (bulky traces/media pruned after a pass); '
            'new-suites/summary.json: exit/counts.\n')
        self.assertTrue(report['old_mode_physics_match_baseline'])
        self.assertEqual(sorted(report['classes']), [f'Task{n}Tests' for n in range(444, 498)])
        for subsystem, row in subsystems.items():
            self.assertTrue(all(r['status'] == 'PASS' for r in row['new_suites'].values()), subsystem)
        for cls, row in report['classes'].items():
            self.assertEqual(row['status'], 'SUPERSEDED' if cls in SUPERSEDED else 'PASS', row)
            if cls in SUPERSEDED:
                self.assertIsNone(row['signature_mismatch'], row)
        self.assertEqual(report['totals']['nonzero_exits'], 0)
        self.assertEqual(report['totals']['skipped'], 0)
        self.assertEqual(errors, 0)
        print(f'PASS regression map: {len(subsystems)} subsystems, {report["totals"]}')


if __name__ == '__main__':
    if sys.argv[1:2] == ['list']:
        print('\n'.join(t.id() for t in selected()))
        sys.exit(0)
    if sys.argv[1:2] == ['select']:
        # Without an explicit evidence dir the classes would write into their original tasks' artifacts.
        if len(sys.argv) != 3 or not os.environ.get('GRAPPLE_OVER_EVIDENCE_DIR'):
            sys.exit('select needs one class name and GRAPPLE_OVER_EVIDENCE_DIR')
        suite = unittest.TestSuite(selected(sys.argv[2]))
        print(f'selected {suite.countTestCases()} tests: ' + ' '.join(t.id() for t in suite), flush=True)
        if not suite.countTestCases():
            sys.exit(2)
        sys.exit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
    unittest.main()
