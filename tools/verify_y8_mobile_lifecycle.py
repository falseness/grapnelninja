"""Mobile browser lifecycle and persistence checks for the Y8 build.

Emulation only: Playwright device descriptors on the Linux Chromium headless
shell (Android-style) and the Linux WebKit port (iPhone-style). Nothing here
certifies Android Chrome or iOS Safari. Every run is offline: the Y8 SDK is
replaced by tools/fixtures/fake-y8-sdk.js and other external URLs are aborted.
"""
import argparse, importlib.metadata, json, pathlib, struct, subprocess, sys, time, traceback
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright
from browser_test_support import QuietHandler, wait_for_boot, EXTERNAL_URL
from verify_y8_release import SDK, FAKE

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILES = [
    {'engine': 'chromium', 'device': 'Pixel 7',
     'label': 'Chromium Android-style emulation: Playwright "Pixel 7" descriptor on the Linux Chromium headless shell; not an Android device'},
    {'engine': 'webkit', 'device': 'iPhone 14',
     'label': 'WebKit iPhone-style emulation: Playwright "iPhone 14" descriptor on the Linux WebKit port; not iOS Safari'},
]
MODES = {'bad': 'Main', 'classic': 'Chill'}
RECORD_KEYS = ['grapnelninja.records', 'grapnelninja.time', 'grapnelninja.lang']

# Installed before any game script: event timeline, frame counter, audio probes.
INIT = r'''
window.__lc = {events: [], frames: 0, physics: 0,
    audio: {AudioContext: 0, webkitAudioContext: 0, Audio: 0, play: 0}};
const push = e => __lc.events.push({t: Math.round(performance.now()), e});
for (const n of ['blur', 'focus', 'resize', 'orientationchange', 'pagehide', 'pageshow'])
    window.addEventListener(n, () => push(n), true);
document.addEventListener('visibilitychange', () => push('visibilitychange:' + document.visibilityState), true);
for (const name of ['AudioContext', 'webkitAudioContext', 'Audio']) {
    const O = window[name];
    if (!O) continue;
    window[name] = new Proxy(O, {construct(t, a, n) { __lc.audio[name]++; return Reflect.construct(t, a, n) }});
}
if (window.HTMLMediaElement) {
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () { __lc.audio.play++; return play.apply(this, arguments) };
}
(function tick() { __lc.frames++; requestAnimationFrame(tick) })();
'''
# After boot: count physics steps, log lifecycle messages and storage writes.
HOOKS = r'''
() => {
    const p = physics; physics = function () { __lc.physics++; return p.apply(this, arguments) };
    const sl = PLATFORM.sendLifecycle;
    PLATFORM.sendLifecycle = (n, d) => { __lc.events.push({t: Math.round(performance.now()), e: 'lifecycle:' + n}); return sl(n, d) };
    const sm = PLATFORM.storage.setMany;
    PLATFORM.storage.setMany = o => { __lc.events.push({t: Math.round(performance.now()), e: 'save:' + Object.keys(o).join(',')}); return sm(o) };
    PLATFORM.onAdState(s => __lc.events.push({t: Math.round(performance.now()), e: 'ad:' + s}));
}
'''
SYNTHETIC_VISIBILITY = r'''
hidden => {
    Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => hidden ? 'hidden' : 'visible'});
    Object.defineProperty(document, 'hidden', {configurable: true, get: () => hidden});
    document.dispatchEvent(new Event('visibilitychange'));
}
'''
STATE = '''() => ({paused: menu.gamePaused, menu: menu.visible, offer: continueOffer.visible, adPending: continueOffer.adPending,
    adOpen, pauseAfterAd, physics: __lc.physics, frames: __lc.frames, visibility: document.visibilityState,
    ninja: ninja ? {x: Math.round(ninja.x), y: Math.round(ninja.y)} : null, width, rotated: isViewRotated()})'''
STORAGE = '''keys => { try { const o = {}; for (const k of keys) o[k] = localStorage.getItem(k); return o } catch (e) { return {error: String(e)} } }'''


def utc():
    return datetime.now(timezone.utc).isoformat()


def png_size(path):
    data = path.read_bytes()[:24]
    return struct.unpack('>II', data[16:24]) if data[:8] == b'\x89PNG\r\n\x1a\n' else (0, 0)


