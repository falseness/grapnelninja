"""Build the Y8 upload zip from an explicit allowlist.

The zip holds only the explicit runtime inventory below, read from HEAD.
Selected working-tree and index files must match that committed revision. Every local reference in
index.html must be relative and present in the zip; the only external URL
allowed is the Y8 SDK. The build fails unless y8config.js holds a real
appId (24 hex chars) and gameId (digits).

Usage: python3 tools/build-y8-zip.py [--out PATH] [--listing PATH]
                                     [--stats PATH] [--refs PATH]
"""
import argparse
import json
import re
import sys
import subprocess
import hashlib
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'artifacts' / 'y8-release' / 'grapnelninja-y8.zip'

# Add runtime resources deliberately; filesystem globs are not release inputs.
RUNTIME_FILES = [
    'collision/broadphase.js',
    'collision/circlewithcircle.js',
    'collision/circlewithline.js',
    'collision/linewithline.js',
    'elements/factory.js',
    'events.js',
    'gameoptions.js',
    'i18n.js',
    'index.html',
    'languagebutton.js',
    'menu.js',
    'moveScreen.js',
    'physics.js',
    'platform.js',
    'progress.js',
    'render/culling.js',
    'render/draw.js',
    'render/effects.js',
    'render/glowsprites.js',
    'respawn.js',
    'sprites/element.js',
    'sprites/empty.js',
    'sprites/floor.js',
    'sprites/grapnel.js',
    'sprites/jumpingcube.js',
    'sprites/leftwall.js',
    'sprites/ninja.js',
    'sprites/rect.js',
    'sprites/scoretext.js',
    'sprites/side.js',
    'sprites/trampoline.js',
    'sprites/triangle.js',
    'style.js',
    'y8config.js',
]
FOLDERS = ['collision', 'elements', 'render', 'sprites']
EXCLUDED = ['tools', 'artifacts', 'screenshots', 'prompts.md', 'AGENTS.md',
            'README.md', '.git', '__pycache__']
SDK_URL = 'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js'
CONFIG_FILE = 'y8config.js'
ID_PATTERNS = {'appId': re.compile(r'^[0-9a-f]{24}$'),
               'gameId': re.compile(r'^[0-9]+$')}
MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 1500

# (tag, attribute) pairs that load a resource
REF_ATTRS = {('script', 'src'), ('link', 'href'), ('img', 'src'),
             ('source', 'src'), ('audio', 'src'), ('video', 'src'),
             ('iframe', 'src'), ('embed', 'src'), ('object', 'data')}


def allowlisted_files(root=ROOT):
    """Explicit runtime paths; unrelated tracked/untracked files cannot enter."""
    return list(RUNTIME_FILES)


def git(root, *args):
    try:
        return subprocess.check_output(['git', '-C', str(root), *args],
                                       stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise SystemExit('committed Git source required: ' +
                         exc.stderr.decode(errors='replace')) from exc


def committed_source(root):
    """Validate source identity, then read immutable Git blobs, never symlinks."""
    root = root.resolve()
    if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()) != root:
        raise SystemExit('source must be a Git repository root')
    revision = git(root, 'rev-parse', 'HEAD').decode().strip()
    entries = {}
    for entry in git(root, 'ls-tree', '-rz', revision).split(b'\0'):
        if entry:
            meta, name = entry.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            entries[name.decode()] = (mode, kind, oid)
    data = {}
    for name in RUNTIME_FILES:
        if name not in entries:
            raise SystemExit(f'missing committed runtime file: {name}')
        mode, kind, oid = entries[name]
        if mode not in ('100644', '100755') or kind != 'blob':
            raise SystemExit(f'unsafe committed runtime path: {name}')
        path = root / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != root):
            raise SystemExit(f'unsafe symlink runtime path: {name}')
        blob = git(root, 'cat-file', 'blob', oid)
        if not path.is_file() or path.read_bytes() != blob:
            raise SystemExit(f'uncommitted runtime changes: {name}')
        data[name] = blob
    if git(root, 'diff', '--cached', revision, '--', *RUNTIME_FILES):
        raise SystemExit('uncommitted runtime changes in index')
    return revision, data


class RefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if (tag, name) in REF_ATTRS and value:
                self.refs.append((tag, name, value.strip()))


def html_references(html):
    parser = RefParser()
    parser.feed(html)
    return parser.refs


def check_references(html, zip_paths):
    """Return (lines, errors) for every resource reference in index.html."""
    lines, errors = [], []
    names = set(zip_paths)
    for tag, attr, ref in html_references(html):
        parsed = urlparse(ref)
        if ref == SDK_URL:
            lines.append(f'{tag} {attr}={ref}: external (Y8 SDK, allowed)')
        elif parsed.scheme or parsed.netloc:
            errors.append(f'{tag} {attr}={ref}: non-relative URL')
        elif ref.startswith('/'):
            errors.append(f'{tag} {attr}={ref}: absolute path')
        elif parsed.path not in names:
            errors.append(f'{tag} {attr}={ref}: missing from the zip')
        else:
            lines.append(f'{tag} {attr}={ref}: present, relative')
    return lines, errors


