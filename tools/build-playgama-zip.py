"""Build the Playgama upload zip from an explicit allowlist.

The zip holds index.html and playgama-bridge-config.json at its root, the
root *.js game files and the collision/, elements/, render/ and sprites/
folders. Only .html/.js/.json files with Latin names go in. Every local
reference in index.html must be relative and present in the zip; the only
external URL allowed is the Playgama Bridge CDN, and it must be the first
<head> script. No analytics hosts may appear in any zipped file.

Usage: python3 tools/build-playgama-zip.py [--out PATH] [--listing PATH]
                                           [--stats PATH] [--refs PATH]
"""
import argparse
import json
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'artifacts' / 'TASK-128' / 'grapnelninja-playgama.zip'

CONFIG_FILE = 'playgama-bridge-config.json'
ROOT_FILES = ['index.html', CONFIG_FILE]
ROOT_GLOBS = ['*.js']
FOLDERS = ['collision', 'elements', 'render', 'sprites']
FOLDER_SUFFIXES = {'.js'}
ALLOWED_SUFFIXES = {'.html', '.js', '.json'}
EXCLUDED = ['tools', 'artifacts', 'screenshots', 'prompts.md', 'AGENTS.md',
            'README.md', '.git', '__pycache__']
EXCLUDED_SUFFIXES = {'.py', '.md'}
SDK_URL = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'
LATIN_NAME = re.compile(r'^[A-Za-z0-9._/-]+$')
ANALYTICS = re.compile(r'googletagmanager|google-analytics|\bgtag\b|'
                       r'mc\.yandex|metrika', re.IGNORECASE)
MAX_BYTES = 300 * 1024 * 1024
MAX_FILES = 500

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
        self.head_scripts = []
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        elif tag == 'script' and self.in_head:
            self.head_scripts.append(dict(attrs).get('src') or '')
        for name, value in attrs:
            if (tag, name) in REF_ATTRS and value:
                self.refs.append((tag, name, value.strip()))

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


def parse_html(html):
    parser = RefParser()
    parser.feed(html)
    return parser


def html_references(html):
    return parse_html(html).refs


def check_references(html, zip_paths):
    """Return (lines, errors) for every resource reference in index.html."""
    lines, errors = [], []
    names = set(zip_paths)
    parser = parse_html(html)
    for tag, attr, ref in parser.refs:
        parsed = urlparse(ref)
        if ref == SDK_URL:
            lines.append(f'{tag} {attr}={ref}: external (Playgama Bridge CDN, allowed)')
        elif parsed.scheme or parsed.netloc:
            errors.append(f'{tag} {attr}={ref}: non-relative URL')
        elif ref.startswith('/'):
            errors.append(f'{tag} {attr}={ref}: absolute path')
        elif parsed.path not in names:
            errors.append(f'{tag} {attr}={ref}: missing from the zip')
        else:
            lines.append(f'{tag} {attr}={ref}: present, relative')
    sdk_count = sum(1 for _, _, ref in parser.refs if ref == SDK_URL)
    if sdk_count != 1:
        errors.append(f'Bridge CDN script found {sdk_count} times, expected 1')
    elif not parser.head_scripts or parser.head_scripts[0] != SDK_URL:
        errors.append('Bridge CDN script is not the first <head> script')
    return lines, errors


def check_bridge_config(text):
    """Return errors if playgama-bridge-config.json is not a JSON object."""
    try:
        data = json.loads(text)
    except ValueError as e:
        return [f'{CONFIG_FILE}: invalid JSON ({e})']
    if not isinstance(data, dict):
        return [f'{CONFIG_FILE}: top level is not an object']
    return []


def excluded_hits(zip_paths):
    return [p for p in zip_paths
            if any(part in EXCLUDED for part in p.split('/'))
            or Path(p).suffix in EXCLUDED_SUFFIXES]


def bad_suffixes(zip_paths):
    return [p for p in zip_paths if Path(p).suffix not in ALLOWED_SUFFIXES]


def non_latin_names(zip_paths):
    return [p for p in zip_paths if not LATIN_NAME.fullmatch(p)]


