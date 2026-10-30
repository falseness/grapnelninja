"""TASK-793: rewarded-ad gate on the Grapple Over 'Go back' button.

Boots the real index.html, sets the go-back checkpoint with a real grapnel
catch and opens the 'Go back?' dialog with a scripted long fall (the
test_go_back_dialog helpers). PLATFORM_BACKEND.isRewardedSupported and
showRewarded are stubbed in the page; showRewarded returns a promise the test
settles itself, so the state while the ad is up is checked too (run paused,
buttons and keys disabled, game audio muted). Result handling: 'rewarded',
'failed' and 'unavailable' go back, 'closed' closes the dialog and keeps
falling, an unknown value or a rejection goes back, no answer within 30 s
goes back and a late answer changes nothing; without rewarded support there
is no marker, no ad call and Go back is free. Every case compares the
ANALYTICS.ad calls with platform.js AD_ACTIONS (type 'rewarded', placement
'go_back').

GO_BACK_AD_EVIDENCE_DIR=DIR writes cases.json (one row per case) and the
dialog-ad-en.png / dialog-ad-ru.png / dialog-free-en.png (1706x932) and
dialog-ad-touch.png (932x430 touch) screenshots there.

    python3 -m unittest discover -s tools -p test_go_back_ad.py -v
"""
import json
import os
import re
from pathlib import Path
import unittest

import test_go_back_dialog as base

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_MS = 30000

# platform.js: result -> ANALYTICS.ad action (results not listed send nothing)
AD_ACTIONS = dict(re.findall(r"(\w+): '(\w+)'", re.search(
    r'const AD_ACTIONS = \{([^}]*)\}', (ROOT / 'platform.js').read_text()).group(1)))

# Stub the backend's rewarded methods and record ANALYTICS.ad calls. Each
# showRewarded call returns a pending promise; AD.settle(kind, value) resolves
# or rejects the latest one.
STUB = '''supported => {
    window.AD = {supported, calls: [], analytics: [], pending: null,
        settle(kind, value) { const p = AD.pending; AD.pending = null; p[kind](value) }}
    PLATFORM_BACKEND.isRewardedSupported = () => AD.supported
    PLATFORM_BACKEND.showRewarded = placement => {
        AD.calls.push(placement)
        return new Promise((resolve, reject) => { AD.pending = {resolve, reject} })
    }
    const ad = ANALYTICS.ad
    ANALYTICS.ad = function(...args) { AD.analytics.push(args); return ad.apply(this, args) }
}'''

AD_STATE = '''() => ({...STATE(), adPending: CLIMB_UI.goBackAdPending, muted: GAME_AUDIO.muted,
    clickable: CLIMB_UI.buttons.map(b => b.clickable), calls: AD.calls.slice(),
    analytics: AD.analytics.slice(), language: LANGUAGE_BUTTON.active(),
    marker: (() => { LAYOUT_PROBE.boxes = []; redrawOverlays()
        const boxes = LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes = null
        return boxes.filter(b => b.kind === 'adMarker').map(b => b.name) })()})'''

# Settle the latest ad request, then let the promise chain run
SETTLE = '''async ([kind, value]) => { AD.settle(kind, value)
    for (let i = 0; i < 5; i++) await Promise.resolve()
    await new Promise(r => setTimeout(r, 0)) }'''


