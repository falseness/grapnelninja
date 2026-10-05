"""Tests for computePhysicsSteps in gameoptions.js (fixed 60 Hz physics pacing).

gameoptions.js is loaded into a node vm context with a stub window, and fed
simulated rAF timestamps. The old runFixedPhysics accumulator (copied from
index.html before TASK-150: starts at 0, no snapping, up to 5 steps of
catch-up) runs on the same timestamps for comparison. Jitter is per frame
interval, uniform +-1.5 ms from a seeded generator (mulberry32).
Set FRAME_PACING_JSON=<path> to also write the old/new histograms to a file.
"""
import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NODE_SCRIPT = r'''
const vm = require('vm')
const fs = require('fs')
const root = process.argv[1]
const ctx = {window: {innerWidth: 844, innerHeight: 390, devicePixelRatio: 3}, Math, console}
vm.createContext(ctx)
vm.runInContext(fs.readFileSync(root + '/gameoptions.js', 'utf8'), ctx)
const stepMs = vm.runInContext('physicsStepMs', ctx)
const computePhysicsSteps = vm.runInContext('computePhysicsSteps', ctx)

// index.html runFixedPhysics before TASK-150, returning the step count
function oldSteps(state, frameTime)
{
    const maxPhysicsFrameMs = stepMs * 5, eps = 0.000001
    if (!state.lastFrameTime) { state.lastFrameTime = frameTime; return 1 }
    const elapsedMs = Math.min(frameTime - state.lastFrameTime, maxPhysicsFrameMs)
    state.lastFrameTime = frameTime
    state.acc = (state.acc || 0) + elapsedMs
    let n = 0
    while (state.acc + eps >= stepMs) { n++; state.acc = Math.max(0, state.acc - stepMs) }
    return n
}

function mulberry32(a)
{
    return function() {
        a |= 0; a = a + 0x6D2B79F5 | 0
        let t = Math.imul(a ^ a >>> 15, 1 | a)
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t
        return ((t ^ t >>> 14) >>> 0) / 4294967296
    }
}

function intervals(name)
{
    const rnd = mulberry32(150)
    const out = []
    for (let i = 0; i < 600; i++)
    {
        if (name === 'hz60_jitter') out.push(1000 / 60 + (rnd() * 3 - 1.5))
        else if (name === 'hz120') out.push(1000 / 120)
        else if (name === 'hz30') out.push(1000 / 30)
        else if (name === 'hitch100') out.push(i === 300 ? 100 : 1000 / 60)
    }
    return out
}

const result = {}
for (const name of ['hz60_jitter', 'hz120', 'hz30', 'hitch100'])
{
    result[name] = {}
    for (const [algo, fn] of [['old', oldSteps], ['new', computePhysicsSteps]])
    {
        const state = {lastFrameTime: 0, accumulatorMs: 0}
        let t = 1000
        fn(state, t)    // first frame: one step in both, not counted
        const steps = intervals(name).map(dt => fn(state, t += dt))
        const histogram = {}
        for (const s of steps) histogram[s] = (histogram[s] || 0) + 1
        result[name][algo] = {histogram, steps}
    }
}
process.stdout.write(JSON.stringify(result))
'''


def simulate():
    out = subprocess.check_output(['node', '-e', NODE_SCRIPT, str(ROOT)], text=True)
    return json.loads(out)


class FramePacingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = simulate()
        for name, algos in cls.result.items():
            print(f"{name}: old={algos['old']['histogram']} new={algos['new']['histogram']}")
        if os.environ.get('FRAME_PACING_JSON'):
            Path(os.environ['FRAME_PACING_JSON']).write_text(json.dumps(
                {name: {algo: v['histogram'] for algo, v in algos.items()}
                 for name, algos in cls.result.items()}, indent=1))

    def steps(self, name, algo='new'):
        return self.result[name][algo]['steps']

    def test_60hz_with_jitter_is_one_step_every_frame(self):
        self.assertEqual(len(self.steps('hz60_jitter')), 600)
        self.assertEqual(set(self.steps('hz60_jitter')), {1})

    def test_old_algorithm_judders_at_60hz_with_jitter(self):
        old = self.result['hz60_jitter']['old']['histogram']
        print(f"old 60 Hz jitter: 0-step frames={old.get('0', 0)} 2-step frames={old.get('2', 0)}")
        self.assertGreater(old.get('0', 0), 0)
        self.assertGreater(old.get('2', 0), 0)

    def test_120hz_alternates_zero_and_one(self):
        steps = self.steps('hz120')
        self.assertTrue(set(steps) <= {0, 1})
        for a, b in zip(steps, steps[1:]):
            self.assertNotEqual(a, b)

    def test_30hz_is_two_steps_every_frame(self):
        self.assertEqual(set(self.steps('hz30')), {2})

    def test_100ms_hitch_catches_up_with_at_most_two_steps(self):
        steps = self.steps('hitch100')
        self.assertLessEqual(steps[300], 2)
        self.assertLessEqual(max(steps), 2)
        self.assertEqual(set(steps[:300] + steps[301:]), {1})


if __name__ == '__main__':
    unittest.main()
