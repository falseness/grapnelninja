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
        tasks={t['id']:t for t in json.loads((ROOT/'artifacts/tasks.json').read_text())}
        for i,s in enumerate(m['sections']):
            a=tasks[f'TASK-{465+i*3}']['description'];b=tasks[f'TASK-{466+i*3}']['description']
            self.assertIn(s['name'],a);self.assertIn(s['landmark']['name'],a)
            self.assertIn(s['recoveryIntent'],a)
            self.assertEqual(s['band'],dict(left=0,right=6480,top=-(i+1)*1620,bottom=-i*1620))
            for j,e in enumerate(m['encounters'][i*4:i*4+4]):
                self.assertIn(e['id']+': '+e['mechanic'],a if j<2 else b)
                self.assertEqual(e['status'],'planned');self.assertEqual(e['elements'],[])
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
        print('PASS manifest/map: 32 planned encounters; 8 landmarks; 8 bands; 33 connectors; 8 recovery destinations; 2 optional shortcuts; approved brief matches')

    def test_validator_and_partial_runtime(self):
        page=self.open()
        result=page.evaluate('''() => {
            const cases={
                duplicate:d=>d.encounters[1].id=d.encounters[0].id,
                geometry:d=>d.geometry.elements[0].x=Infinity,
                polygon:d=>d.geometry.elements[0].points=[{x:0,y:0}],
                reference:d=>d.connectors[0].to='absent',
                missingRoute:d=>d.connectors.pop(),
                elementReference:d=>{d.encounters[0].status='built';d.encounters[0].elements=['absent'];d.sections[0].status='partial'},
                checkpoint:d=>d.sections[0].checkpoint={x:0,y:0},
                nestedCheckpoint:d=>d.geometry.elements[0].respawnPoint={x:0,y:0},
                surface:d=>d.geometry.elements[0].role='lethal',
                boundary:d=>d.geometry.elements[0].grapplable=false,
                wall:d=>d.geometry.elements[1].x+=30,
                sectionOrder:d=>d.sections.reverse(),
                plannedGeometry:d=>d.encounters[0].elements=['mountain-catch'],
                builtEmpty:d=>{d.encounters[0].status='built';d.sections[0].status='partial'},
                band:d=>d.sections[0].band.top=-999,
                recovery:d=>d.recoveries[0].transport='teleport',
                shortcut:d=>d.shortcuts[0].optional=false,
                spawnTrap:d=>d.geometry.elements.push({id:'trap',x:2100,y:-30,role:'solid',points:[{x:0,y:0},{x:120,y:0},{x:120,y:60},{x:0,y:60}]})
            };
            const rejected=Object.entries(cases).map(([name,mutate])=>{
                const d=structuredClone(GRAPPLE_OVER_MOUNTAIN);mutate(d);
                try {loadMountainLevel(d);return {name,rejected:false,error:null}}
                catch(e){return {name,rejected:true,error:e.message}}
            });
            const empty=loadMountainLevel();
            const d=structuredClone(GRAPPLE_OVER_MOUNTAIN);
            d.geometry.elements.push({id:'authored-pad',x:2100,y:-200,role:'solid',grapplable:true,
                points:[{x:0,y:0},{x:300,y:0},{x:300,y:40},{x:0,y:40}]});
            d.encounters[0].status='built';d.encounters[0].elements=['authored-pad'];d.sections[0].status='partial';
            const partial=loadMountainLevel(d);
            // Exercise the actual world under production physics; planning markers
            // must not instantiate terrain or silently become a summit trigger.
            floors=[partial];ninja.x=d.spawn.x;ninja.y=d.spawn.y;ninja.speedX=ninja.speedY=0;
            const player=ninja;
            for(let i=0;i<120;i++) physics();
            draw();
            return {rejected,emptyElements:empty.elements.map(e=>e.id),
                partialElements:partial.elements.map(e=>e.id),plannedCount:d.encounters.filter(e=>e.status==='planned').length,
                builtCount:d.encounters.filter(e=>e.status==='built').length,sectionStatus:d.sections[0].status,
                finish:partial.level.finish,player:{x:ninja.x,y:ninja.y,radius:ninja.radius,speedY:ninja.speedY},
                samePlayer:ninja===player,sameWorld:floors[0]===partial,completed:partial.climbStats.completed};
        }''')
        expected=['DuplicateId','NonFiniteGeometry','MalformedPolygon','MissingReference','MissingReference','MissingReference',
                  'ForbiddenCheckpoint','ForbiddenCheckpoint','InvalidSurfaceRole','BoundaryTrap','BoundaryTrap',
                  'InvalidSectionOrder','InvalidBuildStatus','InvalidBuildStatus','InvalidSectionOrder',
                  'InvalidRecovery','InvalidShortcut','BoundaryTrap']
        for r,code in zip(result['rejected'],expected):
            self.assertTrue(r['rejected'],r);self.assertTrue(r['error'].startswith(code+':'),r)
        self.assertEqual(len(result['emptyElements']),3)
        self.assertEqual(len(result['partialElements']),4)
        self.assertIn('authored-pad',result['partialElements'])
        self.assertEqual((result['plannedCount'],result['builtCount'],result['sectionStatus']),(31,1,'partial'))
        self.assertIsNone(result['finish']);self.assertFalse(result['completed'])
        self.assertTrue(result['samePlayer'] and result['sameWorld'])
        self.assertAlmostEqual(result['player']['y']+result['player']['radius'],120,delta=1e-5)
        self.assertEqual(result['player']['speedY'],0)
        self.evidence.write('validator.json',dict(self.proof,**result,all_rejections_pass=True,partial_runtime_pass=True))
        print('PASS validator: 18 malformed manifests rejected; duplicate IDs, invalid geometry, missing references, checkpoint fields, surface semantics, boundary traps, section ordering')
        print('PASS partial runtime: 31 planned / 1 built; 4 collision elements; physical catch-floor landing; no completion or player replacement')

    def test_source_hashes(self):
        for path,digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        print('PASS source hashes: tested runtime and harness match working tree')


