"""Full-mountain completion proofs: one continuous base-to-summit run driven only by trusted input events."""
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter
from grapple_over_support import state_hash
import test_grapple_over_integration as integration
from test_grapple_over_integration import exit_box


class EvidenceBrowser(integration.LifecycleBrowser):
    """LifecycleBrowser that also collects console errors of every page (observation only)."""

    def __init__(self, browser):
        super().__init__(browser)
        self.console_errors = []

    def new_context(self, **kwargs):
        context = super().new_context(**kwargs)
        context.on('console', lambda m: m.type == 'error' and self.console_errors.append(m.text))
        return context


# In-page exit watcher for the filmstrip: screenshots the production render on the first tick the player is inside
# each encounter exit and at the finish. It reads state only; the frame is drawn with the production draw().
FRAME_JS = '''boxes => { const p = ninja; const hit = [];
    for (const b of boxes) if (!b.seen && p.x >= b.left && p.x <= b.right && p.y >= b.top && p.y <= b.bottom) hit.push(b.id);
    return {hit, completed: floors[0].climbStats.completed} }'''


MOUNTAIN_JS = '''() => ({sections:GRAPPLE_OVER_MOUNTAIN.sections.map(s=>({id:s.id,band:s.band,
        rangeUpgradeZone:s.rangeUpgradeZone||null})),
    encounters:GRAPPLE_OVER_MOUNTAIN.encounters.map(e=>({id:e.id,section:e.section,elements:e.elements,start:e.start,exit:e.exit})),
    shortcuts:GRAPPLE_OVER_MOUNTAIN.shortcuts.map(s=>({id:s.id,from:s.from,to:s.to,status:s.status,optional:s.optional,elements:s.elements})),
    finish:GRAPPLE_OVER_MOUNTAIN.finish,spawn:GRAPPLE_OVER_MOUNTAIN.spawn,movers:GRAPPLE_OVER_MOUNTAIN.geometry.movers,
    elements:GRAPPLE_OVER_MOUNTAIN.geometry.elements.length,
    radius:{base:MODE_DEFINITIONS.grapple_over.acquisitionRadius,upgraded:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius},
    physicsStepMs, cyclesPerTick: typeof cyclesPerTick === 'number' ? cyclesPerTick : null})'''


