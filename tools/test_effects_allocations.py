"""Tests for the allocation-free paths in render/effects.js.

Both the base rev's render/effects.js (splice, .map and per-point objects) and
the worktree's (pooled arrays, in-place compaction) are loaded into separate
node vm contexts with the same stub globals, then fed the same fixed inputs:
particle compaction and the cap must keep order and drop exactly the expired
or oldest particles, and the ribbon points/outline must equal the old algorithm's output value for value,
including when the pooled arrays are reused with fewer points.
The allocation test counts bytes per call of each targeted path, old vs new,
as the heapUsed delta over N warmed-up calls between gc() calls, with a 64 MB
semi-space so no scavenge runs inside the counted loop (checked with a gc
PerformanceObserver). Set EFFECTS_ALLOC_LOG to also write the table to a file.
EFFECTS_BASE defaults to the parent of the commit that added this test, or
HEAD while it is not committed yet.
"""
import json
import math
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

    return out
}

console.log(JSON.stringify({old: run(load(oldPath)), new: run(load(newPath))}))
'''


ALLOC_N = 2000
ALLOC_MAX_POOLED_BYTES = 64
ALLOC_SCRIPT = r'''
const vm = require('vm')
const fs = require('fs')
const {performance, PerformanceObserver, constants} = require('perf_hooks')
const [oldPath, newPath, n] = process.argv.slice(-3)
const N = Number(n)
const WARMUP_ROUNDS = 10
const TRIALS = 5

function load(path) {
    // No Math/Object/... from this context: cross-context Math.sqrt is not inlined
    // by TurboFan and boxes its argument and result, which would be counted here.
    const context = {
        performance: {now: () => 0},
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

const lives = [5, 16, 40, 0.5, 17, 100, 16.0001, -1, 30, 2]
const particleSets = () => Array.from({length: N}, () =>
    lives.map((life, i) => ({id: i, x: i, y: -i, vx: 0.1, vy: -0.05, life, maxLife: 100})))

let sink = 0

function paths(e) {
    const trail = new e.PlayerTrailRenderer()
    const track = Array.from({length: 40}, (_, i) => ({x: i * 3 + Math.sin(i) * 2, y: Math.cos(i * 0.7) * 9}))
    const system = new e.ParticleSystem(null, null)
    return {
        'getRibbonPoints+getRibbonOutline': i => {
            sink += trail.getRibbonOutline(trail.getRibbonPoints(track, 2.5), 2, 6 + (i & 3)).length
        },
        // 10 particles per call, 5 expire (splice per particle in the old code).
        'updateParticles (expiring)': (i, sets) => { system.particles = sets[i]; system.updateParticles(16); sink += system.particles.length },
        // 10 particles per call over a cap of 5.
        'enforceCap': (i, sets) => { system.particles = sets[i]; system.enforceCap(); sink += system.particles.length }
    }
}

const windows = []

function measure(run, needsSets) {
    // Warm up until TurboFan has compiled the path, so the counted calls run optimized code.
    for (let round = 0; round < WARMUP_ROUNDS; ++round) {
        const sets = needsSets ? particleSets() : null
        for (let i = 0; i < N; ++i)
            run(i, sets)
    }
    let best = Infinity
    for (let trial = 0; trial < TRIALS; ++trial) {
        const sets = needsSets ? particleSets() : null
        global.gc()
        global.gc()
        const start = performance.now()
        const before = process.memoryUsage().heapUsed
        for (let i = 0; i < N; ++i)
            run(i, sets)
        const after = process.memoryUsage().heapUsed
        windows.push([start, performance.now()])
        best = Math.min(best, after - before)
    }
    return best
}

const gcs = []
const observer = new PerformanceObserver(list => gcs.push(...list.getEntries()))
observer.observe({entryTypes: ['gc']})

const result = {N, warmup_rounds: WARMUP_ROUNDS, trials: TRIALS, baseline_bytes: measure(() => {}, false), paths: {}}
const oldPaths = paths(load(oldPath))
const newPaths = paths(load(newPath))
for (const name of Object.keys(oldPaths)) {
    const needsSets = name == 'updateParticles (expiring)' || name == 'enforceCap'
    const old = measure(oldPaths[name], needsSets)
    const current = measure(newPaths[name], needsSets)
    result.paths[name] = {
        old: Math.max(0, old - result.baseline_bytes) / N,
        new: Math.max(0, current - result.baseline_bytes) / N
    }
}
setImmediate(() => {
    observer.disconnect()
    result.gc_inside_counted_loops = gcs.filter(entry => windows.some(([start, end]) =>
        entry.startTime < end && entry.startTime + entry.duration > start)).length
    result.sink = sink
    console.log(JSON.stringify(result))
})
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
        cls.old_path = old_path
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

    def test_targeted_paths_allocate_less_and_pooled_paths_allocate_nothing(self):
        result = subprocess.run(
            ['node', '--expose-gc', '--min-semi-space-size=64', '--max-semi-space-size=64',
             '-e', ALLOC_SCRIPT, str(self.old_path), str(ROOT / 'render/effects.js'), str(ALLOC_N)],
            capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        data = json.loads(result.stdout)
        lines = [
            f'old={self.base} (render/effects.js)',
            f'new={git("rev-parse", "HEAD")} (worktree render/effects.js, '
            f'dirty={bool(git("status", "--porcelain", "--", "render/effects.js"))})',
            f'node={subprocess.check_output(["node", "--version"], text=True).strip()} '
            'flags=--expose-gc --min-semi-space-size=64 --max-semi-space-size=64',
            f'method=heapUsed delta over N={data["N"]} calls after gc(), after {data["warmup_rounds"]}x{data["N"]} '
            f'warm-up calls, min of {data["trials"]} trials, minus the empty-loop baseline '
            f'({data["baseline_bytes"]} B per {data["N"]} calls); sampling interval: none (exact byte count)',
            f'gc_inside_counted_loops={data["gc_inside_counted_loops"]}',
            f'{"path":36} {"old B/call":>12} {"new B/call":>12}',
        ]
        for name, row in data['paths'].items():
            lines.append(f'{name:36} {row["old"]:12.1f} {row["new"]:12.1f}')
        table = '\n'.join(lines)
        print('\n' + table)
        if os.environ.get('EFFECTS_ALLOC_LOG'):
            Path(os.environ['EFFECTS_ALLOC_LOG']).write_text(table + '\n')

        self.assertEqual(data['gc_inside_counted_loops'], 0)
        self.assertEqual(len(data['paths']), 3)
        for name, row in data['paths'].items():
            self.assertTrue(math.isfinite(row['old']) and math.isfinite(row['new']), name)
            self.assertLess(row['new'], row['old'], name)
            self.assertLessEqual(row['new'], ALLOC_MAX_POOLED_BYTES, name)


if __name__ == '__main__':
    unittest.main()
