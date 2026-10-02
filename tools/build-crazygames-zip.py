"""Build the CrazyGames upload zip from an explicit allowlist.

The zip holds index.html at its root, the root *.js game files and the
collision/, elements/, render/ and sprites/ folders. Every local reference in
index.html must be relative and present in the zip; the only external URL
allowed is the CrazyGames SDK.

Usage: python3 tools/build-crazygames-zip.py [--out PATH] [--listing PATH]
                                             [--stats PATH] [--refs PATH]
"""
import argparse
import json
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'artifacts' / 'TASK-088' / 'grapnelninja-crazygames.zip'

ROOT_FILES = ['index.html']
ROOT_GLOBS = ['*.js']
FOLDERS = ['collision', 'elements', 'render', 'sprites']
FOLDER_SUFFIXES = {'.js'}
EXCLUDED = ['tools', 'artifacts', 'screenshots', 'prompts.md', 'AGENTS.md',
            'README.md', '.git', '__pycache__']
SDK_URL = 'https://sdk.crazygames.com/crazygames-sdk-v3.js'
MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 1500

# (tag, attribute) pairs that load a resource
REF_ATTRS = {('script', 'src'), ('link', 'href'), ('img', 'src'),
             ('source', 'src'), ('audio', 'src'), ('video', 'src'),
             ('iframe', 'src'), ('embed', 'src'), ('object', 'data')}


def allowlisted_files(root=ROOT):
    """Return sorted zip paths (posix, relative to root) of the allowlist."""
    paths = set()
    for name in ROOT_FILES:
        paths.add(name)
    for pattern in ROOT_GLOBS:
        paths.update(p.name for p in root.glob(pattern) if p.is_file())
    for folder in FOLDERS:
        for p in (root / folder).rglob('*'):
            if p.is_file() and p.suffix in FOLDER_SUFFIXES \
                    and '__pycache__' not in p.parts:
                paths.add(p.relative_to(root).as_posix())
    return sorted(paths)


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
            lines.append(f'{tag} {attr}={ref}: external (CrazyGames SDK, allowed)')
        elif parsed.scheme or parsed.netloc:
            errors.append(f'{tag} {attr}={ref}: non-relative URL')
        elif ref.startswith('/'):
            errors.append(f'{tag} {attr}={ref}: absolute path')
        elif parsed.path not in names:
            errors.append(f'{tag} {attr}={ref}: missing from the zip')
        else:
            lines.append(f'{tag} {attr}={ref}: present, relative')
    return lines, errors


def excluded_hits(zip_paths):
    return [p for p in zip_paths
            if any(part in EXCLUDED for part in p.split('/'))]


def build(out, root=ROOT):
    """Write the zip; return (zip_paths, ref_lines). Raises SystemExit on errors."""
    zip_paths = allowlisted_files(root)
    missing = [p for p in zip_paths if not (root / p).is_file()]
    if missing:
        raise SystemExit(f'missing allowlisted files: {missing}')
    hits = excluded_hits(zip_paths)
    if hits:
        raise SystemExit(f'excluded paths in the allowlist: {hits}')
    html = (root / 'index.html').read_text(encoding='utf-8')
    ref_lines, ref_errors = check_references(html, zip_paths)
    if ref_errors:
        raise SystemExit('bad index.html references:\n' + '\n'.join(ref_errors))

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in zip_paths:
            zf.write(root / path, path)
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
    if not all(stats['checks'].values()):
        print('FAIL')
        return 1
    print('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
