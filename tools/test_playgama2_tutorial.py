"""First-run guidance through production boot, storage, and trusted browser input."""
import hashlib
import json
import subprocess
import unittest
from datetime import datetime, timezone

import test_playgama2_bridge as support


class Playgama2TutorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.Playgama2BridgeTests.setUpClass.__func__(cls)
        cls.results = {}
        paths = subprocess.check_output(['git','ls-files'],cwd=support.ROOT,text=True).splitlines()
        paths += ['tutorial.js','tools/test_playgama2_tutorial.py']
        hashes = {p:hashlib.sha256((support.ROOT/p).read_bytes()).hexdigest() for p in sorted(set(paths)) if (support.ROOT/p).is_file() and not p.startswith(('artifacts/','screenshots/'))}
        (cls.out/'tested-source-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'tutorial-cases.json').write_text(json.dumps(cls.results, indent=2, ensure_ascii=False) + '\n')

    def snapshot(self, page):
        return page.evaluate('''() => ({ms:performance.now(), visible:!TUTORIAL.element.hidden,
            text:TUTORIAL.text.textContent, done:PROGRESS.getTutorialDone(),
            loading:!document.getElementById('loading').hidden, readiness:PLATFORM.readiness,
            throwed:!!grapnel?.throwed, calls:probe.calls, inputs:window.inputs})''')

    def start(self, page, touch):
        point = page.evaluate('''() => { const b=menu.classicVersionButton.background,r=canvas.getBoundingClientRect();
            return {x:r.x+(b.x+b.width/2)*r.width/width,y:r.y+(b.y+b.height/2)*r.height/height}; }''')
        if touch: page.touchscreen.tap(**point)
        else: page.mouse.click(**point)
        page.wait_for_function('!menu.visible && !!ninja')
        page.wait_for_function('!unTouch')

    def matrix(self, lang, touch, fault='normal'):
        case = lang + ('-touch' if touch else '-desktop') + ('' if fault == 'normal' else '-' + fault)
        record = self.results[case] = {'utc':datetime.now(timezone.utc).isoformat(), 'fault':fault}
        context = self.browser.new_context(viewport={'width':800 if touch else 1280,'height':450 if touch else 720}, has_touch=touch)
        self.addCleanup(context.close)
        context.add_init_script("window.inputs=[]; for(const name of ['mousedown','mouseup','touchstart','touchend','click']) window.addEventListener(name,e=>inputs.push({name,trusted:e.isTrusted,target:e.target.tagName,ms:performance.now()}),true)")
        fake = support.FAKE.replace('keys.forEach((key, i) => values[key] = data[i]);', "if (FAULT === 'write_rejected') throw Error('INJECTED write rejection'); keys.forEach((key,i)=>{values[key]=data[i];localStorage.setItem('sdk:'+key,data[i])});")
        fake += '\nbridge.platform.language=' + json.dumps(lang) + ';'
        fake += "\nvalues['grapnelninja.tutorialDone']=localStorage.getItem('sdk:grapnelninja.tutorialDone');"
        context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body='const FAULT='+json.dumps(fault)+', SAVED_LANGUAGE='+json.dumps(lang)+';\n'+fake))
        page = context.new_page()
        page.set_default_timeout(12000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url+'current/index.html')
        support.wait_for_boot(page)
        page.wait_for_function("PLATFORM.readiness.state === 'success'")
        record['boot'] = self.snapshot(page)
        self.assertFalse(record['boot']['loading'])
        self.assertFalse(record['boot']['visible'])
        self.start(page,touch)
        record['first'] = self.snapshot(page)
        self.assertTrue(record['first']['visible'])
        self.assertFalse(record['first']['done'])
        expected = {
            ('en',False):'Hold the mouse button to grapple. Release to let go. Move right to score.',
            ('en',True):'Touch and hold to grapple. Lift your finger to let go. Move right to score.',
            ('ru',False):'Удерживайте кнопку мыши, чтобы зацепиться. Отпустите, чтобы отцепиться. Двигайтесь вправо, чтобы набирать очки.',
            ('ru',True):'Коснитесь и удерживайте палец, чтобы зацепиться. Отпустите, чтобы отцепиться. Двигайтесь вправо, чтобы набирать очки.'}
        self.assertEqual(record['first']['text'],expected[lang,touch])
        geometry = page.evaluate('''() => {const a=TUTORIAL.element.getBoundingClientRect(),b=MUTE_BUTTON.element.getBoundingClientRect();
            const r=canvas.getBoundingClientRect(), m=menu.button.background;
            const hud={left:r.x+m.x*scale[version]*r.width/width,top:r.y+m.y*scale[version]*r.height/height,
                right:r.x+(m.x+m.width)*scale[version]*r.width/width,bottom:r.y+(m.y+m.height)*scale[version]*r.height/height};
            const overlap=(x,y)=>x.left<y.right&&x.right>y.left&&x.top<y.bottom&&x.bottom>y.top;
            return {rect:a.toJSON(),fits:a.left>=0&&a.top>=0&&a.right<=innerWidth&&a.bottom<=innerHeight,
                muteOverlap:overlap(a,b),hudOverlap:overlap(a,hud),clipped:TUTORIAL.element.scrollWidth>TUTORIAL.element.clientWidth};}''')
        record['geometry'] = geometry
        self.assertTrue(geometry['fits']); self.assertFalse(geometry['clipped'])
        self.assertFalse(geometry['muteOverlap']); self.assertFalse(geometry['hudOverlap'])
        capture = self.out / (case+'.png')
        subprocess.run(['import','-window','root',str(capture)],env=self.env,check=True,timeout=12)
        record['capture'] = {'path':capture.name,'sha256':hashlib.sha256(capture.read_bytes()).hexdigest()}
        button=page.locator('#tutorial button')
        if touch: button.tap()
        else: button.click()
        record['dismissed']=self.snapshot(page)
        self.assertFalse(record['dismissed']['visible']); self.assertTrue(record['dismissed']['done'])
        self.assertTrue(any(e['trusted'] and e['target']=='BUTTON' and e['name']=='click' for e in record['dismissed']['inputs']))
        # Hold, observe the real grapnel, then release without changing application state.
        if touch:
            cdp=context.new_cdp_session(page)
            cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':600,'y':140}]})
        else:
            page.mouse.move(850,200); page.mouse.down()
        page.wait_for_function('grapnel.throwed')
        record['held']=self.snapshot(page)
        self.assertTrue(record['held']['throwed'])
        if touch: cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        else: page.mouse.up()
        record['released']=self.snapshot(page)
        self.assertFalse(record['released']['throwed'])
        if fault=='normal':
            page.wait_for_function("localStorage.getItem('sdk:grapnelninja.tutorialDone') === 'true'")
            # Remove local application cache to prove remote storage restores completion.
            page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('grapnelninja.')).forEach(k=>localStorage.removeItem(k))")
        else:
            self.assertEqual(page.evaluate("localStorage.getItem('grapnelninja.tutorialDone')"),'true')
        page.reload(); support.wait_for_boot(page)
        self.start(page,touch)
        record['reload']=self.snapshot(page)
        self.assertFalse(record['reload']['visible']); self.assertTrue(record['reload']['done'])
        self.assertFalse(record['reload']['loading'])
        self.assertEqual(errors,[])
        record['verdict']='PASS first display, device wording, native dismissal, hold/release, readiness before dismissal, persisted reload'
        print('PASS '+case+': '+record['verdict'][5:],flush=True)
        context.close()

    def test_en_desktop(self): self.matrix('en',False)
    def test_en_touch(self): self.matrix('en',True)
    def test_ru_desktop(self): self.matrix('ru',False)
    def test_ru_touch(self): self.matrix('ru',True)
    def test_storage_read_rejection(self): self.matrix('en',False,'storage_rejected')
    def test_storage_write_rejection(self): self.matrix('en',False,'write_rejected')


if __name__ == '__main__': unittest.main()
