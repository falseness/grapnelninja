"""Headless run of tools/android_runner against the working tree (both arms).

The runner must pass the menu-less boot wait (bootComplete && runInProgress),
start each measured mode and record frames; only the probe's active duration
is shortened, the same way playgama_android_runner.prepare() rewrites it.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from browser_test_support import start_browser_test
from playgama_firefox_perf import PROBE
from test_playgama2_bridge import FAKE, SDK

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_MS = int(os.environ.get('ANDROID_RUNNER_ACTIVE_MS', '1500'))


class AndroidRunnerBootTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for f in (ROOT / 'tools/android_runner').iterdir():
            shutil.copyfile(f, root / f.name)
        for arm in ('baseline', 'repair'):
            (root / arm).symlink_to(ROOT, target_is_directory=True)
        (root / 'builds.json').write_text(json.dumps({arm: {'zip_sha256': 'worktree-' + arm}
                                                      for arm in ('baseline', 'repair')}))
        done = 'if (p.activeMs >= 35000) p.done = true;'
        self.assertIn(done, PROBE)
        (root / 'probe.js').write_text('window.installProbe = ' +
                                       PROBE.replace(done, f'if (p.activeMs >= {ACTIVE_MS}) p.done = true;') + ';\n')
        self.url, self.browser = start_browser_test(root, self.addCleanup)

    def test_runner_boots_and_records_both_modes(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        context.route(SDK, lambda route: route.fulfill(content_type='application/javascript', body=
            "const FAULT = 'normal'; const SAVED_LANGUAGE = 'en';\n" + FAKE))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda msg: msg.type == 'error' and errors.append(msg.text))
        page.goto(self.url + 'index.html')
        for field, value in (('model', 'headless'), ('android', 'none'), ('firefox', 'none')):
            page.fill('#' + field, value)
        page.click('#start')
        page.wait_for_function("!document.getElementById('download').disabled", timeout=600000)
        receipt = page.evaluate('receipt')
        status = page.text_content('#status')
        print('status:', status)
        print('error:', receipt.get('error'))
        for run in receipt['runs']:
            starts = [t for t in run['transitions'] if 'state' in t]
            print(f"run mode={run['mode']} started_version={run['started_version']} pair={run['pair']} arm={run['arm']} frames={len(run['frames'])} "
                  f"inputs={len(run['inputs'])} active_ms={run['frames'][-1]['activeMs']:.0f} "
                  f"first_state={json.dumps(starts[0]['state']) if starts else None}")
        print('errors:', errors)
        self.assertNotIn('error', receipt)
        self.assertTrue(status.startswith('Capture complete'))
        self.assertEqual([(r['mode'], r['pair'], r['arm']) for r in receipt['runs']],
                         [(m, p, a) for m in ('classic', 'bad') for p in range(3)
                          for a in (('baseline', 'repair') if p % 2 == 0 else ('repair', 'baseline'))])
        for run in receipt['runs']:
            self.assertEqual(run['started_version'], run['mode'])
            self.assertGreater(len(run['frames']), 10)
            self.assertGreaterEqual(run['frames'][-1]['activeMs'], ACTIVE_MS)
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
