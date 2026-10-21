"""TASK-499: full-mountain runtime cost, measured and bounded.

Task499Tests:
  * test_01: matched old-mode comparison against the immutable TASK-444 baseline revision. For each of classic and bad,
    three warmed tools/perf_mobile.py runs per revision (20 s window, 3 s warmup, seed 1, --no-trace), alternating
    baseline/final; the median frame-interval p95 of the final revision must stay within 1.10x of the baseline's. One
    extra grapple_over run proves the harness selects all three modes under the menu-less boot.
  * test_02: climb physics/render cost in each of the eight sections. The TASK-496 desktop completion route is replayed
    from a fresh base with trusted mouse events and explicit physics() steps (rAF off), and every section's first 300
    ticks are timed (physics() per tick, draw() per tick) with broadphase candidate and visible element counts. Eight
    long-fall scenes drop the player from each section's highest declared fall point.
  * test_03: a 600 simulated-second soak of repeated traversals with save/restore roundtrips at every section start,
    sampling heap usage after forced GC and terrain/mover/trail/cache counts every 120 simulated seconds.
  * test_04: summary.json and source hashes of the tested worktree.

All timings here are headless Chromium on a shared host. Accelerated replay throughput (ticks per wall second) is
reported for the soak but is not device FPS; frame intervals come only from perf_mobile's real rAF loop, and even those
are only meaningful as baseline/final ratios on the same host.
"""
import hashlib
import json
import os
import shlex
import statistics
import subprocess
import sys
import time
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter
from perf_mobile import SEED_SCRIPT

BASELINE_REV = '9639e07'          # TASK-444's pre-change revision (artifacts/TASK-444/pre-change.json)
FINAL_REV = 'worktree'
OLD_MODES = ('classic', 'bad')
REPEATS = 3
RATIO_LIMIT = 1.10
SCENE_TICKS = 300
FALL_TICKS = 600
SOAK_SECONDS = 600
SAMPLE_SECONDS = 120
SOAK_DRAW_EVERY = 30
HEAP_GROWTH_LIMIT = 0.10
VIEWPORT = {'width': 1280, 'height': 720}
HASHED_TOOLS = ['tools/perf_mobile.py', 'tools/browser_test_support.py', 'tools/grapple_over_test_support.py',
                'tools/test_grapple_over_performance.py', 'tools/test_grapple_over_completion.py',
                'tools/test_grapple_over_integration.py', 'tools/test_grapple_over_sections.py']


def source_hashes():
    names = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    names = [n for n in names if (n.endswith('.js') and not n.startswith('tools/')) or n == 'index.html'] + HASHED_TOOLS
    return {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in sorted(names)}


SETUP_JS = "() => {cancelAnimationFrame(game); window.requestAnimationFrame = () => 0; startGame('grapple_over'); CLIMB_UI.restart()}"

# Observation-only wrappers: broadphase tests made during physics() and culling tests made during draw().
INSTRUMENT_JS = '''() => {
    const P = window.__p499 = {physics: false, draw: false, hits: 0, tests: 0, visible: 0, culled: 0, tick: 0,
                               completedAt: null}
    const overlap = window.boundsOverlap, visible = P.isCullBoxVisible = window.isCullBoxVisible
    window.boundsOverlap = function(a, b) {
        const r = overlap(a, b)
        if (P.physics) {P.tests++; if (r) P.hits++}
        return r
    }
    window.isCullBoxVisible = function(box, rect) {
        const r = visible(box, rect)
        if (P.draw) r ? P.visible++ : P.culled++
        return r
    }
}'''

