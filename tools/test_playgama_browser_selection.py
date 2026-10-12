"""Complete sealed SYNTHETIC validator fixtures; never browser FPS evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from playwright.sync_api import sync_playwright
from playgama_render_compare import (selected_protocol, validate_protocol, aggregate,
    launch_browser, audit, read, write, sha, PROTOCOL)
from test_playgama_render_compare import capture_fixture, visual_fixture


class BrowserSelectionTests(unittest.TestCase):
    def test_missing_chrome_no_fallback(self):
        pw = Mock()
        pw.chromium.launch.side_effect = RuntimeError('Chrome unavailable')
        with self.assertRaisesRegex(RuntimeError, 'Chrome unavailable'):
            launch_browser(pw, 'chrome')
        pw.chromium.launch.assert_called_once_with(headless=True, channel='chrome')
        pw.firefox.launch.assert_not_called()
        print('PASS missing Chrome never falls back to Chromium')

    def test_protocol_inventory(self):
        self.assertEqual(selected_protocol(), PROTOCOL)
        for engine in ('firefox', 'chrome', 'chromium'):
            p = selected_protocol(engine)
            self.assertEqual(validate_protocol(p), p)
            self.assertEqual(p['orders'], [['control', 'candidate'], ['candidate', 'control'], ['control', 'candidate']])
            for inventory in ([], [engine, engine], ['firefox', 'chrome'], ['unknown']):
                with self.assertRaisesRegex(AssertionError, 'protocol differs'):
                    validate_protocol(dict(p, engines=inventory))
        print('PASS selected-engine inventories reject omissions/duplicates; AB/BA/AB retained')

    def test_complete_selected_receipts(self):
        with sync_playwright() as pw:
            executable = Path(pw.firefox.executable_path).resolve()
        provenance = dict(engine='firefox', pid=123, executable_path=str(executable),
            executable_sha256=sha(executable.read_bytes()), version='SYNTHETIC',
            launch_arguments=[str(executable), '-juggler-pipe'], channel=None,
            launch_options=dict(headless=True))
        for kind, fixture in (('capture', capture_fixture), ('visuals', visual_fixture)):
            with tempfile.TemporaryDirectory() as d:
                out = Path(d)
                fixture(out)
                protocol = selected_protocol('firefox')
                write(out/'protocol.json', protocol)
                data = read(out/'results.json')
                key = 'runs' if kind == 'capture' else 'comparisons'
                data[key] = [r for r in data[key] if r['engine'] == 'firefox']
                if kind == 'capture':
                    data['comparison'] = aggregate(data[key], protocol=protocol)
                    self.assertFalse(data['comparison']['performance_accepted'])
                write(out/'results.json', data)
                write(out/'environment.json', dict(browsers={'firefox':provenance}))
                receipt = read(out/'manifest.json')
                receipt['command'] += ['--engine', 'firefox']
                lines = (out/'command.log').read_text().splitlines()
                identity = json.loads(lines[0][10:]); identity['command'] = receipt['command']
                lines[0] = 'EXECUTION ' + json.dumps(identity)
                lines.insert(1, 'LAUNCH ' + json.dumps(provenance))
                (out/'command.log').write_text('\n'.join(lines)+'\n')
                def reseal():
                    receipt['evidence_sha256'] = {p.name:sha(p.read_bytes()) for p in out.iterdir() if p.name != 'manifest.json'}
                    write(out/'manifest.json', receipt)
                reseal()
                audit(out)
                print(f'PASS complete sealed selected {kind} fixture; SYNTHETIC validator evidence only')
                original = copy.deepcopy(data)
                for mutation in ('omit', 'duplicate'):
                    data = copy.deepcopy(original)
                    if mutation == 'omit': data[key].pop()
                    else: data[key].append(data[key][-1])
                    write(out/'results.json', data); reseal()
                    with self.assertRaises(AssertionError): audit(out)
                write(out/'results.json', original)
                bad = dict(provenance, executable_sha256='0'*64)
                write(out/'environment.json', dict(browsers={'firefox':bad})); reseal()
                with self.assertRaisesRegex(AssertionError, 'launch identity'): audit(out)
                print(f'PASS selected {kind} omissions/duplicates and provenance tampering rejected')


if __name__ == '__main__': unittest.main()
