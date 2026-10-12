#!/usr/bin/env python3
"""Regression: verify_playgama_audit.py rejects empty structured evidence without a traceback."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'verify_playgama_audit.py'
sys.path.insert(0, str(SCRIPT.parent))
import verify_playgama_audit as audit  # noqa: E402

PAGES = {'technical-requirements': ['T4.1.1', 'T6', 'T8.1', 'T8.2', 'T8.3'],
         'advertising-requirements': ['A1'],
         'user-experience-requirements': ['U4', 'U7'],
         'game-self-check': ['S1']}
STATUS = {'U4': 'FAIL', 'T4.1.1': 'unverified', 'T6': 'unverified', 'T8.1': 'unverified',
          'T8.2': 'unverified', 'T8.3': 'unverified', 'U7': 'unverified'}
COUNTS = {'ready': 6, 'storage': 3, 'audio': 5, 'tutorial': 6, 'ads': 5}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def build_tree(cwd):
    """Write a complete passing evidence tree under cwd/ev (paths are cwd-relative)."""
    ev = cwd / 'ev'
    write(cwd / 'index.html', '<html></html>')
    write(ev / 'proof.txt', 'proof')
    clauses, gaps = [], ['Legacy test-harness gap']
    for page, ids in PAGES.items():
        lines = [f'{n}. clause {cid}' for n, cid in enumerate(ids, 1)]
        snapshot = ev / 'references' / (page + '.md')
        write(snapshot, '\n'.join(lines) + '\n')
        for n, cid in enumerate(ids, 1):
            status = STATUS.get(cid, 'PASS')
            clauses.append({'id': cid, 'clause': lines[n - 1], 'status': status,
                            'scope': 'included', 'reasoning': 'r', 'action': 'a',
                            'reference': {'url': 'https://wiki.playgama.com/playgama/' + page,
                                          'retrieved_utc': '2026-01-01T00:00:00Z',
                                          'snapshot': 'ev/references/' + page + '.md',
                                          'sha256': sha(snapshot), 'line': n},
                            'evidence': [{'path': 'ev/proof.txt', 'sha256': sha(ev / 'proof.txt')}]})
            if status != 'PASS':
                gaps.append(f'**{cid} {status} gap')
    write(ev / 'requirements.json', {'task': 'TASK-246', 'later_ticket_prerequisites': [],
                                     'clauses': clauses})
    write(ev / 'release-gaps.md', '\n'.join(gaps) + '\n')
    for suite, count in COUNTS.items():
        write(ev / 'reruns' / suite / 'tests.log', f'Ran {count} tests in 1.0s\n\nOK\nEXIT_STATUS=0\n')
    write(ev / 'localization-tests.log', 'PASS en-US -> en\nPASS ru-RU -> ru\nPASS de-DE -> en\n'
          '\nOK\nEXIT_STATUS=0\n')
    write(ev / 'i18n-tests.log', 'EXIT_STATUS=1\n')
    verdict = {'verdict': 'PASS'}
    write(ev / 'reruns/ready/ready-events.json', {c: verdict for c in audit.EXPECTED_CASES['ready']})
    write(ev / 'reruns/tutorial/tutorial-cases.json',
          {c: verdict for c in audit.EXPECTED_CASES['tutorial']})
    storage = {c: verdict for c in audit.STORAGE_CASES}
    storage['record-only'] = {'verdict': 'PASS', 'result': {'records': {'classic': 100}},
                              'reloaded': {'records': {'classic': 100}}}
    write(ev / 'reruns/storage/storage-cases.json', storage)
    write(ev / 'reruns/audio/audio-events.json',
          {c: [{'verdict': 'PASS', 'rms': 0.01, 'expected_audible': True},
               {'verdict': 'PASS', 'rms': 0.0, 'expected_audible': False}]
           for c in audit.EXPECTED_CASES['audio']})
    write(ev / 'reruns/ads/ad-events.json',
          {c: [{'verdict': 'PASS', 'request_timestamps': [1000 + 120000 * i for i in range(n)]}]
           for c, n in audit.AD_REQUESTS.items()})
    source = {'index.html': sha(cwd / 'index.html')}
    for n in (244, 245):
        write(cwd / f'artifacts/TASK-{n}/manifest.json', {'final_source_hashes': source})
    write(ev / 'manifest.json', {
        'task': 'TASK-246', 'later_ticket_prerequisites': [], 'baseline_revision': 'abc',
        'baseline_source_hashes': source, 'final_source_hashes': source, 'commands': ['c'],
        'environment': {'os': 'linux'}, 'evidence_paths': ['ev/proof.txt'],
        'limitations': ['l'], 'evidence_hashes': {'ev/proof.txt': sha(ev / 'proof.txt')}})


def mutate(cwd, rel, change):
    path = cwd / 'ev' / rel
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


class VerifyAuditStructuredEvidence(unittest.TestCase):
    def run_verifier(self, change=None):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            build_tree(cwd)
            if change:
                change(cwd)
            proc = subprocess.run([sys.executable, str(SCRIPT), 'ev'], cwd=cwd,
                                  capture_output=True, text=True)
        output = proc.stdout + proc.stderr
        return proc.returncode, output

    def assert_rejected(self, name, change, failure):
        code, output = self.run_verifier(change)
        fail = [line for line in output.splitlines() if line.startswith('FAIL')]
        print(f'ASSERT {name}: exit={code} {fail} traceback_markers={output.count("Traceback")}', flush=True)
        self.assertNotEqual(code, 0, output)
        self.assertEqual(fail, ['FAIL: ' + failure], output)
        self.assertNotIn('Traceback', output)

    def test_complete_tree_passes(self):
        code, output = self.run_verifier()
        print(f'ASSERT complete tree: exit={code} last={output.splitlines()[-1]!r} '
              f'traceback_markers={output.count("Traceback")}', flush=True)
        self.assertEqual(code, 0, output)
        self.assertIn('PASS audit complete; release compliance NOT certified', output)
        self.assertNotIn('Traceback', output)

    def test_empty_ready_cases(self):
        self.assert_rejected('empty ready dict', lambda cwd: mutate(
            cwd, 'reruns/ready/ready-events.json', dict.clear), 'ready structured cases recorded')

    def test_empty_tutorial_cases(self):
        self.assert_rejected('empty tutorial dict', lambda cwd: mutate(
            cwd, 'reruns/tutorial/tutorial-cases.json', dict.clear),
            'tutorial structured cases recorded')

    def test_empty_audio_cases(self):
        self.assert_rejected('empty audio dict', lambda cwd: mutate(
            cwd, 'reruns/audio/audio-events.json', dict.clear), 'audio structured cases recorded')

    def test_empty_audio_event_list(self):
        self.assert_rejected('empty audio list', lambda cwd: mutate(
            cwd, 'reruns/audio/audio-events.json', lambda d: d.update({'en-desktop': []})),
            'en-desktop measured PCM agrees with audible/silent expectation')

    def test_empty_ads_list(self):
        self.assert_rejected('empty ads list', lambda cwd: mutate(
            cwd, 'reruns/ads/ad-events.json', lambda d: d.update({'supported': []})),
            'supported advertising case verdict')

    def test_single_supported_ad_timestamp(self):
        self.assert_rejected('one supported timestamp', lambda cwd: mutate(
            cwd, 'reruns/ads/ad-events.json',
            lambda d: d['supported'][-1].update(request_timestamps=[1000])),
            'supported advertising requests recorded: 2')

    def test_no_supported_ad_timestamps(self):
        self.assert_rejected('zero supported timestamps', lambda cwd: mutate(
            cwd, 'reruns/ads/ad-events.json',
            lambda d: d['supported'][-1].update(request_timestamps=[])),
            'supported advertising requests recorded: 2')

    def test_malformed_event_is_failure_not_traceback(self):
        self.assert_rejected('ads event missing key', lambda cwd: mutate(
            cwd, 'reruns/ads/ad-events.json', lambda d: d['reject'][-1].pop('request_timestamps')),
            "malformed evidence: KeyError: 'request_timestamps'")


if __name__ == '__main__':
    unittest.main()
