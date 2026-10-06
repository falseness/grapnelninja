"""Records, time in game and settings persist through PLATFORM storage (localStorage)."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import (local_store, open_game, seed_store, start_game_test,
                          storage_calls as all_storage_calls)

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
RECORDS_KEY = 'grapnelninja.records'
TIME_KEY = 'grapnelninja.time'
KEYS = [RECORDS_KEY, TIME_KEY, 'grapnelninja.lang']
READY = ('PLATFORM.environment !== "pending" && menu.visible'
         ' && document.getElementById("loading").hidden')


def log(message):
    print('  ' + message, file=sys.stderr)


def storage_calls(page, name):
    return [c for c in all_storage_calls(page) if c['name'] == name]


class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('PROGRESS_EVIDENCE_DIR')

    @classmethod
    def out(cls):
        out = Path(cls.evidence)
        out.mkdir(parents=True, exist_ok=True)
        return out

    def boot(self):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        # Freeze physics so the ninja never dies on its own: run ends come
        # only from the test's own reStart() calls.
        page.evaluate('runFixedPhysics = function () {}')
        self.assertEqual(page.evaluate('PLATFORM.environment'), 'local')
        return page

    def reload(self, page):
        page.reload()
        page.wait_for_function(READY)
        page.evaluate('runFixedPhysics = function () {}')

    def fake_store(self, page):
        return local_store(page)

    def seed_and_reload(self, page, store):
        seed_store(page, store)
        self.reload(page)

    def score(self, page, mode, points):
        page.evaluate('''([mode, points]) => {
            startGame(mode)
            for (let i = 0; i < points; ++i) changeScoreText()
        }''', [mode, points])

    def wait_throttle(self, page):
        page.wait_for_timeout(1100)

    def menu_texts(self, page):
        return page.evaluate('''({classic: menu.classicRecord.text,
            bad: menu.badRecord.text, time: menu.timeInGame.text})''')

    def test_boot_reads_all_keys_with_one_get(self):
        """One storage.get at boot carries every PROGRESS key; no set at boot."""
        page = self.boot()
        gets = storage_calls(page, 'storage.get')
        log(f'boot gets={[c["args"] for c in gets]}')
        self.assertEqual(len(gets), 1)
        self.assertEqual(gets[0]['args'][0], KEYS)
        self.assertEqual(page.evaluate('PROGRESS.keys'), KEYS)
        self.assertEqual(storage_calls(page, 'storage.set'), [])

    def test_records_survive_reload(self):
        """Classic and bad records come back from localStorage after reload."""
        page = self.boot()
        self.score(page, 'classic', 7)
        page.evaluate('reStart()')
        self.wait_throttle(page)
        self.score(page, 'bad', 5)
        page.evaluate('menu.startPause()')
        self.reload(page)
        texts = self.menu_texts(page)
        records = json.loads(self.fake_store(page)[RECORDS_KEY])
        log(f'after reload menu={texts} stored={records}')
        self.assertEqual((texts['classic'], texts['bad']), ('record: 7', 'record: 5'))
        self.assertEqual(records, {'classic': 7, 'bad': 5})
        self.assertEqual(page.evaluate('[scoreText.record.classic, scoreText.record.bad]'),
                         [7, 5])

    def test_time_and_settings_survive_reload(self):
        """Time in game and the lang key round-trip."""
        page = self.boot()
        self.seed_and_reload(page, {TIME_KEY: '125', 'grapnelninja.lang': 'ru'})
        state = page.evaluate('[PROGRESS.getTime(), PROGRESS.getLang()]')
        log(f'seeded state={state} menu time={self.menu_texts(page)["time"]!r}')
        self.assertEqual(state, [125, 'ru'])
        # Since TASK-126 the saved 'ru' also switches the menu to Russian
        self.assertEqual(self.menu_texts(page)['time'], 'время в игре: 2 мин.')

        page.evaluate('''() => {
            PROGRESS.setTime(PROGRESS.getTime() + 60)
            PROGRESS.setLang('en')
            PROGRESS.save()
        }''')
        self.reload(page)
        state = page.evaluate('[PROGRESS.getTime(), PROGRESS.getLang()]')
        log(f'after save+reload state={state}')
        self.assertEqual(state, [185, 'en'])
        self.assertIn('3 minutes', self.menu_texts(page)['time'])

    def test_corrupt_values_fall_back_to_defaults(self):
        """Corrupt JSON, NaN, negative and junk values load as defaults."""
        page = self.boot()
        cases = [
            {RECORDS_KEY: '{not json', TIME_KEY: 'NaN'},
            {RECORDS_KEY: '{"classic":"NaN","bad":-4}', TIME_KEY: '-30'},
            {RECORDS_KEY: 'null', TIME_KEY: 'Infinity', 'grapnelninja.lang': ''},
            {RECORDS_KEY: '[1,2]', TIME_KEY: '{"a":1}'},
        ]
        for store in cases:
            self.seed_and_reload(page, store)
            state = page.evaluate('''[scoreText.record.classic, scoreText.record.bad,
                PROGRESS.getTime(), PROGRESS.getLang()]''')
            log(f'seed={store} -> state={state}')
            self.assertEqual(state, [0, 0, 0, None])
            texts = self.menu_texts(page)
            self.assertEqual((texts['classic'], texts['bad']), ('record: 0', 'record: 0'))
            self.assertIn(' 0 minutes', texts['time'])
        self.score(page, 'classic', 3)
        page.evaluate('reStart()')
        self.assertEqual(json.loads(self.fake_store(page)[RECORDS_KEY]),
                         {'classic': 3, 'bad': 0})

    def test_local_storage_keys(self):
        """Progress goes to localStorage under exactly PROGRESS.keys and survives reload."""
        page = self.boot()
        self.score(page, 'classic', 4)
        page.evaluate('reStart()')
        self.wait_throttle(page)
        self.score(page, 'bad', 6)
        page.evaluate('menu.startPause()')
        local = page.evaluate(f'localStorage.getItem("{RECORDS_KEY}")')
        self.reload(page)
        texts = self.menu_texts(page)
        dump = page.evaluate('''Object.fromEntries(Object.keys(localStorage).sort()
            .map(k => [k, localStorage.getItem(k)]))''')
        log(f'localStorage={dump} menu={texts}')
        self.assertEqual(json.loads(local), {'classic': 4, 'bad': 6})
        self.assertEqual((texts['classic'], texts['bad']), ('record: 4', 'record: 6'))
        self.assertEqual(sorted(dump), sorted(KEYS))

    def test_saves_only_on_meaningful_change(self):
        """No set per point or per frame; one set (all keys) on pause and run end."""
        page = self.boot()
        page.evaluate('startGame("classic")')
        for _ in range(10):
            page.evaluate('changeScoreText()')
            page.wait_for_timeout(50)
        page.wait_for_timeout(500)
        during = len(storage_calls(page, 'storage.set'))
        page.keyboard.press('Escape')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        after_pause = storage_calls(page, 'storage.set')
        log(f'sets during 10 points={during} after pause={len(after_pause)}')
        self.assertEqual(during, 0)
        self.assertEqual(len(after_pause), 1)
        self.assertEqual(after_pause[0]['args'][0], KEYS)

        page.keyboard.press('Escape')
        self.wait_throttle(page)
        for _ in range(15):
            page.evaluate('changeScoreText()')
        page.evaluate('reStart()')
        sets = storage_calls(page, 'storage.set')
        log(f'sets after run end={len(sets)}')
        self.assertEqual(len(sets), 2)
        self.assertEqual(sets[1]['args'][0], KEYS)
        # Nothing changed: a further run end writes nothing
        self.wait_throttle(page)
        page.evaluate('reStart()')
        page.wait_for_timeout(300)
        self.assertEqual(len(storage_calls(page, 'storage.set')), 2)

    def test_throttle_one_set_per_second(self):
        """Rapid saves collapse into one trailing set, >= 1 s after the last."""
        page = self.boot()
        page.evaluate('''() => {
            startGame("classic")
            for (let i = 0; i < 5; ++i) {
                changeScoreText()
                PROGRESS.save()
            }
        }''')
        page.wait_for_timeout(1500)
        sets = storage_calls(page, 'storage.set')
        gaps = [b['t'] - a['t'] for a, b in zip(sets, sets[1:])]
        log(f'sets={len(sets)} gaps={gaps} values={[c["args"][1] for c in sets]}')
        self.assertEqual(len(sets), 2)
        self.assertTrue(all(g >= 990 for g in gaps))
        self.assertEqual(json.loads(sets[-1]['args'][1][0]),
                         {'classic': 5, 'bad': 0})

    def test_pagehide_flushes_new_record(self):
        """Closing the tab mid-run keeps a new record."""
        page = self.boot()
        self.score(page, 'classic', 5)
        self.assertNotIn(RECORDS_KEY, self.fake_store(page))
        page.evaluate('window.dispatchEvent(new PageTransitionEvent("pagehide"))')
        records = json.loads(self.fake_store(page)[RECORDS_KEY])
        log(f'after pagehide records={records}')
        self.assertEqual(records['classic'], 5)

    def test_scripted_session_storage_calls(self):
        """Boot, 2 runs with a new record, menu, reload: 1 get per boot,
        <= 1 set per run end, every set carries all keys."""
        page = self.boot()
        boots = []
        session = {'steps': []}

        def snap(step):
            calls = all_storage_calls(page)
            session['steps'].append({'step': step, 'storageCallsSoFar': len(calls)})
            return calls

        snap('boot')
        for run, points in ((1, 4), (2, 9)):
            before = len(storage_calls(page, 'storage.set'))
            self.score(page, 'classic', points)
            page.evaluate('reStart()')
            after = len(storage_calls(page, 'storage.set'))
            session['steps'].append({'step': f'run {run} end', 'record': points,
                                     'setsThisRunEnd': after - before})
            self.assertLessEqual(after - before, 1)
            self.wait_throttle(page)
        page.evaluate('menu.startPause(); menu.backToMenu.click()')
        self.wait_throttle(page)
        self.assertTrue(page.evaluate('menu.visible'))
        boots.append(snap('menu'))
        self.reload(page)
        boots.append(snap('reload'))
        self.assertEqual(page.evaluate('menu.classicRecord.text'), 'record: 9')

        for i, calls in enumerate(boots):
            gets = [c for c in calls if c['name'] == 'storage.get']
            sets = [c for c in calls if c['name'] == 'storage.set']
            self.assertEqual(len(gets), 1, f'boot {i}')
            for c in sets:
                self.assertEqual(c['args'][0], KEYS)
                self.assertEqual(len(c['args'][1]), len(KEYS))
        session['boots'] = [{
            'boot': i + 1,
            'storageGetCount': sum(c['name'] == 'storage.get' for c in calls),
            'storageSetCount': sum(c['name'] == 'storage.set' for c in calls),
            'everySetHasAllKeys': all(c['args'][0] == KEYS for c in calls
                                      if c['name'] == 'storage.set'),
            'calls': calls,
        } for i, calls in enumerate(boots)]
        session['keys'] = KEYS
        log(f'session boots: ' + ', '.join(
            f'boot {b["boot"]} get={b["storageGetCount"]} set={b["storageSetCount"]}'
            for b in session['boots']))
        if self.evidence:
            (self.out() / 'storage-calls.json').write_text(
                json.dumps(session, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
