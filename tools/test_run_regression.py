#!/usr/bin/env python3
"""run_regression.run_suite kills the whole suite tree on timeout (TASK-851); the runner discovers every
tools/test_*.py minus EXCLUDE (TASK-852). No browser.

FakeGrandchildSuite is the fake suite: it is skipped unless RUN_REGRESSION_FAKE_MARKER is
set, then spawns a SIGTERM-ignoring grandchild whose argv carries that marker and sleeps
past the timeout. Run it through the runner by hand:

    RUN_REGRESSION_FAKE_MARKER=RUNREG_FAKE_GRANDCHILD_x python3 tools/run_regression.py \\
        --out DIR --timeout 2 --only test_run_regression.FakeGrandchildSuite
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import run_regression

MARKER_ENV = 'RUN_REGRESSION_FAKE_MARKER'
FAKE = 'test_run_regression.FakeGrandchildSuite'
GRANDCHILD = ('import signal, time\n'
              'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
              'time.sleep(300)\n')


def marked_pids(marker):
    ps = subprocess.run(['ps', '-eo', 'pid,stat,args'], capture_output=True, text=True).stdout
    return [line for line in ps.splitlines()
            if marker in line and 'ps -eo' not in line and line.split()[1][:1] != 'Z']


@unittest.skipUnless(os.environ.get(MARKER_ENV), f'fake suite: runs only with {MARKER_ENV} set')
class FakeGrandchildSuite(unittest.TestCase):
    def test_spawn_grandchild_and_hang(self):
        subprocess.Popen([sys.executable, '-c', GRANDCHILD, os.environ[MARKER_ENV]])
        time.sleep(120)


class RunSuiteTimeoutTest(unittest.TestCase):
    def run_fake(self, out, marker):
        with mock.patch.object(run_regression, 'TIMEOUT', 2), mock.patch.object(run_regression, 'KILL_GRACE', 1), \
                mock.patch.dict(os.environ, {MARKER_ENV: marker}):
            return run_regression.run_suite(FAKE, out)

    def test_timeout_kills_grandchild(self):
        marker = f'RUNREG_FAKE_GRANDCHILD_{os.getpid()}_{time.time_ns()}'
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            row = self.run_fake(Path(tmp), marker)
            log = (Path(tmp) / f'{FAKE}.log').read_text()
        try:
            self.assertEqual(row['exit'], 124, log)
            self.assertIn('TIMEOUT after 2s', log)
            self.assertLess(time.monotonic() - start, 30)
            time.sleep(0.5)
            self.assertEqual(marked_pids(marker), [], 'grandchild survived the suite timeout')
        finally:
            for line in marked_pids(marker):
                os.kill(int(line.split()[0]), 9)

    def test_normal_suite_exit_code_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {MARKER_ENV: ''}):
                row = run_regression.run_suite(FAKE, Path(tmp))
        self.assertEqual((row['exit'], row['ran'], row['skipped']), (0, 1, 1), json.dumps(row))

    def test_missing_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = run_regression.run_suite('test_no_such_suite_851', Path(tmp))
        self.assertEqual(row['exit'], 2)


class DiscoveryTest(unittest.TestCase):
    def test_suites_are_every_test_file_minus_exclude(self):
        on_disk = sorted(p.stem for p in Path(run_regression.TOOLS).glob('test_*.py'))
        expected = [name for name in on_disk if name not in run_regression.EXCLUDE]
        self.assertEqual(run_regression.SUITES, expected)
        self.assertEqual(run_regression.discover(), expected)
        self.assertGreater(len(expected), 100)
        print(f'DISCOVERED {len(expected)} suites = {len(on_disk)} tools/test_*.py - {len(run_regression.EXCLUDE)} EXCLUDE')

    def test_exclude_entries_have_a_real_reason(self):
        for name, reason in run_regression.EXCLUDE.items():
            self.assertTrue((Path(run_regression.TOOLS) / f'{name}.py').exists(), name)
            self.assertIsInstance(reason, str)
            self.assertNotIn(reason.strip().lower().rstrip('.'), ('', 'fails', 'failing', 'red', 'broken'), name)

    def test_slow_and_timeouts(self):
        suites = set(run_regression.SUITES)
        self.assertLessEqual(run_regression.SLOW, suites)
        self.assertLessEqual(set(run_regression.TIMEOUTS), suites)
        self.assertIn('test_route_shortcuts', run_regression.SLOW)
        self.assertGreaterEqual(run_regression.TIMEOUTS['test_route_shortcuts'], 4 * 3600)
        # test_grapple_over_sections' full suite took 21409 s; 3 h killed it in the TASK-852 full run
        self.assertGreater(run_regression.TIMEOUTS['test_grapple_over_sections'], 21409 * 1.2)
        self.assertGreaterEqual(run_regression.suite_timeout('test_route_shortcuts.SomeClass'), 4 * 3600)
        self.assertEqual(run_regression.suite_timeout('test_play_time'), run_regression.TIMEOUT)
        with mock.patch.object(run_regression, 'TIMEOUT_FORCED', True), mock.patch.object(run_regression, 'TIMEOUT', 5):
            self.assertEqual(run_regression.suite_timeout('test_route_shortcuts'), 5)


if __name__ == '__main__':
    unittest.main()
