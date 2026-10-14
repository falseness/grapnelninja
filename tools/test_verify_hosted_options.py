"""tools/verify_hosted_playgama.py without network.

Context options match each case label, and the full hosted flow runs offline:
the host page, game files and SDK are fulfilled by routes (game files from the
checkout, the fake Bridge from test_playgama2_bridge with storage kept in
sessionStorage across reloads); every other request is aborted.
"""
import argparse
import itertools
import json
import mimetypes
import sys
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_playgama2_bridge as support
import verify_hosted_playgama
from verify_hosted_playgama import context_options

HOST = 'https://host.test/grapnelninja'
GAME = 'https://grapnelninja.games.playgama.net/'


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


class OfflineHostedFlowTest(unittest.TestCase):
    """Runs verify_hosted_playgama.run() end to end against the checkout."""

    @staticmethod
    def prepare(context):
        values = "const values = JSON.parse(sessionStorage.getItem('fake-bridge') || 'null') || {"
        sdk = 'const FAULT="normal", SAVED_LANGUAGE="en";' + support.FAKE
        for old, new in [("const values = {", values),
                         ("keys.forEach((key, i) => values[key] = data[i]);",
                          "keys.forEach((key, i) => values[key] = data[i]); sessionStorage.setItem('fake-bridge', JSON.stringify(values));")]:
            assert sdk.count(old) == 1, old
            sdk = sdk.replace(old, new)

        def game(route):
            path = support.ROOT / route.request.url.split('?')[0][len(GAME):]
            if not path.is_file():
                return route.fulfill(status=404)
            route.fulfill(body=path.read_bytes(),
                          content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        context.route('**/*', lambda route: route.abort())
        context.route(HOST, lambda route: route.fulfill(content_type='text/html', body=
            '<!doctype html><body style="margin:0"><p>Offline host</p>'
            '<iframe src="' + GAME + 'index.html" style="width:100vw;height:90vh;border:0"></iframe>'))
        context.route(GAME + '**', game)
        context.route(support.SDK, lambda route: route.fulfill(content_type='application/javascript', body=sdk))

    def test_offline_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = argparse.Namespace(url=HOST, out=out, engine='chromium', headed=False,
                executable_path=None, device='both', phone=False, modes=['bad', 'classic'])
            verify_hosted_playgama.run(args, prepare=self.prepare)
            report = json.loads((out / 'hosted.json').read_text())
        for row in report['cases']:
            print('HOSTED', row['case'], row['verdict'],
                  'boot', row['boot']['mode'], row['boot']['hint'],
                  'started', row['started']['mode'],
                  'dismissed', row['gameplay'][-1]['hint'],
                  'reloaded', {k: row['reloaded'][k] for k in ('time', 'language', 'hint')}, flush=True)
        self.assertEqual([(r['case'], r['verdict']) for r in report['cases']],
                         [(f'chromium-{d}-{m}', 'PASS') for d in ('desktop', 'touch') for m in ('bad', 'classic')])


if __name__ == '__main__':
    unittest.main()
