"""Build a deterministic, runtime-only ZIP directly from a committed playgama2 tree."""
import argparse
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SDK_URL = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)
def sha(data):
    return hashlib.sha256(data).hexdigest()
class References(HTMLParser):
    def __init__(self):
        super().__init__(); self.paths = []
    def handle_starttag(self, tag, attrs):
        self.paths.extend(v for k, v in attrs if k in ('src', 'href') and v)
def runtime(revision, base_revision=None):
    revision = git('rev-parse', revision + '^{commit}').decode().strip()
    if base_revision is None:
        # Preserve the historical playgama2 containment check for existing callers.
        subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'playgama2'], cwd=ROOT, check=True)
    else:
        baseline = git('rev-parse', base_revision + '^{commit}').decode().strip()
        subprocess.run(['git', 'merge-base', '--is-ancestor', baseline, revision], cwd=ROOT, check=True)
    def blob(path): return git('show', revision + ':' + path)
    files = {'index.html': blob('index.html'), 'playgama-bridge-config.json': blob('playgama-bridge-config.json')}
    refs = References(); refs.feed(files['index.html'].decode())
    for path in refs.paths:
        if path == SDK_URL: continue
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.[A-Za-z0-9]+', path):
            raise ValueError('Non-relative or non-Latin runtime reference: ' + path)
        files[path] = blob(path)  # Git lookup is case-sensitive; never reads the checkout.
    return revision, files

def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, data in sorted(files.items()):
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3; info.external_attr = 0o100644 << 16
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()

def bundle(files):
    """Inline first-party scripts in their original order, removing cold-load requests.

    The source game already requires inline scripts. Keep the vendor SDK external
    and async; no eval, minification, dependency reordering or remote assets.
    """
    html = files['index.html'].decode()
    pattern = r'<script\s+src\s*=\s*([\'\"])([^\'\"]+)\1\s*>\s*</script>'
    def replace(match):
        path = match.group(2)
        source = files[path].decode()
        if re.search(r'</script', source, re.I):
            raise ValueError('Unsafe inline script terminator in ' + path)
        return '<script>\n' + source + '\n</script>'
    html = re.sub(pattern, replace, html)
    refs = References(); refs.feed(html)
    dangling = [path for path in refs.paths if path != SDK_URL]
    if dangling:
        # Only plain '<script src>' is inlined; anything else would ship a reference absent from the ZIP.
        raise ValueError('Unsupported local runtime references left after bundling: ' + ', '.join(dangling))
    if b'<meta charset="UTF-8">' not in html.encode()[:1024]:
        raise ValueError('UTF-8 declaration must precede bundled scripts in the first 1024 bytes')
    return {'index.html': html.encode(), 'playgama-bridge-config.json': files['playgama-bridge-config.json']}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--base-revision', help='Require this committed baseline to be an ancestor of --revision')
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    revision, files = runtime(args.revision, args.base_revision)
    release = args.out / 'grapnelninja-playgama.zip'
    if release.exists(): raise FileExistsError(f'Refusing to overwrite {release}')
    packed = bundle(files)
    data = archive(packed); assert len(data) <= 300 * 1024 * 1024
    release.write_bytes(data)
    baseline = git('rev-parse', args.base_revision + '^{commit}').decode().strip() if args.base_revision else None
    version = re.search(r"buildVersion:\s*'([^']+)'", files['platform.js'].decode()).group(1)
    (args.out/'source.json').write_text(json.dumps({'branch':None if baseline else 'playgama2', 'base_revision':baseline, 'ancestry_policy':'baseline ancestor of revision' if baseline else 'revision ancestor of playgama2', 'build_version':version, 'revision':revision, 'source':'git blobs only', 'external_sdk':'https://bridge.playgama.com/v2/stable/playgama-bridge.js'}, indent=2)+'\n')
    inventory = [{'path':p, 'size':len(b), 'sha256':sha(b), 'source_blob':git('rev-parse', revision+':'+p).decode().strip(), 'source_blob_equivalent':True} for p,b in sorted(files.items())]
    (args.out/'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
    (args.out/'packed-inventory.json').write_text(json.dumps([
        {'path': p, 'size': len(b), 'sha256': sha(b)} for p,b in sorted(packed.items())
    ], indent=2)+'\n')
    print(f'PASS ancestry {baseline} ancestor of {revision}' if baseline else f'PASS default ancestry {revision} ancestor of playgama2')
    print(f'PASS committed source {revision} build {version}; {len(files)} case-correct Latin runtime paths; index.html at root')
    print(f'PASS release {release} bytes={len(data)} sha256={sha(data)}')
if __name__ == '__main__': main()