def check_y8_config(js):
    """Return errors for missing, empty or placeholder IDs in y8config.js."""
    errors = []
    for key, pattern in ID_PATTERNS.items():
        m = re.search(r'\b%s\s*:\s*([\'"])(.*?)\1' % key, js)
        if not m:
            errors.append(f'{key}: missing')
        elif not pattern.fullmatch(m.group(2)):
            errors.append(f'{key}: {m.group(2)!r} does not match {pattern.pattern}')
    return errors


def excluded_hits(zip_paths):
    return [p for p in zip_paths
            if any(part in EXCLUDED for part in p.split('/'))]


def build(out, root=ROOT):
    """Write the zip; return (zip_paths, ref_lines). Raises SystemExit on errors."""
    revision, data = committed_source(root)
    zip_paths = sorted(data)
    id_errors = check_y8_config(data[CONFIG_FILE].decode('utf-8'))
    if id_errors:
        raise SystemExit(f'bad {CONFIG_FILE}:\n' + '\n'.join(id_errors))
    html = data['index.html'].decode('utf-8')
    if not re.search(r'<meta\s+charset=[\'"]utf-8[\'"]', html, re.I):
        raise SystemExit('index.html requires UTF-8 declaration')
    ref_lines, ref_errors = check_references(html, zip_paths)
    if ref_errors:
        raise SystemExit('bad index.html references:\n' + '\n'.join(ref_errors))

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in zip_paths:
            info = zipfile.ZipInfo(path, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, data[path])
    tmp.replace(out)
    return zip_paths, ref_lines


def zip_report(out):
    """Assert the written zip; return (listing lines, stats)."""
    with zipfile.ZipFile(out) as zf:
        infos = zf.infolist()
    names = [i.filename for i in infos]
    listing = [f'{i.file_size:>9} {i.compress_size:>9} {i.filename}' for i in infos]
    stats = {
        'zip': str(out),
        'file_count': len(infos),
        'uncompressed_bytes': sum(i.file_size for i in infos),
        'zip_bytes': out.stat().st_size,
        'max_bytes': MAX_BYTES,
        'max_files': MAX_FILES,
    }
    checks = [
        ('index.html at the zip root', 'index.html' in names),
        ('only allowlisted paths', set(names) == set(allowlisted_files())),
        ('no excluded names (' + ', '.join(EXCLUDED) + ')', not excluded_hits(names)),
        (f'zip size {stats["zip_bytes"]} <= {MAX_BYTES}', stats['zip_bytes'] <= MAX_BYTES),
        (f'file count {len(infos)} <= {MAX_FILES}', len(infos) <= MAX_FILES),
    ]
    stats['checks'] = {name: ok for name, ok in checks}
    return listing, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--listing', type=Path)
    ap.add_argument('--stats', type=Path)
    ap.add_argument('--refs', type=Path)
    ap.add_argument('--inventory', type=Path, help='committed source and ZIP identity')
    args = ap.parse_args(argv)

    zip_paths, ref_lines = build(args.out)
    print(f'wrote {args.out} ({len(zip_paths)} files)')
    for line in ref_lines:
        print('ref', line)
    listing, stats = zip_report(args.out)
    for name, ok in stats['checks'].items():
        print(f'assert {name}: {"PASS" if ok else "FAIL"}')
    if args.listing:
        args.listing.write_text('\n'.join(listing) + '\n')
    if args.stats:
        args.stats.write_text(json.dumps(stats, indent=2) + '\n')
    if args.refs:
        args.refs.write_text('\n'.join(ref_lines) + '\n')
    if args.inventory:
        revision, data = committed_source(ROOT)
        with zipfile.ZipFile(args.out) as archive:
            if any(archive.read(p) != data[p] for p in zip_paths):
                raise SystemExit('source changed during build')
        args.inventory.write_text(json.dumps({
            'source_revision': revision,
            'zip': str(args.out.resolve()),
            'byte_size': args.out.stat().st_size,
            'sha256': hashlib.sha256(args.out.read_bytes()).hexdigest(),
            'external_dependencies': [SDK_URL],
            'files': [{'path': p, 'byte_size': len(data[p]),
                       'sha256': hashlib.sha256(data[p]).hexdigest()}
                      for p in zip_paths],
        }, indent=2) + '\n')
    if not all(stats['checks'].values()):
        print('FAIL')
        return 1
    print('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
