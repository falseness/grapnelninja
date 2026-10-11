"""Compare the published Playgama ZIP with historical committed source, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'a570592a1a52b9af0278efa7583874ae25419d0d'
ZIP_SHA256 = '78473df0ecdb9f959351c517cc60c10c141a1e451ac03ac10232425a29ef88c7'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(path):
    return subprocess.check_output(['git', 'show', REVISION + ':' + path], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    # Execute the exact historical builder, without invoking its CLI or its
    # runtime() helper's unrelated requirement for a local playgama2 branch.
    builder = blob('tools/build_playgama.py')
    historical = {'__name__': 'historical_builder', '__file__': str(ROOT/'tools/build_playgama.py')}
    exec(compile(builder, REVISION + ':tools/build_playgama.py', 'exec'), historical)
    source = {'index.html': blob('index.html'),
              'playgama-bridge-config.json': blob('playgama-bridge-config.json')}
    refs = historical['References']()
    refs.feed(source['index.html'].decode())
    for path in refs.paths:
        if path == 'https://bridge.playgama.com/v2/stable/playgama-bridge.js':
            continue
        source[path] = blob(path)
    packed = historical['bundle'](source)
    rebuilt = historical['archive'](packed)
    data = args.archive.read_bytes()
    with zipfile.ZipFile(args.archive) as archive:
        bad = archive.testzip()
        names = archive.namelist()
        members = []
        for info in archive.infolist():
            actual = archive.read(info.filename)
            expected = packed.get(info.filename)
            members.append({'path': info.filename, 'size': len(actual),
                            'crc32': f'{info.CRC:08x}', 'sha256': sha(actual),
                            'expected_sha256': sha(expected) if expected is not None else None,
                            'byte_equal': actual == expected})
    checks = {'expected_zip_sha256': sha(data) == ZIP_SHA256,
              'crc_ok': bad is None,
              'member_inventory_equal': sorted(names) == sorted(packed),
              'bundled_runtime_byte_equal': all(m['byte_equal'] for m in members),
              'rebuilt_zip_byte_equal': data == rebuilt}
    report = {'revision': REVISION, 'archive': str(args.archive.resolve()),
              'sha256': sha(data), 'expected_sha256': ZIP_SHA256,
              'historical_builder_sha256': sha(builder),
              'comparison_method': 'historical bundle(source git blobs), archive(packed); byte equality',
              'source_runtime_sha256': {p: sha(b) for p, b in sorted(source.items())},
              'rebuilt_zip_sha256': sha(rebuilt), 'bad_crc_member': bad,
              'members': members, 'checks': checks,
              'result': 'PASS' if all(checks.values()) else 'FAIL'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    for name, passed in checks.items():
        print(f'{"PASS" if passed else "FAIL"} {name}')
    for member in members:
        print(f'{"PASS" if member["byte_equal"] else "FAIL"} member {member["path"]} '
              f'bytes={member["size"]} sha256={member["sha256"]}')
    print(f'{report["result"]} ZIP sha256={sha(data)}')
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == '__main__':
    main()
