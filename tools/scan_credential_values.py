"""Count credential values in a directory tree. Prints and writes counts only.

Reads every NAME=value line of the credentials file (default
/root/credentials/grapnelninja/credentials.env; values are never printed or
written) and counts how often each value occurs in the raw bytes of every
file under DIR, and inside every entry of the zip files there. The output
names files and variables, never values.

    python3 tools/scan_credential_values.py DIR --out key-scan.json \
        [--credentials FILE] [--min-length 4]

Exit 0 when no value occurs anywhere, 1 otherwise.
"""
import argparse
import json
from pathlib import Path
import sys
import zipfile

DEFAULT_CREDENTIALS = Path('/root/credentials/grapnelninja/credentials.env')


def read_credentials(path):
    """{NAME: value} from a shell env file (export prefix and quotes allowed)."""
    values = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name = name.removeprefix('export ').strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if name and value:
            values[name] = value
    return values


def count_in(data, needles):
    return {name: data.count(needle) for name, needle in needles.items()}


def scan(root, credentials, out_path=None, min_length=4):
    root = Path(root)
    values = read_credentials(credentials)
    needles = {name: value.encode('utf-8') for name, value in values.items() if len(value) >= min_length}
    skipped = sorted(name for name, value in values.items() if len(value) < min_length)
    out_path = Path(out_path).resolve() if out_path else None
    totals = {name: 0 for name in needles}
    hits, files, zip_entries = [], 0, 0
    for path in sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink()):
        if out_path and path.resolve() == out_path:
            continue
        files += 1
        data = path.read_bytes()
        found = {k: v for k, v in count_in(data, needles).items() if v}
        rel = str(path.relative_to(root))
        if found:
            hits.append({'file': rel, 'counts': found})
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    zip_entries += 1
                    inner = {k: v for k, v in count_in(archive.read(info), needles).items() if v}
                    if inner:
                        hits.append({'file': rel + '!' + info.filename, 'counts': inner})
                    for k, v in inner.items():
                        totals[k] += v
        for k, v in found.items():
            totals[k] += v
    result = {
        'dir': str(root),
        'credentials_file': str(credentials),
        'variables_checked': sorted(needles),
        'variables_skipped_short': skipped,
        'files_scanned': files,
        'zip_entries_scanned': zip_entries,
        'totals': totals,
        'hits': hits,
        'clean': not hits,
    }
    if out_path:
        out_path.write_text(json.dumps(result, indent=1) + '\n', encoding='utf-8')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('dir', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--credentials', type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument('--min-length', type=int, default=4)
    args = parser.parse_args(argv)
    result = scan(args.dir, args.credentials, args.out, args.min_length)
    print(f"files={result['files_scanned']} zip_entries={result['zip_entries_scanned']} "
          f"variables={len(result['variables_checked'])} hits={len(result['hits'])} clean={result['clean']}")
    return 0 if result['clean'] else 1


if __name__ == '__main__':
    sys.exit(main())
