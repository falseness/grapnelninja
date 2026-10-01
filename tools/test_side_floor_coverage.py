"""Ground and ceiling must cover every generated bad-mode obstacle, so cubes never fall out."""
import json
from pathlib import Path
import unittest

from browser_test_support import start_browser_test

ROOT = Path(__file__).resolve().parents[1]
VIEWPORTS = [(1120, 630), (2544, 1327)]


class SideFloorCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def run_probe(self, viewport, scrollWidthsPerTick):
        page = self.browser.new_page(viewport=dict(zip(('width', 'height'), viewport)))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(self.url)
            result = page.evaluate(PROBE, scrollWidthsPerTick)
        finally:
            page.close()
        self.assertEqual(errors, [])
        return result

    def test_cubes_stay_between_ceiling_and_ground(self):
        for viewport in VIEWPORTS:
            # Slow scroll lingers where obstacles outrun the side floors.
            for scrollWidthsPerTick in [0, 1 / 600, 1 / 150]:
                with self.subTest(viewport=viewport, scroll=scrollWidthsPerTick):
                    result = self.run_probe(viewport, scrollWidthsPerTick)
                    self.assertGreater(result['cubes'], 0)
                    self.assertEqual(result['uncovered'], [], json.dumps(result['uncovered'][:3]))
                    self.assertEqual(result['escaped'], [], json.dumps(result['escaped'][:3]))
                    print(f'PASS {viewport} scroll={scrollWidthsPerTick:.4f}: '
                          f'cubes={result["cubes"]}, groups={result["groups"]}', flush=True)


PROBE = r'''scrollWidthsPerTick => {
    let seed = 12345;
    Math.random = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    startGame('bad');
    cancelAnimationFrame(game);
    ninja.move = () => {};
    grapnel.move = () => {};
    const speed = scrollWidthsPerTick * width / cyclesPerTick;
    screen.shouldStartMove = function() { this.speedX = -speed; this.speedY = 0; return true; };

    const cover = floor => [
        Math.min(...floor.elements.map(e => e.getLeftPointX())),
        Math.max(...floor.elements.map(e => e.getRightPointX()))
    ];
    const uncovered = [], escaped = [], seen = new Set(), groups = new Set();
    for (let tick = 0; tick < 1500; ++tick) {
        physics();
        const ground = cover(floors[0]), ceiling = cover(floors[2]);
        const screenLeft = -screen.x;
        for (const e of floors[1].elements) {
            groups.add(e.generationGroupId);
            // Groups already behind the camera are about to be deleted.
            if (floors[1].getGenerationGroup(floors[1].elements.indexOf(e)).rightPointX < screenLeft)
                continue;
            const left = Math.max(e.getLeftPointX(), screenLeft), right = e.getRightPointX();
            if (left < ground[0] || right > ground[1] || left < ceiling[0] || right > ceiling[1])
                uncovered.push({tick, type: e.constructor.name, left, right, ground, ceiling});
            if (!(e instanceof JumpingCube))
                continue;
            seen.add(e);
            if (e.y < floors[1].top - 1 || e.y + e.height > floors[1].bottom + 1)
                escaped.push({tick, group: e.generationGroupId, x: e.x, y: e.y});
        }
        if (uncovered.length || escaped.length)
            break;
    }
    return {cubes: seen.size, groups: groups.size, uncovered, escaped};
}'''


if __name__ == '__main__':
    unittest.main()
