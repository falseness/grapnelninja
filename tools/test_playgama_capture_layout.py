"""Bounded offline production geometry regression; never an FPS capture."""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from playgama_render_compare import ROOT, SDK, FIXTURE, LAYOUT, validate_capture_layout


class ProductionLayoutTests(unittest.TestCase):
    def test_real_touch_layout(self):
        out = Path(os.environ.get('LAYOUT_EVIDENCE_DIR', 'artifacts/TASK-320'))
        out.mkdir(parents=True, exist_ok=True)
        url, browser = start_browser_test(ROOT, self.addCleanup)
        context = browser.new_context(viewport={'width': 844, 'height': 390},
            device_scale_factor=2, has_touch=True, locale='en-US', service_workers='block')
        self.addCleanup(context.close)
        context.route(SDK, lambda r: r.fulfill(content_type='application/javascript', body=FIXTURE))
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.goto(url + 'index.html')
        wait_for_boot(page)
        page.wait_for_function('bootComplete && runInProgress')
        layout = page.evaluate(LAYOUT)
        observation = dict(layout, browser=browser.version, errors=errors,
                           scope='offline geometry only; NOT performance measurement')
        path = out/'actual-layout.json'
        path.write_text(json.dumps(observation, indent=2) + '\n')
        for key, expected in dict(viewport=[844, 390], dpr=2, backing=[1688, 780],
                                  css=[844, 390], logical=[2337, 1080]).items():
            self.assertEqual(layout[key], expected, key)
        self.assertEqual(errors, [])
        validate_capture_layout(layout)
        observation['verdict'] = 'PASS real production layout accepted'
        path.write_text(json.dumps(observation, indent=2) + '\n')
        print(observation['verdict'] + '; ' + json.dumps(observation), flush=True)


if __name__ == '__main__':
    unittest.main()
