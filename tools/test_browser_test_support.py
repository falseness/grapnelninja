"""Assert resource ordering, partial failure, serving, and import safety."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.request import urlopen

import browser_test_support as support


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
                    self.assertIsInstance(actual_browser, support.OfflineBridgeBrowser)
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


if __name__ == '__main__':
    unittest.main()
