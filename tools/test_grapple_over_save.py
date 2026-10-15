"""In-memory save/replay and atomic rejection evidence for TASK-456."""
import hashlib
import json
import unittest

from grapple_over_test_support import ROOT
from test_grapple_over_physics import Task447Tests


FIXTURE = '''kind => {
    const d=structuredClone(GRAPPLE_OVER_LEVEL);
    d.movers=[{id:'step-motion',element:'right-step',axis:'x',min:550,max:650,periodMs:1700,phase:.25}];
    d.elements.push({id:'red',x:1300,y:1400,role:'hazard',points:[{x:0,y:0},{x:300,y:0},{x:300,y:60},{x:0,y:60}]});
    d.encounters[0].elements.push('red');
    floors=[loadFixedLevel(d)];
    ninja.x=1100;ninja.y=600;ninja.speedX=.3;ninja.speedY=1;
    grapnel=new Grapnel({stroke:STYLE.colors.player.cyan});
    pressHeld=false;stalePress=false;
    for(let i=0;i<7;i++)physics();
    if(kind==='wrapped-moving') {
        const e=floors[0].byId.get('right-step');
        grapnel.throwed=grapnel.grappled=true;pressHeld=true;
        grapnel.pos=[[e.x,e.y,e],[e.x+300,e.y,e]];
        ninja.x=e.x+340;ninja.y=e.y+150;
    }
    if(kind==='flight') {
        grapnel.throwed=true;pressHeld=true;
        grapnel.speedX=-2;grapnel.speedY=1;grapnel.traveled=15;
        grapnel.pos=[[ninja.x-15,ninja.y+7,new Empty()]];
        grapnel.move(); // Include a pending swept collision step.
    }
    if(kind==='knockback') {
        ninja.x=1400;ninja.y=1400-ninja.radius+1;ninja.speedY=2;
        pressHeld=true;ninja.collision();
    }
    if(kind==='completed') floors[0].climbStats.completed=true;
    return captureClimbState();
}'''

REPLAY = '''() => {
    const trace=[],events=[];
    const solid=ninja.applySolidContact, hazard=ninja.applyHazardContact;
    ninja.applySolidContact=function(c){events.push(['solid',trace.length]);return solid.call(this,c)};
    ninja.applyHazardContact=function(c){events.push(['hazard',trace.length]);return hazard.call(this,c)};
    for(let i=0;i<600;i++) {physics();trace.push(captureClimbState())}
    delete ninja.applySolidContact;delete ninja.applyHazardContact;
    return {trace,events};
}'''


class Task456Tests(unittest.TestCase):
    task_id='TASK-456'
    open=Task447Tests.open

    @classmethod
    def setUpClass(cls):
        Task447Tests.setUpClass.__func__(cls)
        for name in ('tools/test_grapple_over_save.py',):
            cls.proof['source_hashes'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.evidence.log('CONFIG '+json.dumps(cls.proof,sort_keys=True))

    def test_roundtrip_600_ticks(self):
        page=self.open()
        fixtures=[]
        for kind in ('free-fall','flight','wrapped-moving','knockback','completed'):
            original=page.evaluate(FIXTURE,kind)
            if kind=='wrapped-moving':
                self.assertEqual([p['id'] for p in original['grapple']['segments']],['right-step']*2)
            if kind=='knockback':
                self.assertEqual(original['player']['hazardCooldownMs'],350)
                self.assertTrue(original['input']['stalePress'])
            first=page.evaluate(REPLAY)
            restored=page.evaluate('s=>{restoreClimbState(s);return captureClimbState()}',original)
            second=page.evaluate(REPLAY)
            # Compare every numeric leaf, all IDs, flags, lengths and gameplay events.
            errors=[]
            def compare(a,b):
                self.assertEqual(type(a),type(b))
                if isinstance(a,dict):
                    self.assertEqual(a.keys(),b.keys())
                    for k in a: compare(a[k],b[k])
                elif isinstance(a,list):
                    self.assertEqual(len(a),len(b))
                    for x,y in zip(a,b): compare(x,y)
                elif isinstance(a,(float,int)) and not isinstance(a,bool):
                    errors.append(abs(a-b));self.assertLessEqual(abs(a-b),1e-6)
                else: self.assertEqual(a,b)
            compare(original,restored);compare(first,second)
            fixtures.append(dict(kind=kind,original=original,restored=restored,
                original_run=first,restored_run=second,ticks=600,max_error=max(errors),
                exact_ids_and_events=True))
        self.evidence.write('roundtrip.json',dict(self.proof,fixtures=fixtures,roundtrip_pass=True))
        print('PASS roundtrip: 5 fixtures x 600 physics ticks; max error <=1e-6; exact element IDs and gameplay events')

    def test_invalid_atomic_rejection(self):
        page=self.open()
        page.evaluate(FIXTURE,'wrapped-moving')
        rows=page.evaluate('''() => {
            const base=captureClimbState(),rows=[];
            const mutations={
                'save-version':s=>s.version=99,
                'level-version':s=>s.levelVersion=99,
                'missing-anchor':s=>s.grapple.segments[0].id='missing',
                'missing-element':s=>s.elements.pop(),
                'duplicate-element':s=>s.elements[0].id=s.elements[1].id,
                'nan':s=>s.player.x=NaN,
                'infinity':s=>s.elements[0].dx=Infinity,
                'invalid-local':s=>s.grapple.segments[0].x=-Infinity,
                'negative-tick':s=>s.simulationTick=-1,
                'fractional-tick':s=>s.simulationTick=.5,
                'missing-player':s=>delete s.player,
                'malformed-stats':s=>s.stats.completed='yes',
                'malformed-grapple':s=>s.grapple.segments={},
                'inconsistent-grapple':s=>s.grapple.throwed=false,
                'null':s=>null
            };
            for(const [kind,mutate] of Object.entries(mutations)) {
                let s=structuredClone(base);const changed=mutate(s);if(changed===null)s=null;
                const identities=[ninja,grapnel,floors[0]];let error=null;
                try{restoreClimbState(s)}catch(e){error=e.message}
                rows.push({kind,error,rejected:!!error,
                    unchanged:JSON.stringify(base)===JSON.stringify(captureClimbState()),
                    sameObjects:ninja===identities[0]&&grapnel===identities[1]&&floors[0]===identities[2]});
            }
            return rows;
        }''')
        for row in rows:
            self.assertTrue(row['rejected'] and row['unchanged'] and row['sameObjects'],row)
        self.evidence.write('invalid.json',dict(self.proof,cases=rows,atomic_rejection_pass=True))
        print('PASS invalid: 15 bad versions/references/numbers/malformed states rejected; no partial application')
