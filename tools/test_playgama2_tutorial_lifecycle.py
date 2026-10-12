"""Tutorial checker runner errors: fixture replies across reload/close and injected failures."""
import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path

from playwright._impl._page import BindingCall
from playwright.sync_api import sync_playwright

import test_playgama2_tutorial as checker

TOOLS = Path(__file__).resolve().parent
STOCK_BINDING_CALL = BindingCall.call


class TutorialRunnerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browser = cls.pw.chromium.launch(args=['--no-sandbox'])
        cls.addClassCleanup(cls.browser.close)
        cls.loop = cls.browser._impl_obj._loop

    def setUp(self):
        self.runner = checker.RunnerErrors()
        self.addCleanup(self.runner.install(self.loop))

    def pending(self, name='fixtureSet', error=None):
        """Context whose fixture callback stays pending until release() is called."""
        context = self.browser.new_context()
        self.addCleanup(context.close)
        release, calls = asyncio.Event(), []
        async def wait(*args):
            calls.append(args)
            await release.wait()
            if error: raise error
            return {'rejected': False}
        context.expose_function(name, lambda *args: wait(*args))
        page = context.new_page()
        page.goto('data:text/html,<p>fixture')
        page.evaluate(f'() => {{ window.settled = {name}(["k"], ["v"]).then(r => "resolved", e => "rejected: " + e.message); }}')
        while not calls:
            page.wait_for_timeout(10)
        print(f'  pending {name} callback started with args {calls[0]}', flush=True)
        return context, page, release

    def check(self, expected, unexpected):
        self.runner.settle(self.browser)
        print(f'  expected={self.runner.expected}', flush=True)
        print(f'  unexpected={self.runner.unexpected}', flush=True)
        self.assertEqual(self.runner.expected, expected)
        self.assertEqual(len(self.runner.unexpected), len(unexpected))
        for actual, marker in zip(self.runner.unexpected, unexpected):
            self.assertIn(marker, actual)

    def test_pending_fixture_across_reload_resolves(self):
        context, page, release = self.pending()
        page.reload()
        release.set()
        page.wait_for_timeout(200)
        self.assertEqual(page.evaluate('typeof settled'), 'undefined')
        self.check([], [])
        print('PASS pending fixture across reload: reply delivered, nothing cancelled or leaked', flush=True)

    def test_pending_fixture_across_page_close_is_expected_cancellation(self):
        context, page, release = self.pending()
        page.close()
        release.set()
        self.check([{'binding': 'fixtureSet', 'reply': 'resolve', 'cancelled_by': 'page closed'}], [])
        print('PASS pending fixture across page close: expected cancellation, no leaked task', flush=True)

    def test_pending_fixture_across_context_close_is_expected_cancellation(self):
        context, page, release = self.pending('fixtureGet')
        context.close()
        release.set()
        self.check([{'binding': 'fixtureGet', 'reply': 'resolve', 'cancelled_by': 'context closed'}], [])
        print('PASS pending fixture across context close: expected cancellation, no leaked task', flush=True)

    def test_callback_error_on_live_page_is_unexpected(self):
        context, page, release = self.pending(error=ValueError('INJECTED callback bug'))
        release.set()
        page.wait_for_function('window.settled')
        self.assertEqual(page.evaluate('settled'), 'rejected: INJECTED callback bug')
        self.check([], ["fixture callback fixtureSet raised ValueError('INJECTED callback bug')"])
        print('PASS genuine callback error on live page: unexpected, page sees rejection', flush=True)

    def test_callback_error_across_close_is_not_expected_cancellation(self):
        context, page, release = self.pending(error=ValueError('INJECTED callback bug'))
        page.close()
        release.set()
        self.check([{'binding': 'fixtureSet', 'reply': 'reject', 'cancelled_by': 'page closed'}],
                   ["fixture callback fixtureSet raised ValueError('INJECTED callback bug')"])
        print('PASS genuine callback error across close: still unexpected despite close', flush=True)

    def test_stock_binding_call_leak_is_detected(self):
        # Reproduces TASK-334 under the original Playwright path, seen by the loop handler.
        BindingCall.call = STOCK_BINDING_CALL
        context, page, release = self.pending()
        page.close()
        release.set()
        self.check([], ['unexpected runner error: Task exception was never retrieved: TargetClosedError'])
        print('PASS stock BindingCall reject-after-close leak detected as unexpected', flush=True)

    def test_injected_runner_error_fails_checker(self):
        script = '''
import asyncio, sys, unittest
import test_playgama2_tutorial as checker
start = checker.Playgama2TutorialTests.start
def start_with_runner_error(self, page, touch):
    start(self, page, touch)
    async def boom(): raise RuntimeError('INJECTED unexpected runner error')
    self.browser._impl_obj._loop.create_task(boom())
checker.Playgama2TutorialTests.start = start_with_runner_error
suite = unittest.defaultTestLoader.loadTestsFromName('test_playgama2_tutorial.Playgama2TutorialTests.test_en_desktop')
sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
'''
        env = {**os.environ, 'PYTHONPATH': str(TOOLS), 'PLAYGAMA2_EVIDENCE_DIR':
               os.environ.get('PLAYGAMA2_LIFECYCLE_CHILD_DIR', '/tmp/playgama2-lifecycle-child')}
        child = subprocess.run([sys.executable, '-c', script], env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        print('  child output:\n' + '\n'.join('    | ' + line for line in child.stdout.splitlines()), flush=True)
        print(f'  child exit={child.returncode}', flush=True)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("unexpected runner error: Task exception was never retrieved: RuntimeError('INJECTED unexpected runner error')", child.stdout)
        self.assertIn('AssertionError', child.stdout)
        self.assertNotIn('PASS en-desktop', child.stdout)
        self.assertIn('FAILED', child.stdout)
        print('PASS injected runner error: checker exits nonzero without PASS evidence', flush=True)

if __name__ == '__main__': unittest.main()
