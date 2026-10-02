"""Records and time-in-game persist in localStorage."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from y8_harness import open_game, start_y8_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
RECORDS_KEY = 'grapnelninja.records'
READY = 'PLATFORM.environment === "y8" && menu.visible'
# Count every localStorage write of the records key in window.__recordWrites
COUNT_WRITES = '''(() => {
    window.__recordWrites = 0
    const orig = Storage.prototype.setItem
    Storage.prototype.setItem = function(key, value) {
        if (key === '%s') window.__recordWrites++
        return orig.apply(this, arguments)
    }
})()''' % RECORDS_KEY


def log(message):
    print('  ' + message, file=sys.stderr)


class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_y8_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('Y8_PROGRESS_EVIDENCE_DIR')
        cls.errors = []

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = cls.out()
            for kind in ('console', 'page'):
                lines = [f'{name}: {msg}' for name, errors in cls.errors
                         for msg in errors[kind]]
                (out / f'{kind}-errors.log').write_text(''.join(
                    line + '\n' for line in lines))

    @classmethod
    def out(cls):
        out = Path(cls.evidence)
        out.mkdir(parents=True, exist_ok=True)
        return out

    def boot(self, block_sdk=False):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT,
                                          block_sdk=block_sdk)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.goto(self.url + 'index.html')
        self.wait_ready(page, block_sdk)
        return page

    def wait_ready(self, page, block_sdk=False):
        page.wait_for_function('PLATFORM.environment === "disabled" && menu.visible'
                               if block_sdk else READY)

    def reload(self, page, block_sdk=False):
        page.reload()
        self.wait_ready(page, block_sdk)

    def score_and_pause(self, page, mode, points):
        page.evaluate('''([mode, points]) => {
            startGame(mode)
            for (let i = 0; i < points; ++i) changeScoreText()
            menu.startPause()
        }''', [mode, points])

    def stored_records(self, page):
        return json.loads(page.evaluate(f'localStorage.getItem("{RECORDS_KEY}")'))

    def menu_texts(self, page):
        return page.evaluate('''({classic: menu.classicRecord.text,
            bad: menu.badRecord.text, time: menu.timeInGame.text})''')

    def test_records_and_time_migration(self):
        """(a) classic, (b) bad and (c) legacy time migration via localStorage."""
        page = self.boot()

        self.score_and_pause(page, 'classic', 7)
        self.reload(page)
        texts = self.menu_texts(page)
        records = self.stored_records(page)
        log(f'(a) after reload menu={texts} records={records}')
        self.assertEqual(texts['classic'], 'record: 7')
        self.assertEqual(texts['bad'], 'record: 0')
        self.assertEqual(records['classic'], 7)
        self.assertEqual(page.evaluate('scoreText.record.classic'), 7)
        log('ASSERT (a) classic menu "record: 7" and stored classic == 7: pass')

        self.score_and_pause(page, 'bad', 7)
        self.reload(page)
        texts = self.menu_texts(page)
        records = self.stored_records(page)
        log(f'(b) after reload menu={texts} records={records}')
        self.assertEqual(texts['bad'], 'record: 7')
        self.assertEqual(texts['classic'], 'record: 7')
        self.assertEqual(records, {'classic': 7, 'bad': 7})
        log('ASSERT (b) bad menu "record: 7" and stored bad == 7: pass')

        page.evaluate('''() => {
            localStorage.removeItem("grapnelninja.time")
            localStorage.setItem("time", "125")
        }''')
        self.reload(page)
        stored = page.evaluate('localStorage.getItem("grapnelninja.time")')
        legacy = page.evaluate('localStorage.getItem("time")')
        texts = self.menu_texts(page)
        log(f'(c) grapnelninja.time={stored!r} legacy time={legacy!r} menu time={texts["time"]!r}')
        self.assertEqual(stored, '125')
        self.assertIsNone(legacy)
        self.assertIn('2 minutes', texts['time'])
        log('ASSERT (c) legacy time=125 migrated to grapnelninja.time=125, legacy removed,'
            ' menu "2 minutes": pass')

        # A second load must not migrate again or touch the stored time
        self.reload(page)
        self.assertEqual(page.evaluate('localStorage.getItem("grapnelninja.time")'), '125')

        dump = page.evaluate('''Object.fromEntries(Object.keys(localStorage).sort()
            .map(k => [k, localStorage.getItem(k)]))''')
        log(f'localStorage={dump}')
        if self.evidence:
            page.screenshot(path=str(self.out() / 'menu-after-reload.png'))
            (self.out() / 'storage-dump.json').write_text(json.dumps(dump, indent=2) + '\n')

    def test_blocked_sdk_keeps_records(self):
        """(d) with the SDK blocked, records still persist."""
        page = self.boot(block_sdk=True)
        self.score_and_pause(page, 'classic', 4)
        self.score_and_pause(page, 'bad', 6)
        self.reload(page, block_sdk=True)
        texts = self.menu_texts(page)
        records = self.stored_records(page)
        log(f'(d) blocked SDK menu={texts} records={records}')
        self.assertEqual(texts['classic'], 'record: 4')
        self.assertEqual(texts['bad'], 'record: 6')
        self.assertEqual(records, {'classic': 4, 'bad': 6})
        log('ASSERT (d) blocked SDK records persist: pass')

    def test_records_written_only_on_run_end_or_pause(self):
        """(e) no write per point; one write on pause and on run end."""
        page = self.boot()
        page.evaluate(COUNT_WRITES)
        page.evaluate('startGame("classic")')
        for _ in range(10):
            page.evaluate('changeScoreText()')
            page.wait_for_timeout(50)
        during = page.evaluate('window.__recordWrites')
        page.keyboard.press('Escape')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        after_pause = page.evaluate('window.__recordWrites')
        log(f'(e) record writes during 10 points={during} after pause={after_pause}')
        self.assertEqual(during, 0)
        self.assertEqual(after_pause, 1)
        self.assertGreaterEqual(self.stored_records(page)['classic'], 10)

        page.keyboard.press('Escape')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        for _ in range(15):
            page.evaluate('changeScoreText()')
        self.assertEqual(page.evaluate('window.__recordWrites'), 1)
        page.evaluate('reStart()')
        ended = page.evaluate('window.__recordWrites')
        log(f'(e) record writes after run end={ended}')
        self.assertEqual(ended, 2)
        self.assertEqual(self.stored_records(page)['classic'],
                         page.evaluate('scoreText.record.classic'))
        log('ASSERT (e) 0 writes per point, 1 on pause, 1 on run end: pass')

    def test_pagehide_saves_new_record(self):
        """(f) closing the tab mid-run keeps a new record."""
        page = self.boot()
        page.evaluate('''() => {
            startGame("classic")
            for (let i = 0; i < 5; ++i) changeScoreText()
        }''')
        self.assertIsNone(page.evaluate(f'localStorage.getItem("{RECORDS_KEY}")'))
        page.evaluate('window.dispatchEvent(new PageTransitionEvent("pagehide"))')
        records = self.stored_records(page)
        log(f'(f) after pagehide records={records}')
        self.assertEqual(records['classic'], 5)
        log('ASSERT (f) pagehide saves the new record: pass')

    def test_corrupt_records_tolerated(self):
        """(g) corrupt JSON in the records key loads as zero records."""
        page = self.boot()
        page.evaluate(f'localStorage.setItem("{RECORDS_KEY}", "{{not json")')
        self.reload(page)
        texts = self.menu_texts(page)
        log(f'(g) corrupt records menu={texts}')
        self.assertEqual((texts['classic'], texts['bad']), ('record: 0', 'record: 0'))
        self.score_and_pause(page, 'classic', 3)
        self.assertEqual(self.stored_records(page), {'classic': 3, 'bad': 0})
        log('ASSERT (g) corrupt JSON tolerated, next save overwrites it: pass')


if __name__ == '__main__':
    unittest.main()
