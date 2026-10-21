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

    @classmethod
    def setUpClass(cls):
        from grapple_over_verify import hashes
        import test_grapple_over_sections as sections
        cls.S = sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.browser = EvidenceBrowser(browser)
        page = browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate('''() => ({sections:GRAPPLE_OVER_MOUNTAIN.sections.map(s=>({id:s.id,band:s.band,
                rangeUpgradeZone:s.rangeUpgradeZone||null})),
            encounters:GRAPPLE_OVER_MOUNTAIN.encounters.map(e=>({id:e.id,section:e.section,elements:e.elements,start:e.start,exit:e.exit})),
            shortcuts:GRAPPLE_OVER_MOUNTAIN.shortcuts.map(s=>({id:s.id,from:s.from,to:s.to,status:s.status,optional:s.optional,elements:s.elements})),
            finish:GRAPPLE_OVER_MOUNTAIN.finish,spawn:GRAPPLE_OVER_MOUNTAIN.spawn,movers:GRAPPLE_OVER_MOUNTAIN.geometry.movers,
            elements:GRAPPLE_OVER_MOUNTAIN.geometry.elements.length,
            radius:{base:MODE_DEFINITIONS.grapple_over.acquisitionRadius,upgraded:MODE_DEFINITIONS.grapple_over.upgradedAcquisitionRadius},
            physicsStepMs, cyclesPerTick: typeof cyclesPerTick === 'number' ? cyclesPerTick : null})''')
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
        self.assertEqual({e['event'] for e in inputs}, {'mousedown', 'mouseup'})
        presses = [e for e in inputs if e['event'] == 'mousedown']
        offscreen = [e['tick'] for e in presses if not (0 < e['client']['x'] < VIEWPORT['width'] and 0 < e['client']['y'] < VIEWPORT['height'])]
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


if __name__ == '__main__':
    unittest.main()