class GoBackAdTests(unittest.TestCase):
    open_page = base.GoBackDialogTests.open
    catch = base.GoBackDialogTests.catch
    checkpoint = base.GoBackDialogTests.checkpoint
    long_fall = base.GoBackDialogTests.long_fall
    button = base.GoBackDialogTests.button

    @classmethod
    def setUpClass(cls):
        base.GoBackDialogTests.setUpClass.__func__(cls)
        cls.out = os.environ.get('GO_BACK_AD_EVIDENCE_DIR')
        cls.cases = []

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        if cls.out:
            Path(cls.out).mkdir(parents=True, exist_ok=True)
            Path(cls.out, 'cases.json').write_text(json.dumps(cls.cases, indent=1, sort_keys=True) + '\n')

    def open(self, supported=True, **kw):
        page = self.open_page(**kw)
        page.evaluate(STUB, supported)
        return page

    def state(self, page):
        return page.evaluate(AD_STATE)

    def ticks(self, page, n):
        """n production physics ticks, then the state."""
        page.evaluate('n => { for (let i = 0; i < n; i++) physics() }', n)
        return self.state(page)

    def dialog(self, page):
        """Checkpoint, long fall, dialog up; returns (checkpoint, opened state)."""
        cp = self.checkpoint(page)
        self.long_fall(page)
        opened = self.state(page)
        self.assertTrue(opened['dialog'] and opened['paused'])
        return cp, opened

    def click(self, page, i):
        p = self.button(page, i)
        page.mouse.click(p['x'], p['y'])

    def expected_analytics(self, result):
        return [[AD_ACTIONS[result], 'rewarded', 'go_back']] if result in AD_ACTIONS else []

    def assert_waiting(self, page, opened):
        """The ad is up: paused, buttons/keys/language disabled, audio muted,
        Keep falling and Escape ignored, physics frozen."""
        waiting = self.state(page)
        self.click(page, 1)
        page.keyboard.press('Escape')
        page.keyboard.press('Enter')
        frozen = self.ticks(page, 100)
        self.assertTrue(waiting['adPending'] and waiting['paused'] and waiting['dialog'] and waiting['open'])
        self.assertTrue(waiting['muted'])
        self.assertEqual(waiting['clickable'], [False, False])
        self.assertFalse(waiting['language'])
        self.assertEqual(waiting['calls'], ['go_back'])
        for key in ('ninja', 'speed', 'elapsed', 'timeInGame', 'goBacks', 'falls', 'paused', 'dialog', 'adPending',
                    'calls'):
            self.assertEqual(frozen[key], waiting[key], key)
        self.assertEqual(waiting['ninja'], opened['ninja'])
        return waiting

    def assert_back(self, row, cp, opened):
        self.assertFalse(row['paused'] or row['dialog'] or row['adPending'])
        self.assertTrue(row['grapnel']['grappled'])
        self.assertEqual(row['grapnel']['anchor'], [cp['anchorX'], cp['anchorY']])
        self.assertEqual(row['goBacks'], opened['goBacks'] + 1)
        self.assertEqual(row['recoveries'], 0)
        self.assertTrue(row['goBackArmed'])

    def assert_kept_falling(self, row, opened):
        self.assertFalse(row['paused'] or row['dialog'] or row['adPending'])
        self.assertEqual(row['goBacks'], opened['goBacks'])
        self.assertFalse(row['grapnel']['grappled'])
        self.assertGreater(row['ninja'][1], opened['ninja'][1])
        self.assertFalse(row['goBackArmed'])

    def run_case(self, name, settle, went_back, analytics_result, keyboard=False):
        page = self.open()
        cp, opened = self.dialog(page)
        self.assertEqual(opened['marker'], ['AD'])
        if keyboard:
            page.keyboard.press('Enter')
        else:
            self.click(page, 0)
        waiting = self.assert_waiting(page, opened)
        page.evaluate(SETTLE, list(settle))
        # Keep falling: one tick (more would reach the spawn recovery)
        after = self.ticks(page, 30 if went_back else 1)
        if went_back:
            self.assert_back(after, cp, opened)
        else:
            self.assert_kept_falling(after, opened)
        self.assertFalse(after['muted'])
        self.assertEqual(after['calls'], ['go_back'])
        self.assertEqual(after['analytics'], self.expected_analytics(analytics_result))
        self.cases.append({'case': name, 'supported': True, 'settle': list(settle), 'input': 'Enter' if keyboard else 'mouse',
                           'marker': opened['marker'], 'showRewarded_calls': after['calls'],
                           'while_ad': {k: waiting[k] for k in ('paused', 'dialog', 'adPending', 'muted', 'clickable',
                                                                 'language')},
                           'went_back': after['goBacks'] == opened['goBacks'] + 1,
                           'dialog_closed': not after['dialog'], 'paused_after': after['paused'],
                           'muted_after': after['muted'], 'anchor': after['grapnel']['anchor'],
                           'checkpoint': [cp['anchorX'], cp['anchorY']],
                           'analytics': after['analytics'],
                           'expected_analytics': self.expected_analytics(analytics_result), 'pass': True})
        return page, after

    def test_01_rewarded(self):
        self.run_case('rewarded', ('resolve', 'rewarded'), True, 'rewarded')

    def test_02_failed(self):
        self.run_case('failed', ('resolve', 'failed'), True, 'failed')

    def test_03_unavailable(self):
        self.run_case('unavailable', ('resolve', 'unavailable'), True, 'unavailable', keyboard=True)

    def test_04_closed(self):
        page, after = self.run_case('closed', ('resolve', 'closed'), False, 'closed')
        # Closed early does not count: the fall goes on to the spawn recovery
        down = page.evaluate(base.FALL, [2000, None])
        self.assertEqual(down['recoveries'], 1)
        self.assertFalse(down['dialog'])

    def test_05_other_value_and_rejection(self):
        # PLATFORM passes an unknown value on as 'unavailable' and a rejection
        # as its default 'unavailable': both go back, no analytics
        self.run_case('other_value', ('resolve', 'weird'), True, 'unavailable')
        self.run_case('rejected', ('reject', 'sdk error'), True, 'unavailable')

    def test_06_unsupported_free(self):
        page = self.open(supported=False)
        cp, opened = self.dialog(page)
        self.assertEqual(opened['marker'], [])
        self.click(page, 0)
        after = self.ticks(page, 30)
        self.assert_back(after, cp, opened)
        self.assertEqual(after['calls'], [])
        self.assertEqual(after['analytics'], [])
        self.assertFalse(after['muted'])
        self.cases.append({'case': 'unsupported', 'supported': False, 'input': 'mouse', 'marker': opened['marker'],
                           'showRewarded_calls': after['calls'], 'went_back': True, 'dialog_closed': not after['dialog'],
                           'paused_after': after['paused'], 'muted_after': after['muted'],
                           'anchor': after['grapnel']['anchor'], 'checkpoint': [cp['anchorX'], cp['anchorY']],
                           'analytics': after['analytics'], 'expected_analytics': [], 'pass': True})

    def test_07_no_answer_in_30s(self):
        page = self.open()
        self.assertEqual(page.evaluate('CLIMB_UI.goBackAdTimeoutMs'), TIMEOUT_MS)
        cp, opened = self.dialog(page)
        self.click(page, 0)
        waiting = self.assert_waiting(page, opened)
        page.wait_for_timeout(TIMEOUT_MS - 2000)
        before = self.state(page)
        self.assertTrue(before['adPending'] and before['dialog'] and before['paused'])
        page.wait_for_timeout(3000)
        timed = self.ticks(page, 30)
        # Handled like 'failed': goes back; nothing resolved, so no analytics
        self.assert_back(timed, cp, opened)
        self.assertFalse(timed['muted'])
        self.assertEqual(timed['analytics'], [])
        # A late 'closed' changes nothing in the game; PLATFORM reports it
        page.evaluate(SETTLE, ['resolve', 'closed'])
        late = self.ticks(page, 30)
        self.assertFalse(late['paused'] or late['dialog'] or late['adPending'])
        self.assertEqual(late['goBacks'], timed['goBacks'])
        self.assertEqual(late['grapnel']['anchor'], timed['grapnel']['anchor'])
        self.assertEqual(late['analytics'], self.expected_analytics('closed'))
        self.cases.append({'case': 'no_answer_30s', 'supported': True, 'input': 'mouse', 'marker': opened['marker'],
                           'showRewarded_calls': timed['calls'],
                           'while_ad': {k: waiting[k] for k in ('paused', 'dialog', 'adPending', 'muted', 'clickable',
                                                                 'language')},
                           'pending_at_28s': before['adPending'], 'went_back': timed['goBacks'] == opened['goBacks'] + 1,
                           'dialog_closed': not timed['dialog'], 'paused_after': timed['paused'],
                           'muted_after': timed['muted'], 'anchor': timed['grapnel']['anchor'],
                           'checkpoint': [cp['anchorX'], cp['anchorY']], 'analytics': timed['analytics'],
                           'expected_analytics': [], 'late_closed': {'goBacks_unchanged': True, 'dialog': late['dialog'],
                                                                     'analytics': late['analytics']},
                           'pass': True})

    def test_08_screenshots(self):
        shots = {}
        for name, supported, viewport, touch, lang in (
                ('dialog-ad-en', True, (1706, 932), False, 'en'),
                ('dialog-ad-ru', True, (1706, 932), False, 'ru'),
                ('dialog-free-en', False, (1706, 932), False, 'en'),
                ('dialog-ad-touch', True, (932, 430), True, 'en')):
            page = self.open(supported=supported, viewport=viewport, touch=touch, lang=lang)
            _, row = self.dialog(page)
            # The marker sits inside Go back, clear of its label
            boxes = page.evaluate('''() => { LAYOUT_PROBE.boxes = []; redrawOverlays()
                const b = LAYOUT_PROBE.boxes; LAYOUT_PROBE.boxes = null; return b }''')
            marker = [b for b in boxes if b['kind'] == 'adMarker']
            if supported:
                self.assertEqual(len(marker), 1)
                button = next(b for b in boxes if b['kind'] == 'button' and b['name'] == row['buttons'][0])
                label = [b for b in boxes if b['kind'] == 'text' and b['name'] == row['buttons'][0]]
                m = marker[0]
                self.assertGreaterEqual(m['x'], button['x'])
                self.assertLessEqual(m['x'] + m['width'], button['x'] + button['width'])
                for t in label:
                    self.assertLess(t['x'] + t['width'], m['x'])
            else:
                self.assertEqual(marker, [])
            shots[name] = {'buttons': row['buttons'], 'marker': [b['name'] for b in marker], 'viewport': list(viewport)}
            if self.out:
                Path(self.out).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(self.out, name + '.png')))
        self.assertEqual(shots['dialog-ad-en']['marker'], ['AD'])
        self.assertEqual(shots['dialog-ad-ru']['marker'], ['РЕКЛАМА'])
        self.assertEqual(shots['dialog-ad-ru']['buttons'], ['Вернуться', 'Падать дальше'])
        self.cases.append({'case': 'screenshots', 'shots': shots, 'pass': True})


if __name__ == '__main__':
    unittest.main()
