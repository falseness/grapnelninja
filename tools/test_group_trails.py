"""Browser regression for trail seeds after real advance generation."""
from pathlib import Path
import unittest
import os

from browser_test_support import start_browser_test


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('OBSTACLE_EVIDENCE_DIR', os.environ.get('TASK_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-046')))


class GroupTrailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.errors = []
        cls.addClassCleanup(lambda: (EVIDENCE / 'browser-errors.log').write_text(
            (EVIDENCE / 'browser-errors.log').read_text() + ''.join(error + '\n' for error in cls.errors)
            if (EVIDENCE / 'browser-errors.log').exists() else ''.join(error + '\n' for error in cls.errors)))
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def test_advance_trails(self):
        page = self.browser.new_page(viewport={'width': 772, 'height': 630})
        self.addCleanup(page.close)
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.on('console', lambda message: self.errors.append(message.text)
                if message.type == 'error' else None)
        page.goto(self.url)
        lines = page.evaluate('''() => {
            startGame('bad');
            cancelAnimationFrame(game);
            trackEnabled = true;
            Math.random = () => 0.25;
            const assert = (ok, message) => { if (!ok) throw Error(message); };
            const near = (a, b) => Math.abs(a - b) < 1e-6;
            const lines = [];
            let cases = 0, triangles = 0;
            for (const frame of ['frame7Elements', 'frame9Elements', 'frame3Triangle']) {
                // Include zero velocity to lock down JumpingCube's <= 0 edge.
                for (const velocity of frame === 'frame3Triangle' ? [null] : [-1, 0, 1]) {
                    for (const tick of [true, false]) {
                        for (const quality of [true, false]) {
                            firstCycleInThisTick = tick;
                            QUALITY.playerTrail = quality;
                            const f = new Floor(.2*height, 2*height, {min:0,max:0},
                                [{type:frame,chance:100}], 1);
                            // Use the real factory and deletion flow. Control only cube
                            // velocity before alignment, to exercise both edge choices.
                            const create = elementsFactory.create;
                            elementsFactory.create = function(...args) {
                                const elements = create.apply(this, args);
                                for (const e of elements)
                                    if (e instanceof JumpingCube) e.speedY = velocity;
                                return elements;
                            };
                            try {
                                screen.x = 0;
                                f.generatePrimaryElements();
                                const initialId = f.nextGenerationGroupId - 1;
                                const old = f.elements.filter(e => e.generationGroupId === initialId);
                                const baseline = old.map(e => ({x:e.x, points:e.getPoints()}));
                                const right = Math.max(...old.map(e => e.getRightPointX()));
                                const before = f.nextGenerationGroupId;
                                // Advance the camera by a normal small step until prefill runs low.
                                while (f.nextGenerationGroupId === before) {
                                    screen.x -= 1;
                                    f.replenishElements();
                                }
                                const generated = f.elements.filter(e => e.generationGroupId === before);
                                assert(generated.length === old.length, 'advance group size');
                                assert(old.every(e => f.elements.includes(e)), 'generation depended on deletion');
                                const gap = (Math.min(...generated.map(e => e.getLeftPointX())) - right)*scale.bad;
                                assert(gap >= .20*width - 1e-6 && gap <= .30*width + 1e-6, 'advance gap changed');
                                const dx = generated[0].x - baseline[0].x;
                                assert(dx > 0, 'no translation');
                                const targets = generated.filter(e =>
                                    e instanceof JumpingCube || e instanceof Triangle);
                                assert(targets.length > 0, 'missing trail target');
                                for (const e of targets) {
                                    const original = baseline[generated.indexOf(e)];
                                    assert(near(e.x, original.x + dx), 'translated X mismatch');
                                    assert(e.track.pos.length === 1, 'forced single seed missing');
                                    const seed = e.track.pos[0];
                                    if (e instanceof JumpingCube) {
                                        assert(Number.isFinite(seed.x) && Number.isFinite(seed.y),
                                            'cube seed is not finite scalar coordinates');
                                        assert(near(seed.x, e.x + e.circle.x), 'cube center X');
                                        assert(near(seed.y, velocity > 0 ? e.y : e.getBottomPointY()),
                                            'cube velocity-selected Y edge');
                                    } else {
                                        assert(Array.isArray(seed) && seed.length === 3,
                                            'triangle seed lost polygon shape');
                                        assert(JSON.stringify(seed) === JSON.stringify(e.getPoints()),
                                            'triangle seed differs from current polygon');
                                        assert(seed.every((p,i) => Number.isFinite(p.x) &&
                                            Number.isFinite(p.y) && near(p.x, original.points[i].x + dx) &&
                                            near(p.y, original.points[i].y)), 'triangle translation distorted');
                                        triangles++;
                                    }
                                    QUALITY.playerTrail = true;
                                    // Draw immediately after restoring quality, then exercise lineTo
                                    // with another genuine trail sample (triangles need two polygons).
                                    const real = ctx;
                                    const calls = [];
                                    ctx = new Proxy(real, {
                                        get(target, key) {
                                            const value = target[key];
                                            return typeof value === 'function' ? (...args) => {
                                                if (key === 'moveTo' || key === 'lineTo') {
                                                    assert(args.length === 2 && args.every(Number.isFinite),
                                                        'nonfinite canvas ' + key);
                                                    calls.push(key);
                                                }
                                                return value.apply(target, args);
                                            } : value;
                                        },
                                        set(target, key, value) { target[key] = value; return true; }
                                    });
                                    try {
                                        e.track.draw();
                                        if (e instanceof JumpingCube)
                                            e.track.addPos(seed.x + 1, seed.y + 1, true);
                                        else
                                            e.track.addPos(e.getPoints(), true);
                                        e.track.draw();
                                        assert(calls.includes('moveTo') && calls.includes('lineTo'),
                                            'canvas path not exercised');
                                    } finally { ctx = real; }
                                }
                                cases++;
                                lines.push(`PASS scenario ${frame} velocity=${velocity} tick=${tick} quality=${quality}`);
                            } finally { elementsFactory.create = create; }
                        }
                    }
                }
                lines.push(frame === 'frame3Triangle' ? 'PASS triangle polygon trail preserved'
                    : `PASS ${frame} translated cube trail finite`);
            }
            assert(cases === 28 && triangles >= 4, 'state matrix incomplete');
            lines.push('PASS forced trail seed across tick and quality states');
            return lines;
        }''')
        self.assertEqual(self.errors, [])
        print('\n'.join(lines), flush=True)


if __name__ == '__main__':
    unittest.main()
