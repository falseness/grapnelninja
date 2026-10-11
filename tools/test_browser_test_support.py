"""Assert resource ordering, partial failure, serving, import safety and the offline Y8 SDK stub."""
from contextlib import ExitStack
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
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


# In-page settle probe.  boot() writes the loading text right before
# `await PLATFORM.init()` (environment "pending") and right after it resolves,
# so the mutation marks bracket init() on the page's own clock, independent of
# how long start() later blocks the main thread.  DOMContentLoaded records the
# environment and the SDK script's resource timing.
SETTLE_PROBE_SCRIPT = """
    window.__settle = {marks: []}
    new MutationObserver(records => {
        const el = document.getElementById('loading-progress')
        if (!el) return
        if (records.some(r => r.target === el || r.target.parentNode === el))
            __settle.marks.push({at: performance.now(), text: el.textContent,
                                 env: typeof PLATFORM == 'undefined' ? null : PLATFORM.environment})
    }).observe(document, {childList: true, characterData: true, subtree: true})
    document.addEventListener('DOMContentLoaded', () => {
        const sdk = performance.getEntriesByType('resource').find(e => /y8\\.min\\.js/.test(e.name))
        Object.assign(__settle, {dclNow: performance.now(), envAtDcl: PLATFORM.environment,
                                 sdkResponseEnd: sdk ? sdk.responseEnd : null})
    })
"""


def settle_elapsed_ms(settle):
    """Milliseconds from boot() calling PLATFORM.init() (last mark with environment
    "pending") to boot() resuming after it settled (first mark with a settled
    environment), on the in-page clock."""
    marks = settle['marks']
    called = [m for m in marks if m['env'] == 'pending']
    settled = [m for m in marks if m['env'] in ('disabled', 'y8')]
    if not called or not settled:
        return None
    return settled[0]['at'] - called[-1]['at']


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
        # The settle is measured in-page: boot() calls PLATFORM.init() from the
        # inline script, before DOMContentLoaded, so with the stub the
        # environment is already "disabled" when DOMContentLoaded fires.  (A
        # Python-side rAF poll would instead measure start()'s main-thread
        # work, 300-600 ms on a loaded host.)
        context.add_init_script(SETTLE_PROBE_SCRIPT)
        page = context.new_page()
        errors = []
        page.on('console', lambda msg: msg.type == 'error' and errors.append(msg.text))
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.on('requestfailed', lambda req: errors.append(f'requestfailed {req.url}'))
        page.goto(self.url + 'index.html', wait_until='domcontentloaded')
        settle = page.evaluate('() => window.__settle')
        self.assertEqual(settle['envAtDcl'], 'disabled', settle)
        self.assertIsNotNone(settle['sdkResponseEnd'], settle)
        self.assertLess(settle['sdkResponseEnd'], settle['dclNow'], settle)
        # init() called -> settled, in-page: no 2900 ms fallback timer wait
        elapsed_ms = settle_elapsed_ms(settle)
        self.assertIsNotNone(elapsed_ms, settle)
        self.assertLess(elapsed_ms, 500, settle)
        self.assertEqual(page.evaluate('() => PLATFORM.environment'), 'disabled')
        self.assertFalse(page.evaluate('() => PLATFORM.isRewardedSupported()'))
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
