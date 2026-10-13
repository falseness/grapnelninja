"""Real WebAudio output and native input; faults only at SDK/browser boundaries."""
import json
import subprocess
import unittest
import wave
import struct

import test_playgama2_bridge as support

# Tee the actual master-to-destination signal into a real WebAudio processor.
# The tee emits zeros; the application's original destination connection stays intact.
PROBE = r"""
window.audioProbe = {inputs:[], chunks:[], contexts:0};
for (const name of ['pointerdown','touchstart','keydown'])
    window.addEventListener(name, e => audioProbe.inputs.push({name,trusted:e.isTrusted,ms:performance.now()}), true);
const connect = AudioNode.prototype.connect;
AudioNode.prototype.connect = function(target, ...args) {
    if (target === this.context.destination && !this.context.__measured) {
        this.context.__measured = true;
        audioProbe.contexts++;
        const tap = this.context.createScriptProcessor(1024, 1, 1);
        tap.onaudioprocess = e => {
            const pcm = Array.from(e.inputBuffer.getChannelData(0));
            audioProbe.chunks.push({ms:performance.now(),rate:e.inputBuffer.sampleRate,pcm});
            if (audioProbe.chunks.length > 100) audioProbe.chunks.shift();
        };
        connect.call(this,tap);
        connect.call(tap,target);
    }
    return connect.call(this,target,...args);
};
"""


