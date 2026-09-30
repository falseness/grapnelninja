"""Seeded equal-weight template selection through the real bad-mode Floor."""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test
from verification_scenarios import frames

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get('DISTRIBUTION_EVIDENCE_DIR', ROOT / 'artifacts' / 'TASK-065'))
SELECTIONS = 1000 * len(frames)
TOLERANCE = 0.15


class BadSelectionDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def test_equal_weight_distribution(self):
        page = self.browser.new_page(viewport={'width': 772, 'height': 630})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text)
                if message.type == 'error' else None)
        try:
            page.goto(self.url)
            result = page.evaluate(PROBE, SELECTIONS)
        finally:
            page.close()
        expected = SELECTIONS / len(frames)
        result.update(expectedPerTemplate=expected, tolerance=TOLERANCE,
                      templates=frames)
        (EVIDENCE / 'distribution.json').write_text(json.dumps(result, indent=2) + '\n')
        self.assertEqual(errors, [])
        self.assertEqual(result['weights'], [{'type': frame, 'chance': 1} for frame in frames])
        self.assertEqual(result['selections'], SELECTIONS)
        self.assertEqual(result['fallThrough'], 0)
        self.assertEqual(result['undefinedSelections'], 0)
        self.assertEqual(set(result['counts']), set(frames))
        self.assertEqual(sum(result['counts'].values()), SELECTIONS)
        for frame in frames:
            count = result['counts'][frame]
            self.assertLessEqual(abs(count - expected), TOLERANCE * expected, frame)
            print(f'PASS {frame}: {count} of {SELECTIONS} '
                  f'(expected {expected:.0f} +/- {TOLERANCE * expected:.0f})', flush=True)
        # Extreme Math.random() values: 1 - 2**-53 times 11 rounds up to 11.
        self.assertEqual(result['edges'], {'0': frames[0], 'max': frames[-1]})
        print(f'PASS {SELECTIONS} seeded selections; fall-through=0; undefined=0; '
              f'edges random()=0 -> {frames[0]}, random()=1-2^-53 -> {frames[-1]}', flush=True)
        classic = result['classic']
        self.assertEqual(classic['fallThrough'], 0)
        self.assertEqual(classic['counts'], classic['legacyCounts'])
        print('PASS classic selection identical to the legacy random() <= cumulative rule: '
              + json.dumps(classic['counts'], sort_keys=True), flush=True)


PROBE = r'''selections => {
    startGame('bad');
    cancelAnimationFrame(game);
    const f = floors[1];
    const weights = f.creations.map(c => ({type: c.type, chance: c.chance}));
    const log = console.log;
    let selected, fallThrough = 0;
    // Record the chosen template; an empty group keeps the probe to selection only.
    const stub = () => { elementsFactory.create = (x, y, type) => { selected = type; return []; }; };
    stub();
    console.log = message => { if (message === 'generation element on floor error') fallThrough++; };
    const random = Math.random;
    const pick = floor => { selected = undefined; floor.generateElements(0); return selected; };
    const counts = {};
    let undefinedSelections = 0;
    const edges = {};
    try {
        let seed = 65;
        Math.random = () => ((seed = (1664525*seed + 1013904223) >>> 0) / 4294967296);
        for (let i = 0; i < selections; ++i) {
            const type = pick(f);
            if (type === undefined) undefinedSelections++;
            else counts[type] = (counts[type] || 0) + 1;
        }
        Math.random = () => 0;
        edges['0'] = pick(f);
        Math.random = () => 1 - 2**-53;
        edges.max = pick(f);
        startGame('classic');
        cancelAnimationFrame(game);
        stub();
        const c = floors[1];
        const classic = {counts: {}, legacyCounts: {}, fallThrough: 0};
        const before = fallThrough;
        for (let ticket = 0; ticket < 100; ++ticket) {
            Math.random = () => (ticket + .5) / 100;
            const type = pick(c);
            classic.counts[type] = (classic.counts[type] || 0) + 1;
            let sum = 0;
            const legacy = c.creations.find(creation => ticket <= (sum += creation.chance));
            classic.legacyCounts[legacy.type] = (classic.legacyCounts[legacy.type] || 0) + 1;
        }
        classic.fallThrough = fallThrough - before;
        return {seed: 65, selections, weights, counts, fallThrough, undefinedSelections, edges, classic};
    } finally {
        Math.random = random;
        console.log = log;
    }
}'''

if __name__ == '__main__':
    unittest.main()
