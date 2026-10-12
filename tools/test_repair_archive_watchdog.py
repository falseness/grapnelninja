"""Watchdog regression for tools/test_playgama_repair_archive.py.

A test stuck inside a Playwright wait must end the run: a named FAIL line with
the elapsed seconds, exit status 3, no surviving browser, never a busy hang.
Each browser arm (subTest) gets its own budget. Run from the repo root:
  python3 tools/test_repair_archive_watchdog.py
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

TOOLS = Path(__file__).resolve().parent
RUNNER = textwrap.dedent('''
    import sys, time, unittest
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from playwright.sync_api import sync_playwright
    from test_playgama_repair_archive import BoundedResult, descendants

    class Stuck(unittest.TestCase):
        def test_stuck_in_playwright_wait(self):
            pw = sync_playwright().start(); self.addCleanup(pw.stop)
            browser = pw.chromium.launch(args=['--no-sandbox']); self.addCleanup(browser.close)
            page = browser.new_page()
            Path(sys.argv[3], 'pids').write_text(' '.join(map(str, descendants())))
            print('WAITING forever inside page.wait_for_function', flush=True)
            page.wait_for_function('false', timeout=0)

    class Arms(unittest.TestCase):
        def test_arms_each_within_budget(self):
            for arm in range(3):
                with self.subTest(arm=arm):
                    time.sleep(BoundedResult.timeout * 0.6)

    BoundedResult.timeout = float(sys.argv[2]); BoundedResult.evidence = Path(sys.argv[3])
    case = Stuck if sys.argv[4] == 'stuck' else Arms
    result = unittest.TextTestRunner(verbosity=2, resultclass=BoundedResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(case))
    sys.exit(0 if result.wasSuccessful() else 1)
''')
WATCHDOG = 4


def running(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] not in 'ZX'
    except OSError:
        return False


class WatchdogTests(unittest.TestCase):
    def run_runner(self, case):
        out = Path(tempfile.mkdtemp())
        script = out / 'runner.py'; script.write_text(RUNNER)
        started = time.monotonic()
        proc = subprocess.run([sys.executable, str(script), str(TOOLS), str(WATCHDOG), str(out), case],
                              capture_output=True, text=True, timeout=WATCHDOG * 3 + 30)
        elapsed = time.monotonic() - started
        print(f'--- {case}: exit={proc.returncode} elapsed={elapsed:.1f}s\n{proc.stdout}{proc.stderr}', flush=True)
        return proc, elapsed, out

    def test_stuck_playwright_wait_exits_nonzero_with_named_fail(self):
        proc, elapsed, out = self.run_runner('stuck')
        self.assertEqual(proc.returncode, 3)
        self.assertLess(elapsed, WATCHDOG + 30)
        line = re.search(r'^FAIL: __main__\.Stuck\.test_stuck_in_playwright_wait exceeded 4\.0 seconds watchdog '
                         r'\(elapsed (\d+\.\d) s\)', proc.stdout, re.M)
        self.assertTrue(line, proc.stdout)
        self.assertGreaterEqual(float(line.group(1)), WATCHDOG)
        self.assertIn('stuck_in_playwright_wait', (out / 'watchdog.json').read_text())
        pids = [int(p) for p in (out / 'pids').read_text().split()]
        self.assertGreaterEqual(len(pids), 2)  # Playwright driver + Chromium
        # SIGKILLed processes may need a moment to finish exiting.
        deadline = time.monotonic() + 5
        while (alive := [p for p in pids if running(p)]) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(alive, [], 'browser processes survived the watchdog')
        print(f'PASS watchdog: exit 3 after {elapsed:.1f}s (< {WATCHDOG}+30); {line.group(0)}; {len(pids)} driver/browser processes gone', flush=True)

    def test_budget_is_per_browser_arm(self):
        proc, elapsed, out = self.run_runner('arms')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn('watchdog', proc.stdout)
        self.assertIn('Ran 1 test', proc.stderr)
        self.assertGreater(elapsed, WATCHDOG * 1.5)
        self.assertFalse((out / 'watchdog.json').exists())
        print(f'PASS per-arm budget: 3 arms x {WATCHDOG * 0.6:.1f}s (total > {WATCHDOG}s) passed', flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
