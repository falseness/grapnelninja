"""Storage and audio inside the cross-site itch iframe (TASK-166 harness).

The host page is loaded as http://localhost:<port>/ and the game from
http://127.0.0.1:<port>/, so the iframe is cross-site as on itch.io
(itch.io vs html-classic.itch.zone) and its storage is third-party.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import OfflineBrowser
from itch_harness import start_itch_embed
import test_itch_embed as embed
from playwright.sync_api import sync_playwright

VIEWPORT = {'width': 1920, 'height': 1080}
SCORE = 5
# Chromium switches tried to block third-party storage (scenario b probe)
BLOCK_ARGS = ['--block-third-party-cookies', '--test-third-party-cookie-phaseout']
BLOCK_PREFS = {'profile': {'block_third_party_cookies': True, 'cookie_controls_mode': 1,
                           'default_content_setting_values': {'cookies': 2}}}
LOCAL_STORAGE = '''() => { try { const s = window.localStorage
    if (!s) return {behaviour: 'empty', detail: String(s)}
    s.setItem('__probe', '1'); const back = s.getItem('__probe'); s.removeItem('__probe')
    return back === '1' ? {behaviour: 'works', detail: 'length ' + s.length}
                        : {behaviour: 'empty', detail: 'read back ' + back}
} catch (e) { return {behaviour: 'throws', detail: e.name + ': ' + e.message} } }'''
# Fallback when no switch blocks it: the game frame's localStorage throws
# SecurityError like a cross-origin iframe with blocked storage
THROWING_STORAGE = '''(origin => { if (location.origin !== origin) return
    Object.defineProperty(window, 'localStorage', {configurable: true, get() {
        throw new DOMException("Failed to read the 'localStorage' property from 'Window':"
                               + ' Access is denied for this document.', 'SecurityError') }})
})(%s)'''
SAVED = '''() => ({record: scoreText.record.classic, recordText: menu.classicRecord.text,
    muted: MUTE_BUTTON.muted, audioUserMuted: AUDIO.getState().muted.user,
    language: I18N.language, htmlLang: document.documentElement.lang})'''
STORED = '''() => { try { const s = window.localStorage, out = {}
    for (let i = 0; i < s.length; ++i) out[s.key(i)] = s.getItem(s.key(i))
    return out } catch (e) { return e.name } }'''
# Centre of a corner button (MUTE_BUTTON / LANGUAGE_BUTTON) in frame CSS px
CORNER_CENTER = '''name => {
    const b = name === 'mute' ? MUTE_BUTTON.rect('menu') : LANGUAGE_BUTTON.rect()
    const rect = canvas.getBoundingClientRect()
    return {x: rect.left + (b.x + b.width / 2) * rect.width / width,
            y: rect.top + (b.y + b.height / 2) * rect.height / height}
}'''
# At load of the game frame, before any input: user activation and the state
# of a probe AudioContext (page.evaluate runs with a user gesture, so it can't
# probe this). Only installed in the control context.
AUTOPLAY_PROBE = '''(origin => { if (location.origin !== origin) return
    window.__autoplay = {activationAtLoad: navigator.userActivation.hasBeenActive}
    const c = new AudioContext()
    window.__autoplay.probeContextState = c.state
    c.close()
})(%s)'''
# A spot of the menu with no button (bottom-left corner of the frame)
EMPTY_SPOT = (60, 500)


class ItchStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host_url, cls.game_origin, cls.game_url, _ = start_itch_embed(cls.addClassCleanup)
        # Another site than the game: localhost vs 127.0.0.1
        cls.host_url = host_url.replace('//127.0.0.1:', '//localhost:')
        cls.host_route = re.compile('^' + re.escape(cls.host_url))
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        browser = cls.playwright.chromium.launch(
            args=['--no-sandbox', '--autoplay-policy=user-gesture-required'])
        cls.addClassCleanup(browser.close)
        cls.browser = OfflineBrowser(browser)
        cls.save_evidence = bool(os.environ.get('ITCH_STORAGE_EVIDENCE_DIR'))
        cls.evidence = Path(os.environ.get('ITCH_STORAGE_EVIDENCE_DIR') or '.')
        cls.storage = {'host_url': cls.host_url, 'game_origin': cls.game_origin}
        cls.audio = {}

    def save(self, name, data):
        if self.save_evidence:
            self.evidence.mkdir(parents=True, exist_ok=True)
            (self.evidence / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')

    def new_context(self, init_script=None):
        context = self.browser.new_context(viewport=VIEWPORT, screen=VIEWPORT)
        self.addCleanup(context.close)
        context.route(self.host_route, lambda route: route.continue_())
        context.add_init_script(embed.ERROR_SPY)
        if init_script:
            context.add_init_script(init_script)
        return context

    def open(self, context):
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(self.host_url)
        return page, errors

    def play(self, page):
        frame = embed.ItchEmbedTests.play(self, page)
        self.assertEqual(frame.evaluate('location.origin'), self.game_origin)
        return frame

    def click_game(self, page, x, y):
        box = page.locator('#game_drop').bounding_box()
        page.mouse.click(box['x'] + x, box['y'] + y)

    def click_corner(self, page, frame, name):
        point = frame.evaluate(CORNER_CENTER, name)
        self.click_game(page, point['x'], point['y'])

    def click_button(self, page, frame, name):
        point = frame.evaluate(embed.BUTTON_CENTER, name)
        self.click_game(page, point['x'], point['y'])

    def frame_errors(self, page, frame):
        return page.evaluate('window.__errors') + frame.evaluate('window.__errors')

    def score_run(self, page, frame):
        """A classic run that scores SCORE points, dies and returns to the menu."""
        self.click_button(page, frame, 'classicVersionButton')
        frame.wait_for_function('version === "classic" && !menu.visible')
        frame.wait_for_function('window.__ticks > 10')
        frame.evaluate('n => { for (let i = 0; i < n; ++i) changeScoreText() }', SCORE)
        restarts = frame.evaluate('window.__reStarts')
        frame.evaluate('window.__kill = true')
        frame.wait_for_function('r => !window.__kill && window.__reStarts > r', arg=restarts)
        page.keyboard.press('Escape')
        frame.wait_for_function('menu.gamePaused')
        self.click_button(page, frame, 'backToMenu')
        frame.wait_for_function('menu.visible && !menu.gamePaused')

    def roundtrip(self, context):
        """Set record, mute and language; reload the host page; play again."""
        page, errors = self.open(context)
        frame = self.play(page)
        first = frame.evaluate(SAVED)
        stored_first = frame.evaluate(STORED)
        self.click_corner(page, frame, 'mute')
        frame.wait_for_function('MUTE_BUTTON.muted')
        self.click_corner(page, frame, 'language')
        frame.wait_for_function('I18N.language === "ru"')
        self.score_run(page, frame)
        before = frame.evaluate(SAVED)
        frame.wait_for_function('''n => { const v = localStorage.getItem('grapnelninja.records')
            return v && JSON.parse(v).classic === n && localStorage.getItem('grapnelninja.muted') === '1'
                && localStorage.getItem('grapnelninja.lang') === 'ru' }''', arg=SCORE)
        stored = frame.evaluate(STORED)
        self.assertEqual(self.frame_errors(page, frame), [])
        page.reload()
        self.assertEqual(page.locator('#game_drop').count(), 0)
        frame = self.play(page)
        after = frame.evaluate(SAVED)
        result = {'first_run': first, 'storage_at_first_run': stored_first,
                  'before_reload': before, 'storage_before_reload': stored,
                  'after_reload': after, 'local_storage': frame.evaluate(LOCAL_STORAGE),
                  'errors': self.frame_errors(page, frame) + errors}
        expected = {'record': SCORE, 'muted': True, 'audioUserMuted': True,
                    'language': 'ru', 'htmlLang': 'ru'}
        for key, value in expected.items():
            self.assertEqual(before[key], value, key)
            self.assertEqual(after[key], value, key)
        self.assertIn(str(SCORE), after['recordText'])
        self.assertEqual(result['errors'], [])
        return result, first, stored_first

    def test_a_restored_after_reload(self):
        result, first, _ = self.roundtrip(self.new_context())
        result['browser_flag'] = None
        self.storage['a_normal'] = result
        self.save('storage.json', self.storage)
        self.assertEqual(result['local_storage']['behaviour'], 'works')

    def probe_block_switches(self):
        """localStorage in the iframe under the third-party blocking switches and prefs."""
        profile = tempfile.mkdtemp(prefix='itch-3p-')
        self.addCleanup(shutil.rmtree, profile, True)
        (Path(profile) / 'Default').mkdir()
        (Path(profile) / 'Default' / 'Preferences').write_text(json.dumps(BLOCK_PREFS))
        context = self.playwright.chromium.launch_persistent_context(
            profile, args=['--no-sandbox'] + BLOCK_ARGS, viewport=VIEWPORT)
        try:
            context.route(self.host_route, lambda route: route.continue_())
            page = context.new_page()
            page.goto(self.host_url)
            page.click('#load_game')
            frame = page.wait_for_selector('#game_drop').content_frame()
            frame.wait_for_load_state()
            seen = frame.evaluate(LOCAL_STORAGE)
            version = context.browser.version if context.browser else None
        finally:
            context.close()
        return {'switches': BLOCK_ARGS, 'profile_prefs': BLOCK_PREFS,
                'chromium': version, 'iframe_local_storage': seen}

    def test_b_third_party_storage_blocked(self):
        probe = self.probe_block_switches()
        init_script = None
        if probe['iframe_local_storage']['behaviour'] == 'works':
            # Chromium partitions third-party storage instead of blocking it
            init_script = THROWING_STORAGE % json.dumps(self.game_origin)
        context = self.new_context(init_script)
        page, errors = self.open(context)
        frame = self.play(page)
        seen = frame.evaluate(LOCAL_STORAGE)
        frame_console = []
        page.on('console', lambda m: frame_console.append({'type': m.type, 'text': m.text}))
        self.click_corner(page, frame, 'mute')
        frame.wait_for_function('MUTE_BUTTON.muted')
        self.click_corner(page, frame, 'language')
        frame.wait_for_function('I18N.language === "ru"')
        self.score_run(page, frame)
        page.wait_for_timeout(1200)
        session = frame.evaluate(SAVED)
        reached_play = frame.evaluate('window.__ticks') > 10
        warnings = [m for m in frame_console if m['type'] == 'warning']
        page.reload()
        frame = self.play(page)
        after_reload = frame.evaluate(SAVED)
        all_errors = self.frame_errors(page, frame) + errors
        result = {'browser_flag': probe, 'fallback_init_script': bool(init_script),
                  'local_storage': seen, 'reached_play': reached_play,
                  'session_after_run': session, 'console_warnings': warnings,
                  'after_reload': after_reload,
                  'page_errors_and_unhandled_rejections': all_errors,
                  'error_count': len(all_errors)}
        self.storage['b_third_party_blocked'] = result
        self.save('storage.json', self.storage)
        self.assertIn(seen['behaviour'], ('throws', 'empty'))
        self.assertTrue(reached_play)
        self.assertEqual((session['record'], session['muted'], session['language']), (SCORE, True, 'ru'))
        self.assertIn(str(SCORE), session['recordText'])
        # Nothing persists without storage: the next load starts from defaults
        self.assertEqual((after_reload['record'], after_reload['muted']), (0, False))
        self.assertEqual(all_errors, [])

    def test_c_audio_after_gesture_and_mute(self):
        # Control: the autoplay policy is on, a context made without a gesture is suspended
        page, errors = self.open(self.new_context(AUTOPLAY_PROBE % json.dumps(self.game_origin)))
        frame = self.play(page)
        policy = frame.evaluate('window.__autoplay')
        context = self.new_context()
        page, errors = self.open(context)
        console = []
        page.on('console', lambda m: console.append({'type': m.type, 'text': m.text}))
        frame = self.play(page)
        page.wait_for_timeout(500)
        state = 'AUDIO.getState()'
        result = {'autoplay_policy_control': policy,
                  'after_click_to_play': frame.evaluate(state)}
        self.click_game(page, *EMPTY_SPOT)
        frame.wait_for_function('AUDIO.getState().state === "running"')
        result['after_first_input'] = frame.evaluate(state)
        result['menu_still_visible'] = frame.evaluate('menu.visible')
        self.click_corner(page, frame, 'mute')
        frame.wait_for_function('AUDIO.getState().state === "suspended"')
        result['mute_on'] = frame.evaluate(state)
        self.click_corner(page, frame, 'mute')
        frame.wait_for_function('AUDIO.getState().state === "running"')
        result['mute_off'] = frame.evaluate(state)
        result['audio_console'] = [m for m in console if 'audio' in m['text'].lower()]
        result['errors'] = self.frame_errors(page, frame) + errors
        self.audio.update(result)
        self.save('audio.json', self.audio)
        self.assertEqual(policy, {'activationAtLoad': False, 'probeContextState': 'suspended'})
        before = result['after_click_to_play']
        self.assertEqual((before['started'], before['state'], before['gain']), (False, None, None))
        self.assertEqual((result['after_first_input']['state'], result['after_first_input']['gain']),
                         ('running', 1))
        self.assertTrue(result['menu_still_visible'])
        self.assertEqual((result['mute_on']['gain'], result['mute_on']['muted']['user']), (0, True))
        self.assertEqual((result['mute_off']['gain'], result['mute_off']['muted']['user']), (1, False))
        self.assertEqual(result['audio_console'], [])
        self.assertEqual(result['errors'], [])

    def test_d_fresh_private_context(self):
        context = self.new_context()
        self.assertEqual(context.storage_state()['origins'], [])
        result, first, stored_first = self.roundtrip(context)
        result['browser_flag'] = None
        self.storage['d_fresh_context'] = result
        self.save('storage.json', self.storage)
        # First run: nothing stored, defaults shown
        self.assertEqual(stored_first, {})
        self.assertEqual((first['record'], first['muted'], first['language']), (0, False, 'en'))
        self.assertEqual(result['local_storage']['behaviour'], 'works')


if __name__ == '__main__':
    unittest.main()
