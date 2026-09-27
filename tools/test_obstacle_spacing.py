"""Assert real factory group spacing and preservation at three canvas sizes."""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('OBSTACLE_EVIDENCE_DIR', os.environ.get('TASK_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-046')))


class ObstacleSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def test_spacing_and_preservation(self):
        results = []
        for viewport in [(772, 630), (1280, 720), (1920, 1080)]:
            with self.subTest(viewport=viewport):
                page = self.browser.new_page(viewport=dict(zip(('width', 'height'), viewport)))
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                try:
                    page.goto(self.url)
                    result = page.evaluate(PROBE)
                    self.assertEqual(errors, [])
                    self.assertEqual((result['width'], result['height']), viewport)
                    self.assertEqual(len(result['measurements']), 30)
                    results.append(result)
                    print('\n'.join(result['assertions']), flush=True)
                    for row in result['measurements']:
                        print('PASS gap ' + json.dumps(row, sort_keys=True), flush=True)
                finally:
                    page.close()
        (EVIDENCE / 'spacing.json').write_text(json.dumps(results, indent=2) + '\n')
        self.assertEqual(len(results), 3)
        print('PASS all ten frame templates at three viewports; 90 measured gaps; browser errors=0', flush=True)


PROBE = r'''() => {
    startGame('bad');
    cancelAnimationFrame(game);
    Math.random = () => .25;
    trackEnabled = true;
    firstCycleInThisTick = false;
    QUALITY.playerTrail = false;
    const assert = (ok, message) => { if (!ok) throw Error(message); };
    const near = (a,b) => Math.abs(a-b) <= 1e-6;
    const snapshot = e => ({x:e.x, points:e.getPoints(), y:e.y,
        type:e.constructor.name, fill:e.fill, stroke:e.stroke,
        speedX:e.speedX, speedY:e.speedY, restrictionY:e.restrictionY,
        mass:e.mass, circle:e.circle, width:e.width, height:e.height});
    const types = floors[1].creations.map(c => c.type);
    assert(types.length === 10 && new Set(types).size === 10, 'ten templates required');
    const assertions = [], measurements = [];
    let cubes = 0, triangles = 0, first = 0, translated = 0;
    const makeFloor = type => new Floor(.2*height, 2*height, {min:0,max:0},
        [{type,chance:100}], 1);
    const generate = (f, type, anchor, initial=false) => {
        f.creations = [{type,chance:100}];
        const factory = elementsFactory.create;
        let raw;
        elementsFactory.create = function(...args) {
            const elements = factory.apply(this, args);
            raw = elements.map(snapshot);
            return elements;
        };
        const begin = f.elements.length;
        try {
            // Probe one group; startup now prefills multiple groups.
            if (initial) f.generateElements(.2*width);
            else f.generateElements(anchor);
        } finally { elementsFactory.create = factory; }
        const group = f.elements.slice(begin);
        assert(group.length === raw.length && group.length > 0, 'group size');
        assert(group.every(e => e.generationGroupId === f.nextGenerationGroupId-1 && !e.scored), 'group state');
        const dx = group[0].x - raw[0].x;
        group.forEach((e,i) => {
            const actual = snapshot(e), expected = raw[i];
            assert(near(actual.x, expected.x+dx), 'nonuniform member translation');
            assert(actual.points.length === expected.points.length &&
                actual.points.every((p,j) => near(p.x, expected.points[j].x+dx) &&
                    near(p.y, expected.points[j].y)), 'relative polygon geometry');
            for (const key of Object.keys(expected).filter(k => !['x','points'].includes(k)))
                assert(JSON.stringify(actual[key]) === JSON.stringify(expected[key]), 'motion/geometry changed: '+key);
            if (!initial && version === 'bad') {
                if (e instanceof JumpingCube) {
                    assert(e.track.pos.length === 1, 'cube forced seed');
                    const seed = e.track.pos[0];
                    assert(Number.isFinite(seed.x) && Number.isFinite(seed.y), 'finite scalar cube coordinates');
                    assert(near(seed.x,e.x+e.circle.x) &&
                        near(seed.y,e.speedY>0 ? e.y : e.getBottomPointY()), 'cube translated seed');
                    cubes++;
                } else if (e instanceof Triangle) {
                    assert(e.track.pos.length === 1 && Array.isArray(e.track.pos[0]) &&
                        e.track.pos[0].length === 3 &&
                        JSON.stringify(e.track.pos[0]) === JSON.stringify(e.getPoints()), 'triangle polygon trail');
                    triangles++;
                }
            }
        });
        if (initial || version === 'classic') {
            assert(dx === 0 && JSON.stringify(group.map(snapshot)) === JSON.stringify(raw), 'original placement changed');
            first++;
        } else translated++;
        return group;
    };
    const run = (sequence, label) => {
        const f = makeFloor(sequence[0]);
        let preceding = generate(f, sequence[0], .2*width, true);
        assertions.push(`PASS ${width}x${height} ${label}: first-group placement unchanged`);
        for (const type of sequence.slice(1)) {
            // Move and reorder the predecessor: its last member is deliberately
            // leftmost, so neither template bounds nor the last member suffice.
            preceding.forEach(e => e.x += 13);
            const right = Math.max(...preceding.map(e => e.getRightPointX()));
            const id = preceding[0].generationGroupId;
            f.elements = f.elements.filter(e => e.generationGroupId !== id).concat(
                [...preceding].sort((a,b) => b.getRightPointX()-a.getRightPointX()));
            const group = generate(f, type, f.elements[f.elements.length-1].getRightPointX());
            const left = Math.min(...group.map(e => e.getLeftPointX()));
            const gap = (left-right)*scale.bad;
            assert(near(gap,.10*width), `${type} gap ${gap} expected ${.10*width}`);
            measurements.push({sequence:label, template:type, predecessorRight:right,
                newGroupLeft:left, scale:scale.bad, measuredPixelGap:gap,
                expectedPixelGap:.10*width, tolerancePixels:1e-6, passed:true});
            preceding = group;
        }
    };
    for (const type of types) run([type,type,type], type);
    run([types[9],...types], 'mixed-template');
    assert(translated === 30 && cubes > 0 && triangles > 0, 'coverage incomplete');
    assertions.push(`PASS ${width}x${height}: uniform translation of every group member; unchanged relative polygon geometry and motion settings; grouping preserved`);
    assertions.push(`PASS ${width}x${height}: cube trails finite scalar coordinates (${cubes}); triangle trails retain polygon points (${triangles}); forced seeds with tick/quality disabled`);
    startGame('classic');
    cancelAnimationFrame(game);
    for (const creation of floors[1].creations) {
        const f = makeFloor(creation.type);
        generate(f, creation.type, .2*width, true);
        generate(f, creation.type, 2*width);
    }
    assertions.push(`PASS ${width}x${height}: unchanged classic placement using actual factories`);
    return {width,height,measurements,assertions};
}'''

if __name__ == '__main__':
    unittest.main()
