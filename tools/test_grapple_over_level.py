"""Browser-executed mountain contract and partial-runtime proof for TASK-464."""
import hashlib
import json
import subprocess
import unittest
from xml.etree import ElementTree as ET

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes


def map_plan(m):
    """Code-native full-map schematic; positions describe intent, never collision."""
    ns = 'http://www.w3.org/2000/svg'
    ET.register_namespace('', ns)
    def add(parent, tag, **attrs):
        return ET.SubElement(parent, '{'+ns+'}'+tag, {k:str(v) for k,v in attrs.items()})
    svg = ET.Element('{'+ns+'}svg', dict(viewBox='0 0 1800 2900', width='1800', height='2900'))
    add(svg, 'title').text = 'Grapple Over: full mountain plan, 32 planned encounters'
    add(svg, 'rect', width=1800, height=2900, fill='#101821')
    def label(x,y,text,size=16,color='#e6eef5',parent=svg):
        add(parent,'text',x=x,y=y,fill=color,**{'font-size':size,'font-family':'sans-serif'}).text=text
    label(35,35,'MOUNTAIN PLAN — planned routes, not verified playable terrain',26)
    label(35,64,'R=540 | ascent 24R=12960 | width 12R=6480 | negative Y upward | base starts in S01')
    label(35,89,'Cyan: normal connectors | Orange: physical failure/recovery | Violet: optional shortcuts')
    label(35,114,m['difficulty']['note'])
    label(35,139,'Dashed encounter boxes reserve space. Only the boundary shell is built; no finish trigger or automatic relocation.')
    def xy(n):
        return 400+n['x']/6480*1000, 220+(12960+n['y'])/12960*2480
    nodes={n['id']:n for n in [m['base'],m['summit'],*m['encounters']]}
    for s in reversed(m['sections']):
        g=add(svg,'g',id=s['id'])
        _,y=xy(dict(x=0,y=s['band']['top']))
        add(g,'rect',x=400,y=y,width=1000,height=310,fill='none',stroke='#415163')
        label(20,y+25,s['id']+' '+s['name'],20,parent=g)
        label(20,y+50,f"Band [{s['band']['top']}, {s['band']['bottom']}]",parent=g)
        label(20,y+75,s['landmark']['name'],14,parent=g)
        landmark=add(g,'g',id=s['landmark']['id'])
        lx,ly=xy(s['landmark'])
        add(landmark,'path',d=f'M {lx-25} {ly+18} L {lx-25} {ly-18} L {lx} {ly-35} L {lx+25} {ly-18} L {lx+25} {ly+18} Z',fill='none',stroke='#748497')
        add(landmark,'title').text=s['landmark']['name']+' — planned landmark reservation'
        label(20,y+105,'Recovery: '+next(r['to'] for r in m['recoveries'] if r['id']==s['id']+'-fall'),parent=g)
        # Wrap annotations to avoid crowding neighboring section bands.
        import textwrap
        for k,line in enumerate(textwrap.wrap(s['recoveryIntent'],44)):
            label(20,y+130+k*19,line,13,parent=g)
    for kind,color in [('connectors','#49d4ea'),('recoveries','#ffaf62'),('shortcuts','#cba0ff')]:
        for r in m[kind]:
            x1,y1=xy(nodes[r['from']]);x2,y2=xy(nodes[r['to']])
            g=add(svg,'g',id=r['id'])
            if kind=='recoveries':
                d=f'M {x1} {y1} L 1450 {y1} L 1450 {y2} L {x2} {y2}'
            elif kind=='shortcuts':
                d=f'M {x1} {y1} L 470 {y1} L 470 {y2} L {x2} {y2}'
            else: d=f'M {x1} {y1} L {x2} {y2}'
            add(g,'path',d=d,fill='none',stroke=color,**{'stroke-width':2,'stroke-dasharray':'7 5'})
            add(g,'circle',cx=x2,cy=y2,r=5,fill=color)
            add(g,'title').text=f"{r['id']}: {r['from']} → {r['to']} ({r['status']}); {r['intent']}"
            if kind!='connectors': label(1460 if kind=='recoveries' else 405,(y1+y2)/2,r['id'],13,color,parent=g)
    for n in nodes.values():
        x,y=xy(n);g=add(svg,'g',id=n['id'])
        add(g,'rect',x=x-55,y=y-13,width=110,height=26,fill='#101821',stroke='#49d4ea',**{'stroke-dasharray':'4 3'})
        label(x-48,y+5,n['id'],15,parent=g)
        add(g,'title').text=f"{n['id']} ({n['x']}, {n['y']}) " + n.get('mechanic','design coordinate')
        if 'mechanic' in n: label(800 if x<900 else 420,y+28,n['mechanic'],13,parent=g)
    label(35,2800,'Built shell: grappleable catch floor y=120; non-grappleable outer walls x=0 and x=6480.')
    label(35,2830,'Recovery lines indicate physical falls and rejoin intent; they never teleport or restore highest progress.')
    label(35,2860,'Landmark symbols are reservations. Industrial collision silhouettes are authored in later section tasks.')
    return ET.tostring(svg,encoding='unicode')+'\n'