class Task496Tests(unittest.TestCase):
    """Uninterrupted desktop completion of the final (layout v3) mountain, from a fresh base state to the summit finish.

    One manifest, one recording: the production CLIMB_UI.restart() at the base spawn, then trusted Playwright mouse
    events only, under normal production physics (no initial_setup/initial_snapshot, no mid-run placement, no spawn,
    no gravity/collision/geometry change, no checkpoint). The input sequence is the normal route: the TASK-529 base
    -> S04 exit route (integration.Task529Tests.nominal) up to tick 5787, then the TASK-530 S05 -> S08 route (integration.Task530Tests.UPPER)
    from tick 5787, the tick that TASK-530 used as its labeled fixture. Here that state is reached by playing, not
    restored, so the camera is the continuous one and the upper presses are re-aimed for it (UPPER_CONTINUOUS, found by
    an accelerated probe search; the accepted evidence is this single replay from the base).
    """
    task_id = 'TASK-496'
    JOIN = integration.Task530Tests.FIXTURE_TICK
    PERIOD = 240
    # integration.Task530Tests.UPPER (ticks from JOIN) re-aimed for the continuous camera. TASK-530's fixture restore snaps the camera;
    # here the camera is the one the base run left, 55 CSS px (220 units) lower, and it only follows the player's speed,
    # so every integer-pixel aim grid is offset. Each press is the integer pixel near the archived TASK-530 aim (and its
    # tick within +-2) whose state at the next press best matches the archived TASK-530 trajectory; releases keep their
    # ticks. Found by an accelerated probe search from exact continuous checkpoints (artifacts/TASK-496/tuning/).
    UPPER_CONTINUOUS = [
        (763, 'mousedown', 2548.0, -12456.52449824444),
        (908, 'mouseup', 2548.0, -12456.52449824444),
        (1062, 'mousedown', 3860.0, -10850.047288786416),
        (1123, 'mouseup', 3860.0, -10850.047288786416),
        (1168, 'mousedown', 5263.8424322606725, -9305.453675662922),
        (1408, 'mouseup', 5263.8424322606725, -9305.453675662922),
        (1413, 'mousedown', 4977.908968957398, -9093.581290729557),
        (1533, 'mouseup', 4977.908968957398, -9093.581290729557),
        (2163, 'mousedown', 4704.0, -9112.176622677174),
        (2283, 'mouseup', 4704.0, -9112.176622677174),
        (2358, 'mousedown', 1984.0, -9664.2883249562),
        (2422, 'mouseup', 1984.0, -9664.2883249562),
        (2479, 'mousedown', 1124.0, -10455.288180394948),
        (2652, 'mouseup', 1124.0, -10455.288180394948),
        (2784, 'mousedown', 2640.0, -11505.490023686314),
        (2875, 'mouseup', 2640.0, -11505.490023686314),
        (3465, 'mousedown', 312.0, -11927.530311571234),
        (3703, 'mouseup', 312.0, -11927.530311571234),
        (3749, 'mousedown', 1996.0, -12881.020985597761),
        (3781, 'mouseup', 1996.0, -12881.020985597761),
        (4089, 'mousedown', 1432.0, -12940.0),
        (4159, 'mouseup', 1432.0, -12940.0),
        (4195, 'mousedown', 2348.0, -11956.0),
        (4220, 'mouseup', 2348.0, -11956.0),
        (5042, 'mousedown', 2064.0, -13296.0),
        (5161, 'mouseup', 2064.0, -13296.0),
        (5246, 'mousedown', 436.0, -13332.432767442091),
        (5408, 'mouseup', 436.0, -13332.432767442091),
        (5483, 'mousedown', 4176.0, -13448.0),
        (5530, 'mouseup', 4176.0, -13448.0),
        (5598, 'mousedown', 1397.9293095304356, -13470.248978008756)]
    TICKS = JOIN + integration.Task530Tests.TICKS
    INPUT_EVENTS = ('mousedown', 'mouseup')
    viewport = VIEWPORT

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        import test_grapple_over_sections as sections
        cls.S = sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.browser = EvidenceBrowser(browser)
        page = browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate(MOUNTAIN_JS)
        page.close()
        cls.hashes = hashes()
        for name in ('tools/test_grapple_over_completion.py', 'tools/test_grapple_over_integration.py'):
            cls.hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = dict(browser=browser.version, browser_name='chromium (Playwright, headless)', viewport=VIEWPORT,
            device_scale_factor=1, has_touch=False, input='desktop mouse (page.mouse move/down/up)', hz=60, seed=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'],cwd=ROOT,text=True).splitlines(),
            source_hashes=cls.hashes, level_sha256=cls.hashes['fixedlevel.js'], mountain_sha256=cls.hashes['mountain.js'])
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    # ---- route ----------------------------------------------------------------------------------
    @classmethod
    def route(cls):
        lower = integration.Task529Tests.nominal.__func__(type('Lower', (), dict(S=cls.S, SECTION_STARTS=integration.Task529Tests.SECTION_STARTS)))
        return [r for r in lower if r[0] < cls.JOIN] + [(t+cls.JOIN, e, x, y) for t, e, x, y in cls.UPPER_CONTINUOUS]

    def manifest(self):
        from grapple_over_verify import metadata, validate
        f = self.mountain['finish']
        m = dict(metadata=metadata('base-start'), ticks=self.TICKS,
                 inputs=[dict(tick=t,event=e,world=dict(x=x,y=y)) for t,e,x,y in self.route()],
                 expected_exit=dict(x=[f['left'], f['right']], y=[f['top'], f['bottom']]),
                 required_events=['acquisition','release','bounce'])
        m['metadata']['compact_contacts'] = True
        validate(m)
        self.assertNotIn('initial_setup', m); self.assertNotIn('initial_snapshot', m)
        return m

    def section_starts(self):
        return {**integration.Task529Tests.SECTION_STARTS, **{k: v+self.JOIN for k, v in integration.Task530Tests.SECTION_STARTS.items()}}

    # ---- checks ---------------------------------------------------------------------------------
    def finish(self, trace):
        rows = trace['snapshots']; done = [r['state']['simulation']['stats']['completed'] for r in rows]
        self.assertFalse(done[0])
        flips = [t for t in range(1, len(done)) if done[t] and not done[t-1]]
        self.assertEqual(len(flips), 1, flips)
        tick = flips[0]
        self.assertTrue(all(done[tick:]))
        sim = rows[tick]['state']['simulation']; p = sim['player']
        self.assertTrue(integration.Task530Tests.in_box(p, self.mountain['finish']), p)
        frozen = all(r['state']['simulation']['player'] == p for r in rows[tick:])
        self.assertTrue(frozen)
        return dict(completion_tick=tick, completed_transitions=len(flips), player={k: p[k] for k in ('x','y','speedX','speedY')},
                    finish_region=self.mountain['finish'], frozen_after=frozen, ticks_after=len(rows)-1-tick,
                    elapsed_active_ms=sim['stats']['elapsedActiveMs'], simulation_tick=sim['simulationTick'])

    def continuity(self, m, trace, done):
        sim = [r['state']['simulation'] for r in trace['snapshots']]
        self.assertEqual(m['metadata']['kind'], 'base-start')
        self.assertEqual(trace['metadata']['setupOnlySpawns'], [])
        self.assertIs(trace['metadata']['testOnly'], True)
        p0 = sim[0]['player']; spawn = self.mountain['spawn']
        self.assertEqual((p0['x'],p0['y'],p0['speedX'],p0['speedY']), (spawn['x'],spawn['y'],0,0))
        self.assertEqual(sim[0]['stats']['maxHeight'], 0)
        self.assertEqual(sim[0]['stats']['elapsedActiveMs'], 0)
        self.assertIs(sim[0]['upgrades']['range'], False)
        ticks = [s['simulationTick'] for s in sim]
        # The fixed-step clock advances 8 physics cycles every frame until the finish pauses play inside the completing
        # frame; it never rewinds or restarts, and stays frozen after the finish.
        steps = sorted({b-a for a, b in zip(ticks[:done], ticks[1:done])})
        self.assertEqual(len(steps), 1, steps); self.assertGreater(steps[0], 0)
        final_step = ticks[done]-ticks[done-1]
        self.assertTrue(0 < final_step <= steps[0], final_step)
        self.assertEqual(set(ticks[done:]), {ticks[done]})
        live = sim[:done+1]
        jumps = [max(abs(b['player']['x']-a['player']['x']), abs(b['player']['y']-a['player']['y'])) for a, b in zip(live, live[1:])]
        # No relocation: every per-tick displacement is covered by the recorded speeds (8 physics cycles per tick).
        excess = max(j - 8*max(abs(a['player'][k]) for a in (u, v) for k in ('speedX', 'speedY')) for j, u, v in zip(jumps, live, live[1:]))
        self.assertLess(excess, 1, excess)
        self.assertLess(max(jumps), 40)
        ids = [e['id'] for e in sim[0]['elements']]
        self.assertTrue(all([e['id'] for e in s['elements']] == ids for s in sim))
        # Every mover: small continuous steps and a strict 240-tick period from the level load to the finish (a reset at a
        # section boundary would break it); every other element stays where the level put it (no geometry change).
        index = {k: i for i, k in enumerate(ids)}
        movers, period_error, mover_step = {}, 0, 0
        for v in self.mountain['movers']:
            i, k = index[v['element']], v['axis']
            pos = [s['elements'][i][k] for s in sim[:done]]
            mover_step = max(mover_step, max(abs(b-a) for a, b in zip(pos, pos[1:])))
            period_error = max(period_error, max(abs(pos[t]-pos[t-self.PERIOD]) for t in range(self.PERIOD, len(pos))))
            self.assertAlmostEqual(min(pos), v['min'], delta=1); self.assertAlmostEqual(max(pos), v['max'], delta=1)
            movers[v['element']] = dict(axis=k, min=round(min(pos), 3), max=round(max(pos), 3))
        self.assertEqual(len(movers), len(self.mountain['movers']))
        self.assertLess(mover_step, 2)
        self.assertLess(period_error, 1e-6)
        mover_ids = {v['element'] for v in self.mountain['movers']}
        origin = {e['id']: e for e in sim[0]['elements']}
        moved = sorted({e['id'] for s in sim for e in s['elements'] if e['id'] not in mover_ids and e != origin[e['id']]})
        self.assertEqual(moved, [])
        heights = [s['stats']['maxHeight'] for s in sim]
        self.assertTrue(all(b >= a for a, b in zip(heights, heights[1:])))
        inputs = [e for e in trace['events'] if e['type'] == 'input']
        self.assertEqual(len(inputs), len(m['inputs']))
        self.assertTrue(all(e['trusted'] for e in inputs))
        self.assertEqual({e['event'] for e in inputs}, set(self.INPUT_EVENTS))
        presses = [e for e in inputs if e['event'] == self.INPUT_EVENTS[0]]
        vp = self.viewport
        offscreen = [e['tick'] for e in presses if not (0 < e['client']['x'] < vp['width'] and 0 < e['client']['y'] < vp['height'])]
        self.assertEqual(offscreen, [])
        return dict(base_start=True, kind=m['metadata']['kind'], initial_setup=None, initial_snapshot=None, debug_state_injections=0,
            setup_only_spawns=trace['metadata']['setupOnlySpawns'], mid_run_placements=0, state_resets=0, spliced_attempts=0,
            initial_player=p0, simulation_ticks=[ticks[0], ticks[-1]], simulation_tick_increment=steps, completing_frame_step=final_step,
            clock_frozen_from_tick=done, max_player_step=max(jumps), max_step_beyond_8x_speed=excess,
            stateful_elements=len(ids), geometry_elements=self.mountain['elements'], static_elements_changed=moved, movers=movers, max_mover_step=mover_step, mover_period_ticks=self.PERIOD,
            max_mover_period_error=period_error, max_height_monotonic=True, trusted_inputs=len(inputs), presses=len(presses),
            offscreen_presses=offscreen)

    def upgrade(self, trace, s04_exit):
        sim = [r['state']['simulation'] for r in trace['snapshots']]
        ranges = [s['upgrades']['range'] for s in sim]
        tick = next(t for t, r in enumerate(ranges) if r)
        self.assertFalse(any(ranges[:tick])); self.assertTrue(all(ranges[tick:]))
        self.assertEqual(tick, s04_exit)
        zone = next(s for s in self.mountain['sections'] if s['id'] == 'S05')['rangeUpgradeZone']
        p = sim[tick]['player']
        self.assertTrue(integration.Task530Tests.in_box(p, zone), p)
        reaches = [dict(tick=e['tick'], element=e['after']['rope'][0]['id'], reach=round(e['after']['simulation']['grapple']['traveled'], 1),
                        range_upgraded=ranges[e['tick']]) for e in trace['events'] if e['type'] == 'acquisition']
        self.assertTrue(all(r['reach'] <= self.mountain['radius']['base'] + 1e-6 for r in reaches if not r['range_upgraded']))
        self.assertTrue(all(r['reach'] <= self.mountain['radius']['upgraded'] + 1e-6 for r in reaches))
        return dict(upgrade_tick=tick, s04_04_exit_tick=s04_exit, player={k: p[k] for k in ('x','y')}, s05_range_upgrade_zone=zone,
                    radius_before=self.mountain['radius']['base'], radius_after=self.mountain['radius']['upgraded'],
                    reaches_beyond_base=sum(r['reach'] > self.mountain['radius']['base'] for r in reaches), acquisition_reaches=reaches)

    def shortcuts(self, exits):
        """The two built optional shortcuts skip their section's -02 and -03 encounters; a run takes one only if it reaches the
        section's -04 exit before both skipped exits."""
        out = []
        for s in self.mountain['shortcuts']:
            sec = s['from'][:3]
            skipped = [sec+'-02', sec+'-03']
            taken = not all(exits[k] is not None and exits[k] < exits[s['to']] for k in skipped)
            out.append(dict(id=s['id'], status=s['status'], optional=s['optional'], from_=s['from'], to=s['to'], skipped_encounters=skipped,
                            skipped_exit_ticks=[exits[k] for k in skipped], to_exit_tick=exits[s['to']], taken=taken))
        return out

    def compact(self, trace, keep):
        """Snapshot rows every 30 ticks plus the asserted ticks, every per-tick snapshot hash, the inputs and the mechanics."""
        rows = []
        for r in trace['snapshots']:
            if r['tick'] % 30 and r['tick'] not in keep: continue
            s = r['state']['simulation']; p = s['player']
            rows.append([r['tick'], s['simulationTick'], round(p['x'], 3), round(p['y'], 3), round(p['speedX'], 4), round(p['speedY'], 4),
                         int(s['upgrades']['range']), round(s['stats']['maxHeight'], 2), int(bool(s['grapple'].get('grappled'))),
                         int(s['stats']['completed']), round(s['stats']['elapsedActiveMs'], 3)])
        inputs = [{k: e[k] for k in ('tick', 'event', 'world', 'client', 'trusted')} for e in trace['events'] if e['type'] == 'input']
        return dict(fields=['tick','simulationTick','x','y','speedX','speedY','rangeUpgraded','maxHeight','grappled','completed','elapsedActiveMs'],
                    row_sampling='every 30 ticks plus the encounter exit, upgrade, section start and finish ticks', rows=rows,
                    snapshot_sha256=[r['sha256'] for r in trace['snapshots']], inputs=inputs, mechanics=integration.Task529Tests.mechanics(trace),
                    metadata=trace['metadata'])

    # ---- cases ----------------------------------------------------------------------------------
    def test_01_uninterrupted_completion(self):
        from grapple_over_verify import execute, check_trace
        m = self.manifest()
        starts = self.section_starts()
        self.evidence.write('inputs.json', dict(m, section_starts=starts, join_tick=self.JOIN, upper_route='Task496Tests.UPPER_CONTINUOUS (integration.Task530Tests.UPPER re-aimed for the continuous camera)',
            scope='Fresh base start: production CLIMB_UI.restart() at the base spawn in a new browser context; trusted Playwright '
                  'mouse events only, one continuous input sequence; no initial_setup/initial_snapshot, no spliced attempt, no '
                  'placement, spawn, velocity, mover, gravity, invulnerability or geometry change'))
        # Filmstrip: the production render at the first tick inside each encounter exit and at the finish (display only).
        boxes = [dict(id=e['id'], seen=False, **{k: exit_box(e['exit'])[k] for k in ('left','right','top','bottom')})
                 for e in self.mountain['encounters']]
        frames = []
        def on_frame(page, tick):
            seen = page.evaluate(FRAME_JS, boxes)
            names = seen['hit'] + (['finish'] if seen['completed'] and all(n != 'finish' for _, n in frames) else [])
            for name in names:
                for b in boxes:
                    if b['id'] == name: b['seen'] = True
                page.evaluate('draw()')
                page.screenshot(path=str(self.evidence.path('filmstrip/%05d-%s.jpg' % (tick, name))), type='jpeg', quality=70)
                frames.append((tick, name))
        self.browser.calls.clear(); self.browser.console_errors.clear()
        trace = execute(m, self.browser, self.url, str(self.evidence.path('runs/completion')), clip=True, on_frame=on_frame)
        lifecycle, console_errors = list(self.browser.calls), list(self.browser.console_errors)
        check_trace(m, trace)
        shutil.move(str(self.evidence.path('runs/completion/clip.webm')), str(self.evidence.path('runs/raw-clip.webm')))
        self.browser.calls.clear()
        replay = execute(m, self.browser, self.url, str(self.evidence.path('runs/completion-replay')))
        replay_lifecycle = list(self.browser.calls)
        check_trace(m, replay)
        self.assertEqual(trace, replay)
        recorded, replayed = state_hash(trace), state_hash(replay)
        del replay
        # The audit manifest references the full recorded trace (gzip, sha256 of the JSON bytes); grapple_over_verify audit
        # loads it, replays the manifest from the fresh base and compares every snapshot and event.
        raw = json.dumps(trace, separators=(',', ':')).encode()
        self.evidence.path('manifest-trace.json.gz').write_bytes(gzip.compress(raw, 6, mtime=0))
        self.evidence.write('manifest.json', dict(m, trace_file=dict(name='manifest-trace.json.gz', sha256=hashlib.sha256(raw).hexdigest())))
        del raw
        shutil.rmtree(self.evidence.path('runs/completion')); shutil.rmtree(self.evidence.path('runs/completion-replay'))
        self.analyse(m, trace, recorded, replayed, lifecycle, replay_lifecycle, console_errors, frames)

    def analyse(self, m, trace, recorded, replayed, lifecycle, replay_lifecycle, console_errors, frames):
        """Assertions and compact evidence for one recorded completion (the replay was already compared equal)."""
        starts = self.section_starts()
        players = integration.Task529Tests.players(trace)
        finish = self.finish(trace); done = finish['completion_tick']
        continuity = self.continuity(m, trace, done)
        exits = integration.Task529Tests.first_exit_ticks(self, players, self.mountain['encounters'])
        order = [exits[e['id']] for e in self.mountain['encounters']]
        self.assertEqual(len(order), 32)
        self.assertTrue(all(t is not None for t in order), exits)
        self.assertEqual(order, sorted(order))
        self.assertEqual(exits['S08-04'], done)
        upgrade = self.upgrade(trace, exits['S04-04'])
        mech = integration.Task529Tests.mechanics(trace)
        encounters = []
        for e in self.mountain['encounters']:
            touched = [x for x in mech if x['element'] in e['elements'] and x['type'] in ('acquisition','bounce')]
            self.assertTrue(touched, e['id'])
            encounters.append(dict(id=e['id'], section=e['section'], first_exit_tick=exits[e['id']], first_interaction=touched[0],
                                   interactions=len(touched), acquired=sorted({x['element'] for x in touched if x['type'] == 'acquisition'})))
        shortcuts = self.shortcuts(exits)
        self.assertEqual(len(shortcuts), 2)
        self.assertEqual([s['taken'] for s in shortcuts], [False, False])
        completed = [c for c in lifecycle if c['name'] == 'level_completed']
        self.assertEqual(len(completed), 1)
        self.assertEqual([c['name'] for c in replay_lifecycle if c['name'] == 'level_completed'], ['level_completed'])
        self.assertEqual((completed[0]['x'], completed[0]['y']), (finish['player']['x'], finish['player']['y']))
        self.assertEqual(completed[0]['data']['elapsedActiveMs'], finish['elapsed_active_ms'])
        self.assertEqual(console_errors, [])
        # Active completion time: the in-game clock (physicsStepMs per tick at 60 Hz) at the finish, as the ending shows it.
        self.assertAlmostEqual(finish['elapsed_active_ms'], (done-1)*1000/60 + 1000/60*continuity['completing_frame_step']/continuity['simulation_tick_increment'][0], delta=1)
        sections = sorted({e['section'] for e in self.mountain['encounters']})
        self.assertEqual(len(sections), 8)
        # Filmstrip frames: one per encounter exit plus the finish.
        self.assertEqual(sorted(n for _, n in frames if n != 'finish'), sorted(exits))
        self.assertEqual([t for t, n in frames if n == 'finish'], [done])
        self.assertEqual({n: t for t, n in frames if n != 'finish'}, exits)
        keep = set(order) | {upgrade['upgrade_tick'], done, *starts.values()}
        result = dict(name='uninterrupted desktop completion: fresh base -> summit finish (layout v3, all 32 encounters)', passed=True,
            matching_replay=True, recorded_sha256=recorded, replayed_sha256=replayed, ticks=m['ticks'], full_game_completion=True,
            finish=finish, active_completion_time=dict(elapsed_active_ms=finish['elapsed_active_ms'], seconds=round(finish['elapsed_active_ms']/1000, 3),
                completion_tick=done, note='in-game active clock at 60 Hz (stats.elapsedActiveMs, sent with level_completed)'),
            counts=dict(sections=len(sections), mandatory_encounters=len(self.mountain['encounters']), encounters_exited_in_order=len(order),
                        encounters_interacted=len(encounters), shortcuts_available=len(shortcuts), shortcuts_taken=sum(s['taken'] for s in shortcuts),
                        trusted_inputs=continuity['trusted_inputs'], presses=continuity['presses'], debug_state_injections=0,
                        finish_events=len(completed), level_completed_calls=len(completed), browser_page_errors=0, console_errors=len(console_errors)),
            ending=dict(level_completed_calls=len(completed), recorded_lifecycle=lifecycle, replayed_lifecycle=replay_lifecycle),
            upgrade=upgrade, encounter_exit_ticks=dict(zip([e['id'] for e in self.mountain['encounters']], order)), encounters_in_order=True,
            encounters=encounters, shortcuts=shortcuts, section_starts=starts, continuity=continuity, console_errors=console_errors,
            filmstrip=[dict(tick=t, name=n, file='filmstrip/%05d-%s.jpg' % (t, n)) for t, n in frames], proof=self.proof,
            inputs='inputs.json', manifest='manifest.json', video='completion.webm', trace=self.compact(trace, keep))
        self.evidence.write('trace.json', result)
        print('PASS uninterrupted completion: fresh base start, %d trusted mouse inputs, 0 debug-state injections, 32/32 encounter exits '
              'in order %s, range upgrade at tick %d, %d/2 shortcuts taken, finish at tick %d (%.1f,%.1f), active time %.3f s, exactly one '
              'level_completed, 0 browser errors; replay identical (%s)' % (continuity['trusted_inputs'], order, upgrade['upgrade_tick'],
              sum(s['taken'] for s in shortcuts), done, finish['player']['x'], finish['player']['y'],
              finish['elapsed_active_ms']/1000, recorded[:12]), flush=True)

    def test_02_playback_video(self):
        """completion.webm: the recorded production render, re-timed from the headless wall clock to the 60 Hz game clock."""
        import imageio_ffmpeg
        from PIL import Image
        raw = self.evidence.path('runs/raw-clip.webm')
        self.assertTrue(raw.exists() and raw.stat().st_size > 0, raw)
        result = json.loads(self.evidence.path('trace.json').read_text())
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        probe = lambda p: imageio_ffmpeg.count_frames_and_secs(str(p))
        frames, secs = probe(raw)
        game_secs = result['ticks']/60
        self.assertGreater(secs, game_secs)
        out = self.evidence.path('completion.webm')
        subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', str(raw), '-vf', 'setpts=PTS*%.6f,fps=30' % (game_secs/secs),
                        '-an', '-c:v', 'libvpx-vp9', '-b:v', '1.2M', '-deadline', 'good', '-cpu-used', '4', str(out)], check=True)
        out_frames, out_secs = probe(out)
        self.assertAlmostEqual(out_secs, game_secs, delta=2)
        raw.unlink()
        shutil.rmtree(self.evidence.path('runs'), ignore_errors=True)
        stills = sorted(self.evidence.path('filmstrip').glob('*.jpg'))
        self.assertEqual(len(stills), 33)
        w, h = VIEWPORT['width']//4, VIEWPORT['height']//4
        sheet = Image.new('RGB', (w*6, h*6))
        for i, f in enumerate(stills):
            with Image.open(f) as img: sheet.paste(img.convert('RGB').resize((w, h)), ((i % 6)*w, (i//6)*h))
        sheet.save(self.evidence.path('filmstrip.jpg'), quality=80)
        self.evidence.write('video.json', dict(file='completion.webm', size_bytes=out.stat().st_size, seconds=out_secs, frames=out_frames,
            raw_recording=dict(seconds=secs, frames=frames, note='Playwright records the headless wall clock (each tick draws one frame '
                'and waits 1/60 s plus the headless draw/raster time)'), retime_factor=game_secs/secs, game_seconds=game_secs,
            note='uniform re-time to the 60 Hz game clock; the per-tick wall time varies a little, so video time is approximate, '
                 'use filmstrip/ for exact ticks', filmstrip=[f.name for f in stills], contact_sheet='filmstrip.jpg'))
        print('PASS playback video: completion.webm %.1f s (%d frames, %.1f MB; raw headless recording %.1f s re-timed x%.4f to the %.1f s game '
              'clock), %d filmstrip stills -> filmstrip.jpg' % (out_secs, out_frames, out.stat().st_size/1e6, secs, game_secs/secs, game_secs,
              len(stills)), flush=True)

    def test_03_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: %d runtime, level and harness files match the tested worktree' % len(self.proof['source_hashes']), flush=True)


# ---- TASK-497: touch completion and cross-browser smoke ----------------------------------------
TOUCH_VIEWPORT = {'width': 844, 'height': 390}
CLIMB_KEY = 'grapnelninja.grappleOver'
# Player position, its client point under the current camera, and the camera (display transform only).
VIEW_JS = """() => { const c = GRAPPLE_OVER_TEST.client({x: ninja.x, y: ninja.y});
    return {x: ninja.x, y: ninja.y, cx: c.x, cy: c.y, camera: {x: screen.x, y: screen.y}} }"""
BRIEF_JS = """() => { const s = captureClimbState(); return {mode: version, tick: s.simulationTick, player: s.player,
    grappled: !!s.grapple.grappled, paused: !!menu.gamePaused, run: runInProgress} }"""
# TEST-ONLY setup levels (recorder spawn at tick 0), as in test_grapple_over_tools.test_wrap_and_knockback_events.
FIXTURE_JS = """([kind, far]) => {
    const level = structuredClone(GRAPPLE_OVER_LEVEL);
    const rect = (id, x, y, w, h, role='solid') => ({id, x, y, role, points: [{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
    level.elements = kind === 'wrap' ? [rect('anchor', 1100, 680, 30, 40), rect('corner', 900, 800, 80, 50)]
        : kind === 'knockback' ? [rect('hazard', 400, 700, 600, 100, 'hazard')] : [rect('far', 800 + far, 1400, 40, 40)];
    level.encounters[0].elements = level.elements.map(e => e.id);
    GRAPPLE_OVER_TEST.spawn({level, player: kind === 'knockback' ? {x:700, y:680, speedX:0, speedY:3, hazardCooldownMs:0}
        : {x:800, y:700, speedX:0, speedY: kind === 'wrap' ? 3 : 0}, camera: {x:-450, y:-300}});
}"""
EVENTS_JS = """types => GRAPPLE_OVER_TEST.attempts.at(-1).events.filter(e => types.includes(e.type)).map(e => ({type: e.type, tick: e.tick,
    element: e.after && e.after.rope.length ? e.after.rope.at(-1).id : null,
    rope: [e.before ? e.before.rope.length : null, e.after ? e.after.rope.length : null],
    cooldown: e.after ? e.after.simulation.player.hazardCooldownMs : null, trusted: e.trusted, world: e.world, client: e.client}))"""


def in_view(v, vp):
    return 0 <= v['cx'] <= vp['width'] and 0 <= v['cy'] <= vp['height']


def start_engines(root, add_cleanup, engines):
    """browser_test_support.start_browser_test for several Playwright engines on one server and one Playwright."""
    from functools import partial
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from playwright.sync_api import sync_playwright
    from browser_test_support import OfflineBrowser, QuietHandler, shared_memory_launch_options
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
    add_cleanup(server.server_close)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    add_cleanup(thread.join)
    add_cleanup(server.shutdown)
    playwright = sync_playwright().start()
    add_cleanup(playwright.stop)
    browsers = {}
    for name in engines:
        options = dict(args=['--no-sandbox'], **shared_memory_launch_options()) if name == 'chromium' else {}
        browser = getattr(playwright, name).launch(**options)
        add_cleanup(browser.close)
        browsers[name] = OfflineBrowser(browser)
    return f'http://127.0.0.1:{server.server_port}/', browsers


def smoke(engine, url, browser, route, evidence, check):
    """Desktop (1280x720, mouse/keyboard) smoke scenarios in one engine; check(cond, msg) asserts."""
    from browser_test_support import select_mode
    from grapple_over_support import install_recorder
    from perf_mobile import SEED_SCRIPT
    errors, console = [], []
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    try:
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and console.append(m.text))
        page.add_init_script(SEED_SCRIPT % 1)
        out = {}
        def shot(name, redraw=False):  # the recorder parts hold the game loop, so they draw the current state first
            if redraw: page.evaluate('draw()')
            page.screenshot(path=str(evidence.path('browsers/%s-%s.png' % (engine, name))))
        # startup: index.html boots straight into Grapple Over and the real requestAnimationFrame loop advances the climb.
        page.goto(url); wait_for_boot(page)
        a = page.evaluate(BRIEF_JS); page.wait_for_timeout(800); b = page.evaluate(BRIEF_JS)
        canvas = page.evaluate("""() => { const r = canvas.getBoundingClientRect(); return {css: [r.width, r.height], backing: [canvas.width, canvas.height]} }""")
        check(a['mode'] == 'grapple_over' and a['run'] and not a['paused'], 'startup state %r' % a)
        check(b['tick'] > a['tick'], 'rAF loop does not advance %r %r' % (a, b))
        check(canvas['css'] == [VIEWPORT['width'], VIEWPORT['height']], 'canvas %r' % canvas)
        shot('startup')
        out['startup'] = dict(passed=True, mode=a['mode'], run_in_progress=a['run'], raf_ticks_in_800ms=b['tick'] - a['tick'], canvas=canvas)
        # attachment: the fresh base climb (production CLIMB_UI.restart()), the first normal-route presses as trusted page.mouse events.
        page.evaluate("startGame('grapple_over'); CLIMB_UI.restart()")
        page.wait_for_function('!unTouch'); page.mouse.up()
        install_recorder(page)
        page.evaluate("GRAPPLE_OVER_TEST.begin('attachment')")
        tick = 0
        for t, kind, x, y in route:
            page.evaluate('n => GRAPPLE_OVER_TEST.step(n)', t - tick); tick = t
            p = page.evaluate('w => GRAPPLE_OVER_TEST.client(w)', dict(x=x, y=y))
            page.mouse.move(p['x'], p['y']); (page.mouse.down if kind == 'mousedown' else page.mouse.up)()
        page.evaluate('GRAPPLE_OVER_TEST.step(30)')
        ev = page.evaluate(EVENTS_JS, ['acquisition', 'release', 'input'])
        acq = [e for e in ev if e['type'] == 'acquisition']; inputs = [e for e in ev if e['type'] == 'input']
        check(len(acq) >= 2 and len(inputs) == len(route) and all(e['trusted'] for e in inputs), 'attachment %r' % ev)
        out['attachment'] = dict(passed=True, trusted_inputs=len(inputs), acquisitions=[dict(tick=e['tick'], element=e['element']) for e in acq],
            releases=sum(e['type'] == 'release' for e in ev),
            inputs=[dict(tick=e['tick'], client=e['client'], world=e['world']) for e in inputs])
        page.evaluate("GRAPPLE_OVER_TEST.finish('passed')")
        # pause: the P key; the real game loop is then fed 20 frames of elapsed time and must not advance physics.
        before = page.evaluate(BRIEF_JS)
        page.keyboard.press('p')
        paused = page.evaluate(BRIEF_JS)
        page.evaluate('() => { for (let i = 1; i <= 20; i++) gameLoop(performance.now() + i*20) }')
        frozen = page.evaluate(BRIEF_JS)
        check(paused['paused'] and frozen == paused and paused['player'] == before['player'], 'pause %r %r' % (paused, frozen))
        shot('pause')
        # save/restore: the pause writes the climb; a real reload restores exactly that state, paused.
        page.wait_for_function('([k, t]) => { const v = localStorage.getItem(k); return v && JSON.parse(v).simulationTick === t }',
                               arg=[CLIMB_KEY, paused['tick']])
        saved = page.evaluate('k => JSON.parse(localStorage.getItem(k))', CLIMB_KEY)
        page.reload(); wait_for_boot(page); page.wait_for_function('!unTouch')
        restored = page.evaluate('captureClimbState()')
        rb = page.evaluate(BRIEF_JS)
        check(restored == saved and rb['paused'], 'restore mismatch')
        shot('restored')
        page.keyboard.press('p'); page.wait_for_timeout(500)
        resumed = page.evaluate(BRIEF_JS)
        check(not resumed['paused'] and resumed['tick'] > restored['simulationTick'], 'resume %r' % resumed)
        out['pause'] = dict(passed=True, key='p', frozen_frames=20, state_unchanged=True,
                            resumed_ticks_in_500ms=resumed['tick'] - restored['simulationTick'])
        out['save_restore'] = dict(passed=True, saved_tick=saved['simulationTick'], saved_player={k: saved['player'][k] for k in ('x', 'y')},
                                   reload_restored_equal=True, restored_paused=rb['paused'])
        # three-mode switching through the pause menu: grapple_over -> classic -> bad -> grapple_over; the climb is kept.
        page.keyboard.press('p'); keep = page.evaluate('captureClimbState()')
        modes = []
        for mode in ('classic', 'bad', 'grapple_over'):
            select_mode(page, mode)
            page.wait_for_function('m => version === m', arg=mode)
            page.wait_for_timeout(300)
            modes.append(page.evaluate('() => ({mode: version, paused: !!menu.gamePaused, x: ninja.x, y: ninja.y})'))
            shot('mode-' + mode)
        back = page.evaluate('captureClimbState()')
        check([m['mode'] for m in modes] == ['classic', 'bad', 'grapple_over'], 'modes %r' % modes)
        check(back['player'] == keep['player'] and back['simulationTick'] == keep['simulationTick'], 'climb not kept across modes')
        out['mode_switching'] = dict(passed=True, sequence=modes, climb_kept=True)
        page.evaluate("cancelAnimationFrame(game); if (menu.gamePaused) menu.unPause(); cancelAnimationFrame(game)")
        install_recorder(page)
        # camera ascent/fall: the real mountain, free S06 air with the camera centred there, launched upward; the camera
        # follows the player up and back down, with the player on screen at every 5-tick sample.
        page.evaluate("GRAPPLE_OVER_TEST.begin('camera')")
        page.evaluate("""p => GRAPPLE_OVER_TEST.spawn({player: {x: p.x, y: p.y, speedX: 0, speedY: -6},
            camera: {x: width/2/scale[version] - p.x, y: height/2/scale[version] - p.y}})""", dict(x=4344, y=-8970))
        views = [page.evaluate(VIEW_JS)]
        for _ in range(40):
            page.evaluate('GRAPPLE_OVER_TEST.step(5)'); views.append(page.evaluate(VIEW_JS))
        top = min(range(len(views)), key=lambda i: views[i]['y'])
        rise = views[0]['y'] - views[top]['y']; drop = max(v['y'] for v in views[top:]) - views[top]['y']
        cam_top = max(v['camera']['y'] for v in views[:top+1])
        cam_up = cam_top - views[0]['camera']['y']; cam_down = cam_top - min(v['camera']['y'] for v in views[top:])
        offscreen = [v for v in views if not in_view(v, VIEWPORT)]
        check(rise > 300 and drop > 300 and cam_up > 50 and cam_down > 50 and not offscreen, 'camera %r' % [rise, drop, cam_up, cam_down, offscreen[:2]])
        shot('camera', redraw=True)
        out['camera_ascent_fall'] = dict(passed=True, ticks=200, launch_speed_y=-6, player_rise=round(rise, 1), player_fall=round(drop, 1),
            camera_up=round(cam_up, 1), camera_down=round(cam_down, 1), samples=len(views), player_offscreen_samples=len(offscreen))
        page.evaluate("GRAPPLE_OVER_TEST.finish('passed')")
        # range miss, corner wrap, hazard knockback: production physics on small TEST-ONLY setup levels, trusted mouse aims.
        radius = page.evaluate('MODE_DEFINITIONS.grapple_over.acquisitionRadius')
        page.evaluate("GRAPPLE_OVER_TEST.begin('range-miss')"); page.evaluate(FIXTURE_JS, ['miss', 300])
        p = page.evaluate('GRAPPLE_OVER_TEST.client({x: 1100, y: 700})'); page.mouse.move(p['x'], p['y']); page.mouse.down()
        travel = page.evaluate("""() => { let max = 0, thrown = 0; for (let i = 0; i < 90; i++) { GRAPPLE_OVER_TEST.step(1);
            const g = captureClimbState().grapple; max = Math.max(max, g.traveled || 0); thrown += !!g.throwed } return {max, thrown} }""")
        page.mouse.up()
        ev = page.evaluate(EVENTS_JS, ['acquisition'])
        check(not ev and travel['thrown'] > 0 and 0.9*radius < travel['max'] <= radius + 1e-6, 'miss %r %r' % (ev, travel))
        out['range_miss'] = dict(passed=True, acquisitions=0, max_rope_travel=round(travel['max'], 2), radius=radius,
                                 aim='empty air toward a block 300 units right of the player, 700 below the aim line')
        page.evaluate("GRAPPLE_OVER_TEST.finish('passed')")
        for kind in ('wrap', 'knockback'):
            page.evaluate('k => GRAPPLE_OVER_TEST.begin(k)', kind); page.evaluate(FIXTURE_JS, [kind, 0])
            if kind == 'wrap':
                p = page.evaluate('GRAPPLE_OVER_TEST.client({x: 1100, y: 700})'); page.mouse.move(p['x'], p['y']); page.mouse.down()
            page.evaluate('GRAPPLE_OVER_TEST.step(%d)' % (40 if kind == 'wrap' else 100))
            shot(kind, redraw=True)
            page.evaluate('GRAPPLE_OVER_TEST.step(%d)' % (60 if kind == 'wrap' else 0))
            if kind == 'wrap': page.mouse.up()
            ev = page.evaluate(EVENTS_JS, [kind])
            check(ev, kind)
            if kind == 'wrap':
                check(ev[0]['rope'][0] != ev[0]['rope'][1], 'wrap rope %r' % ev[0])
                out['corner_wrap'] = dict(passed=True, wraps=len(ev), first=dict(tick=ev[0]['tick'], rope_points=ev[0]['rope']))
            else:
                check(ev[0]['cooldown'] > 0, 'knockback %r' % ev[0])
                out['hazard_knockback'] = dict(passed=True, knockbacks=len(ev), first=dict(tick=ev[0]['tick'], cooldown_ms=ev[0]['cooldown']))
            page.evaluate("GRAPPLE_OVER_TEST.finish('passed')")
        alive = page.evaluate("runInProgress && version === 'grapple_over'")
        check(alive, 'hazard ended the run')
        out['hazard_knockback']['nonlethal_run_continues'] = alive
        notice = page.evaluate("!!document.getElementById('climb-save-notice')")
        check(not notice, 'save notice shown')
        check(errors == [] and console == [], 'errors %r %r' % (errors, console))
        return dict(user_agent=page.evaluate('navigator.userAgent'), viewport=VIEWPORT, device_scale_factor=1, input='page.mouse + page.keyboard',
                    scenarios=out, page_errors=errors, console_errors=console)
    finally:
        context.close()


class Task497Tests(unittest.TestCase):
    """Touch completion of the final mountain on Chromium phone landscape, and Firefox/WebKit desktop smoke checks.

    Touch: a fresh base start (production CLIMB_UI.restart()) at 844x390 with has_touch, then trusted CDP touchstart/touchend
    only, through the production document touch handlers. The world aims are TASK-496's normal desktop route as its trusted
    mouse events resolved them (DESKTOP_AIMS, each within one desktop CSS pixel of Task496Tests.route()); every aim is
    converted to a client point through the camera of the dispatch tick (GRAPPLE_OVER_TEST.client), so the phone camera,
    viewport and logical canvas size differ from the desktop run while the world aims stay the same.
    """
    task_id = 'TASK-497'
    JOIN = Task496Tests.JOIN
    PERIOD = Task496Tests.PERIOD
    TICKS = Task496Tests.TICKS
    UPPER_CONTINUOUS = Task496Tests.UPPER_CONTINUOUS
    INPUT_EVENTS = ('touchstart', 'touchend')
    viewport = TOUCH_VIEWPORT
    ENGINES = ('chromium', 'firefox', 'webkit')
    CLIP = True
    # TASK-496's 63 trusted mouse inputs (artifacts/TASK-496/trace.json trace.inputs): tick, resolved world aim.
    DESKTOP_AIMS = [
        (10, 2700, -792), (70, 2700, -792), (255, 4499.40342902858, -1732),
        (334, 4500, -1733.0734705676718), (400, 5248, -2991.7407000249555), (465, 5248, -2991.7927805736053),
        (530, 5948, -3133.008586089358), (615, 5948, -3131.0343867785077), (1500, 6100, -3672.559570499964),
        (1605, 6100, -3673.9835716594735), (1725, 4984, -4668.556038983257), (1785, 4984, -4668.556038983257),
        (1840, 5540, -4708.556038983257), (1950, 5540, -4707.526544322811), (2055, 6060, -5615.76561685546),
        (2117, 6060, -5617.312120860463), (3250, 5520, -5753.610525605578), (3365, 5520, -5750.837671199681),
        (3511, 6200, -6940.4271991519945), (3556, 6200, -6943.708671386393), (3645, 6428, -7490.665618285174),
        (3730, 6428, -7488.098792027549), (3870, 5460, -7952.5673684617905), (3940, 5460, -7953.470237996065),
        (4550, 5232, -7861.470237996065), (4915, 5232, -7861.470237996065), (5031, 2342.665436415109, -8005.470237996065),
        (5101, 2344.5950077136604, -8007.15876172278), (5360, 820, -10903.108237893179), (5450, 820, -10905.770088680845),
        (5585, 820, -12003.83955767875), (5650, 820, -12005.129167609364), (6550, 2548, -12456.52449824444),
        (6695, 2548, -12459.179649776075), (6849, 3860, -10853.25350579851), (6910, 3856.7566897163065, -10850.659370690882),
        (6955, 5263.842432567955, -9307.853722194615), (7195, 5261.9089687031765, -9305.581290728634), (7200, 4976.258226915403, -9093.581290728634),
        (7320, 4976, -9095.156859527946), (7950, 4704, -9112.176622699084), (8070, 4704, -9115.539249906122),
        (8145, 1982.6364031003357, -9664.288324746038), (8209, 1984, -9666.859688261524), (8266, 1124, -10455.28818042699),
        (8439, 1124, -10456.576054251169), (8571, 2640, -11508.643200977016), (8662, 2640, -11507.530311815177),
        (9252, 312, -11927.530311815177), (9490, 312, -11929.35734394555), (9536, 1996, -12884.93627574085),
        (9568, 1996, -12883.128886115293), (9876, 1432, -12940), (9946, 1432, -12940),
        (9982, 2348, -11956), (10007, 2348, -11956), (10829, 2064, -13296),
        (10948, 2064, -13296), (11033, 436, -13332.432708036475), (11195, 436, -13333.400743195207),
        (11270, 4176, -13448), (11317, 4172.122755139362, -13451.346121948422), (11385, 1397.9293089841597, -13472.059690907094),
    ]

    route = classmethod(Task496Tests.__dict__['route'].__func__)
    section_starts = Task496Tests.section_starts
    finish = Task496Tests.finish
    continuity = Task496Tests.continuity
    upgrade = Task496Tests.upgrade
    shortcuts = Task496Tests.shortcuts
    compact = Task496Tests.compact

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        import test_grapple_over_sections as sections
        cls.S = sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, cls.browsers = start_engines(ROOT, cls.addClassCleanup, cls.ENGINES)
        cls.browser = EvidenceBrowser(cls.browsers['chromium'])
        page = cls.browsers['chromium'].new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate(MOUNTAIN_JS)
        page.close()
        cls.hashes = hashes()
        for name in ('tools/test_grapple_over_completion.py', 'tools/test_grapple_over_integration.py'):
            cls.hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        cls.proof = dict(touch=dict(browser=cls.browsers['chromium'].version, browser_name='chromium (Playwright, headless)',
                viewport=TOUCH_VIEWPORT, device_scale_factor=1, has_touch=True, orientation='landscape',
                input='CDP Input.dispatchTouchEvent touchStart/touchEnd (trusted), production document touch handlers'),
            engines={n: dict(version=b.version) for n, b in cls.browsers.items()}, hz=60, seed=1,
            revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_paths=subprocess.check_output(['git','status','--porcelain','--','.',':!artifacts'],cwd=ROOT,text=True).splitlines(),
            source_hashes=cls.hashes, level_sha256=cls.hashes['fixedlevel.js'], mountain_sha256=cls.hashes['mountain.js'])
        cls.evidence.log('CONFIG '+json.dumps(cls.proof, sort_keys=True))

    def manifest(self):
        from grapple_over_verify import metadata, validate
        f = self.mountain['finish']
        route = self.route()
        # Same route as TASK-496: same ticks and events, every aim within one desktop CSS pixel (4 world units) of the route.
        self.assertEqual(len(route), len(self.DESKTOP_AIMS))
        for (t, e, x, y), (at, ax, ay) in zip(route, self.DESKTOP_AIMS):
            self.assertEqual(t, at)
            if e == 'mousedown': self.assertLessEqual(max(abs(x-ax), abs(y-ay)), 4.000001, t)
        md = metadata('base-start'); md['viewport'] = TOUCH_VIEWPORT; md['compact_contacts'] = True
        m = dict(metadata=md, ticks=self.TICKS,
                 inputs=[dict(tick=t, event='touchstart' if e == 'mousedown' else 'touchend', world=dict(x=ax, y=ay))
                         for (t, e, _, _), (_, ax, ay) in zip(route, self.DESKTOP_AIMS)],
                 expected_exit=dict(x=[f['left'], f['right']], y=[f['top'], f['bottom']]),
                 required_events=['acquisition','release','bounce'])
        validate(m)
        self.assertNotIn('initial_setup', m); self.assertNotIn('initial_snapshot', m)
        return m

    def test_01_touch_completion(self):
        from grapple_over_verify import execute, check_trace
        m = self.manifest()
        starts = self.section_starts()
        presses = {e['tick'] for e in m['inputs']}
        stills = {max(v, 1): k for k, v in starts.items()}  # on_frame first runs after tick 1
        views, aims, frames = {}, {}, []
        def on_frame(page, tick):
            # Display only: camera framing every 30 ticks and at inputs; the dispatch transform of the next input.
            if tick % 30 == 0 or tick in presses:
                views[tick] = page.evaluate(VIEW_JS)
            if tick in presses:
                w = next(e['world'] for e in m['inputs'] if e['tick'] == tick)
                aims[tick] = page.evaluate('w => ({client: GRAPPLE_OVER_TEST.client(w), camera: {x: screen.x, y: screen.y}, scale: scale[version]})', w)
            done = page.evaluate('floors[0].climbStats.completed')
            if tick in stills or (done and not any(n == 'finish' for _, n in frames)):
                name = 'finish' if done else stills[tick]
                page.evaluate('draw()')
                page.screenshot(path=str(self.evidence.path('touch-frames/%05d-%s.jpg' % (tick, name))), type='jpeg', quality=75)
                frames.append((tick, name))
        self.browser.calls.clear(); self.browser.console_errors.clear()
        trace = execute(m, self.browser, self.url, str(self.evidence.path('runs/touch')), clip=self.CLIP, on_frame=on_frame)
        lifecycle, console_errors = list(self.browser.calls), list(self.browser.console_errors)
        check_trace(m, trace)
        if self.CLIP: shutil.move(str(self.evidence.path('runs/touch/clip.webm')), str(self.evidence.path('runs/raw-touch-clip.webm')))
        raw = json.dumps(trace, separators=(',', ':')).encode()
        self.evidence.path('touch-manifest-trace.json.gz').write_bytes(gzip.compress(raw, 6, mtime=0))
        self.evidence.write('touch-manifest.json', dict(m, trace_file=dict(name='touch-manifest-trace.json.gz', sha256=hashlib.sha256(raw).hexdigest())))
        del raw
        shutil.rmtree(self.evidence.path('runs/touch'))
        recorded = state_hash(trace)
        players = integration.Task529Tests.players(trace)
        finish = self.finish(trace); done = finish['completion_tick']
        continuity = self.continuity(m, trace, done)
        exits = integration.Task529Tests.first_exit_ticks(self, players, self.mountain['encounters'])
        order = [exits[e['id']] for e in self.mountain['encounters']]
        self.assertEqual(len(order), 32)
        self.assertTrue(all(t is not None for t in order), exits)
        self.assertEqual(order, sorted(order))
        self.assertEqual(exits['S08-04'], done)
        upgrade = self.upgrade(trace, exits['S04-04'])
        mech = integration.Task529Tests.mechanics(trace)
        for e in self.mountain['encounters']:
            self.assertTrue([x for x in mech if x['element'] in e['elements'] and x['type'] in ('acquisition','bounce')], e['id'])
        shortcuts = self.shortcuts(exits)
        self.assertEqual([s['taken'] for s in shortcuts], [False, False])
        completed = [c for c in lifecycle if c['name'] == 'level_completed']
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['data']['elapsedActiveMs'], finish['elapsed_active_ms'])
        self.assertEqual(console_errors, [])
        # Touch inputs: trusted touchstart/touchend events dispatched at the client point of the dispatch-tick camera.
        inputs = [e for e in trace['events'] if e['type'] == 'input']
        rows, max_err = [], 0
        for e, want in zip(inputs, m['inputs']):
            self.assertEqual((e['tick'], e['event']), (want['tick'], want['event']))
            self.assertTrue(e['trusted'])
            row = dict(tick=e['tick'], event=e['event'], world_aim=want['world'], resolved_world=e['world'], client=e['client'])
            if e['event'] == 'touchstart':
                a = aims[e['tick']]
                self.assertAlmostEqual(e['client']['x'], a['client']['x'], delta=0.01); self.assertAlmostEqual(e['client']['y'], a['client']['y'], delta=0.01)
                err = max(abs(e['world'][k]-want['world'][k]) for k in 'xy'); max_err = max(max_err, err)
                row.update(camera=a['camera'], camera_scale=a['scale'], dispatch_client=a['client'], aim_error=err)
            rows.append(row)
        self.assertLess(max_err, 0.01)
        # Camera framing: the player stays on screen at every sample up to the finish.
        live = {t: v for t, v in views.items() if t <= done}
        off = sorted(t for t, v in live.items() if not in_view(v, TOUCH_VIEWPORT))
        self.assertEqual(off, [])
        cams = [v['camera']['y'] for t, v in sorted(live.items())]
        self.assertTrue(len(frames) == len(stills) + 1 and frames[-1] == (done, 'finish'), frames)
        self.evidence.write('touch-inputs.json', dict(viewport=TOUCH_VIEWPORT, device_scale_factor=1, has_touch=True,
            transform='client = canvasCoordsToViewportCoords((world + screen) * scale[version]) at the dispatch tick (GRAPPLE_OVER_TEST.client)',
            aim_source='Task497Tests.DESKTOP_AIMS = TASK-496 trusted mouse inputs (resolved world aims)', touchstarts=continuity['presses'],
            touchends=len(rows)-continuity['presses'], max_touchstart_world_error=max_err, offscreen_touchstarts=continuity['offscreen_presses'], inputs=rows))
        keep = set(order) | {upgrade['upgrade_tick'], done, *starts.values()}
        result = dict(name='touch completion: fresh base -> summit finish at 844x390 (layout v3, all 32 encounters)', passed=True,
            recorded_sha256=recorded, ticks=m['ticks'], full_game_completion=True, finish=finish,
            counts=dict(sections=8, mandatory_encounters=32, encounters_exited_in_order=len(order), shortcuts_taken=sum(s['taken'] for s in shortcuts),
                        trusted_touch_inputs=len(inputs), touchstarts=continuity['presses'], mouse_inputs=sum(e['event'].startswith('mouse') for e in inputs),
                        debug_state_injections=0, finish_events=len(completed), level_completed_calls=len(completed),
                        browser_page_errors=0, console_errors=len(console_errors)),
            ending=dict(recorded_lifecycle=lifecycle), upgrade=upgrade, encounter_exit_ticks=exits, encounters_in_order=True,
            shortcuts=shortcuts, section_starts=starts, continuity=continuity,
            camera_framing=dict(samples=len(live), sampling='every 30 ticks and every input tick, up to the finish', player_offscreen_samples=off,
                                camera_y_range=[round(min(cams), 1), round(max(cams), 1)]),
            frames=[dict(tick=t, name=n, file='touch-frames/%05d-%s.jpg' % (t, n)) for t, n in frames], proof=self.proof,
            manifest='touch-manifest.json', inputs='touch-inputs.json', video='touch-completion.webm', trace=self.compact(trace, keep))
        self.evidence.write('touch-trace.json', result)
        print('PASS touch completion: 844x390 has_touch, fresh base start, %d trusted touch inputs (%d touchstart, 0 mouse), 0 debug-state '
              'injections, 32/32 encounter exits in order, range upgrade at tick %d, %d/2 shortcuts, finish at tick %d (%.1f,%.1f), active %.3f s, '
              'one level_completed, player on screen at %d/%d camera samples, max aim error %.2g, 0 browser errors (%s)' % (len(inputs),
              continuity['presses'], upgrade['upgrade_tick'], sum(s['taken'] for s in shortcuts), done, finish['player']['x'], finish['player']['y'],
              finish['elapsed_active_ms']/1000, len(live), len(live), max_err, recorded[:12]), flush=True)

    def test_02_touch_video(self):
        """touch-completion.webm: the recorded production render, re-timed from the headless wall clock to the 60 Hz game clock."""
        import imageio_ffmpeg
        from PIL import Image
        raw = self.evidence.path('runs/raw-touch-clip.webm')
        self.assertTrue(raw.exists() and raw.stat().st_size > 0, raw)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        frames, secs = imageio_ffmpeg.count_frames_and_secs(str(raw))
        game_secs = self.TICKS/60
        out = self.evidence.path('touch-completion.webm')
        subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', str(raw), '-vf', 'setpts=PTS*%.6f,fps=30' % (game_secs/secs),
                        '-an', '-c:v', 'libvpx-vp9', '-b:v', '0.8M', '-deadline', 'good', '-cpu-used', '4', str(out)], check=True)
        out_frames, out_secs = imageio_ffmpeg.count_frames_and_secs(str(out))
        self.assertAlmostEqual(out_secs, game_secs, delta=2)
        raw.unlink()
        shutil.rmtree(self.evidence.path('runs'), ignore_errors=True)
        stills = sorted(self.evidence.path('touch-frames').glob('*.jpg'))
        self.assertEqual(len(stills), len(self.section_starts()) + 1)
        w, h = TOUCH_VIEWPORT['width']//2, TOUCH_VIEWPORT['height']//2
        sheet = Image.new('RGB', (w*5, h*2))
        for i, f in enumerate(stills):
            with Image.open(f) as img: sheet.paste(img.convert('RGB').resize((w, h)), ((i % 5)*w, (i//5)*h))
        sheet.save(self.evidence.path('touch-frames.jpg'), quality=80)
        self.evidence.write('touch-video.json', dict(file='touch-completion.webm', size_bytes=out.stat().st_size, seconds=out_secs, frames=out_frames,
            raw_recording=dict(seconds=secs, frames=frames), retime_factor=game_secs/secs, game_seconds=game_secs, viewport=TOUCH_VIEWPORT,
            stills=[f.name for f in stills], contact_sheet='touch-frames.jpg'))
        print('PASS touch video: touch-completion.webm %.1f s (%d frames, %.1f MB, 844x390; raw %.1f s re-timed x%.4f), %d stills -> touch-frames.jpg'
              % (out_secs, out_frames, out.stat().st_size/1e6, secs, game_secs/secs, len(stills)), flush=True)

    def test_03_cross_browser_smoke(self):
        """Firefox and WebKit (and Chromium as the reference) desktop smoke: startup, attachment, range miss, corner wrap,
        hazard knockback, camera ascent/fall, save/restore, pause and three-mode switching, with zero page/console errors."""
        route = [r for r in self.route() if r[0] < 340]  # the first two normal-route shots (S01-hoist, then the yard)
        result = {}
        for engine in self.ENGINES:
            with self.subTest(engine=engine):
                failures = []
                def check(cond, msg):
                    if not cond: failures.append(msg)
                    self.assertTrue(cond, '%s: %s' % (engine, msg))
                r = smoke(engine, self.url, self.browsers[engine], route, self.evidence, check)
                result[engine] = dict(engine=engine, version=self.browsers[engine].version, **r)
                print('PASS %s %s smoke: %s; %d page errors, %d console errors' % (engine, result[engine]['version'],
                      ', '.join('%s ok' % k for k, v in r['scenarios'].items() if v['passed']), len(r['page_errors']), len(r['console_errors'])), flush=True)
        self.assertEqual(sorted(result), sorted(self.ENGINES))
        names = ['startup', 'attachment', 'range_miss', 'corner_wrap', 'hazard_knockback', 'camera_ascent_fall', 'save_restore', 'pause', 'mode_switching']
        for engine, r in result.items():
            self.assertEqual(sorted(r['scenarios']), sorted(names), engine)
            self.assertTrue(all(v['passed'] for v in r['scenarios'].values()), engine)
            self.assertEqual((r['page_errors'], r['console_errors']), ([], []), engine)
        self.evidence.write('browsers.json', dict(engines=result, scenarios=names, viewport=VIEWPORT, revision=self.proof['revision'],
            browser_defects_found=[], note='Each engine runs the same trusted-input script; mouse coordinates are integer CSS pixels per '
                'engine, so the second route shot may resolve one pixel apart and acquire a neighbouring S01 anchor (recorded in '
                'attachment.inputs/acquisitions); range miss, wrap, knockback and camera use TEST-ONLY setup levels/spawns.'))

    def test_04_source_hashes(self):
        for path, digest in self.proof['source_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), digest, path)
        print('PASS source hashes: %d runtime, level and harness files match the tested worktree' % len(self.proof['source_hashes']), flush=True)


if __name__ == '__main__':
    unittest.main()
