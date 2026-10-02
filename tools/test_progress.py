"""Records and time-in-game persist through PLATFORM.storage (GamePix)."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamepix_harness import open_game, sdk_calls, sdk_errors, start_gamepix_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
RECORDS_KEY = 'grapnelninja.records'
TIME_KEY = 'grapnelninja.time'
READY = ('typeof menu !== "undefined" && menu.visible'
         ' && !document.getElementById("loading")'
         ' && PLATFORM.environment === "%s"')
STORAGE_CALLS = ('localStorage.getItem', 'localStorage.setItem',
                 'localStorage.removeItem')
# Count every window.localStorage write of the records key in
# window.__recordWrites (the fake GamePix storage writes through to it)
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


def storage_calls(page):
    return [c for c in sdk_calls(page) if c['name'] in STORAGE_CALLS]


class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_gamepix_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('GAMEPIX_PROGRESS_EVIDENCE_DIR')
        cls.errors = []
        cls.check = {}

    @classmethod
    def tearDownClass(cls):
        if cls.evidence:
            out = cls.out()
            for kind in ('console', 'page'):
                lines = [f'{name}: {msg}' for name, errors in cls.errors
                         for msg in errors[kind]]
                (out / f'{kind}-errors.log').write_text(''.join(
                    line + '\n' for line in lines))
            (out / 'progress-check.json').write_text(
                json.dumps(cls.check, indent=2) + '\n')

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
        if not block_sdk:
            # Fake SDK errors (non-string storage, call before loaded) fail
            self.addCleanup(lambda: self.assertEqual(sdk_errors(page), []))
        page.goto(self.url + 'index.html')
        self.wait_ready(page, block_sdk)
        return page

    def wait_ready(self, page, block_sdk=False):
        page.wait_for_function(READY % ('disabled' if block_sdk else 'gamepix'))

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

    def test_record_survives_reload_via_sdk_storage(self):
        """Classic record goes through GamePix.localStorage.setItem (strings)."""
        page = self.boot()
        self.score_and_pause(page, 'classic', 7)
        calls = storage_calls(page)
        writes = [c for c in calls if c['name'] == 'localStorage.setItem'
                  and c['args'][0] == RECORDS_KEY]
        log(f'record writes={[c["args"] for c in writes]}')
        self.assertEqual(len(writes), 1)
        self.assertEqual(json.loads(writes[0]['args'][1]), {'classic': 7, 'bad': 0})
        for c in calls:
            self.assertTrue(all(isinstance(a, str) for a in c['args']), c)
        errors_before_reload = sdk_errors(page)

        self.reload(page)
        texts = self.menu_texts(page)
        reads = [c['args'] for c in storage_calls(page)
                 if c['name'] == 'localStorage.getItem']
        log(f'after reload menu={texts} sdk getItem={reads}')
        self.assertEqual(texts['classic'], 'record: 7')
        self.assertEqual(texts['bad'], 'record: 0')
        self.assertIn([RECORDS_KEY], reads)
        self.assertEqual(page.evaluate('scoreText.record.classic'), 7)

        self.score_and_pause(page, 'bad', 5)
        self.reload(page)
        self.assertEqual(self.menu_texts(page)['bad'], 'record: 5')
        self.assertEqual(self.stored_records(page), {'classic': 7, 'bad': 5})
        log('ASSERT classic record 7 survives reload via GamePix.localStorage: pass')
        self.check['sdk'] = {
            'environment': page.evaluate('PLATFORM.environment'),
            'menu_after_reload': texts,
            'records_setItem_calls': [c['args'] for c in writes],
            'all_storage_args_strings': True,
            'errors_before_reload': errors_before_reload,
            'errors': sdk_errors(page),
        }
        if self.evidence:
            page.screenshot(path=str(self.out() / 'menu-after-reload.png'))

    def test_no_storage_call_before_loaded(self):
        """Every GamePix.localStorage call comes after GamePix.loaded()."""
        page = self.boot()
        names = [c['name'] for c in sdk_calls(page)]
        self.assertEqual(names.count('loaded'), 1)
        first_loaded = names.index('loaded')
        early = [n for n in names[:first_loaded] if n in STORAGE_CALLS]
        log(f'calls={names}')
        self.assertEqual(early, [])
        self.assertTrue(any(n in STORAGE_CALLS for n in names[first_loaded:]))
        self.assertEqual(sdk_errors(page), [])
        self.check['order'] = {'calls': names, 'storage_before_loaded': early,
                               'errors': sdk_errors(page)}

    def test_legacy_time_migration(self):
        """Legacy 'time' moves to grapnelninja.time once, via SDK storage."""
        page = self.boot()
        page.evaluate(f'''() => {{
            localStorage.removeItem("{TIME_KEY}")
            localStorage.setItem("time", "125")
        }}''')
        self.reload(page)
        stored = page.evaluate(f'localStorage.getItem("{TIME_KEY}")')
        legacy = page.evaluate('localStorage.getItem("time")')
        texts = self.menu_texts(page)
        calls = [[c['name'], c['args']] for c in storage_calls(page)]
        log(f'{TIME_KEY}={stored!r} legacy={legacy!r} menu={texts["time"]!r}')
        self.assertEqual(stored, '125')
        self.assertIsNone(legacy)
        self.assertIn('2 minutes', texts['time'])
        self.assertIn(['localStorage.setItem', [TIME_KEY, '125']], calls)
        self.assertIn(['localStorage.removeItem', ['time']], calls)

        # A second load must not migrate again or touch the stored time
        self.reload(page)
        self.assertEqual(page.evaluate(f'localStorage.getItem("{TIME_KEY}")'), '125')
        log('ASSERT legacy time=125 migrated, legacy removed, "2 minutes": pass')
        self.check['migration'] = {'stored_time': stored, 'legacy_after': legacy,
                                   'menu_time': texts['time'],
                                   'storage_calls': calls,
                                   'errors': sdk_errors(page)}

    def test_blocked_sdk_falls_back_to_window_storage(self):
        """With the SDK blocked, records persist in window.localStorage."""
        page = self.boot(block_sdk=True)
        self.assertFalse(page.evaluate('"GamePix" in window'))
        self.score_and_pause(page, 'classic', 4)
        self.score_and_pause(page, 'bad', 6)
        self.reload(page, block_sdk=True)
        texts = self.menu_texts(page)
        records = self.stored_records(page)
        log(f'blocked SDK menu={texts} records={records}')
        self.assertEqual(texts['classic'], 'record: 4')
        self.assertEqual(texts['bad'], 'record: 6')
        self.assertEqual(records, {'classic': 4, 'bad': 6})
        log('ASSERT blocked SDK records persist: pass')
        self.check['fallback'] = {
            'environment': page.evaluate('PLATFORM.environment'),
            'gamepix_defined': page.evaluate('"GamePix" in window'),
            'menu_after_reload': texts, 'window_localStorage_records': records}

    def test_records_written_only_on_run_end_or_pause(self):
        """No write per point; one write on pause and on run end."""
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
        log(f'record writes during 10 points={during} after pause={after_pause}')
        self.assertEqual(during, 0)
        self.assertEqual(after_pause, 1)

        page.keyboard.press('Escape')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        for _ in range(15):
            page.evaluate('changeScoreText()')
        self.assertEqual(page.evaluate('window.__recordWrites'), 1)
        page.evaluate('reStart()')
        self.assertEqual(page.evaluate('window.__recordWrites'), 2)
        self.assertEqual(self.stored_records(page)['classic'],
                         page.evaluate('scoreText.record.classic'))
        log('ASSERT 0 writes per point, 1 on pause, 1 on run end: pass')

    def test_pagehide_saves_new_record(self):
        """Closing the tab mid-run keeps a new record."""
        page = self.boot()
        page.evaluate('''() => {
            startGame("classic")
            for (let i = 0; i < 5; ++i) changeScoreText()
        }''')
        self.assertIsNone(page.evaluate(f'localStorage.getItem("{RECORDS_KEY}")'))
        page.evaluate('window.dispatchEvent(new PageTransitionEvent("pagehide"))')
        self.assertEqual(self.stored_records(page)['classic'], 5)
        log('ASSERT pagehide saves the new record: pass')

    def test_corrupt_records_tolerated(self):
        """Corrupt JSON in the records key boots with zero records."""
        page = self.boot()
        page.evaluate(f'localStorage.setItem("{RECORDS_KEY}", "{{not json")')
        self.reload(page)
        texts = self.menu_texts(page)
        log(f'corrupt records menu={texts}')
        self.assertEqual((texts['classic'], texts['bad']), ('record: 0', 'record: 0'))
        self.score_and_pause(page, 'classic', 3)
        self.assertEqual(self.stored_records(page), {'classic': 3, 'bad': 0})
        log('ASSERT corrupt JSON tolerated, next save overwrites it: pass')
        self.check['corrupt'] = {'menu_after_reload': texts,
                                 'records_after_save': self.stored_records(page),
                                 'errors': sdk_errors(page)}


if __name__ == '__main__':
    unittest.main()
