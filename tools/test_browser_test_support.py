"""Assert resource ordering, partial failure, serving, import safety and the offline Y8 SDK stub."""
from contextlib import ExitStack
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import urlopen

import browser_test_support as support
import render_snapshot

ROOT = Path(__file__).resolve().parents[1]


class BrowserTestSupportTests(unittest.TestCase):
    def exercise_lifecycle(self, fail_launch=False):
        events = []
        owner = unittest.TestCase()
        server = Mock(server_port=12345)
        thread = Mock()
        browser = Mock()
        playwright = Mock()
        for obj, method, label in [
            (server, 'server_close', 'server_close'),
            (server, 'shutdown', 'shutdown'),
            (thread, 'join', 'join'),
            (browser, 'close', 'browser_close'),
            (playwright, 'stop', 'playwright_stop'),
        ]:
            getattr(obj, method).side_effect = lambda label=label: events.append(label)
        playwright.chromium.launch.return_value = browser
        if fail_launch:
            playwright.chromium.launch.side_effect = RuntimeError('controlled launch failure')
        with patch.object(support, 'ThreadingHTTPServer', return_value=server), \
                patch.object(support, 'Thread', return_value=thread), \
                patch.object(support, 'sync_playwright') as factory:
            factory.return_value.start.return_value = playwright
            try:
                if fail_launch:
                    with self.assertRaisesRegex(RuntimeError, 'controlled launch failure'):
                        support.start_browser_test(Path('/supplied/root'), owner.addCleanup)
                else:
                    url, actual_browser = support.start_browser_test(
                        Path('/supplied/root'), owner.addCleanup)
                    self.assertEqual(url, 'http://127.0.0.1:12345/')
                    self.assertIsInstance(actual_browser, support.OfflineBrowser)
                    self.assertIs(actual_browser._browser, browser)
                thread.start.assert_called_once_with()
                playwright.chromium.launch.assert_called_once_with(args=['--no-sandbox'])
                self.assertEqual(events, [])
            finally:
                owner.doCleanups()
        return events

    def test_successful_cleanup_order(self):
        self.assertEqual(self.exercise_lifecycle(), [
            'browser_close', 'playwright_stop', 'shutdown', 'join', 'server_close'])

    def test_browser_launch_failure_cleanup(self):
        self.assertEqual(self.exercise_lifecycle(fail_launch=True), [
            'playwright_stop', 'shutdown', 'join', 'server_close'])

    def test_ephemeral_server_serving_supplied_root(self):
        owner = unittest.TestCase()
        with TemporaryDirectory() as root, patch.object(support, 'sync_playwright'):
            Path(root, 'supplied-root.txt').write_text('supplied root content')
            try:
                url, _ = support.start_browser_test(Path(root), owner.addCleanup)
                self.assertRegex(url, r'^http://127\.0\.0\.1:[1-9][0-9]*/$')
                with urlopen(url + 'supplied-root.txt', timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b'supplied root content')
            finally:
                owner.doCleanups()

    def test_import_without_server_browser_startup(self):
        with patch('http.server.ThreadingHTTPServer', side_effect=AssertionError('server startup')) as server, \
                patch('threading.Thread', side_effect=AssertionError('thread startup')) as thread, \
                patch('playwright.sync_api.sync_playwright', side_effect=AssertionError('browser startup')) as playwright:
            spec = importlib.util.spec_from_file_location('isolated_browser_support', support.__file__)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(callable(module.start_browser_test))
            server.assert_not_called()
            thread.assert_not_called()
            playwright.assert_not_called()


class OfflineSdkStubTests(unittest.TestCase):
    """index.html's cdn.y8.com SDK script is served by the inline stub, not aborted."""
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.url, cls.browser = support.start_browser_test(ROOT, cls.stack.callback)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def test_sdk_stub_boots_disabled_without_console_errors(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('console', lambda msg: msg.type == 'error' and errors.append(msg.text))
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.on('requestfailed', lambda req: errors.append(f'requestfailed {req.url}'))
        # boot() calls PLATFORM.init() from the inline script, before DOMContentLoaded;
        # the aborted-SDK path only settled after init()'s 2900 ms fallback timer.
        page.goto(self.url + 'index.html', wait_until='domcontentloaded')
        start = time.monotonic()
        page.wait_for_function('() => PLATFORM.environment != "pending"', timeout=500)
        elapsed_ms = (time.monotonic() - start) * 1000
        self.assertEqual(page.evaluate('() => PLATFORM.environment'), 'disabled')
        self.assertFalse(page.evaluate('() => PLATFORM.isRewardedSupported()'))
        self.assertLess(elapsed_ms, 500)
        support.wait_for_boot(page)
        page.wait_for_timeout(100)
        self.assertEqual(errors, [])

    def test_boot_frozen_completes_with_no_pending_timers(self):
        context = self.browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.addCleanup(context.close)
        context.add_init_script(render_snapshot.CLOCK_SCRIPT)
        page = context.new_page()
        page.goto(self.url + 'index.html', wait_until='load')
        render_snapshot.boot_frozen(page)
        self.assertEqual(page.evaluate('() => __snap.timers'), [])
        self.assertEqual(page.evaluate('() => __snap.now'), 0)
        self.assertEqual(page.evaluate('() => PLATFORM.environment'), 'disabled')


if __name__ == '__main__':
    unittest.main()
