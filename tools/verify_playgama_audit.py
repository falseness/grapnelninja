#!/usr/bin/env python3
"""Inspect a local audit's evidence without rerunning expensive browser programs.

Run from the repository root. This checks completeness and evidence integrity;
semantic judgments still require reading the dated clauses and linked proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

# Case keys and interstitial request counts written by the TASK-246 rerun suites.
EXPECTED_CASES = {
    'ready': {'immediate', 'retries', 'exhausted', 'unresolved', 'late-init', 'natural'},
    'tutorial': {'en-desktop', 'en-touch', 'ru-desktop', 'ru-touch',
                 'en-desktop-storage_rejected', 'en-desktop-write_rejected'},
    'audio': {'en-desktop', 'ru-desktop', 'en-touch', 'ru-touch', 'host-disabled'},
}
STORAGE_CASES = {'normal', 'late', 'reject-read', 'reject-write', 'delay-write', 'no-local',
                 'record-only'}
AD_REQUESTS = {'supported': 2, 'reject': 1, 'failed': 1, 'throw': 1, 'unsupported': 0}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS ' + message)


def inspect(root):
    for name in ('requirements.json', 'release-gaps.md', 'manifest.json'):
        require((root / name).is_file(), 'required artifact exists: ' + name)
    matrix = json.loads((root / 'requirements.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    clauses = matrix['clauses']
    require(matrix['task'] == manifest['task'] == 'TASK-246', 'task identity')
    require(matrix['later_ticket_prerequisites'] == manifest['later_ticket_prerequisites'] == [],
            'no later ticket is a prerequisite')
    require(len({c['id'] for c in clauses}) == len(clauses), 'unique clause identifiers')
    gaps = (root / 'release-gaps.md').read_text()
    # Independently enumerate every numbered/bulleted normative source line.
    pages = {'technical-requirements', 'advertising-requirements',
             'user-experience-requirements', 'game-self-check'}
    for page in sorted(pages):
        snapshot = root / 'references' / (page + '.md')
        lines = snapshot.read_text().splitlines()
        expected = {i for i, line in enumerate(lines, 1)
                    if re.match(r'^\s*\d+\. ', line) or re.match(r'^\s*\* ', line)}
        actual = [c for c in clauses if Path(c['reference']['snapshot']) == snapshot]
        require(len(actual) == len(expected) and
                {c['reference']['line'] for c in actual} == expected,
                f'{page}: all {len(expected)} clauses covered')
        for c in actual:
            require(c['clause'] == lines[c['reference']['line'] - 1].strip(),
                    c['id'] + ' exact dated source clause')
    checked = set()
    for c in clauses:
        ref = c['reference']
        require(ref['url'].startswith('https://wiki.playgama.com/playgama/') and
                ref['retrieved_utc'] and digest(ref['snapshot']) == ref['sha256'],
                c['id'] + ' reference URL/date/hash')
        require(c['status'] in ('PASS', 'FAIL', 'NA', 'unverified') and
                bool(c['reasoning'].strip()) and bool(c['evidence']),
                c['id'] + ' justified status ' + c['status'])
        if c['status'] in ('FAIL', 'unverified'):
            require(bool(c['action']) and f"**{c['id']} {c['status']} " in gaps,
                    c['id'] + ' release gap and action recorded')
        if c['scope'] == 'excluded':
            require(c['status'] == 'unverified', c['id'] + ' excluded check not a false PASS')
        for e in c['evidence']:
            path = e['path']
            require(all(int(n) <= 246 for n in re.findall(r'TASK-(\d+)', path)),
                    c['id'] + ' evidence through this ticket only')
            if (path, e['sha256']) not in checked:
                require(Path(path).is_file() and digest(path) == e['sha256'],
                        'linked evidence hash ' + path)
                checked.add((path, e['sha256']))
    for suite, count in [('ready', 6), ('storage', 3), ('audio', 5), ('tutorial', 6), ('ads', 5)]:
        log = (root / 'reruns' / suite / 'tests.log').read_text()
        require(re.search(rf'^Ran {count} tests in ', log, re.M) and
                re.search(r'^OK$', log, re.M) and 'EXIT_STATUS=0' in log and
                not re.search(r'^(FAIL:|ERROR:|FAILED \()', log, re.M),
                f'{suite}: Ran {count} tests; OK; EXIT_STATUS=0')
    localization = (root / 'localization-tests.log').read_text()
    require(all(f'PASS {locale} -> {lang}' in localization for locale, lang in
                [('en-US', 'en'), ('ru-RU', 'ru'), ('de-DE', 'en')]) and
            'EXIT_STATUS=0' in localization and '\nOK\n' in localization,
            'current-fixture localization detection, parity and glyphs passed')
    legacy = (root / 'i18n-tests.log').read_text()
    require('EXIT_STATUS=1' in legacy and 'Legacy test-harness gap' in gaps,
            'legacy localization failure retained and disclosed')
    for suite, filename in [('ready', 'ready-events.json'),
                            ('storage', 'storage-cases.json'),
                            ('tutorial', 'tutorial-cases.json')]:
        data = json.loads((root / 'reruns' / suite / filename).read_text())
        if suite == 'storage':
            require(STORAGE_CASES <= set(data), 'storage structured cases recorded')
        else:
            require(set(data) == EXPECTED_CASES[suite], suite + ' structured cases recorded')
        require(all(v['verdict'].startswith('PASS') for v in data.values()),
                suite + ' structured case verdicts agree with logs')
    storage = json.loads((root / 'reruns/storage/storage-cases.json').read_text())
    require(storage['record-only']['result']['records']['classic'] == 100 and
            storage['record-only']['reloaded']['records']['classic'] == 100,
            'record-only offline recovery/reload classic=100')
    audio = json.loads((root / 'reruns/audio/audio-events.json').read_text())
    require(set(audio) == EXPECTED_CASES['audio'], 'audio structured cases recorded')
    for case, events in audio.items():
        require(bool(events) and all(e['verdict'].startswith('PASS') and
                    ((e['rms'] > 0.0001) if e['expected_audible'] else e['rms'] < 0.0001)
                    for e in events), case + ' measured PCM agrees with audible/silent expectation')
    ads = json.loads((root / 'reruns/ads/ad-events.json').read_text())
    require(set(ads) == set(AD_REQUESTS), 'all five advertising outcomes recorded')
    for case, events in ads.items():
        require(bool(events) and events[-1]['verdict'].startswith('PASS'),
                case + ' advertising case verdict')
        times = events[-1]['request_timestamps']
        require(len(times) == AD_REQUESTS[case],
                f'{case} advertising requests recorded: {AD_REQUESTS[case]}')
        require(all(b-a >= 120000 for a, b in zip(times, times[1:])),
                case + ' advertising cooldown >=120000ms')
    for key in ('baseline_revision', 'baseline_source_hashes', 'final_source_hashes',
                'commands', 'environment', 'evidence_paths', 'limitations'):
        require(bool(manifest[key]), 'manifest ' + key)
    for path, sha in manifest['final_source_hashes'].items():
        require(digest(path) == sha, 'final source hash ' + path)
    for path, sha in manifest['baseline_source_hashes'].items():
        if path.endswith(('.html', '.js', '.json')) and not path.startswith('tools/'):
            require(digest(path) == sha, 'runtime unchanged during tests ' + path)
    for path, sha in manifest['evidence_hashes'].items():
        require(digest(path) == sha, 'manifest evidence hash ' + path)
    for path in manifest['evidence_paths']:
        require(Path(path).is_file(), 'manifest evidence exists ' + path)
    for n in (244, 245):
        old = json.loads(Path(f'artifacts/TASK-{n}/manifest.json').read_text())
        for path, sha in old['final_source_hashes'].items():
            require(digest(path) == sha, f'TASK-{n} matching tested source ' + path)
    # These broad claims must stay gaps even when emulated tests pass.
    statuses = {c['id']: c['status'] for c in clauses}
    require(statuses['U4'] == 'FAIL', 'increasing difficulty defect retained')
    require(all(statuses[i] == 'unverified' for i in
                ('T4.1.1', 'T6', 'T8.1', 'T8.2', 'T8.3', 'U7')),
            'native fullscreen/runtime/browser/OS/background gaps retained')
    print('PASS step 1: dated source coverage and every linked artifact inspected')
    print('PASS step 2: release gaps, affected rerun logs and excluded scope inspected')
    print('PASS step 3: manifest, source/evidence hashes and prerequisites inspected')
    print('PASS audit complete; release compliance NOT certified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_dir', type=Path)
    try:
        inspect(parser.parse_args().evidence_dir)
    except AssertionError as error:
        print('FAIL: ' + str(error))
        sys.exit(1)
    except Exception as error:
        print(f'FAIL: malformed evidence: {type(error).__name__}: {error}')
        sys.exit(1)
