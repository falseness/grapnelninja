"""TASK-860: where do the GameAnalytics keys appear? Prints counts only.

Counts GA_GAME_KEY and GA_SECRET_KEY occurrences (values from the
environment or /root/credentials/grapnelninja/credentials.env, never
printed) in every release zip (each entry's bytes, plus the raw zip bytes),
each portal's manifest.json, and the git tree (`git grep` over HEAD and the
working tree). Expected: itch > 0, every other zip 0, manifests 0, git 0.

    python3 tools/scan_ga_keys.py [--release DIR] --out key-scan.json
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gameanalytics_backend import credentials  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PORTALS = ('itch', 'gamepix', 'y8', 'playgama')
NAMES = ('GA_GAME_KEY', 'GA_SECRET_KEY')


def git_grep_count(value, *where):
    """Matching lines of `git grep -F value [where]` (0 when none)."""
    result = subprocess.run(['git', '-C', str(ROOT), 'grep', '-c', '-F', '-e', value, *where],
                            capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise SystemExit('git grep failed: ' + result.stderr.strip())
    return sum(int(line.rsplit(':', 1)[1]) for line in result.stdout.splitlines() if line)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--release', type=Path, default=ROOT / 'artifacts' / 'release-grapple-over')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    env = credentials()
    keys = {n: env[n].encode() for n in NAMES}
    if not all(keys.values()):
        raise SystemExit('GA_GAME_KEY / GA_SECRET_KEY unavailable')
    report = {'release': str(args.release.relative_to(ROOT) if args.release.is_relative_to(ROOT) else args.release),
              'head': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
              'zips': {}, 'manifests': {}, 'git': {}}
    for portal in PORTALS:
        path = args.release / portal / f'grapple-over-{portal}.zip'
        with zipfile.ZipFile(path) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        raw = path.read_bytes()
        report['zips'][portal] = {
            n: {'entries_total': sum(d.count(k) for d in entries.values()),
                'entries_with_key': sorted(e for e, d in entries.items() if k in d),
                'raw_zip_bytes': raw.count(k)}
            for n, k in keys.items()}
        report['manifests'][portal] = {n: (args.release / portal / 'manifest.json').read_bytes().count(k)
                                       for n, k in keys.items()}
    for name, key in keys.items():
        value = key.decode()
        report['git'][name] = {'head_tree': git_grep_count(value, 'HEAD'),
                               'working_tree_tracked': git_grep_count(value),
                               'working_tree_untracked': git_grep_count(value, '--untracked')}
    counts = {p: sum(v['entries_total'] for v in z.values()) for p, z in report['zips'].items()}
    git_total = sum(sum(v.values()) for v in report['git'].values())
    manifest_total = sum(sum(v.values()) for v in report['manifests'].values())
    report['summary'] = {'itch': counts['itch'], 'gamepix': counts['gamepix'], 'y8': counts['y8'],
                         'playgama': counts['playgama'], 'manifests': manifest_total, 'git': git_total}
    report['pass'] = (all(report['zips']['itch'][n]['entries_total'] > 0 for n in NAMES)
                      and counts['gamepix'] == counts['y8'] == counts['playgama'] == 0
                      and manifest_total == 0 and git_total == 0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + '\n')
    print(('PASS ' if report['pass'] else 'FAIL ') + json.dumps(report['summary']))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
