"""Momentum mode registry: the third mode value next to 'classic' and 'bad'.

startGame('momentum') runs the bad-mode world for now; scale, score/record
slots and stored records gain a momentum entry. Records saved before momentum
existed ({classic, bad}) still load and get momentum 0.

Requires Playwright Chromium. No remote requests.
"""
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
RECORDS_KEY = 'grapnelninja.records'


class MomentumRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def open(self, records=None):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        if records is not None:
            context.add_init_script(
                f'localStorage.setItem({RECORDS_KEY!r}, {records!r})')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def test_start_game_momentum_runs(self):
        page = self.open()
        # Boot runs momentum (TASK-019): start bad, then momentum again
        self.assertEqual(page.evaluate('version'), 'momentum')
        page.evaluate("startGame('bad')")
        page.evaluate("startGame('momentum')")
        page.wait_for_timeout(500)
        state = page.evaluate('({version, runInProgress, runOver, x: ninja.x})')
        print('after startGame(momentum):', state)
        self.assertEqual(state['version'], 'momentum')
        self.assertTrue(state['runInProgress'])
        self.assertFalse(state['runOver'])

    def test_scale_momentum_equals_bad(self):
        page = self.open()
        values = page.evaluate('[scale.momentum, scale.bad, scale.classic]')
        print('scale momentum/bad/classic:', values)
        self.assertEqual(values[0], values[1])
        self.assertNotEqual(values[0], values[2])

    def test_score_slots_exist(self):
        page = self.open()
        slots = page.evaluate("[scoreText.count.momentum, scoreText.record.momentum,"
                              " 'momentum' in scoreText.count, 'momentum' in scoreText.record]")
        print('count/record momentum:', slots)
        self.assertEqual(slots, [0, 0, True, True])

    def test_old_records_load_with_momentum_zero(self):
        page = self.open('{"classic":3,"bad":7}')
        records = page.evaluate('({...scoreText.record})')
        print('loaded records:', records)
        self.assertEqual(records, {'classic': 3, 'bad': 7, 'momentum': 0})

    def test_momentum_record_round_trips(self):
        page = self.open('{"classic":3,"bad":7,"momentum":4}')
        self.assertEqual(page.evaluate('scoreText.record.momentum'), 4)
        page.evaluate('scoreText.record.momentum = 9; PROGRESS.flush()')
        page.wait_for_function(f'JSON.parse(localStorage.getItem({RECORDS_KEY!r})).momentum === 9')
        stored = page.evaluate(f'JSON.parse(localStorage.getItem({RECORDS_KEY!r}))')
        print('stored records:', stored)
        self.assertEqual(stored, {'classic': 3, 'bad': 7, 'momentum': 9})

    def test_momentum_label_in_every_language(self):
        page = self.open()
        labels = page.evaluate("Object.fromEntries(I18N.languages.map(l =>"
                               " [l, I18N.dictionaries[l]['menu.momentumVersion']]))")
        print('labels:', labels)
        for language, label in labels.items():
            self.assertTrue(label, language)


if __name__ == '__main__':
    unittest.main()
