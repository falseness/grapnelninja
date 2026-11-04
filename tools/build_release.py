"""Build a Grapple Over release zip for one portal from a committed revision.

    python3 tools/build_release.py --portal itch|gamepix|y8|playgama|all
                                   [--out DIR] [--rev REV]

Writes DIR/<portal>/grapple-over-<portal>.zip and DIR/<portal>/manifest.json
(DIR defaults to artifacts/release-grapple-over). File bytes come from the
git blobs of REV (default HEAD), never from the working tree, so the build
is the same as one made from a clean checkout of REV. The zip is
deterministic (sorted entries, fixed timestamps and modes).

Per portal (ported from the old gamepix/y8/itch_io/playgama-start-firefox
branch scripts):
- runtime files: index.html (at the zip root) plus every local file
  index.html references (<script src>, <link href>, <img src>, ...), plus
  the files the shipped scripts load by path at run time (a quoted string
  literal that is a committed file, e.g. mountain.js's 'leveldata.js', or
  that starts with '<committed dir>/', e.g. menu.js's
  'art/win-' + variant + '.svg' ships art/win-*). Nothing else: tools/,
  tests, artifacts/, screenshots/, docs/, .git, *.py and *.md are refused.
- index.html: the portal SDK tag (docs/platform-sdk.md; none for itch.io)
  and the portal backend tag go right after platform/backends/local.js.
  local.js stays as the shared base library: every portal stub builds on
  LOCAL_PLATFORM_BACKEND and then redefines PLATFORM_BACKEND, so the portal
  file is the build's platform backend.
- analytics: itch and y8 (GA_PORTALS) swap the analytics/backends/none.js
  tag for the vendored GameAnalytics SDK (analytics/vendor/GameAnalytics.min.js,
  its licence file ships next to it) plus analytics/backends/gameanalytics.js,
  whose 'var GA_KEYS = ...' line gets GA_GAME_KEY / GA_SECRET_KEY from the
  environment (required there). GamePix and Playgama keep none.js (both
  forbid third-party analytics).
- buildconfig.js is rewritten: platform, modes (['grapple_over'] for itch,
  gamepix and y8; every mode for playgama), y8 ids (Y8_APP_ID / Y8_GAME_ID
  from the environment, y8 only; required there) and build (the build id,
  '<12-char commit sha>-<commit date YYYYMMDD>').
- build-time bake (TASK-891, tools/release_bake.py): the size-independent
  boot caches are computed once per revision in a headless Chromium boot of
  the revision's source files and shipped as JSON tables. Today that is the
  route arrow table: render/routearrows-baked.js (BAKED_ROUTE_ARROWS, a
  'window.ROUTE_ARROWS_BAKED = <JSON>' line, a script so file:// pages load
  it too), whose tag goes right before render/routearrows.js. The source
  tree has no bake and computes it at run time. A revision whose
  routearrows.js does not read ROUTE_ARROWS_BAKED (before TASK-891) builds
  without it, as it did then.
- single-mode drop (TASK-894): the builds whose modes are ['grapple_over']
  (itch, gamepix, y8; not playgama) leave out OTHER_MODE_SCRIPTS, the
  scripts only the bad and classic modes need (elements/factory.js,
  sprites/rect.js, jumpingcube.js, triangle.js, side.js; sprites/floor.js
  stays: fixedlevel.js's PersistentWorld extends Floor). Their tags go and
  a generated other-mode-stubs.js (other_mode_stubs) takes the first one's
  place: every top-level class and function of those files, empty, so the
  names the shared code still tests (instanceof Rect / Triangle / Side, the
  resize's new ElementsFactory) stay declared; a stub function or a stub
  constructor (but ElementsFactory's) throws. Gated on the revision's
  buildconfig.js naming OTHER_MODE_SCRIPTS, so older revisions build as
  they did.
- bundle (TASK-893, bundle_scripts): the game's own scripts ship as ONE file,
  game-<sha256[:12]>.js (one dot: Playgama's path rule), instead of one tag per file: the local <script src>
  files in index.html order (the build's rewrites and the bake included),
  each whitespace-minified by the vendored esbuild (tools/vendor/esbuild;
  --minify-whitespace only: no identifier is renamed and no syntax is
  rewritten, so the shared globals, render/abswitches.js's window[name]
  replacements and function names stay), separated by ';' lines.
  buildconfig.js, gameanalytics.js and the bake go in verbatim
  (VERBATIM_PARTS). The inline <script>I18N.applyDom()</script> between
  i18n.js (in <head>) and the body scripts is folded in after i18n.js; the
  bundle tag takes the place of the last bundled tag (end of <body>, before
  the inline boot script), and the portal SDK tag (except Playgama's, first
  in <head>) and the vendored GameAnalytics SDK tag (UNBUNDLED_SCRIPTS) move
  right before it. Its first line, window.GAME_BUNDLE_FILES, lists [first
  line, source path, sha256[:16] of the source] per part:
  render/visualsperf.js maps stack lines back to source files with it, and
  bundle_parts / stale_parts / replace_part read it for the tests. The
  source tree keeps separate files; revisions before TASK-893 (no
  GAME_BUNDLE_FILES in visualsperf.js) build unbundled as they did then.
  runtime_files(..., bundle=False) is the per-file build before bundling.
- manifest.json: portal, build id, revision, modes, bundle (path, bytes,
  gzip bytes, parts), zip size and sha256,
  and the per-file list (path, size, sha256). Credential values never go in
  the manifest or the build output, only into the y8 zip's buildconfig.js
  and the itch and y8 zips' analytics/backends/gameanalytics.js.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'artifacts' / 'release-grapple-over'
PORTALS = ('itch', 'gamepix', 'y8', 'playgama')
ALL_MODES = ['grapple_over', 'bad', 'classic']

# docs/platform-sdk.md "Selecting a backend"
LOCAL_TAG = '<script src = "platform/backends/local.js"></script>'
BACKEND_TAG = '<script src = "platform/backends/{portal}.js"></script>'
SDK_TAGS = {
    'itch': None,
    'gamepix': '<script src="https://integration.gamepix.com/sdk/v3/gamepix.sdk.js"></script>',
    'y8': '<script src="https://cdn.y8.com/minimal-sdk/2-0/y8.min.js" async></script>',
    'playgama': '<script src="https://bridge.playgama.com/v2/stable/playgama-bridge.js"></script>',
}
# Bridge required step 2 / Playgama requirement 1.1.2: the SDK script is the
# first script in <head>, loaded normally (not async/defer)
SDK_FIRST_IN_HEAD = {'playgama'}
ANALYTICS_TAG = '<script src = "analytics/backends/none.js"></script>'
GA_SDK = 'analytics/vendor/GameAnalytics.min.js'
GA_LICENSE = 'analytics/vendor/GameAnalytics.LICENSE.txt'
GA_BACKEND = 'analytics/backends/gameanalytics.js'
ANALYTICS_BACKENDS = {'itch': GA_BACKEND, 'gamepix': 'analytics/backends/none.js',
                      'y8': GA_BACKEND, 'playgama': 'analytics/backends/none.js'}
# The portals whose zip ships GameAnalytics (with the keys injected)
GA_PORTALS = tuple(p for p, backend in ANALYTICS_BACKENDS.items() if backend == GA_BACKEND)
GA_KEYS_LINE = re.compile(r'^var GA_KEYS = .*$', re.M)
GA_KEY_FORMAT = {'GA_GAME_KEY': re.compile(r'^[A-Za-z0-9]{32}$'),
                 'GA_SECRET_KEY': re.compile(r'^[A-Za-z0-9]{40}$')}
MODES = {'itch': ['grapple_over'], 'gamepix': ['grapple_over'],
         'y8': ['grapple_over'], 'playgama': ALL_MODES}
CONFIG_LINE = re.compile(r'^const BUILD_CONFIG = .*$', re.M)
# TASK-891 build-time bake
ROUTE_ARROWS_TAG = '<script src = "render/routearrows.js"></script>'
BAKED_ROUTE_ARROWS = 'render/routearrows-baked.js'
BAKED_ROUTE_ARROWS_TAG = f'<script src = "{BAKED_ROUTE_ARROWS}"></script>'
# TASK-894: single-mode builds (MODES == ['grapple_over']) leave out the scripts only
# the bad and classic modes need; one generated stub script keeps their class and
# function names declared (other_mode_stubs)
OTHER_MODE_SCRIPTS = ('elements/factory.js', 'sprites/rect.js', 'sprites/jumpingcube.js',
                      'sprites/triangle.js', 'sprites/side.js')
OTHER_MODE_STUBS = 'other-mode-stubs.js'
# Stub classes the single-mode game does construct (index.html's resize builds a new ElementsFactory)
CONSTRUCTED_STUBS = ('ElementsFactory',)
STUB_DECLARATION = re.compile(r'^(class|function)\s+([A-Za-z_$][\w$]*)', re.M)
# Files a build writes that are no committed blob (their bytes come from the bake / the stubs)
GENERATED_FILES = (BAKED_ROUTE_ARROWS, OTHER_MODE_STUBS)
BAKE_TOOL = Path(__file__).resolve().parent / 'release_bake.py'
_BAKES = {}
# TASK-893 bundle: the game's own scripts ship as one whitespace-minified file
BUNDLE_NAME = re.compile(r'^game-[0-9a-f]{12}\.js$')
# Local scripts that stay separate tags (vendored, already minified)
UNBUNDLED_SCRIPTS = (GA_SDK,)
# Parts the build rewrites go in verbatim (their BUILD_CONFIG / GA_KEYS / bake lines stay as written)
VERBATIM_PARTS = ('buildconfig.js', GA_BACKEND, BAKED_ROUTE_ARROWS, OTHER_MODE_STUBS)
BUNDLE_TABLE = 'window.GAME_BUNDLE_FILES = '
ESBUILD = Path(__file__).resolve().parent / 'vendor' / 'esbuild' / 'esbuild-linux-x64'
SCRIPT_ELEMENT = re.compile(r'<script\b([^>]*)>(.*?)</script\s*>', re.S | re.I)
SCRIPT_SRC = re.compile(r'''\bsrc\s*=\s*(["'])(.*?)\1''', re.S | re.I)
USE_STRICT = re.compile(r'''^\s*(?:(?://[^\n]*\n|/\*.*?\*/)\s*)*['"]use strict['"]''', re.S)

EXCLUDED_DIRS = {'tools', 'tests', 'test', 'artifacts', 'screenshots', 'docs',
                 '.git', '__pycache__', 'node_modules'}
EXCLUDED_SUFFIXES = ('.py', '.md', '.pyc')
LATIN_NAME = re.compile(r'^[A-Za-z0-9._/-]+$')
ZIP_DATE = (1980, 1, 1, 0, 0, 0)

# (tag, attribute) pairs that load a resource
REF_ATTRS = {('script', 'src'), ('link', 'href'), ('img', 'src'),
             ('source', 'src'), ('audio', 'src'), ('video', 'src'),
             ('iframe', 'src'), ('embed', 'src'), ('object', 'data')}
# A quoted string literal that starts with a directory path
JS_PATH_LITERAL = re.compile(r'''['"`]([A-Za-z0-9_-]+/[A-Za-z0-9_./-]*)''')
# A quoted string literal that is a whole file path ('leveldata.js')
FILE_LITERAL = re.compile(r'''['"`]([A-Za-z0-9_-][A-Za-z0-9_./-]*\.[A-Za-z0-9]+)['"`]''')


def git(*args, root=ROOT):
    return subprocess.check_output(['git', '-C', str(root), *args],
                                   stderr=subprocess.PIPE)


class CommittedTree:
    """Read-only view of the files committed at a revision."""
    def __init__(self, rev='HEAD', root=ROOT):
        self.root = root
        self.revision = git('rev-parse', '--verify', rev + '^{commit}', root=root).decode().strip()
        self.date = git('show', '-s', '--format=%cd', '--date=format:%Y%m%d',
                        self.revision, root=root).decode().strip()
        self.blobs = {}
        for entry in git('ls-tree', '-rz', self.revision, root=root).split(b'\0'):
            if not entry:
                continue
            meta, path = entry.split(b'\t', 1)
            _mode, kind, oid = meta.split()
            if kind == b'blob':
                self.blobs[path.decode('utf-8')] = oid.decode()

    def has(self, path):
        return path in self.blobs

    def read(self, path):
        if path not in self.blobs:
            raise FileNotFoundError(f'{path} is not committed at {self.revision}')
        return git('cat-file', 'blob', self.blobs[path], root=self.root)

    def build_id(self):
        return f'{self.revision[:12]}-{self.date}'


class RefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if (tag, name) in REF_ATTRS and value:
                self.refs.append((tag, name, value.strip()))


def html_references(html):
    """[(tag, attr, value)] for every resource reference in html."""
    parser = RefParser()
    parser.feed(html)
    return parser.refs


def local_references(html):
    """Local (relative) paths referenced by html, in document order."""
    paths = []
    for _, _, ref in html_references(html):
        parsed = urlparse(ref)
        if parsed.scheme or parsed.netloc or ref.startswith(('/', 'data:')):
            continue
        if parsed.path not in paths:
            paths.append(parsed.path)
    return paths


def external_references(html):
    return [ref for _, _, ref in html_references(html)
            if urlparse(ref).scheme in ('http', 'https') or ref.startswith('//')]


def script_assets(tree, scripts):
    """Committed files the given scripts load by path at run time.

    A quoted string literal of a shipped script that is a committed file path
    ('leveldata.js', loaded by mountain.js) ships that file; one that starts
    with a committed directory ('art/win-' + variant + '.svg', menu.js) ships
    the committed non-script files under that prefix. Scripts found this way
    are scanned too.
    """
    dirs = {p.split('/', 1)[0] + '/' for p in tree.blobs if '/' in p}
    assets, queue, seen = set(), list(scripts), set()
    while queue:
        script = queue.pop()
        if script in seen:
            continue
        seen.add(script)
        source = tree.read(script).decode('utf-8')
        for literal in FILE_LITERAL.findall(source):
            if tree.has(literal) and literal not in scripts and not refused(literal):
                assets.add(literal)
                if literal.endswith('.js'):
                    queue.append(literal)
        for literal in JS_PATH_LITERAL.findall(source):
            if tree.has(literal) or literal.split('/', 1)[0] + '/' not in dirs:
                continue
            for path in tree.blobs:
                if path.startswith(literal) and not path.endswith('.js') and not refused(path):
                    assets.add(path)
    return sorted(assets)


def sdk_first_in_head(html, tag):
    """html with tag inserted right before the first <script of <head>."""
    head = re.search(r'<head\b[^>]*>(.*?)</head>', html, re.S | re.I)
    if not head:
        raise ValueError('index.html has no <head>')
    first = re.search(r'^([ \t]*)<script\b', head.group(1), re.M | re.I)
    if not first:
        raise ValueError('index.html has no <script> in <head>')
    at = head.start(1) + first.start()
    return html[:at] + first.group(1) + tag + '\n' + html[at:]


def portal_html(html, portal):
    """index.html for the portal: SDK tag + portal backend after local.js (playgama: SDK tag first in <head>)."""
    if html.count(LOCAL_TAG) != 1:
        raise ValueError(f'index.html must load {LOCAL_TAG} exactly once')
    if html.count(ANALYTICS_TAG) != 1:
        raise ValueError(f'index.html must load {ANALYTICS_TAG} exactly once')
    if external_references(html):
        raise ValueError(f'index.html already has external references: {external_references(html)}')
    for other in PORTALS:
        if f'platform/backends/{other}.js' in html:
            raise ValueError(f'index.html already loads platform/backends/{other}.js')
    indent = re.search(r'^([ \t]*)' + re.escape(LOCAL_TAG), html, re.M).group(1)
    tags = [LOCAL_TAG]
    if SDK_TAGS[portal] and portal not in SDK_FIRST_IN_HEAD:
        tags.append(SDK_TAGS[portal])
    tags.append(BACKEND_TAG.format(portal=portal))
    html = html.replace(LOCAL_TAG, ('\n' + indent).join(tags))
    if portal in SDK_FIRST_IN_HEAD:
        html = sdk_first_in_head(html, SDK_TAGS[portal])
    if ANALYTICS_BACKENDS[portal] == GA_BACKEND:
        indent = re.search(r'^([ \t]*)' + re.escape(ANALYTICS_TAG), html, re.M).group(1)
        tags = [f'<script src = "{GA_SDK}"></script>', f'<script src = "{GA_BACKEND}"></script>']
        html = html.replace(ANALYTICS_TAG, ('\n' + indent).join(tags))
    return html


def js_string(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def portal_buildconfig(source, portal, build_id, y8_ids):
    """buildconfig.js with this build's BUILD_CONFIG line."""
    if len(CONFIG_LINE.findall(source)) != 1:
        raise ValueError('buildconfig.js must have exactly one "const BUILD_CONFIG = " line')
    modes = ', '.join(js_string(m) for m in MODES[portal])
    line = (f'const BUILD_CONFIG = {{platform: {js_string(portal)}, modes: [{modes}], '
            f'y8: {{appId: {js_string(y8_ids[0])}, gameId: {js_string(y8_ids[1])}}}, '
            f'build: {js_string(build_id)}}}')
    return CONFIG_LINE.sub(lambda _m: line, source)


