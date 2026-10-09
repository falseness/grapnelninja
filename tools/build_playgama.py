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
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)
def sha(data):
    return hashlib.sha256(data).hexdigest()
class References(HTMLParser):
    def __init__(self):
        super().__init__(); self.paths = []
    def handle_starttag(self, tag, attrs):
        self.paths.extend(v for k, v in attrs if k in ('src', 'href') and v)
def runtime(revision):
    revision = git('rev-parse', revision + '^{commit}').decode().strip()
    subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'playgama2'], cwd=ROOT, check=True)
    def blob(path): return git('show', revision + ':' + path)
    files = {'index.html': blob('index.html'), 'playgama-bridge-config.json': blob('playgama-bridge-config.json')}
    refs = References(); refs.feed(files['index.html'].decode())
    for path in refs.paths:
        if path == 'https://bridge.playgama.com/v2/stable/playgama-bridge.js': continue
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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    revision, files = runtime(args.revision)
    release = args.out / 'grapnelninja-playgama.zip'
    if release.exists(): raise FileExistsError(f'Refusing to overwrite {release}')
    data = archive(files); assert len(data) <= 300 * 1024 * 1024
    release.write_bytes(data)
    (args.out/'source.json').write_text(json.dumps({'branch':'playgama2', 'revision':revision, 'source':'git blobs only', 'external_sdk':'https://bridge.playgama.com/v2/stable/playgama-bridge.js'}, indent=2)+'\n')
    inventory = [{'path':p, 'size':len(b), 'sha256':sha(b), 'source_blob':git('rev-parse', revision+':'+p).decode().strip(), 'source_blob_equivalent':True} for p,b in sorted(files.items())]
    (args.out/'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
    print(f'PASS committed source {revision} on playgama2; {len(files)} case-correct Latin runtime paths; index.html at root')
    print(f'PASS release {release} bytes={len(data)} sha256={sha(data)}')
if __name__ == '__main__': main()
