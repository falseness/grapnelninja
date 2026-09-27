"""Deterministic browser proof of advance coverage through real physics updates."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'artifacts' / 'TASK-046'


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ObstacleAdvanceTests(unittest.TestCase):
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

    def test_advance(self):
        results = []
        for width, height in [(772, 630), (1280, 720), (1920, 1080)]:
            page = self.browser.new_page(viewport={'width': width, 'height': height})
            page.on('pageerror', lambda error: self.errors.append(str(error)))
            page.on('console', lambda message: self.errors.append(message.text)
                    if message.type == 'error' else None)
            try:
                page.goto(self.url)
                result = page.evaluate(PROBE)
                results.append(result)
                print('\n'.join(result['assertions']), flush=True)
                for row in result['creations']:
                    print('PASS creation ' + json.dumps(row, sort_keys=True), flush=True)
                for row in result['coverage']:
                    print('PASS coverage ' + json.dumps(row, sort_keys=True), flush=True)
            finally:
                page.close()
        (EVIDENCE / 'advance.json').write_text(json.dumps(results, indent=2) + '\n')
        self.assertEqual(self.errors, [])
        print('PASS browser errors=0', flush=True)


PROBE = r'''() => {
    const assert = (ok, message) => { if (!ok) throw Error(message); };
    const near = (a,b) => Math.abs(a-b) < 1e-6;
    let seed = 46;
    Math.random = () => ((seed = (1664525*seed + 1013904223) >>> 0) / 4294967296);
    const creations = [], coverage = [], assertions = [];
    let initializing = true, frame = 0;
    const generate = Floor.prototype.generateElements;
    Floor.prototype.generateElements = function(x) {
        const relevant = version === 'bad' && this.primaryElementsQuantity === 1;
        const predecessor = relevant && this.elements.length
            ? this.getGenerationGroup(this.elements.length-1).rightPointX : null;
        const precedingId = relevant && this.elements.length
            ? this.elements[this.elements.length-1].generationGroupId : null;
        const predecessorLeft = precedingId === null ? null : Math.min(...this.elements
            .filter(e => e.generationGroupId === precedingId).map(e => e.getLeftPointX()));
        const id = this.nextGenerationGroupId;
        const count = generate.call(this, x);
        if (relevant) {
            const group = this.elements.filter(e => e.generationGroupId === id);
            const left = Math.min(...group.map(e => e.getLeftPointX()));
            const right = Math.max(...group.map(e => e.getRightPointX()));
            const V = width/scale.bad, R = -screen.x+V;
            if (id > 0) assert(near(left-predecessor, .1*V), '10% creation gap');
            if (!initializing) assert(left > R, 'visible post-initialization spawn');
            creations.push({frame, id, initializing, left, right, predecessorId:precedingId, predecessorLeft, predecessorRight:predecessor,
                cameraX:screen.x, scale:scale.bad, visibleRight:R, viewportWidth:V,
                gap:predecessor === null ? null : left-predecessor, passed:true});
        }
        return count;
    };
    const checkCoverage = (f, phase) => {
        const right = Math.max(...f.elements.map(e => e.getRightPointX()));
        const V = width/scale.bad, R = -screen.x+V;
        assert(right >= R+V, 'coverage shortfall');
        coverage.push({frame, phase, cameraX:screen.x, scale:scale.bad,
            visibleRight:R, viewportWidth:V, generatedRight:right, requiredRight:R+V, passed:true});
    };
    startGame('bad'); cancelAnimationFrame(game);
    let f = floors[1];
    checkCoverage(f, 'startup-before-first-render');
    assert(f.nextGenerationGroupId > 1, 'startup not prefilled');
    assertions.push('PASS startup prefill before rendering; first-group placement checked by spawn regression');
    initializing = false;
    // Keep physics, camera, obstacle movement and generation real. Suppress deaths
    // so a deterministic long traversal can cross every obstacle template.
    ninja.collision = () => {};
    ninja.x = screen.borderX + 1;
    const nominalMax = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent);
    ninja.speedX = nominalMax;
    const initialGroupCount = f.nextGenerationGroupId;
    const originalDelete = f.deleteElements;
    f.deleteElements = () => {};
    for (; f.nextGenerationGroupId === initialGroupCount && frame < 1000; frame++) physics();
    assert(f.nextGenerationGroupId > initialGroupCount, 'replenishment requires deletion');
    assert(f.elements.some(e => e.generationGroupId === 0), 'disabled deletion removed group');
    checkCoverage(f, 'deletion-disabled');
    assertions.push('PASS repeated replenishment independent of deletion through actual physics()');
    f.deleteElements = originalDelete;
    let scoreCalls = 0, scored = new Set(), removed = new Set(), queueSamples = [];
    const score = changeScoreText;
    changeScoreText = () => { scoreCalls++; };
    f.deleteElements = function() {
        const beforeId = this.nextGenerationGroupId;
        const groups = new Map();
        for (const e of this.elements) {
            if (!groups.has(e.generationGroupId)) groups.set(e.generationGroupId, []);
            groups.get(e.generationGroupId).push(e);
        }
        const beforeScore = scoreCalls;
        let expectedScores = 0;
        for (const [id, members] of groups) {
            const right = Math.max(...members.map(e => e.getRightPointX()));
            if (!members[0].scored && right+screen.x < 0) {
                assert(!scored.has(id), 'duplicate score'); scored.add(id); expectedScores++;
            }
        }
        originalDelete.call(this);
        assert(this.nextGenerationGroupId === beforeId, 'deletion-triggered generation');
        assert(scoreCalls-beforeScore === expectedScores, 'exactly-once score count');
        for (const [id, members] of groups) {
            const kept = members.filter(e => this.elements.includes(e)).length;
            assert(kept === 0 || kept === members.length, 'partial-group deletion');
            if (!kept) {
                assert(Math.max(...members.map(e => e.getRightPointX()))+screen.x < screen.getDeletionBorder(),
                    'deleted visible group'); removed.add(id);
            }
        }
    };
    for (let step = 0; step < 2400; step++, frame++) {
        // Horizontal velocity is uncapped in the game. Also stress 4x the
        // configured maximum speed; do not claim a nonexistent horizontal cap.
        ninja.speedX = step < 1200 ? nominalMax : 4*nominalMax;
        ninja.speedY = nominalMax;
        const beforeX = ninja.x, beforeCamera = screen.x, beforeId = f.nextGenerationGroupId;
        physics();
        assert(ninja.x > beforeX && screen.x < beforeCamera, 'physics movement not exercised');
        assert(Math.abs(ninja.speedY) <= nominalMax, 'maximum normal speed clamp not exercised');
        const V = width/scale.bad;
        assert(Math.max(...f.elements.map(e => e.getRightPointX())) >= -screen.x+2*V, 'per-tick coverage');
        if (f.nextGenerationGroupId !== beforeId) checkCoverage(f, 'physics-replenishment');
        if (step % 100 === 0) queueSamples.push({step, cameraX:screen.x,
            retainedGroups:new Set(f.elements.map(e => e.generationGroupId)).size});
    }
    assert(removed.size > 50 && f.nextGenerationGroupId > 50, 'long traversal too short');
    assert(queueSamples.every(s => s.retainedGroups <= 12), 'queue grows with distance');
    assert(!f.elements.some(e => e.generationGroupId === 0), 'old group retained');
    assertions.push(`PASS maximum normal speed via physics(); 4x horizontal stress; repeated replenishment=${coverage.length-2}`);
    assertions.push(`PASS exactly-once scoring=${scoreCalls}; whole-group deletion=${removed.size}; no deletion-triggered duplicate generation`);
    assertions.push(`PASS bounded queue over long deterministic traversal: max retained=${Math.max(...queueSamples.map(s => s.retainedGroups))}; distance=${-screen.x}`);
    changeScoreText = score;
    initializing = true;
    const oldFloor = f;
    reStart(); cancelAnimationFrame(game);
    f = floors[1];
    assert(f !== oldFloor && screen.x === 0 && f.elements[0].generationGroupId === 0 &&
        f.elements.every(e => !e.scored), 'restart did not reset queue');
    checkCoverage(f, 'restart');
    assertions.push('PASS restart resets queue IDs, score flags and camera; startup coverage restored');
    const first = f.elements.filter(e => e.generationGroupId === 0);
    const right = Math.max(...first.map(e => e.getRightPointX()));
    screen.x = -right+1;
    f.deleteElements();
    assert(first.every(e => f.elements.includes(e) && !e.scored), 'partial visible group scored/deleted');
    assertions.push('PASS partial-group visibility retains every member without scoring');
    startGame('classic'); cancelAnimationFrame(game);
    const classic = floors[1], initialId = classic.nextGenerationGroupId;
    assert(initialId === classic.primaryElementsQuantity, 'classic startup changed');
    const originalElements = [...classic.elements];
    screen.x = -100*width;
    classic.replenishElements();
    assert(classic.nextGenerationGroupId === initialId && classic.elements.length === originalElements.length,
        'classic advance generation enabled');
    classic.deleteElements(); classic.deleteElements();
    assert(classic.nextGenerationGroupId > initialId, 'classic replacement stopped');
    assertions.push('PASS classic isolation: original primary count and deletion replacement; no advance generation');
    Floor.prototype.generateElements = generate;
    return {width,height, nominalMax, physicsSteps:frame, creations,coverage,queueSamples,assertions};
}'''

if __name__ == '__main__':
    unittest.main()
