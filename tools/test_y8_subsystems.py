"""Browser-free checks of the TASK-278 subsystems module (timing arms, probe checks, profile math, decision)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_subsystems as ss  # noqa: E402
import y8_feature_ablation as ab  # noqa: E402
import y8_feature_cost as fc  # noqa: E402

EFFECTS = '\n'.join(['// header', 'class BackgroundRenderer', '{', '    draw() {}', '}', 'class ParticleSystem', '{',
                     '    update() {}', '    drawAmbientMotes() {}', '}', 'class PlayerTrailRenderer', '{', '    draw() {}', '}',
                     'class UIStylingHooks', '{', '    draw() {}', '}'])


def fake_raw(arm, frozen=False, steps=(2, 2, 2, 2, 2, 2), draw_replaced=False, warmup=20, window=40):
    frames, t = [], 1000.0
    for i in range(len(steps) + 1):
        frames.append({'t': t, 'dt': None if i == 0 else 10.0, 'canvas': [1280, 720], 'state': {}})
        t += 10.0
    probe = {'arm': arm, 'kind': 'count-only', 'physicsCalls': sum(steps), 'drawCalls': len(frames), 'runFixedPhysicsCalls': len(frames),
             'stepsPerFrame': list(steps), 'frozen': frozen, 'frozenAtActiveMs': 20.0 if frozen else None, 'frozenFrames': 4 if frozen else 0,
             'physicsCallsWhileFrozen': 0, 'inputsBlocked': 0, 'freezeState': {'nx': 1} if frozen else None, 'drawReplaced': draw_replaced}
    return {'case': 'x', 'settings': {'arm': arm, 'warmup_ms': warmup, 'window_ms': window, 'windows': 1}, 'frames': frames,
            'loopProbe': probe, 'warmupEndMs': 20.0}


class Protocol(unittest.TestCase):
    def test_sequence_is_bracketed_and_reversed(self):
        r1, r2 = ss.sequence('r1'), ss.sequence('r2')
        self.assertEqual(r1[0], ss.CONTROL)
        self.assertEqual(r1[-1], ss.CONTROL)
        self.assertEqual(r1[1:-1], list(ss.ARM_ORDER))
        self.assertEqual(r2[1:-1], list(reversed(ss.ARM_ORDER)))
        self.assertEqual(len(r1), len(ss.ARMS) + 1)

    def test_case_name_and_expected_hooks(self):
        self.assertEqual(ss.case_name('bad', 'hud-off', 'r2', 3), 'bad-hud-off-r2-i3')
        self.assertEqual(ss.expected_ablated('full-loop'), [])
        self.assertEqual(ss.expected_ablated('drawing-only'), [])
        self.assertEqual(ss.expected_ablated('simulation-only'), [ss.ALL_DRAW_ABLATED])
        self.assertEqual(ss.expected_ablated('particles-off'), [ab.FEATURES['particles']['removes']])
        for arm in ss.FEATURE_ARMS:
            self.assertIn(ss.ARMS[arm]['feature'], ab.FEATURES)

    def test_tier(self):
        self.assertEqual(ss.tier([5.0, 6.0], 2.0), 'REPEATED')
        self.assertEqual(ss.tier([5.0, -6.0], 2.0), 'CONSISTENT')
        self.assertEqual(ss.tier([5.0, 1.0], 2.0), 'CONSISTENT')
        self.assertEqual(ss.tier([1.0, -1.0], 2.0), 'WITHIN_NOISE')


class Probe(unittest.TestCase):
    def test_drawing_only_requires_frozen_window(self):
        raw = fake_raw('drawing-only', frozen=True, steps=(2, 2, 0, 0, 0, 0))
        raw['probe_summary'] = ss.probe_summary(raw)
        ss.check_probe(raw)
        self.assertEqual(raw['probe_summary']['timing_represents'], 'frozen state rendering (not gameplay)')
        self.assertEqual(raw['probe_summary']['window_steps_total'], 0)
        bad = fake_raw('drawing-only', frozen=True, steps=(2, 2, 1, 0, 0, 0))
        bad['probe_summary'] = ss.probe_summary(bad)
        with self.assertRaises(fc.EvidenceError):
            ss.check_probe(bad)

    def test_live_arms_require_physics_and_draw_state(self):
        raw = fake_raw('full-loop')
        raw['probe_summary'] = ss.probe_summary(raw)
        ss.check_probe(raw)
        self.assertEqual(raw['probe_summary']['timing_represents'], 'active replayed gameplay')
        self.assertEqual(raw['probe_summary']['window_steps_per_frame_mean'], 2.0)
        sim = fake_raw('simulation-only', draw_replaced=True)
        sim['probe_summary'] = ss.probe_summary(sim)
        ss.check_probe(sim)
        self.assertEqual(sim['probe_summary']['timing_represents'], 'physics without drawing (not gameplay)')
        wrong = fake_raw('simulation-only', draw_replaced=False)
        wrong['probe_summary'] = ss.probe_summary(wrong)
        with self.assertRaises(fc.EvidenceError):
            ss.check_probe(wrong)
        frozen_control = fake_raw('full-loop', frozen=True)
        frozen_control['probe_summary'] = ss.probe_summary(frozen_control)
        with self.assertRaises(fc.EvidenceError):
            ss.check_probe(frozen_control)


class ProfileMath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'render').mkdir()
        (root / 'render/effects.js').write_text(EFFECTS)
        self.ranges = ss.effects_class_ranges(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_class_ranges_and_buckets(self):
        self.assertEqual([r[2] for r in self.ranges], ['BackgroundRenderer', 'ParticleSystem', 'PlayerTrailRenderer', 'UIStylingHooks'])
        url = 'http://127.0.0.1:1/render/effects.js'
        self.assertEqual(ss.bucket_for(url, 'update', 7, self.ranges), 'particles')          # 0-based line 7 = line 8
        self.assertEqual(ss.bucket_for(url, 'drawAmbientMotes', 8, self.ranges), 'ambient-glow')
        self.assertEqual(ss.bucket_for(url, 'draw', 12, self.ranges), 'player-trail')
        self.assertEqual(ss.bucket_for(url, 'draw', 16, self.ranges), 'hud')
        self.assertEqual(ss.bucket_for(url, 'draw', 3, self.ranges), 'background')
        self.assertEqual(ss.bucket_for('http://127.0.0.1:1/physics.js', 'calcPhysics', 10, self.ranges), 'simulation')
        self.assertEqual(ss.bucket_for('http://127.0.0.1:1/sprites/ninja.js', 'move', 10, self.ranges), 'simulation')
        self.assertEqual(ss.bucket_for('http://127.0.0.1:1/sprites/ninja.js', 'draw', 10, self.ranges), 'drawing-other')
        self.assertEqual(ss.bucket_for('http://127.0.0.1:1/sprites/scoretext.js', 'draw', 1, self.ranges), 'hud')
        self.assertEqual(ss.bucket_for('', '(garbage collector)', 0, self.ranges), 'gc')
        self.assertEqual(ss.bucket_for('', 'fillText', 0, self.ranges), 'native')
        self.assertEqual(ss.bucket_for('http://127.0.0.1:1/index.html', 'runFixedPhysics', 500, self.ranges), 'loop')

    def test_cpu_profile_aggregation(self):
        cpu = {'nodes': [{'id': 1, 'callFrame': {'functionName': '(root)', 'url': '', 'lineNumber': -1}},
                         {'id': 2, 'callFrame': {'functionName': 'calcPhysics', 'url': 'http://h/physics.js', 'lineNumber': 14}},
                         {'id': 3, 'callFrame': {'functionName': '(garbage collector)', 'url': '', 'lineNumber': -1}},
                         {'id': 4, 'callFrame': {'functionName': 'draw', 'url': 'http://h/render/effects.js', 'lineNumber': 16}}],
               'samples': [2, 2, 3, 4], 'timeDeltas': [1000, 1000, 500, 2500]}
        agg = ss.aggregate_cpu_profile(cpu, self.ranges)
        self.assertEqual(agg['total_sampled_ms'], 5.0)
        self.assertEqual(agg['bucket_ms'], {'hud': 2.5, 'simulation': 2.0, 'gc': 0.5})
        self.assertAlmostEqual(agg['bucket_fraction']['simulation'], 0.4)
        self.assertEqual(agg['top_functions_ms'][0]['function'], 'draw @ effects.js:17')

    def test_heap_profile_aggregation(self):
        heap = {'head': {'callFrame': {'functionName': '(root)', 'url': '', 'lineNumber': -1}, 'selfSize': 0, 'children': [
            {'callFrame': {'functionName': 'pushParticle', 'url': 'http://h/render/effects.js', 'lineNumber': 7}, 'selfSize': 3000, 'children': []},
            {'callFrame': {'functionName': 'move', 'url': 'http://h/sprites/ninja.js', 'lineNumber': 1}, 'selfSize': 1000, 'children': [
                {'callFrame': {'functionName': 'calcSpeed', 'url': 'http://h/sprites/grapnel.js', 'lineNumber': 1}, 'selfSize': 1000, 'children': []}]}]},
                'samples': [1, 2, 3]}
        agg = ss.aggregate_heap_profile(heap, self.ranges)
        self.assertEqual(agg['total_sampled_bytes'], 5000)
        self.assertEqual(agg['bucket_bytes'], {'particles': 3000, 'simulation': 2000})
        self.assertEqual(agg['top_functions_bytes'][0]['bytes'], 3000)

    def test_gc_from_trace_uses_window_marks_and_main_thread(self):
        mark = lambda name, ts: {'cat': 'blink.user_timing', 'ph': 'R', 'name': name, 'ts': ts, 'pid': 7, 'tid': 9}
        gc = lambda name, ts, dur, cat='devtools.timeline', tid=9: {'cat': cat, 'ph': 'X', 'name': name, 'ts': ts, 'dur': dur, 'pid': 7, 'tid': tid}
        events = [mark('fcWindowStart', 1000), gc('MinorGC', 1100, 300), gc('MajorGC', 2000, 1500), gc('MinorGC', 900, 50),
                  gc('MinorGC', 1200, 100, tid=3), gc('V8.GCScavenger', 1150, 200, cat='v8'), mark('fcWindowEnd', 11000)]
        out = ss.gc_from_trace(events)
        self.assertTrue(out['window_found'])
        self.assertEqual(out['timeline_totals']['MinorGC']['count'], 1)
        self.assertEqual(out['timeline_totals']['MajorGC']['total_ms'], 1.5)
        self.assertAlmostEqual(out['timeline_gc_ms'], 1.8)
        self.assertAlmostEqual(out['timeline_gc_fraction_of_window'], 1.8 / 10)
        self.assertEqual(out['v8_totals']['V8.GCScavenger']['count'], 1)
        self.assertFalse(ss.gc_from_trace([gc('MinorGC', 1, 1)])['window_found'])

    def test_memory_series_marks_unavailable_not_zero(self):
        raw = {'memory_api': {'performance_memory': 'unavailable: performance.memory absent',
                              'measureUserAgentSpecificMemory': 'unavailable: API absent',
                              'measureUserAgentSpecificMemory_call': 'unavailable: API absent'},
               'memory_samples': [{'unavailable': 'x', 'activeMs': 0, 't': 1, 'frames': 0, 'label': 'before-start'},
                                  {'unavailable': 'x', 'activeMs': 5000, 't': 2, 'frames': 50, 'label': 'window-start'},
                                  {'unavailable': 'x', 'activeMs': 9000, 't': 3, 'frames': 90, 'label': 'window-end'}],
               'metrics_samples': [{'label': 'before-start', 'activeMs': 0, 'frames': 0, 'metrics': {'JSHeapUsedSize': 10, 'JSHeapTotalSize': 20, 'Nodes': 5}},
                                   {'label': 'window-start', 'activeMs': 5000, 'frames': 50, 'metrics': {'JSHeapUsedSize': 30, 'JSHeapTotalSize': 40, 'Nodes': 5}},
                                   {'label': 'window-end', 'activeMs': 9000, 'frames': 90, 'metrics': {'JSHeapUsedSize': 25, 'JSHeapTotalSize': 40, 'Nodes': 5}}]}
        out = ss.memory_series(raw)
        self.assertEqual(out['usedJSHeapSize_series'], 'unavailable')
        self.assertTrue(out['performance_memory'].startswith('unavailable'))
        self.assertEqual(out['JSHeapUsedSize_series'], [10, 30, 25])
        self.assertEqual(out['window']['drops'], 1)


def paired(control=100.0, sim=16.7, drawing=90.0, features=((3.0, 4.0), (1.0, -1.0), (0.5, 0.2)), noise=2.0):
    arms = {}
    for arm, mean in (('simulation-only', sim), ('drawing-only', drawing)):
        arms[arm] = {'mean_ms': [mean, mean], 'saving_ms': [control - mean, control - mean], 'tier': ss.tier([control - mean] * 2, noise),
                     'fraction_of_control': (control - mean) / control, 'at_environment_ceiling': mean < 21}
    for arm, sv in zip(ss.FEATURE_ARMS, features):
        arms[arm] = {'mean_ms': [control - sv[0], control - sv[1]], 'saving_ms': list(sv), 'tier': ss.tier(list(sv), noise),
                     'fraction_of_control': (sum(sv) / 2) / control}
    return {'result': 'PAIRED', 'control': {'mean_ms': control, 'noise_max_ms': noise}, 'arms': arms}


def session(physics_ms=1.0, gc_ms_total=20.0, frames=100):
    return {'result': 'COMPLETE', 'window_frames': frames, 'per_frame_js': {'physics_ms': physics_ms, 'steps_per_frame': 2.0, 'draw_ms': 4.0},
            'gc': {'window_found': True, 'timeline_gc_ms': gc_ms_total, 'timeline_gc_count': 5, 'timeline_gc_fraction_of_window': 0.002},
            'cpu_profile': {'bucket_fraction': {'simulation': 0.05, 'gc': 0.01}, 'top_functions_ms': [{'function': '(program) @ :0', 'ms': 9.0}, {'function': 'f @ a.js:1', 'ms': 1.0}]},
            'heap_profile': {'bucket_fraction': {'particles': 0.5}, 'top_functions_bytes': [{'function': 'rectangle @ effects.js:10', 'bytes': 100, 'fraction': 0.5}]},
            'activity': {'particle_objects_allocated_in_window': 3}, 'memory_api': {'performance_memory': 'available'}}


class Decision(unittest.TestCase):
    def test_not_material_when_sim_and_gc_small(self):
        d = ss.decide({'results': {m: paired() for m in ss.MODES}}, {'sessions': {m: session() for m in ss.MODES}})
        self.assertEqual(d['verdict'], 'CPU_SIMULATION_GC_NOT_MATERIAL')
        bad = d['per_mode']['bad']
        self.assertAlmostEqual(bad['simulation_plus_gc_ms_per_frame'], 1.2)
        self.assertEqual(bad['material_threshold_ms'], 10.0)
        names = [(c['subsystem'], c['candidate']) for c in d['candidates'] if c['mode'] == 'bad']
        self.assertIn(('particles', True), names)
        self.assertIn(('player-trail', False), names)
        self.assertIn(('simulation (physics JS)', False), names)
        self.assertIn('NOT EQUIVALENT', d['drawing_only_statement'])
        alloc = next(c for c in d['candidates'] if c['subsystem'].startswith('allocation') and c['mode'] == 'bad')
        self.assertFalse(alloc['candidate'])
        self.assertEqual(alloc['hotspots'][0]['function'], 'rectangle @ effects.js:10')
        self.assertEqual(bad['profile']['cpu_hotspots'][0]['function'], 'f @ a.js:1')

    def test_material_and_incomplete(self):
        d = ss.decide({'results': {m: paired() for m in ss.MODES}}, {'sessions': {m: session(physics_ms=8.0, gc_ms_total=1200.0) for m in ss.MODES}})
        self.assertEqual(d['verdict'], 'CPU_SIMULATION_GC_MATERIAL')
        self.assertTrue(any(c['subsystem'] == 'GC pauses' and c['candidate'] for c in d['candidates_for_separate_optimization']))
        one = ss.decide({'results': {'bad': paired(), 'classic': paired()}},
                        {'sessions': {'bad': session(physics_ms=12.0), 'classic': session()}})
        self.assertEqual(one['verdict'], 'CPU_SIMULATION_GC_MATERIAL_IN_ONE_MODE')
        inc = ss.decide({'results': {'bad': paired(), 'classic': {'result': 'INCOMPLETE'}}}, {'sessions': {m: session() for m in ss.MODES}})
        self.assertEqual(inc['verdict'], 'INCOMPLETE')


if __name__ == '__main__':
    unittest.main()
