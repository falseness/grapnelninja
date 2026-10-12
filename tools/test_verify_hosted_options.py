"""Context options of tools/verify_hosted_playgama.py match each case label; no network."""
import itertools
import json
import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_hosted_playgama import context_options


class ContextOptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with sync_playwright() as pw:
            cls.devices = pw.devices

    def test_case_label_matches_effective_options(self):
        for engine, phone, device in itertools.product(
                ('chromium', 'firefox', 'webkit'), (False, True), ('desktop', 'touch', 'both')):
            touches = (False, True) if device == 'both' else (device == 'touch',)
            for touch in touches:
                options = context_options(self.devices, engine, touch, phone)
                label = f'{engine} phone={phone} device={device} case={"touch" if touch else "desktop"}'
                print('OPTIONS', label, json.dumps(options, sort_keys=True), flush=True)
                self.assertIs(options['has_touch'], touch, label)
                if not touch:
                    self.assertNotIn('is_mobile', options, label)
                    self.assertNotIn('Mobile', options.get('user_agent', ''), label)
                if engine == 'firefox':
                    self.assertNotIn('is_mobile', options, label)
                if phone:
                    self.assertEqual(options['viewport'], {'width':915, 'height':412}, label)
                    self.assertNotIn('default_browser_type', options, label)
                else:
                    self.assertEqual(set(options), {'viewport', 'has_touch'}, label)
                if engine != 'firefox' and phone and touch:
                    self.assertIs(options['is_mobile'], True, label)


if __name__ == '__main__':
    unittest.main()