def analytics_hits(texts):
    """texts: {path: text}. Return 'path: match' for every analytics host."""
    hits = []
    for path, text in sorted(texts.items()):
        for m in ANALYTICS.finditer(text):
            hits.append(f'{path}: {m.group(0)}')
    return hits


def run_checks(texts, sizes):
    """texts: {zip path: text}; sizes: {zip path: bytes}. Return [(name, errors)]."""
    names = sorted(texts)
    total = sum(sizes.values())
    html = texts.get('index.html', '')
    _, ref_errors = check_references(html, names)
    config = texts.get(CONFIG_FILE)
    return [
        ('index.html at the zip root', [] if 'index.html' in texts else ['index.html missing']),
        (f'{CONFIG_FILE} present and valid JSON',
         check_bridge_config(config) if config is not None else [f'{CONFIG_FILE} missing']),
        ('only .html/.js/.json files', bad_suffixes(names)),
        ('no excluded names (' + ', '.join(EXCLUDED) + ', *.py, *.md)', excluded_hits(names)),
        ('Latin file names [A-Za-z0-9._/-]', non_latin_names(names)),
        ('every index.html reference is in the zip; only external = Bridge CDN, first <head> script',
         ref_errors),
        ('no analytics hosts', analytics_hits(texts)),
        (f'total size {total} < {MAX_BYTES}', [] if total < MAX_BYTES else [f'{total} bytes']),
        (f'file count {len(names)} < {MAX_FILES}', [] if len(names) < MAX_FILES else [f'{len(names)} files']),
    ]


def build(out, root=ROOT):
    """Write the zip; return (zip_paths, ref_lines). Raises SystemExit on errors."""
    zip_paths = allowlisted_files(root)
    missing = [p for p in zip_paths if not (root / p).is_file()]
    if missing:
        raise SystemExit(f'missing allowlisted files: {missing}')
    texts = {p: (root / p).read_text(encoding='utf-8') for p in zip_paths}
    sizes = {p: (root / p).stat().st_size for p in zip_paths}
    failed = [f'{name}: {errors}' for name, errors in run_checks(texts, sizes) if errors]
    if failed:
        raise SystemExit('build checks failed:\n' + '\n'.join(failed))
    ref_lines, _ = check_references(texts['index.html'], zip_paths)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in zip_paths:
            zf.write(root / path, path)
    tmp.replace(out)
    return zip_paths, ref_lines


def zip_report(out, root=ROOT):
    """Re-check the written zip; return (listing lines, stats)."""
    with zipfile.ZipFile(out) as zf:
        infos = zf.infolist()
        texts = {i.filename: zf.read(i).decode('utf-8') for i in infos}
    sizes = {i.filename: i.file_size for i in infos}
    listing = [f'{i.file_size:>9} {i.compress_size:>9} {i.filename}' for i in infos]
    stats = {
        'zip': str(out),
        'file_count': len(infos),
        'uncompressed_bytes': sum(sizes.values()),
        'zip_bytes': out.stat().st_size,
        'max_bytes': MAX_BYTES,
        'max_files': MAX_FILES,
    }
    checks = run_checks(texts, sizes)
    checks.append(('zip size %d < %d' % (stats['zip_bytes'], MAX_BYTES),
                   [] if stats['zip_bytes'] < MAX_BYTES else ['too big']))
    checks.append(('only allowlisted paths',
                   [] if set(texts) == set(allowlisted_files(root)) else ['allowlist mismatch']))
    stats['checks'] = {name: 'FAIL' if errors else 'PASS' for name, errors in checks}
    stats['errors'] = {name: errors for name, errors in checks if errors}
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
    for name, result in stats['checks'].items():
        print(f'assert {name}: {result}')
    if args.listing:
        args.listing.write_text('\n'.join(listing) + '\n')
    if args.stats:
        args.stats.write_text(json.dumps(stats, indent=2) + '\n')
    if args.refs:
        args.refs.write_text('\n'.join(ref_lines) + '\n')
    if any(r != 'PASS' for r in stats['checks'].values()):
        print('FAIL')
        return 1
    print('OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
