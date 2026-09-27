"""Check actual browser factories, spawn placement, grouped scoring and deletion.

Serve the repository on port 8018, then run with Python Playwright installed.
This deterministic probe is separate from the real-input gameplay capture.
"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 772, 'height': 630})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8018/')
    lines = page.evaluate('''() => {
        startGame('bad');
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
                f.generatePrimaryElements();
                assert(JSON.stringify(f.elements.map(snapshot)) === JSON.stringify(raw.map(snapshot)),
                    creation.type + ': startup geometry changed');
                const baseline = f.elements.map(snapshot);
                const old = [...f.elements];
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
                // Reproduce deletion far behind the player with an otherwise empty queue.
                ninja.x = right + 5*width;
                screen.x = -ninja.x + .35*width;
                f.deleteElements();
                const left = Math.min(...f.elements.map(e => e.getLeftPointX()));
                assert(near(left, ninja.x + .2*width), 'stale anchor or double offset');
                assert(f.elements.length === old.length && old.every(e => !f.elements.includes(e)), 'partial deletion');
                assert(f.elements.every(e => e.generationGroupId === 1 && !e.scored), 'replacement group state');
                const dx = f.elements[0].x - baseline[0].x;
                f.elements.forEach((e,i) => {
                    const actual = snapshot(e), expected = baseline[i];
                    assert(near(actual.x, expected.x + dx), 'nonuniform translation');
                    assert(actual.points.every((point,j) => near(point.x, expected.points[j].x + dx)
                        && near(point.y, expected.points[j].y)), 'polygon distorted');
                    for (const key of ['y','type','fill','stroke','speedX','speedY','restrictionY'])
                        assert(JSON.stringify(actual[key]) === JSON.stringify(expected[key]), 'changed ' + key);
                });
                f.deleteElements();
                assert(scores === before + 1 && f.elements.every(e => e.generationGroupId === 1), 'replacement processed twice');
                // A retained group farther ahead remains the spacing anchor.
                const retainedRight = Math.max(...f.elements.map(e => e.getRightPointX()));
                f.generateElements(retainedRight, ninja.x + .2*width);
                const added = f.elements.filter(e => e.generationGroupId === 2);
                assert(Math.min(...added.map(e => e.getLeftPointX())) > retainedRight, 'retained group overlap');
                lines.push('PASS ' + creation.type + ': startup geometry; forward placement; single translation; types/physics/colors/polygons preserved; grouped score exactly once; whole-group deletion; retained anchor');
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
    assert not errors, errors
    print('\n'.join(lines))
    print('PASS browser page errors=0')
    browser.close()
