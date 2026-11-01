"""TASK-498: shared-system and old-mode regression coverage after the Grapple Over work.

Task498Tests orchestrates child runs only; it never runs itself or any class after Task497Tests:
  * the nine existing shared-system suites (input, resize, pause/time, persistence, ninja bounce,
    broadphase collision, mode switch, camera left wall, boot), each a separate
    `python3 -m unittest discover -s tools -p <suite>.py -v`, logs under logs/;
  * the Grapple Over focused collection Task444Tests..Task497Tests, selected from
    unittest.TestLoader().discover('tools', pattern='test_grapple_over_*.py') by test ID, one child per class
    with GRAPPLE_OVER_EVIDENCE_DIR=<evidence>/new-suites/<Class>; passing runs keep only their logs;
  * a direct seeded classic/bad movement and bounce capture compared with artifacts/TASK-444.

Earlier classes that no longer described the current game (artifacts/TASK-498/diagnosis.md):
  * REPINNED: Task444/455/456/459 are same-named subclasses the selection runs instead of the originals. Their
    TASK-498 text edits now live in the originals (TASK-785/838/839), so since TASK-852 they only refuse to run
    without GRAPPLE_OVER_EVIDENCE_DIR (never into the original tasks' artifacts).
  * SUPERSEDED: classes a later design ticket invalidated. They still run and must fail with exactly the
    recorded signature (failing test, asserting source line, exception text), so new breakage is not hidden.
    Empty since TASK-852: all of them pass again.
  * Task465..Task492 are retired 0-test stubs (TASK-835/846); Task498 test_02 asserts they still exist with 0 tests.

    python3 tools/test_grapple_over_regression.py list            # print the filtered collection, run nothing
    GRAPPLE_OVER_EVIDENCE_DIR=artifacts/... python3 tools/test_grapple_over_regression.py select Class   # one child
"""
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
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
# TASK-465..492 were retired to empty (0-test) stub classes: Task465..488 by 4505cd5 TASK-846 (sections,
# artifacts/TASK-846/retired.md), Task489..492 by d6894cd TASK-835 (integration, artifacts/TASK-835/retired.md).
# Their names stay defined (test_02 asserts they still exist with 0 tests), so the live collection is Task444..497
# minus these.
STUBS = [f'Task{n}Tests' for n in range(465, 493)]
LIVE = [f'Task{n}Tests' for n in range(444, 498) if f'Task{n}Tests' not in STUBS]
# Which live TASK-444..497 classes exercise each shared subsystem the Grapple Over work touched
# (TASK-852 dropped the stubbed Task465/466/487).
SUBSYSTEM_SUITES = {
    'input': ['Task455Tests', 'Task494Tests', 'Task497Tests'],
    'resize/layout': ['Task459Tests', 'Task494Tests', 'Task497Tests'],
    'pause/time': ['Task444Tests', 'Task456Tests', 'Task495Tests'],
    'persistence (save keys)': ['Task456Tests', 'Task459Tests', 'Task495Tests'],
    'ninja bounce': ['Task444Tests', 'Task447Tests', 'Task454Tests'],
    'broadphase collision': ['Task447Tests', 'Task452Tests', 'Task454Tests'],
    'mode switch/navigation': ['Task444Tests', 'Task459Tests', 'Task495Tests'],
    'camera left wall': ['Task462Tests'],
    'boot/startup': ['Task459Tests', 'Task496Tests'],
}
# Classes a later design ticket superseded (artifacts/TASK-498/diagnosis.md, bisected first bad commits).
# failures: (test method, asserting source line, exception line regex), one per FAIL/ERROR block.
# A class listed here must still run and fail with exactly that signature, so new breakage is not hidden.
# Empty since TASK-852: every TASK-498 entry passes again (artifacts/TASK-852/classes/<Class>/tests.log, all OK):
# Task445 (575b720 TASK-838 retired the fixture-geometry test), Task446/448 (e5ee67b TASK-839), Task449 (camera
# re-spec 271eb97 TASK-692), Task450 (17641d7 TASK-834), Task451 (79f8806 TASK-832), Task460 (575b720 TASK-838), Task463
# (3ebd07b TASK-833), Task464 (1e1936a TASK-837); Task457/458 were re-specced earlier by 4915759 TASK-785.
SUPERSEDED = {}