class Task464Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence=EvidenceWriter('TASK-464')
        cls.url,cls.browser=start_browser_test(ROOT,cls.addClassCleanup)
        hashes=source_hashes()
        for path in ('mountain.js','tools/test_grapple_over_level.py'):
            hashes[path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        cls.proof=dict(browser=cls.browser.version,viewport=VIEWPORT,device_scale_factor=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_hashes=hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof,sort_keys=True))

    def open(self):
        context=self.browser.new_context(viewport=VIEWPORT,device_scale_factor=1)
        self.addCleanup(context.close)
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        self.addCleanup(lambda:self.assertEqual(errors,[]))
        page.goto(self.url);wait_for_boot(page)
        page.evaluate("startGame('grapple_over'); menu.unPause(); cancelAnimationFrame(game)")
        page.wait_for_function('!unTouch')
        return page

    def test_manifest_and_full_map(self):
        page=self.open()
        m=page.evaluate('''() => {validateMountainManifest(GRAPPLE_OVER_MOUNTAIN); return GRAPPLE_OVER_MOUNTAIN}''')
        self.assertEqual(len(m['sections']),8);self.assertEqual(len(m['encounters']),32)
        self.assertEqual([s['id'] for s in m['sections']],[f'S{i:02}' for i in range(1,9)])
        self.assertEqual(m['base']['y']-m['summit']['y'],12960)
        self.assertEqual(m['bounds']['right']-m['bounds']['left'],6480)
        self.assertEqual([s['from'] for s in m['shortcuts']],['S03-01','S07-01'])
        # Compare actual browser manifest to the approved task brief, not to its own constants.
        # The TASK-465..489 briefs were rotated out of artifacts/tasks.json into the archive.
        tasks={}
        for path in ('artifacts/old_tasks_do_not_touch/tasks.json','artifacts/tasks.json'):
            if (ROOT/path).exists(): tasks.update({t['id']:t for t in json.loads((ROOT/path).read_text())})
        for i,s in enumerate(m['sections']):
            a=tasks[f'TASK-{465+i*3}']['description'];b=tasks[f'TASK-{466+i*3}']['description']
            self.assertIn(s['name'],a);self.assertIn(s['landmark']['name'],a)
            self.assertIn(s['recoveryIntent'],a)
            # Layout v3 (11719c6 TASK-547 onward) doubles each band upward to 3240.
            self.assertEqual(s['designVersion'],3)
            self.assertEqual(s['band'],dict(left=0,right=6480,top=-(i+2)*1620,bottom=-i*1620))
            # Every encounter is built since the section tickets (9f6506b TASK-465 onward).
            self.assertEqual(s['status'],'built')
            for j,e in enumerate(m['encounters'][i*4:i*4+4]):
                self.assertIn(e['id']+': '+e['mechanic'],a if j<2 else b)
                self.assertEqual(e['status'],'built');self.assertTrue(e['elements'],e['id'])
        self.assertEqual(len(m['connectors']),33);self.assertEqual(len(m['recoveries']),8)
        self.assertFalse(m['difficulty']['validated'])
        self.evidence.write('manifest.json',m)
        self.evidence.path('map-plan.svg').write_text(map_plan(m))
        # Open the generated artifact in Chromium too; check it parses and has all annotations.
        page.goto(self.url+'artifacts/'+str(self.evidence.path('map-plan.svg').relative_to((ROOT/'artifacts').resolve())))
        self.assertEqual(page.locator('parsererror').count(),0)
        for n in [*m['encounters'],*[s['landmark'] for s in m['sections']],*m['connectors'],*m['recoveries'],*m['shortcuts']]:
            self.assertEqual(page.locator('[id="'+n['id']+'"]').count(),1)
        self.assertIn('unvalidated without human feedback',page.locator('svg').text_content())
        print('PASS manifest/map: 32 built encounters; 8 landmarks; 8 bands; 33 connectors; 8 recovery destinations; 2 optional shortcuts; approved brief matches')

    def test_source_hashes(self):
        for path,digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        print('PASS source hashes: tested runtime and harness match working tree')


class Task504Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence=EvidenceWriter('TASK-504')
        cls.url,cls.browser=start_browser_test(ROOT,cls.addClassCleanup)
        hashes=source_hashes()
        hashes['tools/test_grapple_over_level.py']=hashlib.sha256((ROOT/'tools/test_grapple_over_level.py').read_bytes()).hexdigest()
        cls.proof=dict(browser=cls.browser.version,viewport=VIEWPORT,device_scale_factor=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty=subprocess.check_output(['git','status','--porcelain','--','*.js','tools/*.py'],cwd=ROOT,text=True).splitlines(),
            source_hashes=hashes)
        cls.evidence.log('CONFIG '+json.dumps(cls.proof,sort_keys=True))

    def test_03_source_hashes(self):
        for path,digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        print('PASS source hashes: tested runtime and harness match working tree')
