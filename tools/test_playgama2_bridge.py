"""Real application boot/input with a fake SDK at the network boundary.

Run from the repository root with PLAYGAMA2_EVIDENCE_DIR to save proof.
Requires Playwright Chromium, Xvfb, and ImageMagick import. No remote requests.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright
from browser_test_support import OfflineBrowser, QuietHandler, wait_for_boot

ROOT = Path(__file__).resolve().parents[1]
SDK = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'
FAKE = r"""
window.probe = {calls: [], subscriptions: {}, handlers: {}};
function record(name, data) { probe.calls.push({name, data, ms: performance.now()}); }
function on(event, fn) {
    probe.subscriptions[event] = (probe.subscriptions[event] || 0) + 1;
    (probe.handlers[event] ||= []).push(fn);
}
window.emitHost = (event, value) => (probe.handlers[event] || []).forEach(fn => fn(value));
const values = {'grapnelninja.records': {classic: 12, bad: 7},
                'grapnelninja.time': 120, 'grapnelninja.lang': SAVED_LANGUAGE};
window.bridge = {
    async initialize(options) {
        record('initialize', options);
        if (FAULT === 'init_rejected') throw Error('INJECTED init rejection');
        if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(options.configFilePath))
            throw Error('Bridge config must be a relative path, not an external URL');
        const response = await fetch(options.configFilePath);
        if (!response.ok) throw Error('config unavailable');
        record('config', await response.json());
    },
    EVENT_NAME: {PAUSE_STATE_CHANGED: 'pause', AUDIO_STATE_CHANGED: 'audio',
        INTERSTITIAL_STATE_CHANGED: 'interstitial', REWARDED_STATE_CHANGED: 'rewarded'},
    platform: {id: 'fake-host', language: 'ru-RU', isAudioEnabled: true, on,
        sendMessage(name, data) { record(name, data); return Promise.resolve(); }},
    advertisement: {on, off() {}, isRewardedSupported: false, isInterstitialSupported: false},
    storage: {
        async get(keys) {
            record('storage.get', keys);
            if (FAULT === 'storage_rejected') throw Error('INJECTED storage rejection');
            return keys.map(key => values[key] ?? null);
        },
        async set(keys, data) {
            record('storage.set', {keys, values: data});
            keys.forEach((key, i) => values[key] = data[i]);
        }
    }
};
"""


class Playgama2BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', tempfile.mkdtemp()))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        (root / 'nested/game').mkdir(parents=True)
        (root / 'nested/game/current').symlink_to(ROOT, target_is_directory=True)
        baseline = root / 'nested/game/baseline'
        baseline.mkdir()
        # Fixed pre-restoration base keeps visual comparisons meaningful after commit.
        revision = '201d57af1ae3294b8b16585bd2f03cc89af10a8d'
        archive = subprocess.check_output(['git', 'archive', revision], cwd=ROOT)
        subprocess.run(['tar', '-x', '-C', str(baseline)], input=archive, check=True)
        cls.baseline = revision
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        cls.addClassCleanup(cls.server.server_close)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.server.shutdown)
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/nested/game/'
        read_fd, write_fd = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x900x24'], pass_fds=(write_fd,))
        os.close(write_fd)
        cls.addClassCleanup(xvfb.wait)
        cls.addClassCleanup(xvfb.terminate)
        with os.fdopen(read_fd) as pipe:
            cls.env = {**os.environ, 'DISPLAY': ':' + pipe.readline().strip()}
        pw = sync_playwright().start()
        cls.addClassCleanup(pw.stop)
        browser = pw.chromium.launch(headless=False, env=cls.env, args=['--no-sandbox', '--window-size=1280,850'])
        cls.addClassCleanup(browser.close)
        cls.browser = OfflineBrowser(browser)

    def write(self, name, value):
        (self.out / name).write_text(json.dumps(value, indent=2) + '\n')

    def open(self, fault='normal', saved=None, tree='current'):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
        self.addCleanup(context.close)
        context.route(SDK, lambda route: route.fulfill(content_type='application/javascript', body=
            'const FAULT = ' + json.dumps(fault) + '; const SAVED_LANGUAGE = ' + json.dumps(saved) + ';\n' + FAKE))
        page = context.new_page()
        page.set_default_timeout(12000)
        errors, network, console = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda msg: console.append(msg.text))
        page.on('response', lambda response: network.append({'url': response.url, 'status': response.status, 'time': time.time()}))
        page.on('requestfailed', lambda req: network.append({'url': req.url, 'failure': req.failure}))
        page.goto(self.url + tree + '/index.html')
        wait_for_boot(page)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page, network, console

    def click_mode(self, page, mode):
        point = page.evaluate('''mode => {
            const b = menu[mode + 'VersionButton'].background;
            const r = canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width,
                    y:r.y+(b.y+b.height/2)*r.height/height};
        }''', mode)
        page.mouse.click(**point)
        page.wait_for_function('!menu.visible && !!ninja')
        self.assertEqual(page.evaluate('version'), 'classic' if mode == 'classic' else 'bad')

    def test_normal_contract_storage_events_and_nested_network(self):
        page, network, _ = self.open()
        self.assertEqual(page.evaluate('[PLATFORM.environment, PLATFORM.platformId, I18N.language]'), ['playgama', 'fake-host', 'ru'])
        self.assertEqual(page.evaluate('[scoreText.record.classic, scoreText.record.bad, PROGRESS.getTime()]'), [12, 7, 120])
        self.assertTrue(page.evaluate('PLATFORM.init() === PLATFORM.init()'))
        page.evaluate('PLATFORM.gameReady()')
        self.click_mode(page, 'bad')
        page.evaluate("emitHost('pause', true)")
        self.assertTrue(page.evaluate('menu.gamePaused'))
        page.evaluate('menu.unPause()')
        page.evaluate("""() => {
            window.audioEvents = [];
            PLATFORM.onAudio(value => audioEvents.push(value));
            bridge.platform.isAudioEnabled = false;
            emitHost('audio', false);
            emitHost('interstitial', 'opened');
        }""")
        self.assertEqual(page.evaluate('[adOpen, PLATFORM.isAudioEnabled(), audioEvents]'), [False, False, [False]])
        page.evaluate("emitHost('interstitial', 'closed'); emitHost('rewarded', 'opened')")
        self.assertTrue(page.evaluate('adOpen'))
        page.evaluate("emitHost('rewarded', 'failed')")
        self.assertFalse(page.evaluate('adOpen'))
        page.evaluate("setLanguage('en'); PROGRESS.flush()")
        page.wait_for_function("probe.calls.some(c => c.name === 'storage.set')")
        stored = page.evaluate('PLATFORM.storage.getMany(PROGRESS.keys)')
        self.assertEqual(stored['grapnelninja.lang'], 'en')
        self.assertEqual(json.loads(stored['grapnelninja.records']), {'classic': 12, 'bad': 7})
        self.assertFalse(page.evaluate('PLATFORM.isInterstitialSupported()'))
        self.assertEqual(page.evaluate('typeof PLATFORM.requestRewarded'), 'undefined')
        page.evaluate('bridge.advertisement.isRewardedSupported = true; bridge.advertisement.isInterstitialSupported = true')
        self.assertTrue(page.evaluate('PLATFORM.isInterstitialSupported()'))
        self.assertTrue(page.evaluate("['init','now','showInterstitial','sendMessage','sendLifecycle','gameReady','onPause','onAdState'].every(key => typeof PLATFORM[key] === 'function')"))
        data = page.evaluate('({calls: probe.calls, subscriptions: probe.subscriptions})')
        names = [c['name'] for c in data['calls']]
        config = next(c['data'] for c in data['calls'] if c['name'] == 'config')
        self.assertNotIn('rewarded', config['advertisement'])
        self.assertEqual(config['advertisement']['minimumDelayBetweenInterstitial'], 120)
        self.assertNotIn('preloadOnStart', config['advertisement']['interstitial'])
        self.assertEqual(config['advertisement']['interstitial']['placements'], [{'id': 'game_over'}])
        self.assertEqual(names.count('initialize'), 1)
        self.assertEqual(next(c['data'] for c in data['calls'] if c['name'] == 'initialize'),
                         {'configFilePath': './playgama-bridge-config.json'})
        self.assertEqual(names.count('game_ready'), 1)
        self.assertEqual(data['subscriptions'], {'pause': 1, 'audio': 1, 'interstitial': 1, 'rewarded': 1})
        for name in ['level_started', 'level_paused', 'level_resumed', 'storage.get', 'storage.set']:
            self.assertIn(name, names)
        self.assertLess(names.index('game_ready'), names.index('level_started'))
        self.assertEqual(next(c['data'] for c in data['calls'] if c['name'] == 'level_started'), {'world': 'bad'})
        for response in network:
            self.assertEqual(response.get('status'), 200, response)
            self.assertTrue(response['url'] == SDK or response['url'].startswith(self.url + 'current/'))
        for suffix in ['platform.js', 'playgama-bridge-config.json', 'render/draw.js', 'events.js']:
            self.assertTrue(any(r['url'].endswith('/' + suffix) for r in network), suffix)
        self.assertTrue(any(r['url'] == SDK for r in network))
        data.update(verdict='PASS initialization=1 readiness=1 subscriptions=1 each; SDK storage round-trip; lifecycle and host events', stored=stored)
        self.write('events.json', data)
        self.write('network.json', {'verdict': 'PASS SDK, config and nested runtime references: all HTTP 200', 'requests': network})
        print('PASS normal: initialize=1 game_ready=1 subscriptions pause/audio/interstitial/rewarded=1; host ru; SDK storage round-trip; level_started/paused/resumed; nested requests all 200', flush=True)

    def test_saved_language_precedes_host(self):
        page, _, _ = self.open(saved='en')
        self.assertEqual(page.evaluate('[PLATFORM.language, I18N.language]'), ['ru', 'en'])
        print('PASS saved language en precedes host ru', flush=True)

    def test_boundary_rejections(self):
        results = []
        for fault, marker, environment in [('init_rejected', 'initialize failed', 'disabled'), ('storage_rejected', 'storage.get failed', 'playgama')]:
            with self.subTest(fault=fault):
                page, _, console = self.open(fault=fault)
                self.assertEqual(page.evaluate('PLATFORM.environment'), environment)
                self.assertTrue(any(marker in message for message in console))
                self.click_mode(page, 'classic')
                results.append({'fault': fault, 'console': console, 'verdict': 'PASS playable after boundary rejection'})
                page.context.close()
                print('PASS ' + fault + ': ' + marker + '; real menu input starts Chill', flush=True)
        self.write('faults.json', results)

    def test_native_base_and_restored_visuals(self):
        captures = []
        for tree in ['baseline', 'current']:
            for mode in ['menu', 'classic', 'bad']:
                page, _, _ = self.open(saved='en', tree=tree)
                if mode != 'menu':
                    self.click_mode(page, mode)
                page.wait_for_timeout(150)
                name = f'{tree}-{mode}.png'
                subprocess.run(['import', '-window', 'root', str(self.out / name)], env=self.env, check=True, timeout=12)
                state = page.evaluate('({menu:menu.visible, version: typeof version === "undefined" ? null : version, loading:document.getElementById("loading").hidden})')
                self.assertEqual(state['menu'], mode == 'menu')
                self.assertTrue(state['loading'])
                captures.append({'path': name, 'time': time.time(), 'state': state,
                    'sha256': hashlib.sha256((self.out / name).read_bytes()).hexdigest()})
                page.context.close()
        self.write('captures.json', {'baseline_revision': self.baseline, 'verdict': 'PASS six native X11 captures: base/restored menu, Chill (classic), Main (bad)', 'captures': captures})
        print('PASS six native captures: baseline/current menu, Chill/classic, Main/bad', flush=True)


if __name__ == '__main__':
    unittest.main()
