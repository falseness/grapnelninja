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
  file is the build's platform backend. The analytics backend stays
  analytics/backends/none.js.
- buildconfig.js is rewritten: platform, modes (['grapple_over'] for itch,
  gamepix and y8; every mode for playgama), y8 ids (Y8_APP_ID / Y8_GAME_ID
  from the environment, y8 only; required there) and build (the build id,
  '<12-char commit sha>-<commit date YYYYMMDD>').
- manifest.json: portal, build id, revision, modes, zip size and sha256,
  and the per-file list (path, size, sha256). Credential values never go in
  the manifest or the build output, only into the y8 zip's buildconfig.js.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
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
ANALYTICS_TAG = '<script src = "analytics/backends/none.js"></script>'
MODES = {'itch': ['grapple_over'], 'gamepix': ['grapple_over'],
         'y8': ['grapple_over'], 'playgama': ALL_MODES}
CONFIG_LINE = re.compile(r'^const BUILD_CONFIG = .*$', re.M)

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


def portal_html(html, portal):
    """index.html for the portal: SDK tag + portal backend after local.js."""
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
    if SDK_TAGS[portal]:
        tags.append(SDK_TAGS[portal])
    tags.append(BACKEND_TAG.format(portal=portal))
    return html.replace(LOCAL_TAG, ('\n' + indent).join(tags))


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


def refused(path):
    parts = path.split('/')
    return (any(part in EXCLUDED_DIRS for part in parts)
            or path.endswith(EXCLUDED_SUFFIXES) or not LATIN_NAME.match(path))


def runtime_files(tree, portal, y8_ids):
    """{path: bytes} of the portal build."""
    html = portal_html(tree.read('index.html').decode('utf-8'), portal)
    files = {'index.html': html.encode('utf-8')}
    refs = local_references(html)
    for path in refs:
        files[path] = tree.read(path)
    scripts = [p for p in refs if p.endswith('.js')]
    for path in script_assets(tree, scripts):
        files[path] = tree.read(path)
    files['buildconfig.js'] = portal_buildconfig(
        files['buildconfig.js'].decode('utf-8'), portal, tree.build_id(), y8_ids).encode('utf-8')
    bad = sorted(p for p in files if refused(p))
    if bad:
        raise ValueError(f'refused paths in the {portal} build: {bad}')
    return files


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


def build(portal, out=DEFAULT_OUT, rev='HEAD', env=None, tree=None):
    """Write out/<portal>/grapple-over-<portal>.zip + manifest.json; return the manifest."""
    if portal not in PORTALS:
        raise ValueError(f'unknown portal {portal!r}')
    env = os.environ if env is None else env
    tree = tree or CommittedTree(rev)
    files = runtime_files(tree, portal, y8_ids_for(portal, env))
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
        'analytics_backend': 'analytics/backends/none.js',
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