# Passing layout-v2 fixture: S06 (left, 810 range) with bounce platforms, two
# reasoned solid exceptions, movers in all four encounters, two in-band gaps and
# one fall line onto S05-exit under a drag zone. Test data only, not the game.
V2_FIXTURE = '''d => {
    const el=id=>d.geometry.elements.find(e=>e.id===id), rect=(w,h)=>[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]
    for (const id of ['S06-loading-floor','S06-phase-rest','S06-transfer-head','S06-exit']) el(id).role='bounce'
    d.geometry.elements.push({id:'S06-fixture-pad',x:6200,y:-8720,role:'solid',grapplable:true,points:rect(180,30)},
        {id:'S06-fall-drag',x:6200,y:-8250,role:'drag',grapplable:false,points:rect(240,10)})
    Object.assign(d.sections[5],{designVersion:2,
        solidExceptions:[{element:'S06-fixed-head',kind:'lip',reason:'End-stop lip holding the fixed transfer head'},
            {element:'S06-fixture-pad',kind:'rest-pad',reason:'Breather between mover transfers'}],
        gaps:[{id:'head-to-pad',mandatory:true,from:{x:5600,y:-8630},to:{x:6300,y:-8800}},
            {id:'exit-run',mandatory:true,from:{x:5520,y:-9700},to:{x:6210,y:-9600}}],
        fallLines:[{id:'east-drop',from:'S06-loading-floor',x:6300,landing:'S05-exit'}]})
    return d
}'''
V2_NEGATIVE = {
    'straySolid': ("d=>{d.geometry.elements.find(e=>e.id==='S06-loading-floor').role='solid'}", 'LayoutV2StraySolid: S06.S06-loading-floor'),
    'wideRestPad': ("d=>{d.geometry.elements.find(e=>e.id==='S06-fixture-pad').points[1].x=260;d.geometry.elements.find(e=>e.id==='S06-fixture-pad').points[2].x=260}",
                    'LayoutV2StraySolid: S06.solidExceptions.S06-fixture-pad'),
    'tooFewMovers': ("d=>{for(const e of d.encounters.filter(e=>['S06-02','S06-03','S06-04'].includes(e.id))) e.elements=e.elements.filter(x=>!/weight/.test(x))}",
                     'LayoutV2MoverCoverage: S06.movers'),
    'wrongDirection': ("d=>{d.encounters.find(e=>e.id==='S06-04').exit={left:6380,right:6440,top:-9692,bottom:-9680}}", 'LayoutV2Direction: S06.direction'),
    'gap80': ("d=>{d.sections[5].gaps[0].to={x:5600+0.80*810,y:-8630}}", 'LayoutV2GapBand: S06.gaps.head-to-pad'),
    'gap95': ("d=>{d.sections[5].gaps[0].to={x:5600+0.95*810,y:-8630}}", 'LayoutV2GapBand: S06.gaps.head-to-pad'),
    'missingDragZone': ("d=>{d.geometry.elements=d.geometry.elements.filter(e=>e.id!=='S06-fall-drag')}", 'LayoutV2FallDrag: S06.fallLines.east-drop'),
}


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

    open=Task464Tests.open

    def test_01_current_manifest_legacy_and_v2_fixture_passes(self):
        page=self.open()
        r=page.evaluate('''fixture => {
            const current=layoutV2Report(GRAPPLE_OVER_MOUNTAIN); loadMountainLevel()
            const d=eval(fixture)(structuredClone(GRAPPLE_OVER_MOUNTAIN)), world=loadMountainLevel(d)
            return {current, fixture:layoutV2Report(d), fixtureLoaded:world.level.elements.length,
                fixtureDrag:world.dragZones.length, targets:LAYOUT_V2_GAP_TARGETS}
        }''',V2_FIXTURE)
        cur=r['current']['sections']
        self.assertEqual([s['id'] for s in cur],[f'S{i:02}' for i in range(1,9)])
        for s in cur: self.assertEqual((s['designVersion'],s['legacy'],s['failed']),(1,True,False),s)
        self.assertFalse(r['current']['failed']);self.assertEqual(r['current']['v2'],[])
        # Gap targets are TASK-503's frozen band, not new constants.
        gap=json.loads((ROOT/'artifacts/TASK-503/calibration.json').read_text())['gap_metric']['targets']
        self.assertEqual(r['targets'],gap)
        fx=r['fixture'];self.assertEqual(fx['v2'],['S06']);self.assertFalse(fx['failed'])
        s6=next(s for s in fx['sections'] if s['id']=='S06')
        self.assertEqual(sorted(s6['rules']),['bounceDefault','direction','fallDrag','gapBand','moverCoverage'])
        for name,rule in s6['rules'].items(): self.assertTrue(rule['passed'],name)
        self.assertEqual(s6['range'],810);self.assertEqual(s6['errors'],[])
        rules=s6['rules']
        self.assertEqual(rules['moverCoverage']['measured']['count'],4)
        self.assertEqual((rules['direction']['measured']['required'],rules['direction']['measured']['actual']),('left','left'))
        for g in rules['gapBand']['measured']['gaps']: self.assertTrue(689<=g['distance']<=729 and 0.85<=g['fraction']<=0.9,g)
        self.assertEqual(rules['fallDrag']['measured']['fallLines'][0]['dragZone'],'S06-fall-drag')
        self.assertTrue(all(p['role']=='bounce' or p['mover'] or p['exception'] for p in rules['bounceDefault']['measured']['platforms']))
        self.assertEqual(r['fixtureDrag'],1)
        self.evidence.write('rules.json',dict(self.proof,current_manifest=r['current'],v2_fixture=fx,
            v2_fixture_section=s6,fixture_loaded_elements=r['fixtureLoaded'],gap_targets=r['targets'],
            current_all_legacy_no_failure=True,fixture_all_rules_passed=True))
        print('PASS rules: current manifest 8/8 sections v1 legacy, no failure; v2 fixture S06 passes bounceDefault, moverCoverage(4), direction(left), gapBand(810: '
              +', '.join(f"{g['distance']:.1f}" for g in rules['gapBand']['measured']['gaps'])+'), fallDrag')

    def test_02_each_rule_rejects_its_fixture(self):
        page=self.open()
        r=page.evaluate('''([fixture,cases]) => Object.entries(cases).map(([name,[mutate]])=>{
            const d=eval(fixture)(structuredClone(GRAPPLE_OVER_MOUNTAIN)); eval(mutate)(d)
            const s=layoutV2Report(d).sections.find(s=>s.id==='S06')
            let error=null; try {loadMountainLevel(d)} catch(e){error=e.message}
            return {name,error,failedRules:Object.entries(s.rules).filter(([,v])=>!v.passed).map(([k])=>k),
                errors:s.errors,measured:Object.fromEntries(Object.entries(s.rules).filter(([,v])=>!v.passed).map(([k,v])=>[k,v.measured]))}
        })''',[V2_FIXTURE,V2_NEGATIVE])
        expect={'straySolid':'bounceDefault','wideRestPad':'bounceDefault','tooFewMovers':'moverCoverage',
                'wrongDirection':'direction','gap80':'gapBand','gap95':'gapBand','missingDragZone':'fallDrag'}
        for c in r:
            self.assertEqual(c['error'],V2_NEGATIVE[c['name']][1],c)
            self.assertEqual(c['failedRules'],[expect[c['name']]],c)
        frac={c['name']:c['measured']['gapBand']['gaps'][0]['fraction'] for c in r if c['name'].startswith('gap')}
        self.assertAlmostEqual(frac['gap80'],0.80);self.assertAlmostEqual(frac['gap95'],0.95)
        self.evidence.write('negative.json',dict(self.proof,cases=r,all_rejected_with_rule_specific_error=True))
        for c in r: print(f"PASS negative {c['name']}: rejected {c['error']}")

    def test_03_source_hashes(self):
        for path,digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        print('PASS source hashes: tested runtime and harness match working tree')