# n production physics() steps (the same calls GRAPPLE_OVER_TEST.step makes). A measured tick returns
# [physics ms, broadphase hits, broadphase tests (both over the tick's 8 physics cycles), draw ms, elements inside the
#  cull rect after the frame, cull tests made by draw(), rope points, trail points, particles, player y]; drawEvery draws unmeasured frames during the soak.
STEP_JS = '''([n, measure, drawEvery]) => {
    const P = __p499, rows = [], r = v => Math.round(v * 1e4) / 1e4, visible = P.isCullBoxVisible
    for (let i = 0; i < n; i++) {
        const done = floors[0].climbStats.completed
        P.hits = P.tests = 0
        P.physics = true
        const t = performance.now()
        physics()
        const dt = performance.now() - t
        P.physics = false
        P.tick++
        if (!done) P.active = (P.active || 0) + 1
        if (P.completedAt === null && floors[0].climbStats.completed) P.completedAt = P.tick
        const row = measure ? [r(dt), P.hits, P.tests] : null
        if (measure || (drawEvery && P.tick % drawEvery === 0)) {
            P.visible = P.culled = 0
            P.draw = true
            const t2 = performance.now()
            draw()
            const d2 = performance.now() - t2
            P.draw = false
            if (row) row.push(r(d2), floors[0].elements.filter(e => visible(getElementCullBox(e), getCullRect())).length,
                              P.visible + P.culled, grapnel.throwed ? grapnel.pos.length : 0,
                              ninja.track.pos.length, visualEffects.particles.particles.length, r(ninja.y))
        }
        if (row) rows.push(row)
    }
    TUTORIAL_HINT.advance(n * physicsStepMs)
    return rows
}'''
ROW_FIELDS = ['physics_ms', 'broadphase_hits', 'broadphase_tests', 'draw_ms', 'visible_elements', 'cull_tests',
              'rope_points', 'trail_points', 'particles', 'player_y']

CLIENT_JS = '''p => canvasCoordsToViewportCoords({x: (p.x + screen.x) * scale[version], y: (p.y + screen.y) * scale[version]})'''

WORLD_JS = '''() => ({floors: floors.length, elements: floors[0].elements.length, drag_zones: floors[0].dragZones.length,
    movers: floors[0].level.movers.length, geometry_elements: GRAPPLE_OVER_MOUNTAIN.geometry.elements.length,
    sections: GRAPPLE_OVER_MOUNTAIN.sections.map(s => ({id: s.id, band: s.band,
        fall: (s.fallPoints || []).reduce((a, p) => !a || p.y < a.y ? p : a, null)}))})'''

# Save/reload roundtrip of the simulation (JSON, as PROGRESS stores it). The camera is not simulation state; it is
# kept so the following trusted presses map to the same client pixels as in the uninterrupted route.
RESTORE_JS = '''() => {
    const camera = {x: screen.x, y: screen.y}, before = JSON.stringify(captureClimbState())
    restoreClimbState(JSON.parse(before))
    Object.assign(screen, camera)
    return before === JSON.stringify(captureClimbState())
}'''

FALL_JS = '''p => {
    CLIMB_UI.restart()
    Object.assign(ninja, {x: p.x, y: p.y, speedX: 0, speedY: 0})
    grapnel.endShot()
    pressHeld = stalePress = gameplayPressOwned = false
    screen.trackGrappleOver(true)
}'''

# Retained runtime objects: terrain, movers, rope, trails, particles and every Map/Set/Array (or *Cache object)
# held directly by a visual effects renderer, plus the module-level sprite/gradient caches.
COUNTS_JS = '''() => {
    const size = v => v instanceof Map || v instanceof Set ? v.size : Array.isArray(v) ? v.length
        : v && typeof v === 'object' ? Object.keys(v).length : null
    const caches = {}
    for (const [name, renderer] of Object.entries(visualEffects))
        for (const [key, value] of Object.entries(renderer || {}))
            if (value instanceof Map || value instanceof Set || Array.isArray(value) || /cache/i.test(key))
                caches[name + '.' + key] = size(value)
    caches['GLOW_SPRITES.cache'] = GLOW_SPRITES.cache.size
    caches['GLOW_TEXT_METRICS'] = GLOW_TEXT_METRICS.size
    caches['drawGrappleOverPalette.cache.gradients'] = drawGrappleOverPalette.cache ? drawGrappleOverPalette.cache.gradients.length : 0
    const w = floors[0]
    return {terrain: {floors: floors.length, elements: w.elements.length, by_id: w.byId.size, drag_zones: w.dragZones.length,
                      movers: w.level.movers.length, tracks: (w.tracks || []).length},
            trails: {player_track: ninja.track.pos.length, rope_points: grapnel.pos.length,
                     particles: visualEffects.particles.particles.length,
                     landings: visualEffects.screenEffects.landings.length},
            caches}
}'''


