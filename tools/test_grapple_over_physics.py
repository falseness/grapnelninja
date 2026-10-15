"""Focused browser evidence for TASK-447 solid contacts and legacy reflection."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, STATE, source_hashes, step
from perf_mobile import SEED_SCRIPT
from test_ninja_bounce import REFLECTION_CHECK, OLD_FORMULA


SETUP = '''
    const d = structuredClone(GRAPPLE_OVER_LEVEL);
    d.elements = [{id:'surface',x:400,y:700,role:'solid',points}];
    d.encounters[0].elements=['surface'];
    floors=[loadFixedLevel(d)];
    const e=floors[0].elements[0];
    const snapshot = () => {
        const distance=Math.sqrt(Math.min(...e.getLines().map(l => segmentDistanceSquared(l,ninja.x,ninja.y))));
        const inside=pointInPolygon(e.getPoints(),ninja.x,ninja.y);
        return {position:[ninja.x,ninja.y],velocity:[ninja.speedX,ninja.speedY],
            penetration:ninja.radius-(inside ? -distance : distance),inside};
    };
'''
RECT = '[{x:0,y:0},{x:600,y:0},{x:600,y:100},{x:0,y:100}]'


class Task447Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-447')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_physics.py', 'tools/test_ninja_bounce.py'):
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT,
            text=True).strip(), source_hashes=hashes, browser=cls.browser.version,
            viewport=[1280,720], device_scale_factor=1, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, mode='grapple_over'):
        context=self.browser.new_context(viewport={'width':1280,'height':720}, device_scale_factor=1)
        self.addCleanup(context.close)
        page=context.new_page()
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate(SEED_SCRIPT % 1)
        page.evaluate('m => {startGame(m);cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def test_solid_contacts_and_600_tick_rest(self):
        page=self.open()
        rows=page.evaluate('''() => {
            const rows=[];
            for (const kind of ['flat','sloped','corner','edge','sunk','separating','reversed']) {
                let points=RECT;
                if(kind==='sloped') points=[{x:0,y:0},{x:600,y:-300},{x:600,y:100},{x:0,y:100}];
                if(kind==='reversed') points.reverse();
                SETUP
                let nx=0,ny=-1,px=700,py=700;
                if(kind==='sloped') {nx=-1/Math.sqrt(5);ny=-2/Math.sqrt(5);py=550;}
                if(kind==='corner') {nx=-Math.SQRT1_2;ny=-Math.SQRT1_2;px=400;}
                if(kind==='edge') {nx=-1;ny=0;px=400;py=750;}
                const offset=kind==='sunk' ? -2 : ninja.radius-2;
                ninja.x=px+nx*offset;ninja.y=py+ny*offset;
                const vn=kind==='separating' ? 9 : -9;
                ninja.speedX=vn*nx-3*ny;ninja.speedY=vn*ny+3*nx;
                // Deliberately green: collision semantics must come from role.
                e.stroke=STYLE.colors.cube.greenStroke;
                const before=snapshot();ninja.collision();const after=snapshot();
                rows.push({kind,normal:[nx,ny],before,after});
            }
            return rows;
        }'''.replace('RECT', RECT).replace('SETUP', SETUP))
        for row in rows:
            nx,ny=row['normal']; a=row['before']['velocity']; b=row['after']['velocity']
            self.assertLessEqual(row['after']['penetration'], 1e-7, row)
            self.assertFalse(row['after']['inside'], row)
            self.assertAlmostEqual(-a[0]*ny+a[1]*nx, -b[0]*ny+b[1]*nx, places=7)
            self.assertAlmostEqual(b[0]*nx+b[1]*ny, max(0,a[0]*nx+a[1]*ny), places=7)
        fast=page.evaluate('''() => {
            const points=RECT; SETUP
            ninja.x=700;ninja.y=600;ninja.speedX=0;ninja.speedY=1000;
            const before=snapshot(), contacts=[];
            const original=ninja.applySolidContact;
            ninja.applySolidContact=function(c) {
                const before=snapshot();original.call(this,c);
                contacts.push({normal:[c.nx,c.ny],before,after:snapshot()});
            };
            let cycles=0;
            while(!contacts.length && cycles<100) {ninja.move();cycles++;}
            delete ninja.applySolidContact;
            const impact=snapshot();
            let maxPenetration=-Infinity, maxSpeed=0, insideCount=0;
            for(let i=0;i<600;i++) {
                physics();const s=snapshot();
                maxPenetration=Math.max(maxPenetration,s.penetration);
                maxSpeed=Math.max(maxSpeed,Math.hypot(...s.velocity));
                insideCount+=Number(s.inside);
            }
            return {kind:'fast-impact',before,contacts,impact,cycles,
                rest:{ticks:600,maxPenetration,maxSpeed,insideCount,final:snapshot()}};
        }'''.replace('RECT', RECT).replace('SETUP', SETUP))
        self.assertGreater(len(fast['contacts']),0)
        self.assertLessEqual(fast['impact']['penetration'],1e-7)
        self.assertLess(fast['impact']['position'][1],700)
        self.assertEqual(fast['impact']['velocity'],[0,0])
        self.assertEqual(fast['rest']['insideCount'],0)
        self.assertLessEqual(fast['rest']['maxPenetration'],1e-7)
        self.assertEqual(fast['rest']['maxSpeed'],0)
        self.evidence.write('contacts.json', dict(self.proof,fixtures=rows,fast=fast,
            solid_projection_pass=True,rest_600_ticks_outside=True))
        print('PASS solid: flat/sloped/corner/edge/sunk/separating/reversed; inward removed, tangent retained; fast-impact; 600 ticks outside')

    def test_green_reflection_and_old_modes(self):
        baseline=json.loads((ROOT/'artifacts/TASK-444/baseline.json').read_text())
        results={}
        for mode in ('classic','bad','grapple_over'):
            page=self.open(mode)
            result={'formula':page.evaluate(REFLECTION_CHECK, 1)}
            self.assertEqual(result['formula']['maxAbsDiff'],0)
            if mode in baseline['modes']:
                result['initial']=page.evaluate(STATE)
                result['movement_trace']=step(page,12)
                self.assertEqual(result['initial'],baseline['modes'][mode]['initial'])
                self.assertEqual(result['movement_trace'],baseline['modes'][mode]['movement_trace'])
                result['baseline_equal']=True
            result['collisions']=page.evaluate('''() => {
                const old=OLD; const rows=[];
                for(const slope of [0,-0.5]) {
                    for(const f of floors) f.elements=[];
                    const e=new Trampoline({x:400,y:700,points:[{x:0,y:100},{x:0,y:0},
                        {x:600,y:slope*600},{x:600,y:slope*600+100}]});
                    // A solid tag outside Grapple Over still uses the old response.
                    e.surfaceRole=version==='grapple_over' ? 'bounce' : 'solid';
                    if(slope!==0) e.stroke='#a3adb8';
                    floors[0].elements=[e];
                    const nx=slope/Math.hypot(slope,1),ny=-1/Math.hypot(slope,1);
                    ninja.x=700+nx*(ninja.radius-2);ninja.y=700+slope*300+ny*(ninja.radius-2);
                    ninja.speedX=-9*nx-3*ny;ninja.speedY=-9*ny+3*nx;
                    const incoming={speedX:ninja.speedX,speedY:ninja.speedY};
                    const expected=old(incoming,e.getLines()[1]);ninja.collision();
                    rows.push({slope,stroke:e.stroke,role:e.surfaceRole,incoming,expected,outgoing:{speedX:ninja.speedX,speedY:ninja.speedY}});
                }
                return rows;
            }'''.replace('OLD',OLD_FORMULA))
            for row in result['collisions']:
                for key in ('speedX','speedY'):
                    self.assertAlmostEqual(row['outgoing'][key],row['expected'][key])
            results[mode]=result
        self.evidence.write('bounce-comparison.json',dict(self.proof,modes=results,
            baseline_path='artifacts/TASK-444/baseline.json',green_reflection_unchanged=True,
            classic_bad_baseline_equal=True))
        print('PASS green reflection: 60 velocities per mode plus flat/sloped runtime contacts; classic/bad baseline equal')
