"""Records and time-in-game persist through CrazyGames SDK.data (or localStorage)."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crazygames_harness import open_game, sdk_calls, start_crazygames_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
FAKE_PREFIX = '__cgfake:'
READY_FAKE = 'CG.environment === "crazygames" && menu.visible'
READY_BLOCKED = 'CG.environment === "disabled" && menu.visible'


def log(message):
    print('  ' + message, file=sys.stderr)


class CrazyGamesProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_crazygames_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('CG_PROGRESS_EVIDENCE_DIR')
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
        page.wait_for_function(READY_BLOCKED if block_sdk else READY_FAKE)
        return page

    def reload(self, page, block_sdk=False):
        page.reload()
        page.wait_for_function(READY_BLOCKED if block_sdk else READY_FAKE)

    def score_and_pause(self, page, mode, points):
        page.evaluate('''([mode, points]) => {
            startGame(mode)
            for (let i = 0; i < points; ++i) changeScoreText()
            menu.startPause()
        }''', [mode, points])

    def fake_records(self, page):
        return json.loads(page.evaluate(
            'CrazyGames.SDK.data.getItem("grapnelninja.records")'))

    def menu_texts(self, page):
        return page.evaluate('''({classic: menu.classicRecord.text,
            bad: menu.badRecord.text, time: menu.timeInGame.text})''')

    def test_fake_sdk_records_and_time_migration(self):
        """(a) classic, (b) bad and (c) legacy time migration via SDK.data."""
        page = self.boot()

        self.score_and_pause(page, 'classic', 7)
        self.reload(page)
        texts = self.menu_texts(page)
        records = self.fake_records(page)
        log(f'(a) after reload menu={texts} SDK.data records={records}')
        self.assertEqual(texts['classic'], 'record: 7')
        self.assertEqual(texts['bad'], 'record: 0')
        self.assertEqual(records['classic'], 7)
        self.assertEqual(page.evaluate('scoreText.record.classic'), 7)
        log('ASSERT (a) classic menu "record: 7" and SDK.data classic == 7: pass')

        self.score_and_pause(page, 'bad', 7)
        self.reload(page)
        texts = self.menu_texts(page)
        records = self.fake_records(page)
        log(f'(b) after reload menu={texts} SDK.data records={records}')
        self.assertEqual(texts['bad'], 'record: 7')
        self.assertEqual(texts['classic'], 'record: 7')
        self.assertEqual(records, {'classic': 7, 'bad': 7})
        log('ASSERT (b) bad menu "record: 7" and SDK.data bad == 7: pass')

        page.evaluate(f'''() => {{
            localStorage.removeItem("{FAKE_PREFIX}grapnelninja.time")
            localStorage.setItem("time", "125")
        }}''')
        self.reload(page)
        stored = page.evaluate('CrazyGames.SDK.data.getItem("grapnelninja.time")')
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
        self.assertEqual(page.evaluate('CrazyGames.SDK.data.getItem("grapnelninja.time")'), '125')

        dump = page.evaluate(f'''Object.fromEntries(Object.keys(localStorage)
            .filter(k => k.startsWith("{FAKE_PREFIX}")).sort()
            .map(k => [k.slice({len(FAKE_PREFIX)}), localStorage.getItem(k)]))''')
        size = sum(len(k) + len(v) for k, v in dump.items())
        log(f'fake data store={dump} total chars={size}')
        self.assertLess(size, 1024)
        if self.evidence:
            page.screenshot(path=str(self.out() / 'menu-after-reload.png'))
            (self.out() / 'data-dump.json').write_text(json.dumps(dump, indent=2) + '\n')

    def test_blocked_sdk_uses_local_storage(self):
        """(d) with the SDK blocked, records persist through localStorage."""
        page = self.boot(block_sdk=True)
        self.score_and_pause(page, 'classic', 4)
        self.score_and_pause(page, 'bad', 6)
        self.reload(page, block_sdk=True)
        texts = self.menu_texts(page)
        records = json.loads(page.evaluate('localStorage.getItem("grapnelninja.records")'))
        fake_keys = page.evaluate(
            f'Object.keys(localStorage).filter(k => k.startsWith("{FAKE_PREFIX}"))')
        log(f'(d) blocked SDK menu={texts} localStorage records={records} fake keys={fake_keys}')
        self.assertEqual(texts['classic'], 'record: 4')
        self.assertEqual(texts['bad'], 'record: 6')
        self.assertEqual(records, {'classic': 4, 'bad': 6})
        self.assertEqual(fake_keys, [])
        log('ASSERT (d) blocked SDK records persist via localStorage: pass')

    def test_set_item_calls_per_run(self):
        """(e) a 10-point run writes SDK.data at most twice."""
        page = self.boot()
        page.evaluate('startGame("classic")')
        before = len(sdk_calls(page))
        for _ in range(10):
            page.evaluate('changeScoreText()')
            page.wait_for_timeout(50)
        page.keyboard.press('Escape')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        calls = sdk_calls(page)[before:]
        sets = [c['args'] for c in calls if c['name'] == 'data.setItem']
        log(f'(e) setItem calls during 10-point run={len(sets)} {sets}')
        self.assertLessEqual(len(sets), 2)
        self.assertEqual(json.loads(page.evaluate(
            'CrazyGames.SDK.data.getItem("grapnelninja.records")'))['classic'],
            page.evaluate('scoreText.record.classic'))
        self.assertGreaterEqual(page.evaluate('scoreText.record.classic'), 10)
        log('ASSERT (e) setItem calls <= 2: pass')


if __name__ == '__main__':
    unittest.main()