def pct(values, p):
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 4)


def stats(values):
    return dict(n=len(values), mean=round(sum(values) / len(values), 4), p50=pct(values, 50), p95=pct(values, 95),
                max=round(max(values), 4))


class Task499Tests(unittest.TestCase):
    task_id = 'TASK-499'

    @classmethod
    def setUpClass(cls):
        import test_grapple_over_completion as completion
        import test_grapple_over_sections as sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.hashes = source_hashes()
        route_cls = completion.Task496Tests
        route_cls.S = sections
        cls.route = route_cls.route()
        cls.route_ticks = route_cls.TICKS
        cls.section_starts = route_cls.section_starts(route_cls)
        cls.revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        cls.dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', '.', ':!artifacts'],
                                            cwd=ROOT, text=True).splitlines()
        cls.evidence.log('CONFIG ' + json.dumps(dict(case='setUpClass', revision=cls.revision, dirty_paths=cls.dirty,
                                                     source_hashes=cls.hashes), sort_keys=True))

    # ---- shared browser driver -----------------------------------------------------------------------------------
    def open_climb(self):
        self.url, browser = start_browser_test(ROOT, self.addCleanup)
        self.browser_version = browser.version
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors = []
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and self.errors.append('console: ' + m.text))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate(SETUP_JS)
        page.wait_for_function('!unTouch')
        page.mouse.up()
        page.evaluate(INSTRUMENT_JS)
        self.config = dict(browser=browser.version, browser_name='chromium (Playwright, headless)', viewport=VIEWPORT,
                           device_scale_factor=1, input='trusted page.mouse events', seed=1, physics_hz=60,
                           cycles_per_tick=page.evaluate('cyclesPerTick'), rAF='disabled; explicit physics() steps')
        return page, context

    def traverse(self, page, windows=None, hooks=None, draw_every=0, stop=None):
        """Replays the TASK-496 route once from the current base start. windows: {name: (start, end)} measured tick
        ranges; hooks: {tick: fn(tick)} called before that tick's inputs; stop: last tick to step (exclusive)."""
        windows, hooks = windows or {}, hooks or {}
        end = self.route_ticks if stop is None else stop
        bounds = {0, end} | {t for t, *_ in self.route if t < end} | {t for t in hooks if t < end}
        for a, b in windows.values():
            bounds.update(t for t in (a, b) if t < end)
        bounds = sorted(bounds)
        rows = {name: [] for name in windows}
        for tick, next_tick in zip(bounds, bounds[1:]):
            if tick in hooks:
                hooks[tick](tick)
            for t, event, x, y in self.route:
                if t != tick:
                    continue
                point = page.evaluate(CLIENT_JS, dict(x=x, y=y))
                if event == 'mousedown':
                    self.assertTrue(0 < point['x'] < VIEWPORT['width'] and 0 < point['y'] < VIEWPORT['height'], (tick, point))
                page.mouse.move(point['x'], point['y'])
                (page.mouse.down if event == 'mousedown' else page.mouse.up)()
            name = next((n for n, (a, b) in windows.items() if a <= tick < b), None)
            result = page.evaluate(STEP_JS, [next_tick - tick, name is not None, draw_every])
            if name:
                rows[name] += result
        return rows

    def scene(self, rows):
        cols = list(zip(*rows))
        col = dict(zip(ROW_FIELDS, cols))
        return dict(ticks=len(rows), physics_ms=stats(col['physics_ms']), draw_ms=stats(col['draw_ms']),
                    broadphase_candidates_per_tick=stats(col['broadphase_hits']),
                    broadphase_tests_per_tick=stats(col['broadphase_tests']),
                    visible_elements=stats(col['visible_elements']), cull_tests_per_frame=stats(col['cull_tests']),
                    rope_points_max=max(col['rope_points']), trail_points_max=max(col['trail_points']),
                    particles_max=max(col['particles']), player_y=[min(col['player_y']), max(col['player_y'])])

    # ---- cases ---------------------------------------------------------------------------------------------------
    def test_01_old_mode_matched_comparison(self):
        perf = self.evidence.path('perf/.keep').parent
        baseline_sha = subprocess.check_output(['git', 'rev-parse', BASELINE_REV], cwd=ROOT, text=True).strip()
        archived = json.loads((ROOT / 'artifacts/TASK-444/perf/classic-1.json').read_text())
        runs = {}

        def run(rev, mode, repeat):
            out = perf / f'{rev}-{mode}-{repeat}.json'
            cmd = ['python3', 'tools/perf_mobile.py', '--rev', rev, '--mode', mode, '--seconds', '20', '--warmup', '3',
                   '--seed', '1', '--no-trace', '--out', str(out.relative_to(ROOT))]
            self.evidence.log('COMMAND ' + shlex.join(cmd))
            started = time.time()
            with out.with_suffix('.log').open('w') as log:
                code = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
            self.evidence.log(f'EXIT {code} {out.name} wall_s={time.time() - started:.1f}')
            self.assertEqual(code, 0, out.with_suffix('.log').read_text()[-2000:])
            result = json.loads(out.read_text())
            self.assertEqual(result['page_errors'], [])
            self.assertEqual(result['selected']['mode'], mode)
            self.assertFalse(result['selected']['paused'])
            runs[rev, mode, repeat] = result
            return result

        order = []
        for repeat in range(1, REPEATS + 1):
            for mode in OLD_MODES:
                pair = (BASELINE_REV, FINAL_REV) if repeat % 2 else (FINAL_REV, BASELINE_REV)
                for rev in pair:
                    run(rev, mode, repeat)
                    order.append(f'{rev}-{mode}-{repeat}')
        go = run(FINAL_REV, 'grapple_over', 1)
        self.assertGreater(go['frames'], 0)
        self.assertEqual(go['selected']['flow'], 'boot run + menu.selectMode')

        results = list(runs.values())
        configs = {json.dumps([r['provenance']['browser_version'], r['emulation'], r['seconds'], r['seed'],
                               r['warmup_seconds'], r['provenance']['trace'], r['provenance']['harness_files_sha256'],
                               r['provenance']['runtime_scripts_sha256']], sort_keys=True) for r in results}
        self.assertEqual(len(configs), 1, 'every run must share browser and harness configuration')
        self.assertTrue(all(r['rev'] == baseline_sha for (rev, *_), r in runs.items() if rev == BASELINE_REV))
        final_revs = {r['rev'] for (rev, *_), r in runs.items() if rev == FINAL_REV}
        self.assertEqual(len(final_revs), 1, final_revs)
        reusable = (archived['provenance']['browser_version'] == results[0]['provenance']['browser_version'] and
                    archived['provenance']['harness_files_sha256'] == results[0]['provenance']['harness_files_sha256'])
        modes = {}
        for mode in OLD_MODES:
            row = {}
            for metric in ('frame_interval_ms_after_warmup', 'physics_ms', 'draw_ms'):
                base = [runs[BASELINE_REV, mode, i][metric]['p95'] for i in range(1, REPEATS + 1)]
                final = [runs[FINAL_REV, mode, i][metric]['p95'] for i in range(1, REPEATS + 1)]
                row[metric] = dict(baseline_p95=base, final_p95=final, baseline_median=statistics.median(base),
                                   final_median=statistics.median(final),
                                   ratio=round(statistics.median(final) / statistics.median(base), 4))
            row['frames'] = dict(baseline=[runs[BASELINE_REV, mode, i]['frames'] for i in range(1, REPEATS + 1)],
                                 final=[runs[FINAL_REV, mode, i]['frames'] for i in range(1, REPEATS + 1)])
            modes[mode] = row
        comparison = dict(baseline_rev=baseline_sha, final_rev=final_revs.pop(), order=order,
                          gated_metric='median over 3 runs of frame_interval_ms_after_warmup.p95, final/baseline',
                          limit=RATIO_LIMIT, modes=modes,
                          archived_task444=dict(browser=archived['provenance']['browser_version'],
                                                harness_files_sha256=archived['provenance']['harness_files_sha256'],
                                                reused=False, reusable=reusable,
                                                reason='fresh alternated baseline runs: the TASK-444 archive was made by an older perf_mobile.py '
                                                       '(different harness hash), so only fresh matched runs are compared'),
                          config=json.loads(configs.pop()),
                          grapple_over=dict(file=f'{FINAL_REV}-grapple_over-1.json', selected=go['selected'],
                                            frames=go['frames'], page_errors=go['page_errors']),
                          page_errors=sum(len(r['page_errors']) for r in runs.values()),
                          note='perf_mobile frame intervals are headless Chromium under a 4x CPU throttle on a shared '
                               'host; only the baseline/final ratio is meaningful, not the absolute FPS')
        self.evidence.write('perf/comparison.json', comparison)
        for mode in OLD_MODES:
            self.assertLessEqual(modes[mode]['frame_interval_ms_after_warmup']['ratio'], RATIO_LIMIT, (mode, modes[mode]))

    def test_02_climb_scenes(self):
        page, _ = self.open_climb()
        world = page.evaluate(WORLD_JS)
        starts = self.section_starts
        ids = [s['id'] for s in world['sections']]
        self.assertEqual(ids, sorted(starts))
        windows = {sid: (starts[sid], starts[sid] + SCENE_TICKS) for sid in ids}
        started = time.monotonic()
        rows = self.traverse(page, windows)
        wall = time.monotonic() - started
        p = page.evaluate('() => ({completedAt: __p499.completedAt, ticks: __p499.tick, completed: floors[0].climbStats.completed})')
        # Instrumentation is observation-only: the route still finishes on TASK-496's tick.
        self.assertEqual(p['completedAt'], 11453, p)
        climb = {}
        for sid in ids:
            self.assertEqual(len(rows[sid]), SCENE_TICKS)
            climb[sid] = dict(window=list(windows[sid]), **self.scene(rows[sid]))
        falls = {}
        for s in world['sections']:
            f = s['fall']
            page.evaluate(FALL_JS, f)
            page.evaluate('() => {__p499.tick = 0}')
            fall_rows = self.traverse_free(page, FALL_TICKS)
            summary = self.scene(fall_rows)
            summary.update(fall_point=f, drop=round(summary['player_y'][1] - f['y'], 1))
            falls[s['id']] = summary
        scenes = dict(config=self.config, route='Task496Tests.route() (TASK-496 desktop completion), fresh base start',
                      completion_tick=p['completedAt'], traversal_wall_s=round(wall, 1), world=dict(
                          elements=world['elements'], drag_zones=world['drag_zones'], movers=world['movers'],
                          geometry_elements=world['geometry_elements']),
                      scene_ticks=SCENE_TICKS, fall_ticks=FALL_TICKS, row_fields=ROW_FIELDS,
                      climb=climb, falls=falls, browser_errors=list(self.errors),
                      raw=dict(climb=rows, falls_note='fall rows summarised only'),
                      note='per-tick physics()/draw() cost of explicit accelerated steps in headless Chromium '
                           '(1280x720, DPR 1, no CPU throttle); not device FPS')
        self.evidence.write('perf/scenes.json', scenes)
        self.assertEqual(self.errors, [])
        for name, sc in list(climb.items()) + [('fall ' + k, v) for k, v in falls.items()]:
            # The broadphase keeps the exact tests to a handful of nearby elements per physics cycle in every scene.
            self.assertLess(sc['broadphase_candidates_per_tick']['max'] / self.config['cycles_per_tick'], world['elements'] / 10, name)
            self.assertLess(sc['visible_elements']['max'], world['elements'], name)
        for k, v in falls.items():
            self.assertGreater(v['drop'], 200, (k, v['drop']))

    def traverse_free(self, page, ticks):
        rows = []
        for _ in range(0, ticks, 100):
            rows += page.evaluate(STEP_JS, [100, True, 0])
        return rows

    def test_03_soak(self):
        page, context = self.open_climb()
        cdp = context.new_cdp_session(page)
        ticks_per_sample = SAMPLE_SECONDS * 60
        total = SOAK_SECONDS * 60
        samples, restores, traversals = [], [], []
        started = time.monotonic()

        def sample(_tick=None):
            cdp.send('HeapProfiler.collectGarbage')
            cdp.send('HeapProfiler.collectGarbage')
            heap = cdp.send('Runtime.getHeapUsage')
            state = page.evaluate('() => ({active: __p499.active || 0, ticks: __p499.tick})')
            samples.append(dict(simulated_s=round(state['active'] / 60, 3), active_ticks=state['active'],
                                wall_s=round(time.monotonic() - started, 2), heap_used=heap['usedSize'],
                                heap_total=heap['totalSize'], **page.evaluate(COUNTS_JS)))

        def restore(tick):
            restores.append(dict(traversal=len(traversals), tick=tick, exact=page.evaluate(RESTORE_JS)))

        sample()
        active = 0
        while active < total:
            if traversals:
                page.evaluate('() => {CLIMB_UI.restart(); __p499.completedAt = null}')
                page.mouse.up()
            page.evaluate('() => {__p499.tick = 0}')
            remaining = total - active
            # Hooks on this traversal's tick axis: restorations at every section start and the GC samples that fall
            # on a multiple of 120 simulated seconds (only active, i.e. uncompleted, ticks count as simulated time).
            hooks = {starts: restore for starts in self.section_starts.values() if starts > 0}
            for k in range(1, total // ticks_per_sample + 1):
                local = k * ticks_per_sample - active
                if 0 < local <= min(11453, remaining):
                    hooks[local] = sample
            stop = None if remaining > 11453 else remaining
            if stop is not None and stop in hooks:
                del hooks[stop]
            self.traverse(page, hooks=hooks, draw_every=SOAK_DRAW_EVERY, stop=stop)
            p = page.evaluate('() => ({completedAt: __p499.completedAt, active: __p499.active})')
            traversals.append(dict(completed_at=p['completedAt'], stopped_at=stop))
            if stop is None:
                self.assertEqual(p['completedAt'], 11453, p)
            active = p['active']
        sample()
        wall = time.monotonic() - started
        self.assertEqual(samples[-1]['active_ticks'], total)
        self.assertEqual([s['simulated_s'] for s in samples], [i * SAMPLE_SECONDS for i in range(SOAK_SECONDS // SAMPLE_SECONDS + 1)])
        warm = samples[1:]
        growth = (warm[-1]['heap_used'] - warm[0]['heap_used']) / warm[0]['heap_used']
        terrain = {json.dumps(s['terrain'], sort_keys=True) for s in samples}
        cache_growth = {k: [s['caches'][k] for s in warm] for k in warm[0]['caches']}
        # A collection still growing sets a new high at the last sample, above the first one after warmup and every
        # sample since. Bounded per-frame collections (trail ribbons, landings) rise and fall without doing so.
        grown = {k: v for k, v in cache_growth.items() if v[-1] > max(v[:-1])}
        trails = {k: max(s['trails'][k] for s in samples) for k in samples[0]['trails']}
        limits = page.evaluate('() => ({player_track: STYLE.timing.trailPoints, landings: STYLE.screenEffects.landingMaxCount})')
        particles = [s['trails']['particles'] for s in warm]
        soak = dict(config=self.config, simulated_s=SOAK_SECONDS, wall_s=round(wall, 1),
                    accelerated_ticks_per_wall_s=round(total / wall, 1),
                    note='accelerated replay throughput (explicit physics() steps, draw() every 30th tick) is not device FPS',
                    traversals=traversals, restores=dict(count=len(restores), all_exact=all(r['exact'] for r in restores)),
                    samples=samples, warmup_s=SAMPLE_SECONDS,
                    heap=dict(first_after_warmup=warm[0]['heap_used'], last=warm[-1]['heap_used'],
                              growth=round(growth, 4), limit=HEAP_GROWTH_LIMIT),
                    terrain_constant=len(terrain) == 1, cache_series=cache_growth, caches_grown=grown, trails_max=trails,
                    trail_limits=limits, particles_after_warmup=particles,
                    browser_errors=list(self.errors),
                    limits_note='bounds on this host/browser only; no universal mobile FPS is asserted')
        self.evidence.write('soak.json', soak)
        self.assertEqual(self.errors, [])
        self.assertTrue(soak['restores']['all_exact'])
        self.assertEqual(len(terrain), 1, terrain)
        self.assertEqual(grown, {})
        for k, limit in limits.items():
            self.assertLessEqual(trails[k], limit, k)
        self.assertLessEqual(particles[-1], particles[0])
        self.assertLessEqual(growth, HEAP_GROWTH_LIMIT, soak['heap'])

    def test_04_summary(self):
        comparison = json.loads(self.evidence.path('perf/comparison.json').read_text())
        scenes = json.loads(self.evidence.path('perf/scenes.json').read_text())
        soak = json.loads(self.evidence.path('soak.json').read_text())
        now = source_hashes()
        self.assertEqual(now, self.hashes, 'sources changed during the run')
        gated = 'frame_interval_ms_after_warmup'
        ratios = {mode: row[gated]['ratio'] for mode, row in comparison['modes'].items()}
        # physics()/draw() wall time per call: reported for diagnosis, not the frame cost a player sees
        components = {mode: {k: row[k]['ratio'] for k in ('physics_ms', 'draw_ms')} for mode, row in comparison['modes'].items()}
        summary = dict(revision=self.revision, dirty_paths=self.dirty, source_hashes=now,
                       old_mode_p95_ratios=ratios, gated_metric=comparison['gated_metric'], limit=RATIO_LIMIT,
                       old_modes_pass=all(r <= RATIO_LIMIT for r in ratios.values()),
                       diagnostic_component_p95_ratios=components,
                       diagnostic_note='median p95 of per-call physics()/draw() ms, not gated; see review.md',
                       browser_errors=comparison['page_errors'] + len(scenes['browser_errors']) + len(soak['browser_errors']),
                       climb_scenes={k: dict(physics_p95=v['physics_ms']['p95'], draw_p95=v['draw_ms']['p95'],
                                             candidates_max=v['broadphase_candidates_per_tick']['max'],
                                             visible_max=v['visible_elements']['max']) for k, v in scenes['climb'].items()},
                       fall_scenes={k: dict(physics_p95=v['physics_ms']['p95'], draw_p95=v['draw_ms']['p95'],
                                            candidates_max=v['broadphase_candidates_per_tick']['max'], drop=v['drop'])
                                    for k, v in scenes['falls'].items()},
                       soak=dict(heap_growth=soak['heap']['growth'], terrain_constant=soak['terrain_constant'],
                                 caches_grown=soak['caches_grown'], restores_exact=soak['restores']['all_exact']),
                       completion_tick=scenes['completion_tick'])
        self.evidence.write('perf/summary.json', summary)
        self.assertTrue(summary['old_modes_pass'])
        self.assertEqual(summary['browser_errors'], 0)


if __name__ == '__main__':
    unittest.main()
