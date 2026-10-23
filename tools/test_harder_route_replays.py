"""Recorded production-input coverage of all transfers, not a from-spawn climb."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest
from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'tools'
DIR = Path(os.environ.get('HARDER_LEVEL_DIR', ROOT / 'artifacts/levels'))

class HarderReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = DIR / 'extended-mountain.level.json'
        if not path.exists(): path = DIR / 'level.json'
        cls.level = json.loads(path.read_text())
        cls.upper = json.loads((TOOLS / 'fixtures/harder-upper-inputs.json').read_text())
        cls.local = json.loads((TOOLS / 'fixtures/harder-transfer-inputs.json').read_text())
        cls.stack = ExitStack(); cls.addClassCleanup(cls.stack.close)
        url, browser = start_browser_test(ROOT, cls.stack.callback)
        cls.pages = {}
        for script in ('opening_combination_replay', 'probe_level_routes'):
            page = browser.new_page(); page.goto(url); wait_for_boot_run(page)
            page.add_script_tag(path=str(TOOLS / (script + '.js')))
            cls.pages[script] = page

    def test_upper_combinations(self):
        self.assertEqual([r['source'] for r in self.upper], [16,19,23,27])
        page = self.pages['opening_combination_replay']
        for record in self.upper:
            n = record['source']
            with self.subTest(source=n):
                log = page.evaluate('o=>OPENING_REPLAY.run(o)', dict(level=self.level,
                    fixture=record['fixture'], inputs=record['inputs'], budget=record['budget'],
                    stopOn=dict(id='P'+str(n+3),ny='up')))
                self.assertEqual(log['acquisitionRadius'],540)
                self.assertLess(log['maxStep'],200)
                if n==27:
                    self.assertTrue(log['completed'])
                    f=self.level['finish'];q=log['final']
                    self.assertTrue(f['left']<=q['x']<=f['right'] and f['top']<=q['y']<=f['bottom'])
                else:self.assertIsNotNone(log['stopped'])
                high=n
                for c in log['contacts']:
                    index=int(c['id'].split('-')[0][1:])
                    self.assertLessEqual(index,high+1,c)
                    high=max(high,index)
                self.assertGreaterEqual(high,n+2 if n==27 else n+3)
                ceiling=next(c for c in log['contacts'] if c['id']==f'P{n+1}-body0' and c['ny']>.9)
                slope=next(c for c in log['contacts'] if c['id']==f'P{n+2}-body0' and c['ny']<-.9)
                self.assertGreater(slope['vyIn'],0)
                self.assertLess(slope['vyOut'],0)
                self.assertLess(ceiling['tick'],slope['tick'])
                arrival=log['final'] if n==27 else log['stopped']
                self.assertLess(slope['tick'],arrival['tick'])
                self.assertLess(arrival['y'],slope['y'])

    def test_other_transfers(self):
        page = self.pages['probe_level_routes']
        for policy in self.local:
            with self.subTest(source=policy['source']):
                result=page.evaluate('o=>ROUTE_PROBE.run(o)',dict(policy,level=self.level))
                self.assertIsNotNone(result['hit'])
                self.assertEqual(result['hit']['id'],policy['target']+'-body0')

    def test_coverage(self):
        covered={2,3,4,5} # continuous opening replay in test_opening_jump_variety
        for r in self.upper: covered.update(range(r['source'],r['source']+3))
        covered.update(int(p['source'][1:]) for p in self.local)
        self.assertEqual(covered,set(range(30)))

if __name__=='__main__':unittest.main()
