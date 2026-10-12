"""Independently inspect a release directory produced by docs/playgama-release.md.

Recomputes the inlined bundle from Git blobs with the builder's own runtime()
and bundle(), then compares it with the ZIP, its rebuild, packed-inventory.json,
inventory.json and the extracted-ZIP suite report. Any mismatch prints one
`FAIL: ...` line and exits 1; no browser tests are repeated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from build_playgama import ROOT, archive, bundle, runtime

MEMBERS = {'index.html', 'playgama-bridge-config.json'}


class Fail(Exception):
    pass


def digest(data): return hashlib.sha256(data).hexdigest()


def check(condition, message):
    if not condition: raise Fail(message)


def verify(out):
    def read(name):
        try: return json.loads((out/name).read_text())
        except (OSError, ValueError) as error: raise Fail(f'{name}: {error}')
    source, inventory, packed_inventory = read('source.json'), read('inventory.json'), read('packed-inventory.json')
    suite = read('suite/suite.json')
    revision, baseline = source.get('revision'), source.get('base_revision')
    check(baseline, 'source.json has no base_revision; build with --base-revision')
    ancestry = subprocess.run(['git', 'merge-base', '--is-ancestor', baseline, revision], cwd=ROOT, capture_output=True)
    check(ancestry.returncode == 0, f'base_revision {baseline} is not an ancestor of {revision}')
    print(f'PASS source.json base_revision {baseline} ancestor of revision {revision}')

    _, files = runtime(revision, baseline)
    packed = bundle(files)
    check([{'path':p, 'size':len(b), 'sha256':digest(b)} for p, b in sorted(files.items())] ==
          [{k: row[k] for k in ('path', 'size', 'sha256')} for row in inventory],
          'inventory.json differs from the Git source blobs of the revision')
    print(f'PASS inventory.json {len(inventory)} source files equal Git blobs at {revision}')
    check([{'path':p, 'size':len(b), 'sha256':digest(b)} for p, b in sorted(packed.items())] == packed_inventory,
          'packed-inventory.json differs from bundle() recomputed from Git')
    print(f'PASS packed-inventory.json equals recomputed bundle() ({len(packed)} members)')

    release_path = out/'grapnelninja-playgama.zip'
    try: release, rebuild = release_path.read_bytes(), (out/'rebuild/grapnelninja-playgama.zip').read_bytes()
    except OSError as error: raise Fail(str(error))
    check(release == rebuild, 'rebuild/grapnelninja-playgama.zip differs from grapnelninja-playgama.zip')
    check(len(release) <= 300*1024*1024, f'ZIP is {len(release)} bytes, over 300 MB')
    try:
        with zipfile.ZipFile(release_path) as z:
            check(z.testzip() is None, 'ZIP CRC check failed')
            names = z.namelist()
            check(len(names) == len(set(names)) and set(names) == MEMBERS, f'ZIP members {sorted(names)} != {sorted(MEMBERS)}')
            for name in sorted(MEMBERS):
                check(z.read(name) == packed[name], f'ZIP member {name} differs from recomputed bundle()')
    except zipfile.BadZipFile as error: raise Fail(f'{release_path}: {error}')
    check(archive(packed) == release, 'ZIP bytes differ from deterministic archive() of the recomputed bundle')
    print(f'PASS grapnelninja-playgama.zip {len(release)} bytes sha256 {digest(release)}: members equal bundle(), rebuild identical')

    check(suite.get('zip_sha256') == digest(release), 'suite/suite.json was produced for a different ZIP')
    check(suite.get('successful') is True and suite.get('tests_run', 0) > 0, 'suite/suite.json reports an unsuccessful extracted-ZIP run')
    check(suite.get('extracted_members') == {p: digest(b) for p, b in packed.items()}, 'suite/suite.json extracted members differ from the bundle')
    print(f'PASS suite/suite.json {suite["tests_run"]} extracted-ZIP tests successful on this ZIP')


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out
    try:
        verify(out)
    except Fail as error:
        print(f'FAIL: {error}'); sys.exit(1)
    except Exception as error:
        print(f'FAIL: {type(error).__name__}: {error}'.replace('\n', ' ')); sys.exit(1)
    print('PASS release directory verified')


if __name__ == '__main__': main()
