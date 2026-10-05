"""Tests for the allocation-free paths in render/effects.js.

Both the base rev's render/effects.js (splice, .map and per-point objects) and
the worktree's (pooled arrays, in-place compaction) are loaded into separate
node vm contexts with the same stub globals, then fed the same fixed inputs:
particle compaction and the cap must keep order and drop exactly the expired
or oldest particles, and the ribbon points/outline, flash segments and
triangle palette colors must equal the old algorithm's output value for value,
including when the pooled arrays are reused with fewer points.
EFFECTS_BASE defaults to the parent of the commit that added this test, or
HEAD while it is not committed yet.
"""
import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_PATH = 'tools/test_effects_allocations.py'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def base_rev():
    if os.environ.get('EFFECTS_BASE'):
        return os.environ['EFFECTS_BASE']
    added = git('log', '-1', '--format=%H', '--diff-filter=A', '--', TEST_PATH)
    return git('rev-parse', f'{added}~1' if added else 'HEAD')


NODE_SCRIPT = r'''
const vm = require('vm')
const fs = require('fs')
const [oldPath, newPath] = process.argv.slice(-2)

function load(path) {
    const context = {
        Math, Object, Array, JSON, WeakMap, Map, performance: {now: () => 0},
        screen: {x: 12.5, y: -7.25},
        trackEnabled: true, version: 'bad', scale: {bad: 1, classic: 1},
        QUALITY: {particles: true, playerTrail: true, backgroundMotion: true},
        STYLE: {
            features: {particles: true, playerTrail: true, background: true},
            particles: {maxCount: 5},
            trails: {player: {tailWidthRatio: 0.2, headWidthRatio: 1, minPointDistanceRatio: 0.5,
                              widthRatio: 1, glowWidthRatio: 1, minSegmentRatio: 0, maxAlpha: 1, edgeAlpha: 1}},
            colors: {background: {triangleSilhouetteFill: 'f', triangleSilhouetteStroke: 's',
                                   triangleSilhouetteMagentaFill: 'mf', triangleSilhouetteBlueStroke: 'bs'}}
        }
    }
    vm.createContext(context)
    vm.runInContext(fs.readFileSync(path, 'utf8') +
        '\n;this.__e = {ParticleSystem, PlayerTrailRenderer, BackgroundRenderer}', context)
    return context.__e
}

const copy = value => JSON.parse(JSON.stringify(value))

function particles() {
    const lives = [5, 16, 40, 0.5, 17, 100, 16.0001, -1, 30, 2]
    return lives.map((life, i) => ({id: i, x: i, y: -i, vx: 0.1 * i, vy: -0.05 * i, life, maxLife: 100}))
}

function run(e) {
    const out = {}
    const system = new e.ParticleSystem(null, null)
    system.particles = particles()
    const before = system.particles.slice()
    system.updateParticles(16)
    out.update = copy(system.particles)
    out.update_same_objects = system.particles.every(p => before.includes(p))
    system.updateParticles(16)
    out.update2 = copy(system.particles)
    system.updateParticles(1000)
    out.update_all_expired = copy(system.particles)

    system.particles = particles()
    system.enforceCap()
    out.cap = copy(system.particles)
    system.particles = particles().slice(0, 3)
    system.enforceCap()
    out.cap_under = copy(system.particles)

    const trail = new e.PlayerTrailRenderer()
    const tracks = [
        Array.from({length: 40}, (_, i) => ({x: i * 3 + Math.sin(i) * 2, y: Math.cos(i * 0.7) * 9})),
        [{x: 0, y: 0}, {x: 0, y: 0}, {x: 4, y: 1}, {x: 4, y: 1}, {x: 9, y: 5}, {x: 9, y: 5}],
        [{x: 1, y: 1}, {x: 2, y: 3}],
        Array.from({length: 7}, (_, i) => ({x: i * 0.3, y: i * i * 0.2})),
        [{x: 3, y: 3}, {x: 3, y: 3}, {x: 3, y: 3}]
    ]
    out.ribbon = []
    for (const positions of tracks)
        for (const minDistance of [0, 0.5, 2.5])
            for (const visibleStart of [1, 2, 5])
                for (const width of [6, 13.5]) {
                    const points = trail.getRibbonPoints(positions, minDistance)
                    const pointsCopy = copy(points)
                    const outline = positions.length - visibleStart < 2
                        ? null : copy(trail.getRibbonOutline(points, visibleStart, width))
                    out.ribbon.push({points: pointsCopy, outline})
                }

    const background = new e.BackgroundRenderer(null, null)
    const flashes = [
        {form: 'broken'}, {form: 'fragments'}, {},
        {form: 'broken', segments: [{start: 0.1, end: 0.2}, {start: 0.3, end: 0.9}]},
        {form: 'fragments', fragments: [{x: 0.1, y: -0.2, length: 0.5}]},
        {form: 'broken'}
    ]
    out.flash = flashes.map((flash, i) => copy(background.getFlashSegments(flash, 10 + i, 20 - i, -0.7 + i * 0.3, 300 + i * 17)))
    out.palette = ['magenta', 'blue', 'other', 'magenta'].map(p => copy(background.getTrianglePaletteColors(p)))
    return out
}

console.log(JSON.stringify({old: run(load(oldPath)), new: run(load(newPath))}))
'''


class EffectsAllocationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = base_rev()
        old_path = Path('/tmp/test_effects_allocations_base.js')
        old_path.write_text(git('show', f'{cls.base}:render/effects.js') + '\n')
        result = subprocess.run(
            ['node', '-e', NODE_SCRIPT, str(old_path), str(ROOT / 'render/effects.js')],
            capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        data = json.loads(result.stdout)
        cls.old, cls.new = data['old'], data['new']
        print(f'\nbase={cls.base} worktree={git("rev-parse", "HEAD")}+worktree')

    def test_particle_compaction_keeps_order_and_drops_expired(self):
        lives = [5, 16, 40, 0.5, 17, 100, 16.0001, -1, 30, 2]
        expected_ids = [i for i, life in enumerate(lives) if life - 16 > 0]
        self.assertEqual([p['id'] for p in self.new['update']], expected_ids)
        self.assertTrue(self.new['update_same_objects'])
        self.assertEqual(self.new['update'], self.old['update'])
        self.assertEqual(self.new['update2'], self.old['update2'])
        self.assertEqual(self.new['update_all_expired'], [])
        print('kept ids', expected_ids)

    def test_enforce_cap_drops_oldest_in_order(self):
        self.assertEqual([p['id'] for p in self.new['cap']], [5, 6, 7, 8, 9])
        self.assertEqual(self.new['cap'], self.old['cap'])
        self.assertEqual(self.new['cap_under'], self.old['cap_under'])

    def test_ribbon_points_and_outline_equal_old_algorithm(self):
        self.assertEqual(len(self.new['ribbon']), len(self.old['ribbon']))
        compared = 0
        for i, (new, old) in enumerate(zip(self.new['ribbon'], self.old['ribbon'])):
            self.assertEqual(new['points'], old['points'], i)
            self.assertEqual(new['outline'], old['outline'], i)
            compared += old['outline'] is not None
        self.assertGreater(compared, 50)
        print('ribbon cases', len(self.old['ribbon']), 'outlines compared', compared)

    def test_flash_segments_and_triangle_palette_equal_old(self):
        self.assertEqual(self.new['flash'], self.old['flash'])
        self.assertEqual(self.new['palette'], self.old['palette'])


if __name__ == '__main__':
    unittest.main()
