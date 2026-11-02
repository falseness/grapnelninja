"""TASK-855: tools/build_release.py release zips for itch, gamepix, y8, playgama.

Builds the four zips from HEAD into a temp dir, then per portal:
- static: index.html at the zip root; every local file index.html references
  is in the zip, and every zip entry is index.html, one of those references
  or a file a shipped script loads by a path literal (leveldata.js,
  art/win-*); no
  tools/, artifacts/, screenshots/, docs/, .git, *.py or *.md; exactly one
  portal backend tag and it is the portal's (local.js stays as the shared
  base the stubs need, loaded before it); the portal SDK tag from
  docs/platform-sdk.md right before the backend tag and no other external
  reference (none at all for itch); analytics backend none.js; buildconfig
  modes ['grapple_over'] (itch, gamepix, y8) or every mode (playgama), the
  build id in BUILD_CONFIG and the manifest; y8 appId/gameId non-empty in
  the y8 zip and absent from every other zip; manifest file list, sizes and
  sha256 match the zip.
- boot: the zip extracted to a temp dir and served over http, every external
  request blocked (no portal SDK), boots into a running Grapple Over run
  with the portal backend, a drawn canvas, and no uncaught page error, also
  after a grapple click and a second of play.

Y8_APP_ID / Y8_GAME_ID come from the environment or, when unset, from
/root/credentials/grapnelninja/credentials.env (values are never printed).
BUILD_RELEASE_EVIDENCE_DIR=DIR writes boot-<portal>.png and boot.json there.

    python3 tools/test_build_release.py -v
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from html.parser import HTMLParser

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release  # noqa: E402
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402
from game_harness import collect_errors  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS = Path('/root/credentials/grapnelninja/credentials.env')
PORTALS = ('itch', 'gamepix', 'y8', 'playgama')
SDK_URLS = {
    'itch': None,
    'gamepix': 'https://integration.gamepix.com/sdk/v3/gamepix.sdk.js',
    'y8': 'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js',
    'playgama': 'https://bridge.playgama.com/v2/stable/playgama-bridge.js',
}
EXPECTED_MODES = {'itch': ['grapple_over'], 'gamepix': ['grapple_over'],
                  'y8': ['grapple_over'], 'playgama': ['grapple_over', 'bad', 'classic']}
FORBIDDEN_PARTS = {'tools', 'artifacts', 'screenshots', 'docs', '.git', 'tests', '__pycache__'}
BACKEND = re.compile(r'^platform/backends/([a-z0-9_]+)\.js$')
VIEWPORT = {'width': 1280, 'height': 720}


def y8_env():
    """{'Y8_APP_ID', 'Y8_GAME_ID'} from the environment or the credentials file."""
    env = {k: os.environ.get(k, '') for k in ('Y8_APP_ID', 'Y8_GAME_ID')}
    if all(env.values()) or not CREDENTIALS.exists():
        return env
    for line in CREDENTIALS.read_text().splitlines():
        m = re.match(r'^\s*(?:export\s+)?(Y8_APP_ID|Y8_GAME_ID)=(.*)$', line)
        if m and not env[m.group(1)]:
            env[m.group(1)] = m.group(2).strip().strip('"\'')
    return env


class Scripts(HTMLParser):
    """Every <script>/<link>/<img>... reference, and the script srcs in order."""
    def __init__(self):
        super().__init__()
        self.refs, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'script' and a.get('src'):
            self.scripts.append((a['src'].strip(), 'async' in a or 'defer' in a))
        for name in ('src', 'href', 'data'):
            if a.get(name) and (tag, name) in build_release.REF_ATTRS:
                self.refs.append(a[name].strip())


def parse(html):
    p = Scripts()
    p.feed(html)
    return p


def build_config(source):
    """BUILD_CONFIG of a buildconfig.js, evaluated as JSON-ish text."""
    line = re.search(r'^const BUILD_CONFIG = (.*)$', source, re.M).group(1)
    as_json = re.sub(r"'((?:[^'\\]|\\.)*)'", lambda m: json.dumps(m.group(1)), line)
    as_json = re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', as_json)
    return json.loads(as_json)


class BuildReleaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix='build-release-'))
        cls.env = y8_env()
        if not all(cls.env.values()):
            raise unittest.SkipTest('Y8_APP_ID / Y8_GAME_ID unavailable')
        cls.tree = build_release.CommittedTree('HEAD')
        cls.manifests, cls.zips = {}, {}
        for portal in PORTALS:
            cls.manifests[portal] = build_release.build(portal, cls.out, env=cls.env, tree=cls.tree)
            data = (cls.out / portal / f'grapple-over-{portal}.zip').read_bytes()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                cls.zips[portal] = {n: z.read(n) for n in z.namelist()}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def html(self, portal):
        return self.zips[portal]['index.html'].decode('utf-8')

    def test_01_index_at_root_and_nothing_unreferenced(self):
        for portal in PORTALS:
            with self.subTest(portal=portal):
                files = self.zips[portal]
                self.assertIn('index.html', files)
                refs = [r for r in parse(self.html(portal)).refs
                        if not re.match(r'^(https?:)?//', r)]
                for ref in refs:
                    self.assertIn(ref, files, f'{portal}: {ref} referenced by index.html is missing')
                # Path literals of shipped scripts: mountain.js 'leveldata.js',
                # menu.js 'art/win-' + variant + '.svg'
                literals, prefixes = set(), set()
                for name, data in files.items():
                    if name.endswith('.js'):
                        source = data.decode('utf-8')
                        literals.update(re.findall(r"""['"`]([A-Za-z0-9_./-]+)['"`]""", source))
                        prefixes.update(re.findall(r"""['"`](art/[A-Za-z0-9_./-]*)""", source))
                for name in files:
                    referenced = (name == 'index.html' or name in refs or name in literals
                                  or any(name.startswith(p) for p in prefixes))
                    self.assertTrue(referenced, f'{portal}: {name} is not referenced')
                    self.assertFalse(set(name.split('/')) & FORBIDDEN_PARTS, f'{portal}: {name}')
                    self.assertFalse(name.endswith(('.py', '.md')), f'{portal}: {name}')
                self.assertIn('art/win-default.svg', files)
                self.assertIn('art/win-long.svg', files)
                self.assertIn('leveldata.js', files)

    def test_02_one_portal_backend_and_sdk_tag(self):
        for portal in PORTALS:
            with self.subTest(portal=portal):
                scripts = parse(self.html(portal)).scripts
                srcs = [s for s, _ in scripts]
                backends = [BACKEND.match(s).group(1) for s in srcs if BACKEND.match(s)]
                portal_backends = [b for b in backends if b != 'local']
                self.assertEqual(portal_backends, [portal])
                # local.js is the shared base the portal stubs build on; it loads
                # once, before the portal backend, which loads before platform.js
                self.assertEqual(backends, ['local', portal])
                i_local = srcs.index('platform/backends/local.js')
                i_backend = srcs.index(f'platform/backends/{portal}.js')
                self.assertLess(i_local, i_backend)
                self.assertEqual(srcs[i_backend + 1], 'platform.js')
                self.assertIn('buildconfig.js', srcs[:i_local])
                external = [(s, a) for s, a in scripts if re.match(r'^(https?:)?//', s)]
                other_refs = [r for r in parse(self.html(portal)).refs
                              if re.match(r'^(https?:)?//', r) and r != SDK_URLS[portal]]
                self.assertEqual(other_refs, [])
                if SDK_URLS[portal] is None:
                    self.assertEqual(external, [])
                else:
                    self.assertEqual([s for s, _ in external], [SDK_URLS[portal]])
                    self.assertEqual(srcs[i_backend - 1], SDK_URLS[portal])
                    self.assertEqual(external[0][1], portal == 'y8')  # only Y8's tag is async
                self.assertIn('analytics/backends/none.js', srcs)
                self.assertEqual([s for s in srcs if s.startswith('analytics/backends/')],
                                 ['analytics/backends/none.js'])
                self.assertIn(f'platform/backends/{portal}.js', self.zips[portal])
                for other in PORTALS:
                    if other != portal:
                        self.assertNotIn(f'platform/backends/{other}.js', self.zips[portal])

    def test_03_buildconfig(self):
        for portal in PORTALS:
            with self.subTest(portal=portal):
                config = build_config(self.zips[portal]['buildconfig.js'].decode('utf-8'))
                self.assertEqual(config['platform'], portal)
                self.assertEqual(config['modes'], EXPECTED_MODES[portal])
                self.assertEqual(config['build'], self.tree.build_id())
                self.assertRegex(config['build'], r'^[0-9a-f]{12}-\d{8}$')
                self.assertEqual(self.manifests[portal]['build_id'], config['build'])
                if portal == 'y8':
                    self.assertTrue(config['y8']['appId'], 'y8 appId is empty')
                    self.assertTrue(config['y8']['gameId'], 'y8 gameId is empty')
                    self.assertTrue(config['y8']['appId'] == self.env['Y8_APP_ID'],
                                    'y8 appId differs from Y8_APP_ID')
                    self.assertTrue(config['y8']['gameId'] == self.env['Y8_GAME_ID'],
                                    'y8 gameId differs from Y8_GAME_ID')
                else:
                    self.assertEqual(config['y8'], {'appId': '', 'gameId': ''})
                # the rest of buildconfig.js is the repo file
                repo = self.tree.read('buildconfig.js').decode('utf-8')
                strip = lambda s: re.sub(r'^const BUILD_CONFIG = .*$', '', s, flags=re.M)
                self.assertEqual(strip(self.zips[portal]['buildconfig.js'].decode('utf-8')), strip(repo))

    def test_04_y8_ids_only_in_y8_zip(self):
        secrets = [self.env['Y8_APP_ID'].encode(), self.env['Y8_GAME_ID'].encode()]
        for portal in PORTALS:
            zip_bytes = (self.out / portal / f'grapple-over-{portal}.zip').read_bytes()
            manifest = (self.out / portal / 'manifest.json').read_bytes()
            joined = b'\n'.join(self.zips[portal].values())
            for i, secret in enumerate(secrets):
                with self.subTest(portal=portal, id=('appId', 'gameId')[i]):
                    self.assertFalse(secret in manifest, 'y8 id in a manifest')
                    if portal == 'y8':
                        self.assertTrue(secret in self.zips['y8']['buildconfig.js'], 'y8 id missing')
                    else:
                        self.assertFalse(secret in joined, f'y8 id found in the {portal} zip')
                        self.assertFalse(secret in zip_bytes, f'y8 id found in the {portal} zip bytes')

    def test_05_manifest_matches_zip(self):
        import hashlib
        for portal in PORTALS:
            with self.subTest(portal=portal):
                m = json.loads((self.out / portal / 'manifest.json').read_text())
                zip_bytes = (self.out / portal / f'grapple-over-{portal}.zip').read_bytes()
                self.assertEqual(m['portal'], portal)
                self.assertEqual(m['revision'], self.tree.revision)
                self.assertEqual(m['zip_size'], len(zip_bytes))
                self.assertEqual(m['zip_sha256'], hashlib.sha256(zip_bytes).hexdigest())
                self.assertEqual(m['modes'], EXPECTED_MODES[portal])
                self.assertEqual(m['analytics_backend'], 'analytics/backends/none.js')
                self.assertEqual(sorted(f['path'] for f in m['files']), sorted(self.zips[portal]))
                for f in m['files']:
                    data = self.zips[portal][f['path']]
                    self.assertEqual(f['size'], len(data), f['path'])
                    self.assertEqual(f['sha256'], hashlib.sha256(data).hexdigest(), f['path'])

    def test_06_deterministic(self):
        again = Path(tempfile.mkdtemp(prefix='build-release-again-'))
        try:
            for portal in PORTALS:
                build_release.build(portal, again, env=self.env, tree=self.tree)
                with self.subTest(portal=portal):
                    self.assertEqual((again / portal / f'grapple-over-{portal}.zip').read_bytes(),
                                     (self.out / portal / f'grapple-over-{portal}.zip').read_bytes())
        finally:
            shutil.rmtree(again, ignore_errors=True)

    def test_07_boot_each_zip_without_sdk(self):
        evidence = os.environ.get('BUILD_RELEASE_EVIDENCE_DIR')
        if evidence:
            Path(evidence).mkdir(parents=True, exist_ok=True)
        report = {'revision': self.tree.revision, 'build_id': self.tree.build_id(),
                  'viewport': VIEWPORT, 'sdk': 'no portal SDK: every external request aborted (the Playgama SDK URL gets the offline fixture without window.bridge)', 'portals': {}}
        for portal in PORTALS:
            with self.subTest(portal=portal), ExitStack() as stack:
                site = Path(tempfile.mkdtemp(prefix=f'boot-{portal}-'))
                stack.callback(shutil.rmtree, site, True)
                with zipfile.ZipFile(self.out / portal / f'grapple-over-{portal}.zip') as z:
                    z.extractall(site)
                url, browser = start_browser_test(site, stack.callback)
                context = browser.new_context(viewport=VIEWPORT)
                stack.callback(context.close)
                requests = []
                context.on('request', lambda r: requests.append(r.url))
                page = context.new_page()
                errors = collect_errors(page)
                page.goto(url + 'index.html')
                wait_for_boot_run(page)
                state = page.evaluate('''() => ({
                    version, runInProgress, paused: menu.gamePaused,
                    platformId: PLATFORM_BACKEND.platformId,
                    buildPlatform: BUILD_CONFIG.platform, modes: BUILD_CONFIG.modes,
                    build: BUILD_CONFIG.build, modeButtons: menu.modeButtons.map(b => b.mode),
                    ninja: [ninja.x, ninja.y]})''')
                box = page.locator('#canvas').bounding_box()
                page.mouse.click(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.3)
                page.wait_for_timeout(1000)
                after = page.evaluate('() => ({version, runInProgress, paused: menu.gamePaused})')
                png = page.locator('#canvas').screenshot()
                image = Image.open(io.BytesIO(png)).convert('RGB')
                colors = len(set(image.resize((160, 90)).getdata()))
                if evidence:
                    (Path(evidence) / f'boot-{portal}.png').write_bytes(png)
                external = sorted({u for u in requests if not u.startswith(url)})
                result = dict(state, after=after, canvas_colors=colors,
                              canvas_size=list(image.size), page_errors=errors['page'],
                              console_errors=errors['console'], external_requests=external,
                              screenshot=f'boot-{portal}.png' if evidence else None)
                report['portals'][portal] = result
                self.assertEqual(errors['page'], [])
                self.assertEqual(state['version'], 'grapple_over')
                self.assertTrue(state['runInProgress'])
                self.assertFalse(state['paused'])
                self.assertEqual(state['platformId'], portal)
                self.assertEqual(state['buildPlatform'], portal)
                self.assertEqual(state['modes'], EXPECTED_MODES[portal])
                self.assertEqual(state['modeButtons'],
                                 EXPECTED_MODES[portal] if len(EXPECTED_MODES[portal]) > 1 else [])
                self.assertEqual(after['version'], 'grapple_over')
                self.assertTrue(after['runInProgress'])
                self.assertGreater(colors, 20, f'{portal}: canvas looks blank')
                expected_external = [SDK_URLS[portal]] if SDK_URLS[portal] else []
                self.assertEqual(external, expected_external)
                result['pass'] = True
        report['pass'] = all(r.get('pass') for r in report['portals'].values()) \
            and len(report['portals']) == len(PORTALS)
        if evidence:
            (Path(evidence) / 'boot.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