class Session:
    """One page under one emulation profile; collects evidence and verdicts."""

    def __init__(self, out, pw, browser, profile, mode, context_kind, fake_config, deny_storage):
        self.out, self.profile, self.mode, self.kind = out, profile, mode, context_kind
        self.row = {'engine': profile['engine'], 'browser_version': browser.version, 'device': profile['device'],
                    'descriptor': pw.devices[profile['device']], 'emulation': profile['label'], 'mode': mode,
                    'mode_label': MODES[mode], 'context': context_kind, 'fake_sdk_config': fake_config,
                    'storage_denied': deny_storage, 'cases': [], 'page_errors': [], 'console_errors': [],
                    'console_warnings': [], 'failed_requests': [], 'captures': [], 'verdict': 'PASS'}
        self.context = browser.new_context(**pw.devices[profile['device']])
        self.context.route(EXTERNAL_URL, lambda r: (self.row['failed_requests'].append(
            {'url': r.request.url.split('?')[0], 'outcome': 'aborted by test (offline)'}), r.abort()))
        self.context.route(SDK, lambda r: r.fulfill(content_type='text/javascript', body=FAKE))
        self.context.add_init_script('window.__y8Fake=' + json.dumps(fake_config))
        self.context.add_init_script(INIT)
        if deny_storage:
            self.context.add_init_script('''Object.defineProperty(window, 'localStorage',
                {configurable: true, get() { throw new DOMException('Storage access denied by test', 'SecurityError') }})''')
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.page.on('pageerror', lambda e: self.row['page_errors'].append(str(e)))
        self.page.on('console', self.on_console)
        self.page.on('requestfailed', lambda r: self.row['failed_requests'].append(
            {'url': r.url.split('?')[0], 'outcome': r.failure or 'failed'}))
        self.hidden_method = None

    def on_console(self, msg):
        if msg.type == 'error':
            self.row['console_errors'].append(msg.text)
        elif msg.type == 'warning':
            self.row['console_warnings'].append(msg.text)

    # -- helpers ---------------------------------------------------------
    def log(self, *a):
        print(self.profile['engine'], self.mode, self.kind, *a, flush=True)

    def state(self):
        return self.page.evaluate(STATE)

    def events(self, start):
        return [e['e'] for e in self.page.evaluate('__lc.events')[start:]]

    def mark(self):
        return self.page.evaluate('__lc.events.length')

    def tap_expr(self, expr):
        xy = self.page.evaluate('expr=>{const b=eval(expr);return canvasCoordsToViewportCoords({x:b.x+b.width/2,y:b.y+b.height/2})}', expr)
        self.page.touchscreen.tap(xy['x'], xy['y'])

    def tap_play_area(self):
        """Trusted tap on empty gameplay space, away from pause-panel controls."""
        xy = self.page.evaluate('''() => { const b = menu.getPausePanel();
            return canvasCoordsToViewportCoords({x: b.x * 0.5, y: b.y + b.height * 0.5}) }''')
        self.page.touchscreen.tap(xy['x'], xy['y'])

    def set_hidden(self, hidden):
        """Synthetic tab hide: neither headless engine can really hide a page
        (Chromium's Page.setWebLifecycleState was probed and leaves the
        document visible), so visibilityState is overridden and the event
        dispatched. rAF keeps running, which makes the no-physics check stricter."""
        self.page.evaluate(SYNTHETIC_VISIBILITY, hidden)
        self.hidden_method = 'synthetic: document.visibilityState override + visibilitychange event (rAF keeps running)'

    def capture(self, stage):
        name = f"{self.profile['engine']}-{self.mode}-{self.kind}-{stage}.png"
        path = self.out / 'captures' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(path))
        w, h = png_size(path)
        self.row['captures'].append({'file': 'captures/' + name, 'stage': stage, 'width': w, 'height': h,
                                     'bytes': path.stat().st_size, 'viewport': self.page.viewport_size})

    def case(self, name, fn):
        row = {'case': name}
        start = self.mark()
        try:
            row.update(fn() or {})
            row['verdict'] = row.get('verdict', 'PASS')
        except Exception:
            row['verdict'] = 'FAIL'
            row['error'] = traceback.format_exc()
            self.row['verdict'] = 'FAIL'
        row['events'] = self.events(start)
        self.row['cases'].append(row)
        self.log(row['verdict'], name, row.get('error', '').strip().splitlines()[-1:] or '')
        return row

    def check(self, cond, message):
        if not cond:
            raise AssertionError(message)

    def resume_and_verify(self):
        """Pause menu Resume must restore physics: no unrecoverable pause."""
        self.page.wait_for_function('!unTouch')
        self.tap_expr('menu.resume.background')
        self.page.wait_for_function('!menu.gamePaused')
        before = self.page.evaluate('__lc.physics')
        self.page.wait_for_function('n => __lc.physics > n', arg=before)
        return {'resumed': True, 'physics_before': before, 'physics_after': self.page.evaluate('__lc.physics')}

    # -- cases -----------------------------------------------------------
    def boot(self, url):
        t = time.monotonic()
        self.page.goto(url, wait_until='domcontentloaded')
        wait_for_boot(self.page)
        ms = round((time.monotonic() - t) * 1000)
        self.page.evaluate(HOOKS)
        self.page.wait_for_function('!unTouch')
        return {'menu_ms': ms, 'environment': self.page.evaluate('PLATFORM.environment'),
                'language': self.page.evaluate('I18N.language'), 'storage_before': self.page.evaluate(STORAGE, RECORD_KEYS)}

    def start_run(self):
        self.tap_expr(f'menu.{self.mode}VersionButton.background')
        self.page.wait_for_function('!menu.visible && !menu.gamePaused')
        self.page.wait_for_function('!unTouch')
        before = self.page.evaluate('__lc.physics')
        self.page.wait_for_function('n => __lc.physics > n + 10', arg=before)
        self.capture('play')
        return {'state': self.state()}

    def background_foreground(self):
        before = self.state()
        self.check(not before['paused'], 'run not active before backgrounding')
        self.set_hidden(True)
        self.page.wait_for_function('menu.gamePaused')
        a = self.state()
        self.page.wait_for_timeout(400)
        b = self.state()
        self.check(a['physics'] == b['physics'], f"physics advanced while hidden: {a['physics']} -> {b['physics']}")
        self.check(a['ninja'] == b['ninja'], f"ninja moved while hidden: {a['ninja']} -> {b['ninja']}")
        self.tap_play_area()
        self.page.wait_for_timeout(150)
        c = self.state()
        thrown = self.page.evaluate('grapnel.throwed')
        self.check(not thrown and c['paused'] and c['physics'] == b['physics'], 'input while hidden reached gameplay')
        self.set_hidden(False)
        self.page.wait_for_timeout(300)
        d = self.state()
        self.check(d['paused'], 'pause was dropped on foreground without the player')
        self.check(d['physics'] == b['physics'], 'physics ran after foreground while paused')
        self.check(d['frames'] > c['frames'], 'render loop did not resume after foreground')
        self.capture('background-paused')
        storage = self.page.evaluate(STORAGE, RECORD_KEYS)
        r = self.resume_and_verify()
        return {'hidden_method': self.hidden_method, 'before': before, 'hidden': b, 'after_foreground': d,
                'storage_while_hidden': storage, 'rAF_stopped_while_hidden': c['frames'] == a['frames'], **r}

    def blur_focus(self):
        before = self.state()
        self.check(not before['paused'], 'run not active before blur')
        self.page.evaluate("window.dispatchEvent(new Event('blur'))")
        self.page.wait_for_function('menu.gamePaused')
        self.page.wait_for_timeout(200)
        a = self.state()
        self.page.evaluate("window.dispatchEvent(new Event('focus'))")
        self.page.wait_for_timeout(200)
        b = self.state()
        self.check(b['paused'] and a['physics'] == b['physics'], 'focus resumed physics without the player')
        r = self.resume_and_verify()
        return {'event_method': 'synthetic window blur/focus events', 'before': before, 'after_blur': a, 'after_focus': b, **r}

    def resize(self, stage):
        vp = dict(self.page.viewport_size)
        before = self.state()
        out = {'from': vp, 'before': before}
        self.page.set_viewport_size({'width': vp['height'], 'height': vp['width']})
        self.page.wait_for_timeout(350)
        rotated = self.state()
        self.check(rotated['paused'] == before['paused'] and rotated['offer'] == before['offer'], 'resize changed pause/offer state')
        self.capture(stage + '-landscape')
        self.page.set_viewport_size(vp)
        self.page.wait_for_timeout(350)
        back = self.state()
        self.check(back['width'] == before['width'], f"logical width not restored: {before['width']} -> {back['width']}")
        self.check(not self.row['page_errors'], self.row['page_errors'])
        out.update({'landscape': rotated, 'back': back})
        return out

    def resize_during_play(self):
        out = self.resize('play')
        before = self.page.evaluate('__lc.physics')
        self.page.wait_for_function('n => __lc.physics > n', arg=before)
        out['physics_continues'] = True
        return out

    def death(self):
        self.page.wait_for_function('!ninja.isInvulnerable()')
        supported = self.page.evaluate('PLATFORM.isRewardedSupported()')
        self.page.evaluate('scoreText.count[version] = CONTINUE_MIN_SCORE; onLethalDeath()')
        if not supported:
            # No rewarded ads: the death restarts the run immediately
            self.page.wait_for_function('!continueOffer.visible && !menu.visible && scoreText.count[version] === 0')
            before = self.page.evaluate('__lc.physics')
            self.page.wait_for_function('n => __lc.physics > n', arg=before)
            return {'rewarded_supported': False, 'restarted_without_offer': True, 'state': self.state()}
        self.page.wait_for_function('continueOffer.visible')
        a = self.state()
        self.page.wait_for_timeout(300)
        b = self.state()
        self.check(a['physics'] == b['physics'], 'physics ran behind the continue offer')
        self.capture('death')
        return {'offer': b, 'rewarded_supported': True}

    def resize_during_death(self):
        return self.resize('death')

    def ad_with_lifecycle(self):
        """Background during the rewarded ad: pause lands after the respawn."""
        self.page.evaluate('window.__y8Fake.adDurationMs = 5000')
        self.tap_expr('continueOffer.continueButton.background')
        self.page.wait_for_function('adOpen')
        start = self.mark()
        self.resize('ad')
        self.set_hidden(True)
        self.page.wait_for_timeout(150)
        hidden = self.state()
        self.check(hidden['pauseAfterAd'] and not hidden['paused'], 'pause did not defer while the ad plays')
        self.set_hidden(False)
        self.page.wait_for_function('!adOpen && !continueOffer.visible', timeout=15000)
        self.page.wait_for_function('menu.gamePaused')
        after = self.state()
        self.check(not after['pauseAfterAd'] and not after['offer'], 'deferred pause did not clear')
        order = self.events(start)
        self.check(order.index('ad:closed') < order.index('lifecycle:level_paused'), f'pause before ad close: {order}')
        self.capture('after-ad-paused')
        r = self.resume_and_verify()
        return {'during_ad': hidden, 'after_ad': after, 'hidden_method': self.hidden_method, **r}

    def ad_failure(self):
        """A rejected/no-fill ad must leave a working Restart."""
        self.tap_expr('continueOffer.continueButton.background')
        self.page.wait_for_function('!continueOffer.adPending')
        shown = self.page.evaluate('continueOffer.visible && !continueOffer.watchVisible()')
        self.page.wait_for_function('!unTouch')
        self.tap_expr('continueOffer.restartButton.background')
        self.page.wait_for_function('!continueOffer.visible && !menu.visible')
        before = self.page.evaluate('__lc.physics')
        self.page.wait_for_function('n => __lc.physics > n', arg=before)
        return {'error_notice_shown': shown, 'restarted': True}

    def audio_state(self):
        a = self.page.evaluate('__lc.audio')
        media = self.page.evaluate("document.querySelectorAll('audio,video').length")
        init_args = self.page.evaluate("(window.__y8Fake.calls || []).filter(c => c.name === 'init').map(c => c.args)")
        source = (ROOT / 'platform.js').read_text()
        self.check(sum(a.values()) == 0 and media == 0, f'unexpected audio objects: {a} media={media}')
        return {'constructed': a, 'media_elements': media, 'sdk_init_args': init_args,
                'sdk_sound_option': 'off' if "sound: 'off'" in source else 'unknown',
                'note': 'The game has no audio pipeline: nothing to unlock on first touch or to mute; '
                        'the SDK is initialised with sound off. Verified after trusted taps.'}

    def persistence(self, url):
        """Records, time and language survive a reload on the same storage."""
        self.page.evaluate(f"scoreText.record['{self.mode}'] = 77; PROGRESS.setTime(300); PROGRESS.setLang('ru'); PROGRESS.save(); PROGRESS.flush()")
        saved = self.page.evaluate(STORAGE, RECORD_KEYS)
        self.page.reload(wait_until='domcontentloaded')
        wait_for_boot(self.page)
        self.page.evaluate(HOOKS)
        loaded = self.page.evaluate(f"({{record: scoreText.record['{self.mode}'], time: PROGRESS.getTime(), lang: I18N.language, env: PLATFORM.environment}})")
        after = self.page.evaluate(STORAGE, RECORD_KEYS)
        if self.row['storage_denied']:
            self.check(loaded['record'] == 0 and loaded['time'] == 0, f'denied storage still restored values: {loaded}')
            expectation = 'session memory only: values reset on reload, boot and play still work'
        else:
            self.check(loaded == {'record': 77, 'time': 300, 'lang': 'ru', 'env': loaded['env']}, f'reload lost progress: {loaded}')
            expectation = 'records/time/lang restored from localStorage'
        return {'saved_before_reload': saved, 'loaded_after_reload': loaded, 'storage_after_reload': after,
                'expectation': expectation, 'warnings': list(self.row['console_warnings'])}

    def background_flush(self):
        """A change made inside the save throttle window is on disk once hidden."""
        self.page.wait_for_function('!unTouch')
        self.page.evaluate("PROGRESS.setLang('en'); PROGRESS.save()")
        self.page.evaluate("PROGRESS.setTime(999); PROGRESS.save()")
        start = self.mark()
        self.set_hidden(True)
        stored = self.page.evaluate('k => PLATFORM.storage.getMany(k)' if self.row['storage_denied'] else STORAGE, RECORD_KEYS)
        self.set_hidden(False)
        self.check(stored.get('grapnelninja.time') == '999', f'time not flushed on hidden: {stored}')
        return {'storage_right_after_hidden': stored, 'events': self.events(start)}

    def close(self):
        self.row['audio'] = self.page.evaluate('__lc.audio')
        self.context.close()


