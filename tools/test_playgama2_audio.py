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
            self.assertGreater(result['rms'], .001, result)
            self.assertEqual(result['state']['state'], 'running')
        else:
            self.assertLess(result['rms'], .00001, result)
        result['verdict'] = 'PASS ' + phase
        print(f"PASS {case}/{phase}: rms={result['rms']:.7f} samples={result['samples']} state={result['state']} t={result['ms']:.1f}ms", flush=True)

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
        # Trusted first gesture starts gameplay, including the production music graph.
        point = page.evaluate('''() => { const b=menu.classicVersionButton.background,r=canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}; }''')
        if touch: page.touchscreen.tap(**point)
        else: page.mouse.click(**point)
        self.assertFalse(page.evaluate('menu.visible'))
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
        page.evaluate("bridge.advertisement.isInterstitialSupported=true; bridge.advertisement.showInterstitial=()=>{emitHost('interstitial','opened'); throw Error('INJECTED ad failure')}; window.adResult=PLATFORM.showInterstitial()")
        self.assertEqual(page.evaluate('adResult'),'failed')
        self.measure(page,case,'ad-exception-recovered',True)
        page.evaluate("PLATFORM.interstitialPlayingTimeoutMs=60; bridge.advertisement.showInterstitial=()=>emitHost('interstitial','opened'); window.adResult=PLATFORM.showInterstitial()")
        self.assertEqual(page.evaluate('adResult'),'closed')
        self.measure(page,case,'ad-timeout-recovered',True)
        page.evaluate("bridge.advertisement.isRewardedSupported=true; bridge.advertisement.showRewarded=()=>{emitHost('rewarded','opened'); return Promise.reject(Error('INJECTED rejection'))}; window.adResult=PLATFORM.requestRewarded()")
        self.assertEqual(page.evaluate('adResult'),{'status':'unavailable','reason':'exception'})
        self.measure(page,case,'rewarded-rejection-recovered',True)
        self.toggle(page,touch)
        page.evaluate("emitHost('rewarded','opened'); emitHost('rewarded','failed')")
        self.measure(page,case,'ad-close-user-muted',False)
        page.context.close()

    def test_en_desktop(self): self.matrix('en',False)
    def test_ru_desktop(self): self.matrix('ru',False)
    def test_en_touch(self): self.matrix('en',True)
    def test_ru_touch(self): self.matrix('ru',True)

    def test_initial_host_disabled(self):
        page = self.open('en',False,host=False)
        page.keyboard.press('a')
        self.measure(page,'host-disabled','gesture',False)
        page.evaluate("bridge.platform.isAudioEnabled=true; emitHost('audio',true)")
        self.measure(page,'host-disabled','host-enabled',True)


if __name__ == '__main__': unittest.main()
