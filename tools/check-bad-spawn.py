"""Check actual browser factories, spawn placement, grouped scoring and deletion.

Serve the repository on port 8018, then run with Python Playwright installed.
This deterministic probe is separate from the real-input gameplay capture.
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 772, 'height': 630})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    page.goto('http://127.0.0.1:8018/')
    lines = page.evaluate('''() => {
        startGame('bad');
        cancelAnimationFrame(game);
        const lines = [];
        const assert = (ok, message) => { if (!ok) throw Error(message); };
        const near = (a, b) => Math.abs(a - b) < 1e-6;
        const originalRandom = Math.random;
        const originalScore = changeScoreText;
        let scores = 0;
        Math.random = () => 0.25;
        changeScoreText = () => scores++;
        try {
            for (const creation of floors[1].creations) {
                const f = new Floor(.2*height, 2*height, {min:0,max:0},
                    [{type:creation.type,chance:100}], 1);
                const raw = elementsFactory.create({min:.2*width,max:.2*width},
                    {min:f.top,max:f.bottom}, creation.type);
                const snapshot = e => ({x:e.x, y:e.y, type:e.constructor.name,
                    points:e.getPoints(), fill:e.fill, stroke:e.stroke,
                    speedX:e.speedX, speedY:e.speedY, restrictionY:e.restrictionY});
                screen.x = 0;
                f.generatePrimaryElements();
                const first = f.elements.filter(e => e.generationGroupId === 0);
                assert(JSON.stringify(first.map(snapshot)) === JSON.stringify(raw.map(snapshot)),
                    creation.type + ': startup geometry changed');
                const baseline = first.map(snapshot);
                const old = [...first];
                const right = Math.max(...old.map(e => e.getRightPointX()));
                // A partially visible multi-object group must neither score nor delete.
                screen.x = -right + 1;
                f.deleteElements();
                assert(old.every((e,i) => f.elements[i] === e && !e.scored), 'partial group changed');
                const before = scores;
                screen.x = -right - 1;
                f.deleteElements();
                assert(scores === before + 1 && old.every(e => e.scored), 'group score missing');
                f.deleteElements();
                assert(scores === before + 1 && old.every(e => f.elements.includes(e)), 'duplicate score/early deletion');
                const replacement = f.elements.filter(e => e.generationGroupId === 1);
                assert(replacement.length === old.length, 'prefill missing second group');
                const left = Math.min(...replacement.map(e => e.getLeftPointX()));
                assert(near((left - right) * scale.bad, .10*width), 'advance gap');
                const generationCount = f.nextGenerationGroupId;
                screen.x = screen.getDeletionBorder() - right - 1;
                f.deleteElements();
                assert(old.every(e => !f.elements.includes(e)), 'partial deletion');
                assert(f.nextGenerationGroupId === generationCount, 'deletion generated duplicates');
                const dx = replacement[0].x - baseline[0].x;
                replacement.forEach((e,i) => {
                    const actual = snapshot(e), expected = baseline[i];
                    assert(near(actual.x, expected.x + dx), 'nonuniform translation');
                    assert(actual.points.every((point,j) => near(point.x, expected.points[j].x + dx)
                        && near(point.y, expected.points[j].y)), 'polygon distorted');
                    for (const key of ['y','type','fill','stroke','speedX','speedY','restrictionY'])
                        assert(JSON.stringify(actual[key]) === JSON.stringify(expected[key]), 'changed ' + key);
                });
                lines.push('PASS ' + creation.type + ': startup geometry; exact 10% spacing; single translation; types/physics/colors/polygons preserved; grouped score exactly once; whole-group deletion; advance prefill; no deletion-triggered generation');
            }
            version = 'classic';
            const f = new Floor(0,height,{min:0,max:0},[],1);
            const element = {x:123};
            f.alignBadVersionGeneratedElements([element], 1000, 2000);
            assert(element.x === 123, 'classic alignment changed');
            lines.push('PASS classic: bad-mode alignment does not affect classic placement');
        } finally {
            Math.random = originalRandom;
            changeScoreText = originalScore;
        }
        return lines;
    }''')
    evidence = Path(os.environ.get('TASK_EVIDENCE_DIR', 'artifacts/TASK-046'))
    evidence.mkdir(parents=True, exist_ok=True)
    with (evidence / 'browser-errors.log').open('a') as log:
        log.write(''.join(error + '\n' for error in errors))
    assert not errors, errors
    print('\n'.join(lines))
    print('PASS browser page errors=0')
    browser.close()