# Cases a later ticket deliberately @unittest.skip-ed: (exact skipped test names, reason regex, commit, ticket).
# A child may skip exactly these and nothing else; any other skip fails test_02 (TASK-852).
STALE_ROUTE = r'^TASK-496 route recorded before TASK-704 launch and later physics; no longer completes layout v3'
KNOWN_SKIPS = {
    'Task496Tests': dict(tests={'test_01_uninterrupted_completion', 'test_02_playback_video'}, reason=STALE_ROUTE,
                         commit='4915759', ticket='TASK-785 completion on legacy-v3 with stale full-route replays skipped'),
    'Task497Tests': dict(tests={'test_01_touch_completion', 'test_02_touch_video'}, reason=STALE_ROUTE,
                         commit='4915759', ticket='TASK-785 completion on legacy-v3 with stale full-route replays skipped'),
}


def skipped_tests(text):
    """{test method: skip reason} of one -v log (a docstring line may sit between the name and the result)."""
    return dict(re.findall(r"^(test\w+) \([\w.]+\)(?:\n(?!test)[^\n]*)*? \.\.\. skipped '([^\n]*)'$", text, re.M))


def skip_mismatch(cls, skipped):
    """None when skipped ({test: reason}) is exactly KNOWN_SKIPS[cls] (or empty when cls has none)."""
    known = KNOWN_SKIPS.get(cls)
    if set(skipped) != (known['tests'] if known else set()):
        return f'skipped {sorted(skipped)}, expected {sorted(known["tests"]) if known else []}'
    bad = {t: r for t, r in skipped.items() if not re.search(known['reason'], r)}
    return f'unexpected skip reasons {bad}' if bad else None


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


class Repinned:
    """A re-pinned earlier class: refuses to run into the original task's own artifacts."""
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('GRAPPLE_OVER_EVIDENCE_DIR'):
            raise RuntimeError(f'{cls.__name__} re-pin needs GRAPPLE_OVER_EVIDENCE_DIR')
        super().setUpClass()


# The TASK-498 text re-pins (modeButtons instead of backToMenu, keeping the boot run, the tap debounce, no
# same-mode button in the climb pause) were made in the originals themselves by e5ee67b TASK-839 (Task444
# modeButtons, Task455 menu.unPause) and 575b720 TASK-838 / earlier (Task459 '!unTouch' tap, same-mode title), so
# TASK-852 dropped them. These subclasses now only refuse to run into the original tasks' own artifacts.
class Task444Tests(Repinned, _baseline.Task444Tests):
    pass


class Task455Tests(Repinned, _world.Task455Tests):
    pass


class Task456Tests(Repinned, _save.Task456Tests):
    pass


class Task459Tests(Repinned, _modes.Task459Tests):
    pass


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