class Playgama2AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'audio-events.json').write_text(json.dumps(cls.results, indent=2) + '\n')

    def open(self, lang, touch, saved=False, host=True):
        context = self.browser.new_context(viewport={'width':800 if touch else 1280,'height':450 if touch else 720}, has_touch=touch)
        self.addCleanup(context.close)
        context.add_init_script(PROBE)
        fake = support.FAKE
        fake += "\nvalues['grapnelninja.muted'] = localStorage.getItem('sdk-muted') || " + json.dumps('true' if saved else 'false') + ";"
        fake = fake.replace('keys.forEach((key, i) => values[key] = data[i]);', "keys.forEach((key, i) => { values[key] = data[i]; if (key === 'grapnelninja.muted') localStorage.setItem('sdk-muted',data[i]); });")
        fake += '\nbridge.platform.isAudioEnabled = ' + json.dumps(host) + ';'
        context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body='const FAULT="normal", SAVED_LANGUAGE='+json.dumps(lang)+';\n'+fake))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.goto(self.url + 'current/index.html')
        support.wait_for_boot(page)
        return page

    def measure(self, page, case, phase, audible):
        page.wait_for_timeout(180)
        page.evaluate('audioProbe.chunks = []')
        page.wait_for_timeout(300)
        result = page.evaluate('''() => {
            const chunks = audioProbe.chunks, pcm = chunks.flatMap(c=>c.pcm);
            return {ms:performance.now(),state:AUDIO.getState(),inputs:audioProbe.inputs,
                contexts:audioProbe.contexts,samples:pcm.length,
                rms:Math.sqrt(pcm.reduce((s,v)=>s+v*v,0)/Math.max(1,pcm.length)),
                peak:pcm.reduce((s,v)=>Math.max(s,Math.abs(v)),0),
                rate:chunks[0]?.rate || 44100, pcm};
        }''')
        pcm = result.pop('pcm')
        wav = self.out / f'{case}-{phase}.wav'
        with wave.open(str(wav), 'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(result['rate'])
            f.writeframes(b''.join(struct.pack('<h',max(-32768,min(32767,int(v*32767)))) for v in pcm))
        result.update(phase=phase, wav=wav.name, expected_audible=audible)
        self.results.setdefault(case, []).append(result)
        if audible:
            self.assertGreater(result['samples'], 0, result)
            self.assertGreater(result['rms'], .001, result)
            self.assertEqual(result['state']['state'], 'running')
        else:
            self.assertLess(result['rms'], .00001, result)
        result['verdict'] = 'PASS ' + phase
        print(f"PASS {case}/{phase}: rms={result['rms']:.7f} samples={result['samples']} state={result['state']} t={result['ms']:.1f}ms", flush=True)

    def start(self, page, touch):
        # The run (and its music request) starts at boot, before any input; the
        # AudioContext must only appear on the first trusted gesture. That gesture
        # is the real HUD-menu then pause-switch click/tap into classic.
        self.assertTrue(page.evaluate('runInProgress && !menu.visible'))
        support.Playgama2BridgeTests.click_mode(self, page, 'classic', touch)
        self.assertTrue(page.evaluate('runInProgress && !menu.visible && !menu.gamePaused'))
        self.assertTrue(page.evaluate('AUDIO.getState().started'))

    def toggle(self, page, touch):
        button = page.get_by_role('button', name=page.locator('#mute-button').get_attribute('aria-label'), exact=True)
        if touch: button.tap()
        else: button.click()

    def capture(self, page, case, phase):
        path = self.out / f'{case}-{phase}.png'
        subprocess.run(['import','-window','root',str(path)], env=self.env, check=True, timeout=12)
        import hashlib
        self.results[case][-1]['capture'] = {'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'label':page.locator('#mute-button').get_attribute('aria-label')}

    def matrix(self, lang, touch):
        case = lang + ('-touch' if touch else '-desktop')
        page = self.open(lang,touch)
        self.measure(page,case,'before-gesture',False)
        self.assertFalse(page.evaluate('AUDIO.getState().started'))
        self.start(page, touch)
        self.measure(page,case,'fresh-unlocked',True)
        self.assertTrue(page.evaluate('audioProbe.inputs.some(e=>e.trusted)'))
        self.capture(page,case,'fresh')
        # Gameplay input produces a synthesized throw, not just ambient output.
        page.wait_for_timeout(300)
        if touch: page.touchscreen.tap(400,220)
        else: page.mouse.click(600,350)
        self.assertTrue(page.evaluate("__audioLog.some(e=>e.name==='throw' && !e.muted)"))
        self.toggle(page,touch)
        self.measure(page,case,'user-muted',False)
        page.wait_for_function("localStorage.getItem('sdk-muted') === 'true'")
        self.results[case][-1]['storage_calls'] = page.evaluate("probe.calls.filter(e=>e.name==='storage.set')")
        page.reload(); support.wait_for_boot(page)
        self.assertEqual(page.locator('#mute-button').get_attribute('aria-pressed'),'true')
        page.keyboard.press('a')
        self.measure(page,case,'saved-muted',False)
        self.capture(page,case,'saved-muted')
        self.toggle(page,touch)
        self.measure(page,case,'restored',True)
        page.wait_for_function("localStorage.getItem('sdk-muted') === 'false'")
        page.reload(); support.wait_for_boot(page)
        self.measure(page,case,'restored-before-gesture',False)
        page.keyboard.press('a')
        self.measure(page,case,'restored-session',True)
        self.capture(page,case,'restored')
        # Native keyboard semantics, including Space (game scroll suppression must not consume it).
        page.locator('#mute-button').focus(); page.keyboard.press('Space')
        self.measure(page,case,'keyboard-muted',False)
        page.keyboard.press('Enter')
        self.measure(page,case,'keyboard-restored',True)
        page.evaluate("bridge.platform.isAudioEnabled=false; emitHost('audio',false); emitHost('pause',true); emitHost('interstitial','opened'); emitHost('rewarded','opened')")
        self.measure(page,case,'nested-pauses',False)
        page.evaluate("emitHost('interstitial','failed'); bridge.platform.isAudioEnabled=true; emitHost('audio',true); emitHost('pause',false)")
        self.assertTrue(page.evaluate('adOpen'))
        self.measure(page,case,'rewarded-still-open',False)
        page.evaluate("emitHost('rewarded','closed')")
        self.measure(page,case,'all-causes-cleared',True)
        # OS/browser boundary events, without replacing application handlers.
        page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('blur'))")
        self.measure(page,case,'background',False)
        page.evaluate("emitHost('pause',true); delete document.visibilityState; document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus'))")
        self.measure(page,case,'foreground-host-paused',False)
        page.evaluate("emitHost('pause',false)")
        self.measure(page,case,'foreground',True)
        # Actual death/ad failure paths are covered by test_playgama2_ads.py.
        self.assertEqual(page.evaluate('typeof PLATFORM.requestRewarded'),'undefined')
        self.measure(page,case,'after-host-events',True)
        self.toggle(page,touch)
        page.evaluate("emitHost('rewarded','opened'); emitHost('rewarded','failed')")
        self.measure(page,case,'ad-close-user-muted',False)
        page.context.close()

    def test_en_desktop(self): self.matrix('en',False)
    def test_ru_desktop(self): self.matrix('ru',False)
    def test_en_touch(self): self.matrix('en',True)
    def test_ru_touch(self): self.matrix('ru',True)

    def test_orientation_audio_mute_and_recovery(self):
        page = self.open('en', True)
        case = 'orientation'
        evidence = {
            'browser': 'Chromium', 'version': self.browser.version,
            'emulation': 'Desktop Chromium with has_touch=True; not native Android evidence',
            'user_agent': page.evaluate('navigator.userAgent'),
            'offline': True, 'sdk': 'local fake at network boundary',
            'checkpoints': self.results.setdefault(case, []),
        }
        path = self.out / 'orientation-audio.json'

        def checkpoint(phase, portrait=False, source=None):
            audible = not portrait and source is None
            self.measure(page, case, phase, audible)
            result = evidence['checkpoints'][-1]
            result.update(page.evaluate('''() => ({
                viewport: {width: innerWidth, height: innerHeight},
                overlay: getComputedStyle(document.getElementById('rotate-prompt')).display,
                overlay_visible: !!document.getElementById('rotate-prompt').getClientRects().length,
                inert: document.getElementById('stage').inert,
                rotated: isViewRotated(),
                coarse_pointer: matchMedia('(pointer: coarse)').matches
            })'''))
            result.update(expected_portrait=portrait, overlapping_mute=source)
            path.write_text(json.dumps(evidence, indent=2) + '\n')
            self.assertTrue(any(i['trusted'] and i['name'] == 'touchstart' for i in result['inputs']))
            self.assertTrue(result['coarse_pointer'])
            self.assertEqual(result['inert'], portrait)
            self.assertEqual(result['rotated'], portrait)
            self.assertEqual(result['overlay_visible'], portrait)
            self.assertEqual(result['overlay'], 'flex' if portrait else 'none')
            self.assertEqual(result['state']['muted']['orientation'], portrait)
            self.assertEqual(result['state']['gain'], 1 if audible else 0)
            if source:
                self.assertTrue(result['state']['muted'][source])

        def rotate(portrait):
            page.set_viewport_size({'width': 450 if portrait else 800,
                                    'height': 800 if portrait else 450})
            page.wait_for_function('(portrait) => document.getElementById("stage").inert === portrait', arg=portrait)

        # Start production gameplay/music through a trusted browser touch.
        self.assertFalse(page.evaluate('AUDIO.getState().started'))
        self.start(page, True)
        checkpoint('landscape-start')
        rotate(True)
        checkpoint('portrait', True)
        rotate(False)
        checkpoint('landscape-recovery')
        for source in ('user', 'host'):
            if source == 'user':
                self.toggle(page, True)
            else:
                page.evaluate("bridge.platform.isAudioEnabled=false; emitHost('audio',false)")
            checkpoint(source + '-muted', source=source)
            rotate(True)
            checkpoint(source + '-portrait', True, source)
            rotate(False)
            checkpoint(source + '-landscape', source=source)
            if source == 'user':
                self.toggle(page, True)
            else:
                page.evaluate("bridge.platform.isAudioEnabled=true; emitHost('audio',true)")
            checkpoint(source + '-released')
        print('PASS orientation audio mute and recovery', flush=True)

    def test_initial_host_disabled(self):
        page = self.open('en',False,host=False)
        page.keyboard.press('a')
        self.measure(page,'host-disabled','gesture',False)
        page.evaluate("bridge.platform.isAudioEnabled=true; emitHost('audio',true)")
        self.measure(page,'host-disabled','host-enabled',True)


if __name__ == '__main__': unittest.main()
