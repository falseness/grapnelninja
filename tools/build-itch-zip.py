"""Build the itch.io HTML5 upload zip from the files tracked in git.

The file set starts at index.html and follows every resource reference:
<script src>, <link href>, <img>/<audio>/<source> src, CSS url(...) and
any quoted asset path string in the HTML and the JS. Files come from
`git show <rev>:<path>` (HEAD by default), never from the working tree.
The zip is deterministic: sorted entries, fixed timestamps and modes.

Every itch rule is checked (R-ids from artifacts/TASK-160/itch-requirements.md)
and a JSON report is printed; the exit code is non-zero on any failure.

Usage: python3 tools/build-itch-zip.py [--rev REV] [--out PATH] [--report PATH]
"""
import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / 'artifacts' / 'itch' / 'grapnelninja-itch.zip'

ENTRY = 'index.html'
MAX_FILES = 1000
MAX_PATH = 240
MAX_TOTAL = 500 * 1024 * 1024
MAX_FILE = 200 * 1024 * 1024
ZIP_TIME = (1980, 1, 1, 0, 0, 0)

EXCLUDED_DIRS = {'tools', 'artifacts', 'screenshots', '.agents'}
EXCLUDED_NAMES = {'AGENTS.md', 'prompts.md'}
EXCLUDED_SUFFIXES = {'.md', '.py'}

# (tag, attribute) pairs that load a resource
REF_ATTRS = {('script', 'src'), ('link', 'href'), ('img', 'src'),
             ('source', 'src'), ('audio', 'src'), ('video', 'src'),
             ('iframe', 'src'), ('embed', 'src'), ('object', 'data')}
ASSET_EXT = r'(?:png|jpe?g|gif|webp|svg|ico|mp3|ogg|wav|m4a|json|js|css|woff2?|ttf|html|txt|wasm)'
ASSET_STRING = re.compile(r'''(['"`])([^'"`\s<>]+\.''' + ASSET_EXT + r''')\1''')
CSS_URL = re.compile(r'''url\(\s*['"]?([^'")\s]+)['"]?\s*\)''')
# absolute URLs and protocol-relative //host strings (not // comments)
EXTERNAL = re.compile(r'''(?:https?|wss?)://|['"`(]\s*//[A-Za-z0-9-]+\.[A-Za-z]''')
TEXT_SUFFIXES = {'.html', '.js', '.css', '.json', '.svg', '.txt'}

RULES = {
    'R1': 'index.html at the zip root',
    'R2': 'archive is a .zip',
    'R3': f'at most {MAX_FILES} files',
    'R4': f'every path at most {MAX_PATH} characters',
    'R5': 'extracted total at most 500 MB',
    'R6': 'every file at most 200 MB',
    'R7': 'paths are UTF-8; every reference exists with the exact case',
    'R8': 'no absolute (/...) references',
    'R9': 'no folder (.../) references',
    'R10': 'no http:// and no external origin (fully offline)',
    'X1': 'no excluded files (tools/, artifacts/, screenshots/, .git*, .agents/, *.md, *.py)',
    'X2': 'zip entries are byte-equal to git show <rev>:<path>',
}


def git_tree(rev='HEAD', root=ROOT):
    """Return {path: bytes} for every file tracked at rev."""
    names = subprocess.run(['git', 'ls-tree', '-r', '-z', '--name-only', rev],
                           cwd=root, check=True, capture_output=True).stdout
    tree = {}
    for raw in names.split(b'\0'):
        if raw:
            path = raw.decode('utf-8', 'surrogateescape')
            tree[path] = git_show(rev, path, root)
    return tree


def git_show(rev, path, root=ROOT):
    return subprocess.run(['git', 'show', f'{rev}:{path}'], cwd=root,
                          check=True, capture_output=True).stdout


def is_excluded(path):
    parts = PurePosixPath(path).parts
    return (any(p in EXCLUDED_DIRS or p.startswith('.git') for p in parts)
            or parts[-1] in EXCLUDED_NAMES
            or PurePosixPath(path).suffix in EXCLUDED_SUFFIXES)


class RefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if (tag, name) in REF_ATTRS and value and value.strip():
                self.refs.append(value.strip())


def text_refs(path, text):
    """Return the raw reference strings found in one text file."""
    refs = []
    if path.endswith('.html'):
        parser = RefParser()
        parser.feed(text)
        refs += parser.refs
    refs += [m.group(2) for m in ASSET_STRING.finditer(text)]
    refs += CSS_URL.findall(text)
    return refs