def class_case_counts():
    """{TaskNNNTests: [test count of each definition]} over the test_grapple_over_*.py modules."""
    loader, out = unittest.TestLoader(), {}
    for path in sorted(TOOLS.glob('test_grapple_over_*.py')):
        module = importlib.import_module(path.stem)
        for name, obj in vars(module).items():
            if (NEW_CLASS.match(name) and isinstance(obj, type) and issubclass(obj, unittest.TestCase)
                    and obj.__module__ == module.__name__):
                out.setdefault(name, []).append(loader.loadTestsFromTestCase(obj).countTestCases())
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
    'The TASK-498 startup/navigation re-pins (Task444 menu.modeButtons, Task455/456 resuming the paused boot run, '
    'Task459 tap debounce and no same-mode button) now live in the original classes (TASK-785/838/839); the '
    'Task444/455/456/459 subclasses here only guard GRAPPLE_OVER_EVIDENCE_DIR. Task465..492 are retired 0-test stubs '
    '(TASK-835/846). Task496/497 skip exactly their two stale full-route replays each (KNOWN_SKIPS, 4915759 '
    'TASK-785); any other skip fails. '
    'Classes a later design ticket superseded run unchanged and must fail with exactly their recorded signature '
    '(SUPERSEDED, artifacts/TASK-498/diagnosis.md, re-checked by TASK-852).')


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
        self.assertEqual(classes, LIVE)
        self.assertNotIn('Task498Tests', classes)
        counts = class_case_counts()
        for stub in STUBS:  # retired, not vanished: still defined, with no cases
            self.assertEqual(counts.get(stub), [0], stub)
        self.assertEqual(sorted(counts), [f'Task{n}Tests' for n in range(444, 498)])
        self.evidence.log(f'STUBS {len(STUBS)} classes Task465..Task492 defined with 0 tests')
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
            summary['skipped_tests'] = skipped_tests((out / 'tests.log').read_text())
            summary['skip_mismatch'] = skip_mismatch(cls, summary['skipped_tests'])
            summary['known_skips'] = len(summary['skipped_tests']) if summary['skip_mismatch'] is None else 0
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
                self.assertIsNone(summary['skip_mismatch'], summary)  # only KNOWN_SKIPS, exactly
                if cls in SUPERSEDED:
                    self.assertEqual(summary['exit'], 1, summary)
                    self.assertIsNone(summary['signature_mismatch'], summary)
                    continue
                self.assertEqual(summary['exit'], 0, summary)
                self.assertTrue(summary['result'].startswith('OK'), summary)
                self.assertEqual(summary['result'], f'OK (skipped={summary["known_skips"]})'
                                 if summary['known_skips'] else 'OK', summary)
                self.assertEqual(summary['browser_errors'], 0, summary)
                self.assertFalse(any('Task498Tests' in c or not NEW_CLASS.match(c.split('.')[0])
                                     for c in summary['cases']), summary['cases'])
        print(f'PASS {len(tests)} tests in {len(classes)} classes Task444..Task497 minus {len(STUBS)} 0-test stubs: '
              f'{len(classes) - len(SUPERSEDED)} exit 0 ({len(REPINNED)} re-pinned), '
              f'only the {sum(len(k["tests"]) for k in KNOWN_SKIPS.values())} KNOWN_SKIPS skipped; '
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
                                       **({'known_skips': sorted(s['skipped_tests']),
                                           'skip_source': f"{KNOWN_SKIPS[c]['commit']} {KNOWN_SKIPS[c]['ticket']}"}
                                          if s['known_skips'] else {}),
                                       **({k: s[k] for k in ('commit', 'ticket', 'observed_failures',
                                                              'signature_mismatch')} if c in SUPERSEDED else {}))
                               for c, s in new.items()},
                      superseded_source='artifacts/TASK-498/diagnosis.md, re-checked by TASK-852',
                      stubs=STUBS,
                      old_mode_physics_match_baseline=all(all(v for k, v in row.items() if k != 'browser_errors')
                                                          for row in traces['comparison'].values()),
                      totals=dict(existing_suites=len(legacy), existing_tests=sum(s['ran'] for s in legacy.values()),
                                  new_classes=len(new), new_tests=sum(s['ran'] for s in new.values()),
                                  stub_classes=len(STUBS),
                                  passed_classes=sum(s['status'] == 'PASS' for s in new.values()),
                                  superseded_classes=sum(s['status'] == 'SUPERSEDED' for s in new.values()),
                                  nonzero_exits=sum(s['exit'] != 0 for s in list(legacy.values()) + live),
                                  skipped=sum(s['skipped'] for s in legacy.values()) + sum(
                                      len(s['skipped_tests']) - s['known_skips'] for s in new.values()),
                                  known_skips=sum(s['known_skips'] for s in new.values()),
                                  browser_errors=errors),
                      expected_changes_vs_preserved=STARTUP_NOTE)
        self.evidence.write('regression.json', report)
        self.evidence.path('logs/README.md').write_text(
            '# TASK-498 suite logs\n\n' + STARTUP_NOTE + '\n\nlogs/<suite>.log: complete output of each existing '
            'shared-system suite; logs/legacy-summary.json: exit/counts. new-suites/<Class>/tests.log: complete '
            'output of each live Task444..Task497 child run (Task465..492 are 0-test stubs; bulky traces/media pruned after a pass); '
            'new-suites/summary.json: exit/counts.\n')
        self.assertTrue(report['old_mode_physics_match_baseline'])
        self.assertEqual(sorted(report['classes']), LIVE)
        for subsystem, row in subsystems.items():
            self.assertTrue(all(r['status'] == 'PASS' for r in row['new_suites'].values()), subsystem)
        for cls, row in report['classes'].items():
            self.assertEqual(row['status'], 'SUPERSEDED' if cls in SUPERSEDED else 'PASS', row)
            if cls in SUPERSEDED:
                self.assertIsNone(row['signature_mismatch'], row)
        self.assertEqual(report['totals']['nonzero_exits'], 0)
        self.assertEqual(report['totals']['skipped'], 0)  # beyond KNOWN_SKIPS
        self.assertEqual(report['totals']['known_skips'], sum(len(k['tests']) for k in KNOWN_SKIPS.values()))
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