def ga_backend(source, keys):
    """gameanalytics.js with the GA_KEYS line filled from (game key, secret key)."""
    if len(GA_KEYS_LINE.findall(source)) != 1:
        raise ValueError(f'{GA_BACKEND} must have exactly one "var GA_KEYS = " line')
    line = f'var GA_KEYS = {{gameKey: {js_string(keys[0])}, secretKey: {js_string(keys[1])}}}'
    return GA_KEYS_LINE.sub(lambda _m: line, source)


def refused(path):
    parts = path.split('/')
    return (any(part in EXCLUDED_DIRS for part in parts)
            or path.endswith(EXCLUDED_SUFFIXES) or not LATIN_NAME.match(path))


def source_files(tree):
    """{path: bytes}: the revision's own index.html, its local references and the files its scripts load."""
    html = tree.read('index.html').decode('utf-8')
    files = {'index.html': html.encode('utf-8')}
    refs = local_references(html)
    for path in refs:
        files[path] = tree.read(path)
    for path in script_assets(tree, [p for p in refs if p.endswith('.js')]):
        files[path] = tree.read(path)
    return files


def baked_caches(tree):
    """tools/release_bake.py's JSON for the revision (one headless boot per revision and process)."""
    if tree.revision not in _BAKES:
        site = Path(tempfile.mkdtemp(prefix='release-bake-'))
        try:
            for path, data in source_files(tree).items():
                (site / path).parent.mkdir(parents=True, exist_ok=True)
                (site / path).write_bytes(data)
            out = subprocess.run([sys.executable, str(BAKE_TOOL), str(site)], check=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
            _BAKES[tree.revision] = json.loads(out.stdout)
        except subprocess.CalledProcessError as error:
            raise SystemExit(f'build-time bake failed: {error.stderr.decode(errors="replace")[-2000:]}')
        finally:
            shutil.rmtree(site, ignore_errors=True)
    return _BAKES[tree.revision]


def baked_route_arrows_js(table):
    return ('// Generated by tools/build_release.py (tools/release_bake.py, TASK-891); do not edit.\n'
            '// Route arrow values of the level (render/routearrows.js ROUTE_ARROWS_BAKED).\n'
            'window.ROUTE_ARROWS_BAKED = ' + json.dumps(table, separators=(',', ':')) + '\n').encode('utf-8')


def with_baked_tag(html):
    if html.count(ROUTE_ARROWS_TAG) != 1:
        raise ValueError(f'index.html must load {ROUTE_ARROWS_TAG} exactly once')
    indent = re.search(r'^([ \t]*)' + re.escape(ROUTE_ARROWS_TAG), html, re.M).group(1)
    return html.replace(ROUTE_ARROWS_TAG, BAKED_ROUTE_ARROWS_TAG + '\n' + indent + ROUTE_ARROWS_TAG)


def bakes_route_arrows(tree):
    """True when the revision's render/routearrows.js reads the bake (TASK-891 on); older revisions build as before."""
    return tree.has('render/routearrows.js') and b'ROUTE_ARROWS_BAKED' in tree.read('render/routearrows.js')


def drops_other_modes(tree, portal):
    """True for a single-mode portal at a revision from TASK-894 on (its buildconfig.js names OTHER_MODE_SCRIPTS)."""
    return (MODES[portal] == ['grapple_over'] and tree.has('buildconfig.js')
            and b'OTHER_MODE_SCRIPTS' in tree.read('buildconfig.js'))


def without_other_mode_tags(html):
    """html with the OTHER_MODE_SCRIPTS tags removed and the stub script's tag at the first one's place."""
    for i, path in enumerate(OTHER_MODE_SCRIPTS):
        tag = f'<script src = "{path}"></script>'
        if html.count(tag) != 1:
            raise ValueError(f'index.html must load {tag} exactly once')
        at = html.index(tag)
        html = remove_span(html, at, at + len(tag),
                           [f'<script src = "{OTHER_MODE_STUBS}"></script>'] if i == 0 else None)
    return html


def other_mode_stubs(sources):
    """other-mode-stubs.js for {path: source} of OTHER_MODE_SCRIPTS: each top-level class and function, empty.

    Grapple Over never creates an object of these classes or calls these
    functions, but its code names them: instanceof tests (render/effects.js,
    sprites/ninja.js, respawn.js), index.html's resize (new ElementsFactory).
    A stub class answers instanceof false, as the real class does when none of
    its objects exists; constructing one (except CONSTRUCTED_STUBS) or calling
    a stub function throws, so a missed use shows as a page error. Top-level
    constants and lets are not stubbed: nothing outside these files uses them.
    """
    lines = ['// Generated by tools/build_release.py (TASK-894); do not edit.',
             '// Single-mode build: ' + ', '.join(sources) + ' (bad and classic modes only)',
             '// are left out. Their names stay declared; using one throws.',
             "function otherModeOnly(name) {throw new Error(name + ' is not in this single-mode build')}"]
    for path, source in sources.items():
        for kind, name in STUB_DECLARATION.findall(source):
            if kind == 'function':
                lines.append(f"function {name}() {{otherModeOnly('{name}')}}")
            elif name in CONSTRUCTED_STUBS:
                lines.append(f'class {name} {{}}')
            else:
                lines.append(f"class {name} {{constructor() {{otherModeOnly('{name}')}}}}")
    return ('\n'.join(lines) + '\n').encode('utf-8')


def runtime_files(tree, portal, y8_ids, ga_keys=('', ''), bundle=True):
    """{path: bytes} of the portal build (bundle=False: the per-script files before bundle_scripts)."""
    html = portal_html(tree.read('index.html').decode('utf-8'), portal)
    baked = bakes_route_arrows(tree)
    if baked:
        html = with_baked_tag(html)
    stubbed = drops_other_modes(tree, portal)
    if stubbed:
        html = without_other_mode_tags(html)
    files = {'index.html': html.encode('utf-8')}
    refs = local_references(html)
    for path in refs:
        if path not in GENERATED_FILES:
            files[path] = tree.read(path)
    if baked:
        files[BAKED_ROUTE_ARROWS] = baked_route_arrows_js(baked_caches(tree)['route_arrows'])
    if stubbed:
        files[OTHER_MODE_STUBS] = other_mode_stubs({p: tree.read(p).decode('utf-8') for p in OTHER_MODE_SCRIPTS})
    scripts = [p for p in refs if p.endswith('.js') and p not in GENERATED_FILES]
    for path in script_assets(tree, scripts):
        files[path] = tree.read(path)
    files['buildconfig.js'] = portal_buildconfig(
        files['buildconfig.js'].decode('utf-8'), portal, tree.build_id(), y8_ids).encode('utf-8')
    if GA_BACKEND in files:
        files[GA_BACKEND] = ga_backend(files[GA_BACKEND].decode('utf-8'), ga_keys).encode('utf-8')
        files[GA_LICENSE] = tree.read(GA_LICENSE)
    bad = sorted(p for p in files if refused(p))
    if bad:
        raise ValueError(f'refused paths in the {portal} build: {bad}')
    return bundle_scripts(files) if bundle and bundles_scripts(tree) else files


def bundles_scripts(tree):
    """Revisions from TASK-893 on bundle (their visualsperf.js maps bundle lines); older ones build as before."""
    return (tree.has('render/visualsperf.js')
            and b'GAME_BUNDLE_FILES' in tree.read('render/visualsperf.js'))


def esbuild_binary():
    binary = os.environ.get('ESBUILD') or str(ESBUILD)
    if not os.access(binary, os.X_OK):
        raise SystemExit(f'no esbuild at {binary} (tools/vendor/esbuild/README.txt; ESBUILD=path overrides)')
    return binary


def minify_whitespace(sources):
    """[str] -> [str]: esbuild --minify-whitespace of each source (no renaming, no syntax rewrites)."""
    if not sources:
        return []
    work = Path(tempfile.mkdtemp(prefix='release-minify-'))
    try:
        names = [f'part{i:03d}.js' for i in range(len(sources))]
        (work / 'in').mkdir()
        for name, source in zip(names, sources):
            (work / 'in' / name).write_text(source, encoding='utf-8')
        out = subprocess.run([esbuild_binary(), *names, '--minify-whitespace', '--charset=utf8',
                              '--legal-comments=none', '--log-level=error', '--outdir=../out'],
                             cwd=work / 'in', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if out.returncode:
            raise ValueError('esbuild failed: ' + out.stderr.decode(errors='replace')[-2000:])
        return [(work / 'out' / name).read_text(encoding='utf-8') for name in names]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def remove_span(html, start, end, replacement=None):
    """html without [start, end) - the whole line when the element is alone on it - or with replacement lines there."""
    line_start = html.rfind('\n', 0, start) + 1
    line_end = html.find('\n', end)
    line_end = len(html) if line_end < 0 else line_end
    alone = not html[line_start:start].strip() and not html[end:line_end].strip()
    if replacement is None:
        return html[:line_start] + html[line_end + 1:] if alone else html[:start] + html[end:]
    indent = html[line_start:start] if alone else ''
    text = ('\n' + indent).join(replacement)
    return html[:line_start] + indent + text + html[line_end:] if alone else html[:start] + text + html[end:]


def bundle_scripts(files):
    """files with the game's local <script src> files (and the inline scripts between them) as ONE bundle.

    The bundle is the scripts in index.html order, each whitespace-minified
    by esbuild (VERBATIM_PARTS as written), separated by ';' lines; its tag
    takes the place of the last bundled tag. Inline scripts between the first
    and the last bundled tag are folded in at their place (I18N.applyDom());
    the other tags there (portal SDK, vendored GameAnalytics SDK) move right
    before the bundle tag, in their order. Line 1 is
    window.GAME_BUNDLE_FILES = [[first line, path, sha256[:16] of the source], ...]
    (render/visualsperf.js maps stack lines back to the source file with it).
    """
    html = files['index.html'].decode('utf-8')
    elements = []
    for m in SCRIPT_ELEMENT.finditer(html):
        src = SCRIPT_SRC.search(m.group(1))
        src = src.group(2).strip() if src else None
        local = bool(src) and not urlparse(src).scheme and not src.startswith('//')
        deferred = re.search(r'\b(async|defer|type)\b', m.group(1), re.I)
        elements.append({'span': m.span(), 'src': src, 'code': m.group(2),
                         'bundled': local and src not in UNBUNDLED_SCRIPTS and not deferred})
    indexes = [i for i, e in enumerate(elements) if e['bundled']]
    if not indexes:
        raise ValueError('index.html has no local script to bundle')
    first, last = indexes[0], indexes[-1]
    parts, moved = [], []
    for e in elements[first:last + 1]:
        if e['bundled']:
            parts.append((e['src'], files[e['src']].decode('utf-8')))
        elif e['src'] is None:
            parts.append((f'index.html#inline{len(parts)}', e['code']))
        else:
            moved.append(html[e['span'][0]:e['span'][1]])
    for path, code in parts:
        if USE_STRICT.match(code):
            raise ValueError(f'{path} starts with "use strict": it would change the whole bundle')
    minified = iter(minify_whitespace([code for path, code in parts if path not in VERBATIM_PARTS]))
    data = assemble_bundle([(path, code if path in VERBATIM_PARTS else next(minified),
                             sha256(code.encode('utf-8'))[:16]) for path, code in parts])
    name = f'game-{sha256(data)[:12]}.js'
    for i in range(len(elements) - 1, -1, -1):
        e = elements[i]
        if i == last:
            html = remove_span(html, *e['span'], moved + [f'<script src = "{name}"></script>'])
        elif first <= i < last:
            html = remove_span(html, *e['span'])
    out = {p: b for p, b in files.items() if p not in {path for path, _ in parts}}
    out['index.html'] = html.encode('utf-8')
    out[name] = data
    return out


def assemble_bundle(chunks):
    """Bundle bytes of [(path, chunk text, source sha16)]: the table line, then each chunk and a ';' line."""
    table, line, body = [], 2, []
    for path, chunk, sha in chunks:
        chunk = chunk.rstrip('\n')
        table.append([line, path, sha])
        body.append(chunk + '\n;\n')
        line += chunk.count('\n') + 2
    return (BUNDLE_TABLE + json.dumps(table, separators=(',', ':')) + '\n' + ''.join(body)).encode('utf-8')


def bundle_path(files):
    """The bundle's path among a build's files (None before TASK-893)."""
    names = [p for p in files if BUNDLE_NAME.match(p)]
    if len(names) > 1:
        raise ValueError(f'more than one bundle: {names}')
    return names[0] if names else None


def bundle_table(data):
    """[{line, path, sha16}] of a bundle's GAME_BUNDLE_FILES line."""
    first = data.decode('utf-8').split('\n', 1)[0]
    if not first.startswith(BUNDLE_TABLE):
        raise ValueError('not a game bundle')
    return [{'line': line, 'path': path, 'sha16': sha} for line, path, sha in json.loads(first[len(BUNDLE_TABLE):])]


def bundle_parts(files):
    """{path: chunk bytes} of the build's bundle in load order (a VERBATIM_PARTS chunk is the
    rewritten file as written, without its last newline; the others are whitespace-minified)."""
    name = bundle_path(files)
    lines = files[name].decode('utf-8').split('\n')
    table = bundle_table(files[name])
    parts = {}
    for i, row in enumerate(table):
        end = table[i + 1]['line'] - 1 if i + 1 < len(table) else len(lines) - 1
        parts[row['path']] = '\n'.join(lines[row['line'] - 1:end - 1]).encode('utf-8')
    return parts


def bundle_part(files, path):
    """bytes of one part of the build's bundle (see bundle_parts)."""
    parts = bundle_parts(files)
    if path not in parts:
        raise KeyError(f'{path} is not in {bundle_path(files)}')
    return parts[path]


def stale_parts(files, read, rewritten=VERBATIM_PARTS):
    """Bundle parts whose source differs from read(path) (bytes or None); inline and rewritten parts skipped."""
    stale = []
    for row in bundle_table(files[bundle_path(files)]):
        if row['path'].startswith('index.html#') or row['path'] in rewritten:
            continue
        data = read(row['path'])
        if data is None or sha256(data)[:16] != row['sha16']:
            stale.append(row['path'])
    return stale


def replace_part(files, path, source):
    """Bundle bytes with part path's chunk replaced by source (str, used verbatim) - for tests."""
    parts = bundle_parts(files)
    if path not in parts:
        raise KeyError(path)
    table = {row['path']: row['sha16'] for row in bundle_table(files[bundle_path(files)])}
    return assemble_bundle([(p, source if p == path else chunk.decode('utf-8'),
                             sha256(source.encode('utf-8'))[:16] if p == path else table[p])
                            for p, chunk in parts.items()])


def bundle_info(files):
    """Manifest entry of the bundle: path, raw and gzip bytes, its parts."""
    name = bundle_path(files)
    if not name:
        return None
    data = files[name]
    return {'path': name, 'bytes': len(data), 'gzip_bytes': len(gzip.compress(data, 9, mtime=0)),
            'parts': [row['path'] for row in bundle_table(data)]}


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path, ZIP_DATE)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def y8_ids_for(portal, env):
    if portal != 'y8':
        return '', ''
    app_id, game_id = env.get('Y8_APP_ID', '').strip(), env.get('Y8_GAME_ID', '').strip()
    if not app_id or not game_id:
        raise SystemExit('y8 build needs Y8_APP_ID and Y8_GAME_ID in the environment '
                         '(set -a; . /root/credentials/grapnelninja/credentials.env; set +a)')
    return app_id, game_id


def ga_keys_for(portal, env):
    if ANALYTICS_BACKENDS[portal] != GA_BACKEND:
        return '', ''
    keys = []
    for name in ('GA_GAME_KEY', 'GA_SECRET_KEY'):
        value = env.get(name, '').strip()
        if not value:
            raise SystemExit(f'{portal} build needs GA_GAME_KEY and GA_SECRET_KEY in the environment '
                             '(set -a; . /root/credentials/grapnelninja/credentials.env; set +a)')
        if not GA_KEY_FORMAT[name].match(value):
            raise SystemExit(f'{name} does not look like a GameAnalytics key (value not printed)')
        keys.append(value)
    return tuple(keys)


def build(portal, out=DEFAULT_OUT, rev='HEAD', env=None, tree=None):
    """Write out/<portal>/grapple-over-<portal>.zip + manifest.json; return the manifest."""
    if portal not in PORTALS:
        raise ValueError(f'unknown portal {portal!r}')
    env = os.environ if env is None else env
    tree = tree or CommittedTree(rev)
    files = runtime_files(tree, portal, y8_ids_for(portal, env), ga_keys_for(portal, env))
    data = archive(files)
    folder = Path(out) / portal
    folder.mkdir(parents=True, exist_ok=True)
    zip_path = folder / f'grapple-over-{portal}.zip'
    zip_path.write_bytes(data)
    manifest = {
        'portal': portal,
        'build_id': tree.build_id(),
        'revision': tree.revision,
        'source': 'git blobs at revision (same as a clean checkout)',
        'modes': MODES[portal],
        'platform_backend': f'platform/backends/{portal}.js',
        'sdk_tag': SDK_TAGS[portal],
        'analytics_backend': ANALYTICS_BACKENDS[portal],
        'analytics_keys_injected': ANALYTICS_BACKENDS[portal] == GA_BACKEND,
        'baked': ({BAKED_ROUTE_ARROWS: {'arrows': len(baked_caches(tree)['route_arrows']['arrows']),
                                        'layoutId': baked_caches(tree)['route_arrows']['layoutId']}}
                  if bakes_route_arrows(tree) else {}),
        'bundle': bundle_info(files),
        'zip': zip_path.name,
        'zip_size': len(data),
        'zip_sha256': sha256(data),
        'file_count': len(files),
        'total_size': sum(len(b) for b in files.values()),
        'files': [{'path': p, 'size': len(b), 'sha256': sha256(b)}
                  for p, b in sorted(files.items())],
    }
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--portal', required=True, choices=PORTALS + ('all',))
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                        help='output root; the build goes to OUT/<portal>/ (default %(default)s)')
    parser.add_argument('--rev', default='HEAD', help='committed revision to build (default HEAD)')
    args = parser.parse_args(argv)
    tree = CommittedTree(args.rev)
    for portal in PORTALS if args.portal == 'all' else (args.portal,):
        m = build(portal, args.out, tree=tree)
        print(f'PASS {portal}: {Path(args.out) / portal / m["zip"]} build={m["build_id"]} '
              f'files={m["file_count"]} bytes={m["zip_size"]} sha256={m["zip_sha256"]} '
              f'modes={m["modes"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