def classify(ref, base):
    """Return (rule id, message) for a bad reference, or (None, resolved path)."""
    if ref.startswith(('data:', '#', 'blob:')):
        return None, None
    parts = urlsplit(ref)
    if parts.scheme or parts.netloc:
        return 'R10', f'{ref}: external URL'
    if ref.startswith('/'):
        return 'R8', f'{ref}: absolute path'
    if parts.path.endswith('/'):
        return 'R9', f'{ref}: folder reference'
    joined = PurePosixPath(base).parent / parts.path
    resolved = []
    for part in joined.parts:
        if part == '..':
            if not resolved:
                return 'R8', f'{ref}: escapes the zip root'
            resolved.pop()
        elif part != '.':
            resolved.append(part)
    return None, '/'.join(resolved)


def collect(tree):
    """Follow references from index.html. Return (files, refs log, errors)."""
    errors = []
    log = []
    lower = {}
    for path in tree:
        lower.setdefault(path.lower(), path)
    files, queue = [], []
    if ENTRY in tree:
        files.append(ENTRY)
        queue.append(ENTRY)
    else:
        errors.append(('R1', f'{ENTRY} missing from the tree root'))
    while queue:
        src = queue.pop(0)
        if PurePosixPath(src).suffix not in TEXT_SUFFIXES:
            continue
        text = tree[src].decode('utf-8', 'replace')
        for ref in text_refs(src, text):
            rule, value = classify(ref, src)
            if rule:
                errors.append((rule, f'{src}: {value}'))
                continue
            if value is None:
                continue
            if value not in tree:
                if value.lower() in lower:
                    errors.append(('R7', f'{src}: {ref}: case mismatch, tracked as '
                                         f'{lower[value.lower()]}'))
                else:
                    errors.append(('R7', f'{src}: {ref}: unresolved reference'))
                continue
            log.append(f'{src} -> {value}')
            if value not in files:
                files.append(value)
                queue.append(value)
    return sorted(files), log, errors


def external_hits(path, data):
    if PurePosixPath(path).suffix not in TEXT_SUFFIXES:
        return []
    text = data.decode('utf-8', 'replace')
    hits = []
    for no, line in enumerate(text.splitlines(), 1):
        for m in EXTERNAL.finditer(line):
            hits.append(('R10', f'{path}:{no}: {line.strip()[:120]}'))
    return hits


def file_errors(files, tree):
    errors = []
    for path in files:
        data = tree[path]
        if is_excluded(path):
            errors.append(('X1', f'{path}: excluded file'))
        if len(path) > MAX_PATH:
            errors.append(('R4', f'{path[:60]}...: {len(path)} characters'))
        try:
            path.encode('utf-8')
        except UnicodeEncodeError:
            errors.append(('R7', f'{path!r}: not valid UTF-8'))
        if len(data) > MAX_FILE:
            errors.append(('R6', f'{path}: {len(data)} bytes'))
        errors += external_hits(path, data)
    if len(files) > MAX_FILES:
        errors.append(('R3', f'{len(files)} files'))
    total = sum(len(tree[p]) for p in files)
    if total > MAX_TOTAL:
        errors.append(('R5', f'{total} bytes'))
    return errors


def write_zip(files, tree):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            zf.writestr(info, tree[path])
    return buf.getvalue()


def zip_errors(blob, tree):
    """Re-check the written zip itself (R1, R2, X2)."""
    errors = []
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        return [('R2', 'not a zip archive')]
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        if ENTRY not in names:
            errors.append(('R1', f'{ENTRY} is not at the zip root'))
        for name in names:
            if tree.get(name) != zf.read(name):
                errors.append(('X2', f'{name}: differs from the git blob'))
    return errors


def build(tree):
    """Return (zip bytes or None, report dict)."""
    files, log, errors = collect(tree)
    files = [p for p in files if p in tree]
    errors += file_errors(files, tree)
    blob = None
    if not errors:
        blob = write_zip(files, tree)
        errors += zip_errors(blob, tree)
    failed = {}
    for rule, msg in errors:
        failed.setdefault(rule, []).append(msg)
    report = {
        'checks': {rid: {'rule': name, 'status': 'FAIL' if rid in failed else 'PASS',
                         'errors': failed.get(rid, [])}
                   for rid, name in RULES.items()},
        'file_count': len(files),
        'total_bytes': sum(len(tree[p]) for p in files),
        'max_path_length': max((len(p) for p in files), default=0),
        'zip_bytes': len(blob) if blob else None,
        'files': files,
        'references': log,
        'ok': not failed,
    }
    return (blob if not failed else None), report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--rev', default='HEAD')
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--report', type=Path)
    args = ap.parse_args(argv)

    blob, report = build(git_tree(args.rev))
    report['rev'] = subprocess.run(['git', 'rev-parse', args.rev], cwd=ROOT, check=True,
                                   capture_output=True, text=True).stdout.strip()
    if blob:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(blob)
        report['zip'] = str(args.out)
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text + '\n')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
