"""Browser regression for trail seeds after real generation-group replacement."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'artifacts' / 'TASK-043'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class GroupTrailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.errors = []
        cls.addClassCleanup(lambda: (EVIDENCE / 'browser-errors.log').write_text(
            ''.join(error + '\n' for error in cls.errors)))
        server = ThreadingHTTPServer(('127.0.0.1', 0),
                                     partial(QuietHandler, directory=str(ROOT)))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.url = f'http://127.0.0.1:{server.server_port}/'
        playwright = sync_playwright().start()
        cls.addClassCleanup(playwright.stop)
        cls.browser = playwright.chromium.launch(args=['--no-sandbox'])
        cls.addClassCleanup(cls.browser.close)

    def test_replacement_trails(self):
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
                                f.generatePrimaryElements();
                                const old = [...f.elements];
                                const baseline = old.map(e => ({x:e.x, points:e.getPoints()}));
                                const right = Math.max(...old.map(e => e.getRightPointX()));
                                ninja.x = right + 5*width;
                                screen.x = -ninja.x + .35*width;
                                f.deleteElements(); // Score the entire old group.
                                assert(old.every(e => e.scored), 'old group not scored');
                                f.deleteElements(); // Replace the scored group.
                                assert(f.nextGenerationGroupId === 2 &&
                                    f.elements.length === old.length &&
                                    old.every(e => !f.elements.includes(e)) &&
                                    f.elements.every(e => e.generationGroupId === 1 && !e.scored),
                                    'whole-group advancement failed');
                                assert(near(Math.min(...f.elements.map(e => e.getLeftPointX())),
                                    ninja.x + .2*width), 'replacement not ahead of player');
                                const dx = f.elements[0].x - baseline[0].x;
                                assert(dx > 0, 'no translation');
                                const targets = f.elements.filter(e =>
                                    e instanceof JumpingCube || e instanceof Triangle);
                                assert(targets.length > 0, 'missing trail target');
                                for (const e of targets) {
                                    const original = baseline[f.elements.indexOf(e)];
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
