"""Desktop production-path matrix: trusted inputs, natural deaths, SDK boundary fault.

Captures are native-resolution Chromium viewport PNGs, without resampling.
No physics, renderer, input handler, or application state is replaced.

The title menu is gone (TASK-364): the page boots straight into a 'bad' run,
'classic' is reached through the pause screen's mode switch, and the death
screen (shown when a game over interstitial is due, TASK-370) switches back.
The language button sits on the pause and death screens, the fps counter on
the pause screen. Runnable from the repo root or tools/: git and source
hashes resolve against ROOT.

PLAYGAMA2_EVIDENCE_DIR selects the output directory (default artifacts/TASK-393).
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from datetime import datetime, timezone

from browser_test_support import start_browser_test, wait_for_boot
from layout_matrix import PROBE, evaluate
import test_playgama2_bridge as support
from test_mode_switch import EXTRA

SIZES = [(800, 600), (925, 925), (1920, 1080), (2560, 1080)]


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', support.ROOT / 'artifacts/TASK-393'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(support.ROOT, cls.addClassCleanup)
        cls.results, cls.errors, cls.console = {}, [], []
        paths = subprocess.check_output(['git', 'ls-files'], text=True, cwd=support.ROOT).splitlines()
        paths += ['tools/test_playgama2_desktop.py']
        cls.hashes = {p: hashlib.sha256((support.ROOT / p).read_bytes()).hexdigest() for p in sorted(set(paths))
                      if not p.startswith(('artifacts/', 'screenshots/'))}
        (cls.out / 'tested-source-hashes.json').write_text(json.dumps(cls.hashes, indent=2)+'\n')

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'layout.json').write_text(json.dumps(cls.results, indent=2)+'\n')
        (cls.out / 'browser-errors.log').write_text(''.join(x+'\n' for x in cls.errors))
        (cls.out / 'console.log').write_text(''.join(x+'\n' for x in cls.console))

    def click(self, p, expression, scaled=False):
        p.wait_for_function('!unTouch')
        point = p.evaluate('''() => {const b='''+expression+''',r=canvas.getBoundingClientRect(),s='''+('scale[version]' if scaled else '1')+''';
            return {x:r.x+(b.x+b.width/2)*s*r.width/width,y:r.y+(b.y+b.height/2)*s*r.height/height}}''')
        self.assertEqual(p.evaluate('p=>document.elementFromPoint(p.x,p.y).tagName', point), 'CANVAS')
        p.mouse.click(**point)
        self.record['hits'].append({'control': expression, 'point': point, 'target': 'CANVAS', 'trusted': True})

    def shot(self, p, phase, draw='draw()'):
        p.evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        raw = p.evaluate(PROBE, draw)
        row, boxes = evaluate(raw, False)
        row.update(raw=raw, phase=phase, utc=datetime.now(timezone.utc).isoformat())
        self.record['screens'].append(row)
        self.assertEqual(row['failures'], [], row)
        c, w = raw['canvas'], raw['scroll']['window']
        self.assertTrue(abs(c['width']-w['width'])<1 or abs(c['height']-w['height'])<1)
        self.assertGreaterEqual(c['left'], -0.5); self.assertGreaterEqual(c['top'], -0.5)
        self.assertLessEqual(c['left']+c['width'], w['width']+0.5)
        self.assertLessEqual(c['top']+c['height'], w['height']+0.5)
        distortion = p.evaluate('Math.abs(canvas.getBoundingClientRect().width/width-canvas.getBoundingClientRect().height/height)')
        self.assertLess(distortion, .001)
        dom = p.evaluate('''() => [...document.querySelectorAll('button, #tutorial')].filter(e=>!e.hidden&&e.getBoundingClientRect().width).map(e=>{
            const r=e.getBoundingClientRect(); return {id:e.id||e.textContent,rect:r.toJSON(),fits:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
            unclipped:e.scrollWidth<=e.clientWidth,hit:e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}})''')
        row['dom'] = dom
        for d in dom:
            self.assertTrue(d['fits'] and d['unclipped'] and d['hit'], d)
        name = self.case+'-'+phase+'.png'
        p.screenshot(path=str(self.out/name))
        row['capture'] = {'path':name, 'sha256':hashlib.sha256((self.out/name).read_bytes()).hexdigest(), 'native_viewport':p.viewport_size}

    # Real clicks: HUD menu button, then the pause screen's mode switch
    def switch_on_pause(self, p, target):
        self.click(p, 'menu.button.background', True)
        p.wait_for_function('menu.gamePaused')
        self.assertEqual(p.evaluate('menu.backToMenu.text.text'), p.evaluate("I18N.t('menu.chillVersion')"))
        self.click(p, 'menu.backToMenu.background')
        p.wait_for_function('t => version === t && !!ninja && runInProgress && !menu.gamePaused', arg=target)

    def matrix(self, size, mode):
        self.case = f'{size[0]}x{size[1]}-{mode}'
        self.record = self.results[self.case] = {'screens':[], 'hits':[], 'utc':datetime.now(timezone.utc).isoformat()}
        ctx = self.browser.new_context(viewport=dict(zip(('width','height'), size)), locale='en-US')
        self.addCleanup(ctx.close)
        ctx.add_init_script("window.realInputs=[]; for(const n of ['mousedown','mouseup','keydown','click']) addEventListener(n,e=>realInputs.push({type:n,trusted:e.isTrusted}),true)")
        fault = 'storage_rejected' if size == SIZES[-1] else 'normal'
        ctx.route(support.SDK, lambda r:r.fulfill(content_type='application/javascript',body='const FAULT='+json.dumps(fault)+', SAVED_LANGUAGE="en";\n'+support.FAKE+EXTRA+'\nbridge.platform.language="en";'))
        p = ctx.new_page(); p.set_default_timeout(20000)
        errors=[]
        p.on('pageerror', lambda e:errors.append(str(e)))
        p.on('console', lambda m:self.console.append(self.case+' '+m.type+': '+m.text))
        p.on('console', lambda m:errors.append(m.text) if m.type=='error' else None)
        self.addCleanup(lambda:self.errors.extend(self.case+' '+e for e in errors))
        p.goto(self.url+'index.html'); wait_for_boot(p)
        # Boot run (TASK-360): a 'bad' run with the tutorial hint, no title menu
        p.wait_for_function('bootComplete && runInProgress && !!ninja')
        self.assertEqual(p.evaluate('[version, TUTORIAL_HINT.visible, menu.gamePaused]'), ['bad', True, False])
        self.shot(p, 'boot-run')
        if mode == 'classic':
            self.switch_on_pause(p, 'classic')
        self.assertEqual(p.evaluate('version'), mode)
        self.shot(p, 'tutorial')
        self.assertTrue(p.evaluate('TUTORIAL_HINT.visible && !TUTORIAL_HINT.pressed'))
        p.mouse.move(size[0]*.7,size[1]*.3); p.mouse.down()
        p.wait_for_function('grapnel.throwed')
        self.assertTrue(p.evaluate('TUTORIAL_HINT.pressed'))
        p.mouse.up(); self.assertFalse(p.evaluate('grapnel.throwed'))
        p.keyboard.press('p'); self.assertTrue(p.evaluate('menu.gamePaused'))
        self.shot(p, 'settings', 'menu.drawPauseScreen()')
        self.click(p, 'LANGUAGE_BUTTON.rect()')
        self.assertEqual(p.evaluate('I18N.language'), 'ru')
        self.click(p, 'LANGUAGE_BUTTON.rect()')
        self.assertEqual(p.evaluate('I18N.language'), 'en')
        self.click(p, 'menu.pauseFpsCounterCheckbox.hitRect()')
        self.assertTrue(p.evaluate('fpsCounter.enabled'))
        self.click(p, 'menu.pauseFpsCounterCheckbox.hitRect()')
        self.assertFalse(p.evaluate('fpsCounter.enabled'))
        before = p.evaluate('({score:scoreText.count[version],mode:version,x:ninja.x,y:ninja.y,time:PROGRESS.getTime(),record:scoreText.record[version]})')
        other = SIZES[(SIZES.index(size)+1)%len(SIZES)]
        for target in [other,size]:
            p.set_viewport_size(dict(zip(('width','height'),target))); p.wait_for_timeout(250)
            after = p.evaluate('({score:scoreText.count[version],mode:version,x:ninja.x,y:ninja.y,time:PROGRESS.getTime(),record:scoreText.record[version]})')
            self.assertEqual(before,after)
            self.record.setdefault('resize',[]).append({'before':before,'after':after,'viewport':target})
            self.shot(p,'resize-'+str(target[0]),'menu.drawPauseScreen()')
        self.click(p,'menu.resume.background'); self.assertFalse(p.evaluate('menu.gamePaused'))
        p.keyboard.press('Escape'); self.assertTrue(p.evaluate('menu.gamePaused'))
        p.keyboard.press('Escape'); self.assertFalse(p.evaluate('menu.gamePaused'))
        self.click(p,'menu.button.background',True); self.assertTrue(p.evaluate('menu.gamePaused'))
        self.click(p,'menu.resume.background')
        self.shot(p,'gameplay')
        # Death UI is shared between modes. Cover it at each viewport through
        # Chill's natural idle death; Main can bounce indefinitely without death.
        if mode == 'bad':
            self.switch_on_pause(p, 'classic')
        # No interstitial was requested yet, so a game over ad is due and the
        # death screen opens (TASK-370)
        self.assertTrue(p.evaluate('PLATFORM.isInterstitialDue()'))
        p.wait_for_function('continueOffer.visible && !continueOffer.adPending', timeout=60000)
        self.record['death_mode'] = p.evaluate('version')
        self.assertEqual(self.record['death_mode'], 'classic')
        self.assertEqual(p.evaluate('continueOffer.switchButton.text.text'), p.evaluate("I18N.t('menu.mainVersion')"))
        self.shot(p,'death','continueOffer.draw()')
        self.click(p,'continueOffer.switchButton.background')
        p.wait_for_function("version === 'bad' && !!ninja && runInProgress && !continueOffer.visible && !interstitialPending && !menu.gamePaused")
        self.assertIn('game_over', p.evaluate("probe.calls.filter(c => c.name === 'interstitial_request').map(c => c.data)"))
        self.shot(p,'switched')
        self.assertTrue(p.evaluate('realInputs.length>10 && realInputs.every(e=>e.trusted)'))
        p.mouse.wheel(0,800); p.keyboard.press('PageDown')
        self.assertEqual(p.evaluate('[scrollX,scrollY]'),[0,0])
        self.assertEqual(errors,[])
        self.record.update(verdict='PASS', fault=fault, inputs=p.evaluate('realInputs'))
        print('PASS '+self.case+': boot-run/tutorial-hint/settings/gameplay/death-switch; native mouse/keyboard dismissal; resize progress identical; bounds, hit tests, aspect, no deformation/scroll/overlap/errors',flush=True)
        ctx.close()


for size in SIZES:
    for mode in ('classic','bad'):
        setattr(DesktopTests,f'test_{size[0]}x{size[1]}_{mode}',lambda self,s=size,m=mode:self.matrix(s,m))

if __name__ == '__main__':
    unittest.main()
