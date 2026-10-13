"""Score progression integration and short trusted-input sessions.

Deterministic geometry probes inject scores, not movement or collision results.
The separate input sessions start at injected scores 0/15/25 so late encounters
can be exercised without claiming natural high-score or human balance testing.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from browser_test_support import start_browser_test, wait_for_boot
import test_playgama2_bridge as support


class ProgressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR') or tempfile.mkdtemp())
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(support.ROOT, cls.addClassCleanup)
        cls.results, cls.errors = {}, []

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'progression.json').write_text(json.dumps({
            'browser': cls.browser.version, 'cases': cls.results,
            'limitation': 'Injected starting scores; automated input is not human balance certification.'
        }, indent=2) + '\n')
        (cls.out / 'browser-errors.log').write_text(''.join(e + '\n' for e in cls.errors))

    def page(self, viewport):
        context = self.browser.new_context(viewport=viewport)
        self.addCleanup(context.close)
        context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript',
            body='const FAULT="normal", SAVED_LANGUAGE="en";\n' + support.FAKE))
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('console', lambda m: self.errors.append(m.text) if m.type == 'error' else None)
        page.goto(self.url + 'index.html')
        wait_for_boot(page)
        return page

    def test_geometry_and_lifecycle(self):
        for size in [(800, 600), (1920, 1080), (2560, 1080)]:
            page = self.page(dict(zip(('width', 'height'), size)))
            result = page.evaluate(GEOMETRY)
            self.results['geometry-' + str(size)] = result
            self.assertEqual(self.errors, [])
            print(f'PASS {size}: both modes; all templates; scores 0/5/6/15/25/10000; '
                  'bounded decreasing gaps; existing groups unchanged; reset/mode isolation; resize', flush=True)
            page.context.close()

    def test_input_sessions(self):
        for mode in ('classic', 'bad'):
            for score in (0, 15, 25):
                key = f'{mode}-{score}'
                page = self.page({'width': 1280, 'height': 720})
                # Boot runs 'bad'; classic is reached through the pause switch.
                # The canvas tutorial hint needs no dismiss click (TASK-367).
                support.Playgama2BridgeTests.click_mode(self, page, mode)
                # Explicit late-stage setup: retain production factories/physics/input.
                page.evaluate('''score => {
                    scoreText.count[version]=score;
                    floors[1].elements=[];
                    floors[1].nextGenerationGroupId=0;
                    floors[1].generatePrimaryElements();
                    window.trustedInputs=[];
                    addEventListener('mousedown',e=>trustedInputs.push(e.isTrusted));
                }''', score)
                row = {'injected_start_score': score, 'samples': [], 'captures': []}
                self.results[key] = row
                page.keyboard.press('p')
                before = page.evaluate('JSON.stringify({score:scoreText.count[version],x:ninja.x,y:ninja.y,spacing:obstacleSpacingScale(scoreText.count[version])})')
                page.wait_for_timeout(500)
                self.assertEqual(before, page.evaluate('JSON.stringify({score:scoreText.count[version],x:ninja.x,y:ninja.y,spacing:obstacleSpacingScale(scoreText.count[version])})'))
                page.keyboard.press('p')
                start = time.monotonic()
                while time.monotonic() - start < 15:
                    if page.evaluate('continueOffer.visible'):
                        break
                    page.mouse.move(900, 160)
                    page.mouse.down()
                    page.wait_for_timeout(150)
                    page.mouse.up()
                    page.wait_for_timeout(350)
                    sample = page.evaluate('''() => ({x:ninja.x,y:ninja.y,score:scoreText.count[version],
                        groups:floors[1].nextGenerationGroupId,dead:continueOffer.visible,
                        elements:floors[1].elements.length})''')
                    self.assertLess(sample['elements'], 500)
                    row['samples'].append(sample)
                self.assertGreater(len(row['samples']), 1)
                self.assertGreater(len({(s['x'], s['y']) for s in row['samples']}), 1)
                self.assertTrue(page.evaluate('trustedInputs.length>1 && trustedInputs.every(Boolean)'))
                row['elapsed_seconds'] = time.monotonic() - start
                shot = self.out / (key + '.png')
                page.screenshot(path=str(shot))
                row['captures'].append({'path': shot.name, 'sha256': hashlib.sha256(shot.read_bytes()).hexdigest()})
                row['verdict'] = 'PASS'
                self.assertEqual(self.errors, [])
                print(f'PASS {key}: trusted grapnel input; moving production physics; pause freezes score/spacing; '
                      f'{len(row["samples"])} samples; no browser errors (injected starting score)', flush=True)
                page.context.close()


GEOMETRY = r'''() => {
    const assert = (ok, message) => {if (!ok) throw Error(message)};
    const near = (a,b) => Math.abs(a-b)<1e-6;
    const rows = [];
    for (const mode of ['classic','bad']) {
        startGame(mode); cancelAnimationFrame(game);
        const types = floors[1].creations.map(c=>c.type);
        for (const type of types) {
            let previousGap = Infinity;
            for (const score of [0,5,6,15,25,10000]) {
                scoreText.count[mode] = score;
                Math.random = () => .25;
                const f = new Floor(floors[1].top, floors[1].bottom,
                    {...floors[1].elementsIntervalX}, [{type,chance:100}], mode==='bad'?1:8);
                f.generateElements(.2*width);
                const right = Math.max(...f.elements.map(e=>e.getRightPointX()));
                const old = JSON.stringify(f.elements.map(e=>({x:e.x,y:e.y,points:e.getPoints()})));
                const n = f.elements.length;
                f.generateElements(right);
                const group = f.elements.slice(n);
                assert(old===JSON.stringify(f.elements.slice(0,n).map(e=>({x:e.x,y:e.y,points:e.getPoints()}))), 'existing group moved');
                const gap = (Math.min(...group.map(e=>e.getLeftPointX()))-right)*scale[mode];
                const factor = obstacleSpacingScale(score);
                assert(near(factor, score<=5?1:score>=25?.8:1-(score-5)*.01), 'ramp');
                // Classic templates may extend left of their sampled anchor.
                // Compare same template/seed, so its geometry offset cancels.
                if (score===0) rows.push({mode,type,baseGap:gap,measurements:[]});
                const row = rows[rows.length-1];
                const baseline = mode==='bad' ? .225*width : .375*width;
                const reduction = baseline*(1-factor);
                assert(Math.abs((row.baseGap-gap)-reduction)<2, 'unexpected gap reduction');
                assert(gap<=previousGap+1e-6, 'non-monotonic spacing');
                assert(gap>0, 'overlapping groups');
                row.measurements.push({score,factor,gap}); previousGap=gap;
                assert(group.every(e=>e.generationGroupId===1), 'group identity');
            }
        }
        scoreText.count[mode] = 10000;
        reStart(); cancelAnimationFrame(game);
        assert(scoreText.count[mode]===0 && obstacleSpacingScale(scoreText.count[mode])===1, 'restart reset');
        // Width rescale must affect future spacing once, not the score factor.
        scoreText.count[mode] = 15;
        const f = floors[1], old = {...f.elementsIntervalX};
        f.rescaleSpacing(1.5);
        assert(near(f.elementsIntervalX.min,old.min*1.5) && near(f.elementsIntervalX.max,old.max*1.5), 'resize interval');
        assert(near(obstacleSpacingScale(scoreText.count[mode]),.9), 'resize progression');
    }
    startGame('classic'); cancelAnimationFrame(game);
    assert(scoreText.count.classic===0 && obstacleSpacingScale(scoreText.count.classic)===1, 'mode reset');
    // Exercise the score-production path, including duplicate deletion scans.
    const f = floors[1];
    scoreText.count.classic = 5;
    const g = f.getGenerationGroup(0);
    screen.x = -g.rightPointX-1;
    f.deleteElements();
    assert(scoreText.count.classic===6 && near(obstacleSpacingScale(scoreText.count.classic),.99), 'cleared group progression');
    f.deleteElements();
    assert(scoreText.count.classic===6, 'group double scored');
    assert(obstacleSpacingScale(-1)===1 && obstacleSpacingScale(NaN)===1 && obstacleSpacingScale(Infinity)===1, 'invalid score');
    return {verdict:'PASS',rows};
}'''
