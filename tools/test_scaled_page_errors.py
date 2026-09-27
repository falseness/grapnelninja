"""Run the CLI scripts' actual scaled-page setup and rejection in Chromium."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from playwright.sync_api import sync_playwright


class ScaledPageErrorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(args=['--no-sandbox'])
        cls.addClassCleanup(cls.browser.close)

    def check_scaled_page(self, tool, width, event):
        source = Path(__file__).with_name(f'verify-{tool}-percentages.py')
        tree = ast.parse(source.read_text())
        browser_block = next(n for n in tree.body if isinstance(n, ast.With))
        # Select the real independent-axis setup, including every statement
        # from page creation through navigation; do not recreate its listeners.
        starts = [i for i, n in enumerate(browser_block.body)
                  if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                  and isinstance(n.value.func, ast.Attribute)
                  and n.value.func.attr == 'new_page'
                  and any(k.arg == 'viewport' and ast.literal_eval(k.value) ==
                          {'width': width, 'height': 720}
                          for k in n.value.keywords)]
        self.assertEqual(len(starts), 1)
        start = starts[0]
        end = next(i for i in range(start + 1, len(browser_block.body))
                   if isinstance(browser_block.body[i], ast.Expr)
                   and isinstance(browser_block.body[i].value, ast.Call)
                   and isinstance(browser_block.body[i].value.func, ast.Attribute)
                   and browser_block.body[i].value.func.attr == 'goto')
        setup = ast.Module(body=browser_block.body[start:end + 1], type_ignores=[])
        rejection = next(n for n in reversed(tree.body) if isinstance(n, ast.Assert))
        rejection = ast.Module(body=[rejection], type_ignores=[])
        marker = f'{tool} {width}x720 injected {event}'

        def new_page(**kwargs):
            page = self.browser.new_page(**kwargs)
            self.addCleanup(page.close)
            page.route('**/*', lambda route: route.fulfill(
                content_type='text/html', body='<!doctype html><title>clean</title>'))
            # Init scripts run during navigation, before the document's scripts.
            if event == 'console':
                page.add_init_script(f'console.error({marker!r});')
            elif event == 'pageerror':
                page.add_init_script(f'throw new Error({marker!r});')
            return page

        namespace = {'browser': SimpleNamespace(new_page=new_page),
                     'args': SimpleNamespace(url='http://scaled-page.test/'),
                     'errors': [], 'console': []}
        exec(compile(setup, str(source), 'exec'), namespace)
        check = compile(rejection, str(source), 'exec')
        if event == 'clean':
            self.assertEqual(namespace['errors'], [])
            self.assertEqual(namespace['console'], [])
            exec(check, namespace)
            result = 'clean control accepted'
        else:
            bucket = 'console' if event == 'console' else 'errors'
            other = 'errors' if event == 'console' else 'console'
            self.assertEqual(namespace[other], [])
            self.assertEqual(len(namespace[bucket]), 1)
            self.assertIn(marker, namespace[bucket][0])
            with self.assertRaises(AssertionError):
                exec(check, namespace)
            result = f'collected {namespace[bucket][0]!r}; rejected'
        print(f'PASS {source.name} {width}x720 {event}: {result}', flush=True)


for tool, width in [('gameplay', 1280), ('frame', 1600)]:
    for event in ['console', 'pageerror', 'clean']:
        def test(self, tool=tool, width=width, event=event):
            self.check_scaled_page(tool, width, event)
        setattr(ScaledPageErrorsTests, f'test_{tool}_{width}x720_{event}', test)


if __name__ == '__main__':
    unittest.main()