def run(root, out):
    out.mkdir(parents=True, exist_ok=True)
    report = {'tool': 'tools/verify_y8_mobile_lifecycle.py', 'utc_start': utc(), 'root': str(root),
              'source_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, capture_output=True).stdout.strip(),
              'profiles': [], 'runs': [], 'unverified': [
                  'Real Android Chrome and iOS Safari behaviour (OS backgrounding, audio focus, memory kills): emulation only.',
                  'Tab hiding is synthetic in both engines (visibilityState override + visibilitychange); headless Chromium Page.setWebLifecycleState was probed and does not hide the document, and the Linux WebKit port exposes no lifecycle control. Real rAF suspension while hidden is therefore not exercised.',
                  'Blur/focus are synthetic window events in both engines (headless windows have no OS focus).',
                  'Firefox mobile is out of scope for this ticket.']}
    with ExitStack() as stack:
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.server_close); stack.callback(server.shutdown)
        pw = stack.enter_context(sync_playwright())
        url = f'http://127.0.0.1:{server.server_port}/'
        report['playwright'] = importlib.metadata.version('playwright')
        for profile in PROFILES:
            browser = stack.enter_context(getattr(pw, profile['engine']).launch(args=['--no-sandbox'] if profile['engine'] == 'chromium' else []))
            report['profiles'].append({**profile, 'browser_version': browser.version, 'descriptor': pw.devices[profile['device']]})
            contexts = [('main', {}, False)]
            for mode in MODES:
                for kind, fake, deny in contexts if mode == 'classic' else contexts + [
                        ('storage-denied', {}, True), ('sdk-reject', {'initReject': True}, False),
                        ('sdk-hang', {'initHang': True}, False), ('ad-reject', {'rewardOutcome': 'reject'}, False),
                        ('ad-nofill', {'rewardOutcome': 'noAdPreloaded'}, False)]:
                    s = Session(out, pw, browser, profile, mode, kind, fake, deny)
                    try:
                        s.case('boot', lambda: s.boot(url))
                        s.case('start-run', s.start_run)
                        s.case('background-foreground', s.background_foreground)
                        s.case('blur-focus', s.blur_focus)
                        s.case('resize-during-play', s.resize_during_play)
                        d = s.case('death', s.death)
                        if d.get('rewarded_supported'):
                            s.case('resize-during-death', s.resize_during_death)
                            if kind in ('ad-reject', 'ad-nofill'):
                                s.case('ad-failure-restart', s.ad_failure)
                            else:
                                s.case('ad-background-resize', s.ad_with_lifecycle)
                        s.case('audio-state', s.audio_state)
                        s.case('persistence-reload', lambda: s.persistence(url))
                        s.case('background-flush', s.background_flush)
                        s.case('no-uncaught-errors', lambda: s.check(not s.row['page_errors'] and not s.row['console_errors'],
                                                                      {'page': s.row['page_errors'], 'console': s.row['console_errors']}))
                    finally:
                        s.close()
                        report['runs'].append(s.row)
                        report['utc_end'] = utc()
                        report['overall'] = 'PASS' if all(r['verdict'] == 'PASS' for r in report['runs']) else 'FAIL'
                        (out / 'mobile-lifecycle.json').write_text(json.dumps(report, indent=2))
    print('OVERALL', report['overall'], 'runs', len(report['runs']), 'cases',
          sum(len(r['cases']) for r in report['runs']), 'failed cases',
          sum(c['verdict'] != 'PASS' for r in report['runs'] for c in r['cases']), flush=True)
    return report['overall'] == 'PASS'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=pathlib.Path, default=ROOT)
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    sys.exit(0 if run(a.root, a.out) else 1)
