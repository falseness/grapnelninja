"""TASK-446 runtime proof for authored, persistent fixture loading."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, STATE, source_hashes, step
from perf_mobile import SEED_SCRIPT

GEOMETRY = '''world => world.elements.map(e => ({id:e.id, role:e.surfaceRole,
    x:e.x,y:e.y,points:e.points}))'''


class Task446Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-446')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        for name in ('fixedlevel.js', 'tools/test_grapple_over_world.py'):
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            cwd=ROOT, text=True).strip(), 'source_hashes': hashes,
            'browser': cls.browser.version, 'viewports': [[1280, 720], [960, 720]],
            'device_scale_factor': 1, 'seed': 1}
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, width=1280, mode='grapple_over'):
        context = self.browser.new_context(viewport={'width': width, 'height': 720},
                                           device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate(SEED_SCRIPT % 1)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def test_repeated_loads_validation_and_movers(self):
        observations = []
        for width in (1280, 960):
            page = self.open(width)
            for repeat in range(2):
                rows = page.evaluate('() => (' + GEOMETRY + ')(loadFixedLevel())')
                observations.append(dict(viewport=[width, 720], repeat=repeat, geometry=rows))
        self.assertEqual([e['id'] for e in rows], ['base', 'right-step', 'left-step', 'top-step'])
        for observation in observations:
            self.assertEqual(observation['geometry'], observations[0]['geometry'])
        errors = page.evaluate('''() => {
            const cases = {
                duplicate: d => d.elements[1].id = d.elements[0].id,
                nonfinite: d => d.elements[0].x = Infinity,
                polygon: d => d.elements[0].points = [{x:0,y:0},{x:1,y:1}],
                crossed: d => d.elements[0].points = [{x:0,y:0},{x:3,y:3},{x:0,y:3},{x:3,y:0}],
                repeated: d => d.elements[0].points[1] = d.elements[0].points[0],
                mover: d => d.movers = [{id:'move',element:'base',axis:'x',min:200,max:100,periodMs:1000,phase:0}],
                moverOutside: d => d.movers = [{id:'move',element:'base',axis:'x',min:100,max:1800,periodMs:1000,phase:0}],
                reference: d => d.encounters[0].elements.push('absent'),
                section: d => d.sections[0].encounters.push('absent'),
                moverReference: d => d.movers = [{id:'move',element:'absent'}],
                bounds: d => d.bounds.right = d.bounds.left,
                spawn: d => d.spawn.y = NaN,
                finish: d => d.finish = {left:0,right:1,top:0,bottom:NaN},
                role: d => d.elements[0].role = 'lethal',
                version: d => d.version = 2
            };
            return Object.entries(cases).map(([name, mutate]) => {
                const d = structuredClone(GRAPPLE_OVER_LEVEL); mutate(d);
                try {loadFixedLevel(d); return {name,error:null}}
                catch (e) {return {name,error:e.message}}
            });
        }''')
        expected = ['DuplicateId', 'NonFiniteGeometry', 'MalformedPolygon', 'MalformedPolygon',
                    'MalformedPolygon', 'InvalidMoverBounds', 'InvalidMoverBounds', 'MissingReference',
                    'MissingReference', 'MissingReference', 'InvalidBounds', 'NonFiniteGeometry',
                    'NonFiniteGeometry', 'InvalidSurfaceRole', 'UnsupportedVersion']
        for row, name in zip(errors, expected):
            self.assertTrue(row['error'].startswith(name + ':'), row)
        movers = page.evaluate('''() => {
            const d = structuredClone(GRAPPLE_OVER_LEVEL);
            d.movers = [{id:'move',element:'right-step',axis:'x',min:600,max:700,periodMs:1000,phase:0}];
            const a = loadFixedLevel(d), b = loadFixedLevel(d);
            d.elements[1].points[0].x = 99;
            const rows = [];
            for (let i=0;i<960;i++) {
                a.moveElements(); b.moveElements();
                if ([239,479,719,959].includes(i)) rows.push({step:i+1,
                    x:a.byId.get('right-step').x, otherX:b.byId.get('right-step').x,
                    dx:a.byId.get('right-step').dx});
            }
            return {rows, isolated:a.elements[1].points[0].x === 0};
        }''')
        self.assertTrue(movers['isolated'])
        for row, x in zip(movers['rows'], (700, 600, 700, 600)):
            self.assertAlmostEqual(row['x'], x)
            self.assertEqual(row['x'], row['otherX'])
        self.evidence.write('loader.json', dict(self.proof, observations=observations,
            identical_geometry_ids=True, invalid_fixtures=errors, movers=movers,
            camera_travel_proof='world-trace.json'))
        print('PASS loader: 4 repeated loads at 2 viewports; identical geometry/IDs; 15 named validation errors; deterministic movers')

    def test_camera_travel_preserves_world(self):
        page = self.open()
        trace = page.evaluate('''() => {
            let proceduralCalls = 0;
            const originals = [];
            for (const [proto, names] of [[Floor.prototype,['generateElements','generatePrimaryElements','replenishElements']],
                                         [ElementsFactory.prototype,['create']]])
                for (const name of names) {
                    originals.push([proto,name,proto[name]]);
                    proto[name] = function() {proceduralCalls++; throw new Error('Procedural spawning: '+name)};
                }
            try {
                startGame('grapple_over'); cancelAnimationFrame(game);
                const world = floors[0], elements = world.elements, refs = elements.slice();
                const geometry = () => elements.map(e => ({id:e.id,x:e.x,y:e.y,points:e.points}));
                const before = geometry(), rows = [];
                for (const [direction,x,y] of [['origin',0,0],['forward',-10000,0],
                    ['backward',10000,0],['up',0,10000],['down',0,-10000],['return',0,0]]) {
                    screen.x=x; screen.y=y;
                    physics(); draw();
                    world.deleteElements(); world.replenishElements();
                    world.generatePrimaryElements(); world.generateElements();
                    rows.push({direction,camera:[screen.x,screen.y],count:world.elements.length,
                        sameGroup:floors[0]===world, sameArray:world.elements===elements,
                        sameObjects:refs.every((e,i)=>world.elements[i]===e),geometry:geometry()});
                }
                return {before,rows,proceduralCalls};
            } finally {for (const [proto,name,fn] of originals) proto[name]=fn}
        }''')
        self.assertEqual(trace['proceduralCalls'], 0)
        for row in trace['rows']:
            self.assertEqual(row['count'], 4)
            self.assertTrue(row['sameGroup'] and row['sameArray'] and row['sameObjects'])
            self.assertEqual(row['geometry'], trace['before'])
        self.evidence.write('world-trace.json', dict(self.proof, **trace,
            constant_terrain_identity_count=True, no_procedural_spawning=True))
        print('PASS travel: forward/backward/up/down/return; count=4; same objects and geometry; proceduralCalls=0')

    def test_classic_bad_baseline(self):
        baseline = json.loads((ROOT / 'artifacts/TASK-444/baseline.json').read_text())
        for mode in ('classic', 'bad'):
            page = self.open(mode=mode)
            self.assertEqual(page.evaluate(STATE), baseline['modes'][mode]['initial'])
            self.assertEqual(step(page, 12), baseline['modes'][mode]['movement_trace'])
        print('PASS classic/bad: initial state and 12-step traces equal TASK-444 baseline')
