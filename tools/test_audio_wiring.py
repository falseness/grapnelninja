"""Sounds wired into gameplay, the speaker mute button, pause during the ad.

Every gameplay event is checked through window.__audioLog (audio.js logs
each AUDIO.play). The mute button toggles the 'user' mute source and is
saved under grapnelninja.muted. The pause-during-ad tests are the TASK-107
g05/g06 cases: a hidden tab or a window blur while the rewarded ad plays
pauses the run right after the respawn.

Env: AUDIO_WIRING_EVIDENCE_DIR receives event-sounds.json, mute-persist.json,
hit-areas.json, pause-during-ad.json and screens/{menu,pause,hud}-WxH.png.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import playgama_harness as harness
from playgama_harness import (bridge_calls, bridge_errors, open_game,
                              start_playgama_test)

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
PORTRAIT = {'width': 390, 'height': 844}
MUTED_KEY = 'grapnelninja.muted'
READY = ('PLATFORM.environment !== "pending" && menu.visible'
         ' && document.getElementById("loading").hidden')
# The rewarded ad stays 'opened' long enough to act while it plays
# 5 s: the ad must still be open when a loaded host gets to the blur/hidden check
SLOW_REWARD = {'rewardedSeq': ['loading', 'opened',
                               {'state': 'rewarded', 'delayMs': 5000}, 'closed']}

# Keep the ninja where it is after every physics tick so it never dies on its
# own; while the continue offer is shown the ninja is left alone.
PIN_NINJA = '''() => {
    const physicsStep = window.physics
    window.physics = function() {
        const result = physicsStep.apply(this, arguments)
        if (continueOffer.visible)
            return result
        if (!window.__pin || window.__pinNinja !== ninja)
        {
            window.__pin = {x: ninja.x, y: ninja.y}
            window.__pinNinja = ninja
        }
        ninja.x = window.__pin.x
        ninja.y = window.__pin.y
        ninja.speedX = 0
        ninja.speedY = 0
        return result
    }
    const respawn = window.respawnNinja
    window.respawnNinja = function() {
        const result = respawn.apply(this, arguments)
        window.__pin = {x: ninja.x, y: ninja.y}
        return result
    }
}'''

SET_VISIBILITY = '''(state) => {
    Object.defineProperty(document, 'visibilityState',
        {configurable: true, get: () => state})
    Object.defineProperty(document, 'hidden',
        {configurable: true, get: () => state === 'hidden'})
    document.dispatchEvent(new Event('visibilitychange'))
}'''

CENTER = '''(path) => { const b = eval(path).background
    return {x: b.x + b.width / 2, y: b.y + b.height / 2} }'''


def log(message):
    print('  ' + message, file=sys.stderr)


def canvas_to_viewport(page, x, y):
    """CSS viewport point of logical canvas point (x, y)."""
    return page.evaluate('''([x, y]) => { const r = canvas.getBoundingClientRect()
        return {x: r.left + x * r.width / width, y: r.top + y * r.height / height} }''',
                         [x, y])


def storage_sets(page):
    return [c for c in bridge_calls(page) if c['name'] == 'storage.set']


class AudioWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('AUDIO_WIRING_EVIDENCE_DIR')
        cls.pause_cases = {}

    @classmethod
    def tearDownClass(cls):
        if cls.pause_cases:
            cls.write_evidence('pause-during-ad.json', cls.pause_cases)

    @classmethod
    def write_evidence(cls, name, data):
        if not cls.evidence:
            return
        out = Path(cls.evidence)
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(json.dumps(data, indent=2) + '\n')

    def screenshot(self, page, name):
        if not self.evidence:
            return
        out = Path(self.evidence) / 'screens'
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / name))

    def boot(self, viewport=VIEWPORT, fake=None, touch=False):
        if touch:
            context, page, errors = self.touch_context(viewport, fake)
        else:
            context, page, errors = open_game(self.browser, 'about:blank', viewport, fake)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        page.evaluate(PIN_NINJA)
        return page

    def touch_context(self, viewport, fake):
        context = self.browser.new_context(viewport=viewport, has_touch=True,
                                           is_mobile=True)
        context.route(harness.BRIDGE_URL, lambda route: route.fulfill(
            path=str(harness.FAKE_BRIDGE), content_type='application/javascript'))
        context.route(harness.CONFIG_ROUTE, harness.serve_config)
        context.add_init_script(
            f'window.__fakeBridge = Object.assign(window.__fakeBridge || {{}}, '
            f'{json.dumps(fake or {})})')
        page = context.new_page()
        return context, page, harness.collect_errors(page)

    def reload(self, page):
        page.reload()
        page.wait_for_function(READY)
        page.evaluate(PIN_NINJA)

    def wait_input(self, page):
        # events.js ignores input for STYLE.timing.inputUntouchMs after a button click
        page.wait_for_timeout(page.evaluate('STYLE.timing.inputUntouchMs') + 100)

    def click_logical(self, page, x, y, touch=False):
        p = canvas_to_viewport(page, x, y)
        if touch:
            page.touchscreen.tap(round(p['x']), round(p['y']))
        else:
            page.mouse.click(p['x'], p['y'])
        self.wait_input(page)

    def click_button(self, page, path, touch=False):
        c = page.evaluate(CENTER, path)
        self.click_logical(page, c['x'], c['y'], touch)

    def click_mute(self, page, touch=False):
        r = page.evaluate('MUTE_BUTTON.rect(MUTE_BUTTON.current())')
        self.click_logical(page, r['x'] + r['width'] / 2, r['y'] + r['height'] / 2, touch)

    def sounds(self, page):
        return page.evaluate('__audioLog.map(e => e.name)')

    def new_entries(self, page, start):
        return page.evaluate('n => __audioLog.slice(n)', start)

    def audio_log_length(self, page):
        return page.evaluate('__audioLog.length')

    def start(self, page, mode='classic'):
        self.click_button(page, 'menu.classicVersionButton' if mode == 'classic'
                          else 'menu.badVersionButton')
        self.assertFalse(page.evaluate('menu.visible'))

    # Gameplay events -> sounds

    def test_event_sound_mapping(self):
        """Each of the 8 gameplay/UI events plays its sound once."""
        page = self.boot()
        rows = []

        def expect(event, sound, action, since=None):
            n = self.audio_log_length(page) if since is None else since
            action()
            entries = self.new_entries(page, n)
            names = [e['name'] for e in entries]
            self.assertIn(sound, names, f'{event}: {names}')
            entry = next(e for e in entries if e['name'] == sound)
            rows.append({'event': event, 'sound': sound, 'audioLog': entry,
                         'allNewEntries': names})
            log(f'{event} -> {names}')

        expect('menu button click (chill version)', 'click',
               lambda: self.start(page))

        def throw():
            p = canvas_to_viewport(page, page.evaluate('0.5 * width'),
                                   page.evaluate('0.03 * height'))
            page.mouse.move(p['x'], p['y'])
            page.mouse.down()
        before_throw = self.audio_log_length(page)
        expect('grapnel throw (mouse down in the play field)', 'throw', throw)

        def attach():
            page.wait_for_function('grapnel.isGrappled()', timeout=5000)
            page.mouse.up()
        # The hook can land in the same frame as the throw
        expect('grapnel attaches to the ceiling', 'hook', attach, since=before_throw)
        self.assertEqual(self.sounds(page).count('hook'), 1)

        page.evaluate('scoreText.record[version] = 0')
        expect('point scored (changeScoreText)', 'score',
               lambda: page.evaluate('changeScoreText()'))
        # The point above already beat record 0: the record sound played with it
        self.assertEqual(self.sounds(page).count('record'), 1)
        rows.append({'event': 'new record in this run (first point above the record)',
                     'sound': 'record',
                     'audioLog': page.evaluate(
                         '__audioLog.filter(e => e.name == "record")[0]'),
                     'allNewEntries': ['score', 'record']})

        expect('ninja bounces off a trampoline', 'trampoline', lambda: page.evaluate('''() => {
            const t = floors.flatMap(f => f.elements).find(e => e instanceof Trampoline)
            const who = {x: ninja.x, y: ninja.y, radius: ninja.radius, speedX: 1, speedY: 1}
            t.collision(who, t.getLines()[0])
        }'''))

        # Classic floors spawn no jumping cubes: drop one on screen above the
        # bottom side floor and let the real physics bounce it
        expect('jumping cube bounces on screen', 'bounce', lambda: (page.evaluate('''() => {
            const size = 0.05 * height
            floors[1].elements.push(new JumpingCube({x: 0.5 * width - screen.x,
                y: 0.6 * height - screen.y, width: size, height: size,
                fill: STYLE.colors.cube.blueFill, stroke: STYLE.colors.cube.blueStroke}))
        }'''), page.wait_for_function('__audioLog.some(e => e.name == "bounce")',
                                      timeout=60000)))

        expect('lethal death (score below the continue minimum)', 'death',
               lambda: page.evaluate('() => { scoreText.count[version] = 0; onLethalDeath() }'))

        self.assertEqual(sorted(r['sound'] for r in rows),
                         sorted(['click', 'throw', 'hook', 'score', 'record',
                                 'trampoline', 'death', 'bounce']))
        self.write_evidence('event-sounds.json', rows)

    def test_record_sound_once_per_record_run(self):
        page = self.boot()
        self.start(page)
        page.evaluate('''() => { scoreText.record[version] = 3
            for (let i = 0; i < 6; ++i) changeScoreText() }''')
        names = self.sounds(page)
        self.assertEqual((names.count('score'), names.count('record')), (6, 1))
        # Next run: record is 6 now, 4 points do not beat it, 3 more do
        page.evaluate('reStart()')
        page.evaluate('for (let i = 0; i < 4; ++i) changeScoreText()')
        self.assertEqual(self.sounds(page).count('record'), 1)
        page.evaluate('for (let i = 0; i < 3; ++i) changeScoreText()')
        names = self.sounds(page)
        self.assertEqual((names.count('score'), names.count('record')), (13, 2))
        log(f'score x13, record x2 over two record runs')

    def test_click_on_every_menu_pause_offer_button(self):
        page = self.boot()
        clicks = lambda: self.sounds(page).count('click')
        steps = [('menu fps checkbox', lambda: self.click_button_checkbox(page, 'menu.mainFpsCounterCheckbox')),
                 ('menu fps checkbox off', lambda: self.click_button_checkbox(page, 'menu.mainFpsCounterCheckbox')),
                 ('chill version', lambda: self.click_button(page, 'menu.classicVersionButton')),
                 ('HUD menu button', lambda: self.click_hud_menu(page)),
                 ('pause fps checkbox', lambda: self.click_button_checkbox(page, 'menu.pauseFpsCounterCheckbox')),
                 ('resume', lambda: self.click_button(page, 'menu.resume')),
                 ('HUD menu button again', lambda: self.click_hud_menu(page)),
                 ('back to menu', lambda: self.click_button(page, 'menu.backToMenu')),
                 ('main version', lambda: self.click_button(page, 'menu.badVersionButton')),
                 ('offer restart', lambda: self.offer_restart(page)),
                 ('mute (menu)', lambda: self.click_mute_after_menu(page))]
        seen = []
        for name, action in steps:
            before = clicks()
            action()
            self.assertEqual(clicks(), before + 1, name)
            seen.append(name)
        log(f'click sound on: {seen}')

    def click_button_checkbox(self, page, path):
        c = page.evaluate('''(path) => { const b = eval(path)
            return {x: b.x + b.size / 2, y: b.y} }''', path)
        self.click_logical(page, c['x'], c['y'])

    def click_hud_menu(self, page):
        c = page.evaluate('''() => { const b = menu.button.background, s = scale[version]
            return {x: (b.x + b.width / 2) * s, y: (b.y + b.height / 2) * s} }''')
        self.click_logical(page, c['x'], c['y'])
        self.assertTrue(page.evaluate('menu.gamePaused'))

    def offer_restart(self, page):
        page.evaluate('() => { scoreText.count[version] = 5; onLethalDeath() }')
        self.assertTrue(page.evaluate('continueOffer.visible'))
        self.click_button(page, 'continueOffer.restartButton')
        self.assertFalse(page.evaluate('continueOffer.visible'))

    def click_mute_after_menu(self, page):
        page.evaluate('() => { menu.backToMenu.clickable = true; menu.backToMenu.click() }')
        self.click_mute(page)

    # Music and mute

    def test_music_runs_while_unmuted(self):
        page = self.boot()
        page.keyboard.press('Shift')
        page.wait_for_function('AUDIO.getState().state === "running"')
        s = page.evaluate('AUDIO.getState()')
        self.assertEqual((s['music'], s['gain'], s['state']), (True, 1, 'running'))
        self.click_mute(page)
        page.wait_for_function('AUDIO.getState().state === "suspended"')
        s = page.evaluate('AUDIO.getState()')
        self.assertEqual((s['gain'], s['muted']['user']), (0, True))
        self.click_mute(page)
        page.wait_for_function('AUDIO.getState().state === "running"')
        self.assertEqual(page.evaluate('AUDIO.getState().gain'), 1)
        log('music on while unmuted; mute suspends, unmute resumes')

    def test_mute_persists_and_hud_click_does_not_throw(self):
        page = self.boot()
        self.click_mute(page)
        page.wait_for_function('AUDIO.getState().state === "suspended"')
        after_click = page.evaluate('AUDIO.getState()')
        self.assertTrue(page.evaluate('MUTE_BUTTON.muted && PROGRESS.getMuted()'))
        sets = storage_sets(page)
        self.assertEqual(len(sets), 1)
        stored = dict(zip(*sets[-1]['args']))
        self.assertEqual(stored[MUTED_KEY], '1')

        self.reload(page)
        restored = page.evaluate('({button: MUTE_BUTTON.muted, progress: PROGRESS.getMuted(),'
                                 ' audio: AUDIO.getState()})')
        self.assertTrue(restored['button'] and restored['progress'])
        self.assertTrue(restored['audio']['muted']['user'])
        page.keyboard.press('Shift')
        page.wait_for_function('AUDIO.getState().started')
        page.wait_for_timeout(200)
        after_reload = page.evaluate('AUDIO.getState()')
        self.assertEqual((after_reload['gain'], after_reload['state']), (0, 'suspended'))
        self.screenshot(page, 'menu-muted-1280x720.png')

        # In a run: the HUD mute click unmutes and never throws the grapnel
        self.start(page)
        page.wait_for_timeout(300)
        before = page.evaluate('({throwed: grapnel.throwed, throws: '
                               '__audioLog.filter(e => e.name == "throw").length})')
        self.click_mute(page)
        hud = page.evaluate('''({throwed: grapnel.throwed, muted: MUTE_BUTTON.muted,
            throws: __audioLog.filter(e => e.name == "throw").length,
            paused: menu.gamePaused, menu: menu.visible})''')
        self.assertEqual(before, {'throwed': False, 'throws': 0})
        self.assertEqual(hud, {'throwed': False, 'muted': False, 'throws': 0,
                               'paused': False, 'menu': False})
        page.wait_for_function(f'PROGRESS.getMuted() === false')
        page.wait_for_timeout(1100)
        stored_after_hud = dict(zip(*storage_sets(page)[-1]['args']))
        self.assertEqual(stored_after_hud[MUTED_KEY], '0')
        self.write_evidence('mute-persist.json', {
            'menuClick': {'storage.set': stored, 'audio': after_click},
            'afterReload': {'MUTE_BUTTON.muted': restored['button'],
                            'PROGRESS.getMuted': restored['progress'],
                            'audioBeforeGesture': restored['audio'],
                            'audioAfterGesture': after_reload,
                            'masterGain': after_reload['gain']},
            'hudClick': {'before': before, 'after': hud,
                         'grapnel.throwed': hud['throwed'],
                         'storage.set': stored_after_hud}})
        log(f'muted stored {stored[MUTED_KEY]}, gain after reload {after_reload["gain"]}, '
            f'HUD click throwed={hud["throwed"]}')

    def test_touch_hud_mute_does_not_throw(self):
        page = self.boot(PORTRAIT, touch=True)
        self.click_button(page, 'menu.classicVersionButton', touch=True)
        page.wait_for_timeout(300)
        self.click_mute(page, touch=True)
        state = page.evaluate('({throwed: grapnel.throwed, muted: MUTE_BUTTON.muted,'
                              ' throws: __audioLog.filter(e => e.name == "throw").length})')
        self.assertEqual(state, {'throwed': False, 'muted': True, 'throws': 0})
        log(f'touch HUD mute at 390x844: {state}')

    def test_pause_mute_keeps_pause(self):
        page = self.boot()
        self.start(page)
        page.keyboard.press('p')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        self.click_mute(page)
        self.assertEqual(page.evaluate('[menu.gamePaused, MUTE_BUTTON.muted, grapnel.throwed]'),
                         [True, True, False])

    def test_hit_areas_and_screens(self):
        """Speaker icon on menu, pause and HUD; hit area >= 44 CSS px."""
        areas = {}
        for viewport in (VIEWPORT, PORTRAIT):
            size = f'{viewport["width"]}x{viewport["height"]}'
            page = self.boot(viewport)
            for where in ('menu', 'pause', 'hud'):
                if where == 'hud':
                    page.evaluate('menu.unPause()')
                    page.wait_for_timeout(200)
                elif where == 'pause':
                    self.start(page)
                    page.keyboard.press('p')
                self.assertEqual(page.evaluate('MUTE_BUTTON.current()'), where)
                info = page.evaluate('''() => {
                    const r = MUTE_BUTTON.rect(MUTE_BUTTON.current())
                    const css = canvas.getBoundingClientRect().height / height
                    // Canvas pixel inside the speaker body
                    const k = canvas.height / height
                    const px = ctx.getImageData(Math.round((r.x + 0.45 * r.width) * k),
                        Math.round((r.y + 0.5 * r.height) * k), 1, 1).data
                    return {rect: r, cssWidth: r.width * css, cssHeight: r.height * css,
                            speakerPixel: Array.from(px),
                            inside: r.x >= 0 && r.y >= 0 && r.x + r.width <= width &&
                                    r.y + r.height <= height}
                }''')
                self.assertGreaterEqual(info['cssWidth'], 44 - 1e-6, (size, where))
                self.assertGreaterEqual(info['cssHeight'], 44 - 1e-6, (size, where))
                self.assertTrue(info['inside'], (size, where))
                # hudGlow #30d5c8: the green channel dominates
                r, g, b, a = info['speakerPixel']
                self.assertGreater(g, 150, (size, where, info['speakerPixel']))
                areas[f'{where}-{size}'] = info
                self.screenshot(page, f'{where}-{size}.png')
                log(f'{where} {size}: {info["cssWidth"]:.1f} CSS px, pixel {info["speakerPixel"]}')
        self.write_evidence('hit-areas.json', areas)

    # TASK-107 g05/g06 re-port: pause requested while the ad is pending

    def paused_after_ad(self, how):
        page = self.boot(fake=SLOW_REWARD)
        self.start(page)
        page.evaluate('() => { scoreText.count[version] = 5; onLethalDeath() }')
        self.assertTrue(page.evaluate('continueOffer.visible'))
        self.click_button(page, 'continueOffer.continueButton')
        self.assertTrue(page.evaluate('continueOffer.adPending'), 'ad not pending')
        if how == 'hidden':
            page.evaluate(SET_VISIBILITY, 'hidden')
        else:
            page.evaluate('window.dispatchEvent(new Event("blur"))')
        during = page.evaluate('({paused: menu.gamePaused, offer: continueOffer.visible})')
        page.wait_for_function('!continueOffer.visible', timeout=10000)
        if how == 'hidden':
            page.evaluate(SET_VISIBILITY, 'visible')
        state = page.evaluate('''({paused: menu.gamePaused, offer: continueOffer.visible,
            continueUsed: continueUsed, invulnerable: ninja.isInvulnerable()})''')
        self.pause_cases[how] = {'duringAd': during, 'afterRespawn': state}
        self.assertEqual(during, {'paused': False, 'offer': True})
        self.assertTrue(state['paused'], f'{how} during the ad: run not paused after the respawn')
        self.assertTrue(state['continueUsed'])
        log(f'{how} during the ad -> {state}')

    def test_g05_hidden_during_ad_pauses_after(self):
        self.paused_after_ad('hidden')

    def test_g06_blur_during_ad_pauses_after(self):
        self.paused_after_ad('blur')


if __name__ == '__main__':
    unittest.main()
