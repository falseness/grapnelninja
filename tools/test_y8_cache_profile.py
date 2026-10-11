"""Browser-free checks of the TASK-277 cache/resize profile module."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import y8_cache_profile as cp  # noqa: E402

CONSTANTS = {'crystals_maxPixelScale': 1, 'nearRocks_maxPixelScale': 1, 'lights_resolutionScale': 0.2,
             'window_background_scale': 0.25, 'window_bars_every_frames': 4,
             'glow': {'ambientGlow': {'resolutionScale': 0.25, 'blurLevels': 4}, 'playerGlow': {'resolutionScale': 0.25, 'blurLevels': 4}}}


def snapshot(vw, vh, dpr, **overrides):
    exp = cp.expected_dimensions({'viewport': [vw, vh], 'density': dpr}, CONSTANTS)
    key = '|'.join(str(x) for x in exp['tile_key'])
    s = {'resizeTimerNull': True, 'logical': [exp['logical_width'], 1080], 'computedLogicalWidth': exp['logical_width'],
         'css': {'width': exp['css'][0], 'height': exp['css'][1]}, 'canvas': exp['backing'], 'lightmap': exp['lightmap'],
         'tiles': {'far': {'key': key, 'size': exp['tile']}, 'near': {'key': key, 'size': exp['tile']}},
         'glowLevels': exp['glow_levels'], 'bars': exp['bars'], 'viewport': [vw, vh], 'density': dpr}
    s.update(overrides)
    return s


class Dimensions(unittest.TestCase):
    def test_debounce_from_source(self):
        self.assertEqual(cp.debounce_ms_from_source(), 100)
        self.assertGreater(cp.settle_extra_ms(100), 100)
        self.assertEqual(cp.settle_extra_ms(100), 300)
        self.assertEqual(cp.settle_extra_ms(10), 250)

    def test_expected_dimensions_dpr1_and_dpr2(self):
        e1 = cp.expected_dimensions({'viewport': [1280, 720], 'density': 1}, CONSTANTS)
        e2 = cp.expected_dimensions({'viewport': [1280, 720], 'density': 2}, CONSTANTS)
        self.assertEqual(e1['logical_width'], 1920)
        self.assertEqual(e1['backing'], [1280, 720])
        self.assertEqual(e2['backing'], [2560, 1440])
        self.assertEqual(e1['lightmap'], e2['lightmap'])  # logical-size based, DPR independent
        self.assertEqual(e1['tile'], [1280, 720])          # pixelScale 1280/1920
        self.assertEqual(e2['tile'], [1920, 1080])         # capped at maxPixelScale 1
        self.assertEqual(e1['glow_levels']['ambientGlow'][0], [320, 180])
        self.assertEqual(e2['glow_levels']['ambientGlow'], [[640, 360], [320, 180], [160, 90], [80, 45]])
        self.assertEqual(e1['bars'], [])

    def test_letterbox_bars(self):
        e = cp.expected_dimensions({'viewport': [640, 540], 'density': 1}, CONSTANTS)
        self.assertEqual(e['logical_width'], 1440)
        self.assertEqual(e['css'], [640, 480])
        self.assertEqual(len(e['bars']), 2)
        # top bar: full width, 30 px + overlap (2 + 2 / 0.25 = 10) -> 40 px at 0.25 -> ceil(160) x ceil(10)
        self.assertEqual(e['bars'][0], [160, 10])

    def test_settled_assertions_pass_and_fail(self):
        ok = cp.settled_assertions(snapshot(960, 540, 1), CONSTANTS)
        self.assertTrue(ok['settled'], ok['checks'])
        stale = cp.settled_assertions(snapshot(960, 540, 1, canvas=[1280, 720]), CONSTANTS)
        self.assertFalse(stale['settled'])
        self.assertFalse(stale['checks']['main_backing_equals_round_css_times_dpr'])
        pending = cp.settled_assertions(snapshot(960, 540, 1, resizeTimerNull=False), CONSTANTS)
        self.assertFalse(pending['checks']['resize_timer_idle'])
        old_tile = snapshot(960, 540, 2)
        old_tile['tiles']['far']['key'] = '1920|1080|0.6666666666666666'
        self.assertFalse(cp.settled_assertions(old_tile, CONSTANTS)['checks']['tile_keys_match_viewport'])

    def test_expected_backing_from_dimensions(self):
        self.assertEqual(cp.expected_backing({'css': [1280, 720], 'dpr': 2}), [2560, 1440])
        self.assertEqual(cp.expected_backing({'css': [640.4, 480.3], 'dpr': 1}), [640, 480])


class Protocol(unittest.TestCase):
    def test_sequence_reversed_in_r2(self):
        r1, r2 = cp.sequence('r1', 'dpr1'), cp.sequence('r2', 'dpr1')
        self.assertEqual(len(r1), 7)                      # 3 arms x 2 scenes + the natural replay control
        self.assertEqual(r1[-1], ('control', 'replay'))
        self.assertEqual(len(cp.sequence('r1', 'dpr2')), 6)  # no replay scene at dpr2 (camera never moves there)
        self.assertEqual(r1, list(reversed(r2)))
        self.assertEqual(r1[0], ('control', 'stationary'))
        self.assertEqual(cp.case_name('dpr2', 'bad', 'world-off', 'moving', 'r2', 0), 'dpr2-bad-world-off-moving-r2-i0')

    def test_replay_scenes(self):
        self.assertEqual(cp.replay_for('classic', 'stationary', 'desktop', 5000, 10000, 1), [])
        self.assertEqual(cp.replay_for('classic', 'moving', 'desktop', 5000, 10000, 1), [])  # driven camera, no input
        replay = cp.replay_for('classic', 'replay', 'desktop-dpr2', 5000, 10000, 1)
        self.assertGreater(len(replay), 10)
        self.assertEqual(replay, cp.replay_for('classic', 'replay', 'desktop', 5000, 10000, 1))  # same CSS box in both contexts

    def test_tiers(self):
        self.assertEqual(cp.tier([5.0, 6.0], 2.0), 'REPEATED')
        self.assertEqual(cp.tier([5.0, -6.0], 2.0), 'CONSISTENT')
        self.assertEqual(cp.tier([5.0, 1.0], 2.0), 'CONSISTENT')
        self.assertEqual(cp.tier([1.0, -1.0], 2.0), 'WITHIN_NOISE')

    def test_delta(self):
        self.assertEqual(cp.delta({'a': 1, 'b': 2}, {'a': 1, 'b': 5, 'c': 1}), {'b': 3, 'c': 1})

    def test_scene_check(self):
        raw = {'settings': {'scene': 'stationary'}, 'density': {'camera': {'travel_px': 0, 'moving_fraction': 0}}, 'frames': [1] * 5}
        cp.check_scene(raw)
        raw['density']['camera']['travel_px'] = 3
        with self.assertRaises(cp.fc.EvidenceError):
            cp.check_scene(raw)
        moving = {'settings': {'scene': 'moving'}, 'density': {'camera': {'travel_px': 0, 'moving_fraction': 0}}, 'frames': [1] * 5,
                  'cameraDrive': {'frames': 5, 'travel_px': 120.0}}
        cp.check_scene(moving)
        moving['cameraDrive']['frames'] = 2  # drive missed frames
        with self.assertRaises(cp.fc.EvidenceError):
            cp.check_scene(moving)
        undriven = {'settings': {'scene': 'moving'}, 'density': {'camera': {'travel_px': 0, 'moving_fraction': 0}}, 'frames': [1] * 5}
        with self.assertRaises(cp.fc.EvidenceError):
            cp.check_scene(undriven)
        replay = {'settings': {'scene': 'replay'}, 'density': {'camera': {'travel_px': 0, 'moving_fraction': 0}}, 'frames': [1] * 5}
        cp.check_scene(replay)  # natural travel is recorded, not required
        replay['cameraDrive'] = {'frames': 5, 'travel_px': 1}
        with self.assertRaises(cp.fc.EvidenceError):
            cp.check_scene(replay)


class Bounds(unittest.TestCase):
    def make_raw(self, steady_alloc=0, dup_alloc=0, tile_per_step=2, steady_origin='BackgroundRenderer.getLayerTile', resize_origin='BackgroundRenderer.getLayerTile'):
        step = {'counters_delta': {'tileBuildsFar': tile_per_step // 2 or 1, 'tileBuildsNear': tile_per_step - (tile_per_step // 2 or 1),
                                   'canvasAllocations': tile_per_step, 'alloc:' + resize_origin: tile_per_step, 'backingChanges': 30},
                'settled': {'settled': True}, 'canvasCount': 20, 'dimensions_changed': {'viewport': True, 'backing': True, 'tiles': True}}
        return {'identical_frames': {'counters_delta': {'canvasAllocations': steady_alloc, 'alloc:' + steady_origin: steady_alloc,
                                                        'backingChanges': 2 * steady_alloc, 'cullRectRebuilds': 60}},
                'camera_shifts': {'counters_delta': {}},
                'resize_cycles': [{'cycle': c, 'steps': [dict(step) for _ in cp.RESIZE_STEPS]} for c in range(cp.RESIZE_CYCLES)],
                'duplicate_resize': {'counters_delta': {'canvasAllocations': dup_alloc}},
                'final': {'tiles': {'far': {}, 'near': {}}, 'gradientCacheSize': 1,
                          'glowLevels': {'ambientGlow': [[1, 1]] * 4, 'playerGlow': [[1, 1]] * 4, 'bloom': []}}}

    def test_bounds_pass(self):
        b = cp.cache_bounds_check(self.make_raw())
        self.assertTrue(b['all_pass'], b['checks'])

    def test_bounds_catch_steady_state_and_duplicate_allocations(self):
        recon = cp.cache_bounds_check(self.make_raw(steady_alloc=1))
        self.assertFalse(recon['checks']['steady_state_reconstruction_allocations_zero'])
        self.assertEqual(recon['steady_state_allocation_origins']['reconstruction'], {'BackgroundRenderer.getLayerTile': 1})
        lazy = cp.cache_bounds_check(self.make_raw(steady_alloc=2, steady_origin='LightmapRenderer.getShapeLight'))
        self.assertTrue(lazy['checks']['steady_state_reconstruction_allocations_zero'])
        self.assertTrue(lazy['checks']['steady_state_backing_changes_only_lazy_allocations'])
        self.assertEqual(lazy['steady_state_allocation_origins']['lazy'], {'LightmapRenderer.getShapeLight': 2})
        self.assertFalse(cp.cache_bounds_check(self.make_raw(dup_alloc=1))['checks']['duplicate_resize_zero_allocations_and_builds'])
        self.assertFalse(cp.cache_bounds_check(self.make_raw(tile_per_step=4))['checks']['tile_builds_per_settled_resize_le_bound'])
        unknown = cp.cache_bounds_check(self.make_raw(resize_origin='SomethingElse.build'))
        self.assertFalse(unknown['checks']['allocation_origins_all_known'])
        self.assertEqual(unknown['unknown_origins'], ['SomethingElse.build'])

    def test_profile_settled_counts(self):
        raw = self.make_raw()
        self.assertEqual(cp.profile_settled_counts(raw), (40, 40))


if __name__ == '__main__':
    unittest.main()
