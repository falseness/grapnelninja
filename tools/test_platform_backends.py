"""Every platform backend (local + the portal stubs) boots the game.

For each of local/itch/gamepix/y8/playgama a Playwright route rewrites the
backend <script> tag in the served index.html (a portal stub loads right
after local.js, whose LOCAL_PLATFORM_BACKEND it reuses), boots to the first
playable frame, records PLATFORM.getPlatformId(), round-trips one key
through PLATFORM.storage.setMany/getMany and calls every facade method once
with no page or console error.

PLATFORM_BACKENDS_EVIDENCE_DIR, when set, receives backends.json:
[{backend, platformId, storageRoundTrip, pageErrors}].
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import open_game, start_game_test
from test_platform_facade import CALLS, READY, VIEWPORT

ROOT = Path(__file__).resolve().parent.parent
BACKENDS = ['local', 'itch', 'gamepix', 'y8', 'playgama']
LOCAL_TAG = '<script src = "platform/backends/local.js"></script>'
ROUND_TRIP_KEY = 'grapnelninja.backendProbe'


def backend_tag(backend):
    if backend == 'local':
        return LOCAL_TAG
    return LOCAL_TAG + '\n        <script src = "platform/backends/%s.js"></script>' % backend


class PlatformBackendTests(unittest.TestCase):
    results = []

    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        evidence = os.environ.get('PLATFORM_BACKENDS_EVIDENCE_DIR')
        if evidence:
            out = Path(evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'backends.json').write_text(json.dumps(cls.results, separators=(',', ':')) + '\n')

    def test_01_index_loads_local_by_default(self):
        html = (ROOT / 'index.html').read_text()
        self.assertEqual(html.count(LOCAL_TAG), 1)
        self.assertEqual(html.count('platform/backends/'), 1)
        for backend in BACKENDS[1:]:
            source = (ROOT / ('platform/backends/%s.js' % backend)).read_text()
            self.assertIn("platformId: '%s'" % backend, source)
            self.assertIn('LOCAL_PLATFORM_BACKEND', source)

    def test_02_every_backend_boots(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                self.results.append(self.check(backend))

    def check(self, backend):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT, locale='en-US')
        try:
            def rewrite(route):
                response = route.fetch()
                body = response.text()
                self.assertEqual(body.count(LOCAL_TAG), 1)
                route.fulfill(response=response, body=body.replace(LOCAL_TAG, backend_tag(backend)))
            context.route('**/index.html', rewrite)
            fallbacks = []
            page.on('console', lambda msg: 'PLATFORM_BACKEND.' in msg.text and fallbacks.append(msg.text))
            page.goto(self.url + 'index.html')
            page.wait_for_function(READY)
            loaded = page.evaluate('''() => [...document.scripts].map(s => s.getAttribute('src'))
                .filter(src => src && src.startsWith('platform/backends/'))''')
            expected = ['platform/backends/local.js'] + \
                ([] if backend == 'local' else ['platform/backends/%s.js' % backend])
            self.assertEqual(loaded, expected)
            platform_id = page.evaluate('PLATFORM.getPlatformId()')
            self.assertEqual(platform_id, backend)
            self.assertEqual(page.evaluate('[PLATFORM.platformId, PLATFORM_BACKEND.platformId]'),
                             [backend, backend])
            written = page.evaluate('PLATFORM.storage.setMany({"%s": "v"})' % ROUND_TRIP_KEY)
            read = page.evaluate('PLATFORM.storage.getMany(["%s"])' % ROUND_TRIP_KEY)
            self.assertTrue(written)
            self.assertEqual(read, {ROUND_TRIP_KEY: 'v'})
            for path, (call, _) in CALLS.items():
                page.evaluate('async () => { await %s }' % call)
            page.evaluate('PLATFORM.init()')
            page.wait_for_timeout(100)
            self.assertEqual(errors['page'], [])
            self.assertEqual(errors['console'], [])
            # The facade never fell back to a default (no failed inner method)
            self.assertEqual(fallbacks, [])
            return {'backend': backend, 'platformId': platform_id,
                    'storageRoundTrip': bool(written) and read == {ROUND_TRIP_KEY: 'v'},
                    'pageErrors': len(errors['page']), 'methodsCalled': len(CALLS) + 1}
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
