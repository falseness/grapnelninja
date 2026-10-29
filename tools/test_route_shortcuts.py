"""Whole-route finite shortcut matrix on the shipped level (production input and physics).

Every probe is tools/probe_level_routes.js ROUTE_PROBE on importedMountainLevel() (acquisition
radius 540): the player is placed once at zero speed (or restored from a carried state), then
only document mouse events and physics() run. A probe fails if its first contact or attachment
on a panel later than the source is not the source's successor (a skip). Contacts with earlier
panels (falling back) are not skips. The chute slabs of one no-grapple zone are one route step (TASK-710: the
big zones' rope-free crossing bounces off their slabs in any order): a hit on a later slab of the source's zone, or
on the step after it, is reported as zoneSlab, not a skip; a hit beyond that step (a zone or transfer bypassed)
is still a skip. A highDrop hit before the player first reaches the source is
reported as preArrival (the fixture's approach), not counted as a source skip.

Sources and targets are semantic: fragments are in route order, and for every source the
targets are all panels beyond its successor within TARGET_REACH units (complete-polygon gap),
plus the next two beyond it. Policy classes:
  pumped     pumps (0,1,2,3,5) x fractions (.2,.5,.8), throw at once; and pumps (1,2,3,5) x
             fractions with the throw held until the target is in range (release jump)
  panelEnd   fractions (.02,.98) x pumps (1,3) x both throw modes (releases at the panel ends)
  highDrop   drops 1000/2000 (carried fall speed) x pumps (0,1) x both throw modes
  underside  ceiling sources only: start under the underside at (.2,.5,.8), hold, then 0 or 3
             hand-over-hand re-grabs either way, release, both throw modes
  carried    the state of up to 3 probes that reached a source's successor is restored, and the
             successor runs pumps (0,1) x both throw modes against its own targets
This is a bounded policy matrix: not a proof of shortcut absence and not a full-climb proof.

    ROUTE_SHORTCUTS_EVIDENCE_DIR=DIR python3 -m unittest discover -s tools -p test_route_shortcuts.py -v

writes DIR/shortcuts.json (compact rows). ROUTE_SHORTCUTS_WORKERS sets the browser count (default 4);
ROUTE_SHORTCUTS_SOURCES=P2,R3 limits the sources (semantic ids) for quick iteration;
ROUTE_SHORTCUTS_LEVEL_DIR=DIR probes an unshipped candidate (default artifacts/levels).
ROUTE_SHORTCUTS_WALLS=1 (TASK-780) runs only the safe-space wall cases (fragment['walls'], extra bodies of a panel):
every wall is a source (the probe starts on the wall body, targets = panels beyond the owner's successor within
TARGET_REACH of the wall, plus the next two) and a target (every source before the owner's predecessor within
TARGET_REACH of the wall, or up to three steps before it, aims at the wall body). A hit on a wall counts as a hit on
its owner panel. The carried pass runs as usual. The whole-route source assertion is skipped.
"""
from contextlib import ExitStack
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import check_level_geometry as geometry  # noqa: E402
import convert_extended_mountain_svg as conv  # noqa: E402

LEVELS = Path(os.environ.get('ROUTE_SHORTCUTS_LEVEL_DIR', ROOT / 'artifacts/levels'))
EVIDENCE = os.environ.get('ROUTE_SHORTCUTS_EVIDENCE_DIR')
WORKERS = int(os.environ.get('ROUTE_SHORTCUTS_WORKERS', '4'))
# Optional comma-separated semantic source ids for quick local iteration (the full run sets none).
ONLY = [x for x in os.environ.get('ROUTE_SHORTCUTS_SOURCES', '').split(',') if x]
WALLS = os.environ.get('ROUTE_SHORTCUTS_WALLS') == '1'
TARGET_REACH = 5000
BUDGET = 1800
PUMPS, FRACTIONS = (0, 1, 2, 3, 5), (.2, .5, .8)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def route():
    m = json.loads((LEVELS / 'extended-mountain-measurements.json').read_text())
    fs = m['fragments']
    bodies = [conv.bodies(f) for f in fs]
    pairs = []
    for i in range(len(fs) - 2):
        for j in range(i + 2, len(fs)):
            gap = geometry.union_distance(bodies[i], bodies[j])[0]
            if gap <= TARGET_REACH or j <= i + 3:
                pairs.append(dict(source=fs[i]['id'], target=fs[j]['id'], gap=round(gap, 1)))
    return m, pairs


def wall_pairs(m):
    """TASK-780: pairs with a safe-space wall body as the source or the target."""
    fs = m['fragments']
    bodies = [conv.bodies(f) for f in fs]
    pairs = []
    for k, f in enumerate(fs):
        for w in f.get('walls', []):
            wall, body = [bodies[k][w['body']]], '%s-body%d' % (f['id'], w['body'])
            for j in range(k + 2, len(fs)):
                gap = geometry.union_distance(wall, bodies[j])[0]
                if gap <= TARGET_REACH or j <= k + 3:
                    pairs.append(dict(source=f['id'], target=fs[j]['id'], gap=round(gap, 1), sourceBody=body,
                                      wall=w['semanticId'], role='source'))
            for i in range(k - 1):
                gap = geometry.union_distance(bodies[i], wall)[0]
                if gap <= TARGET_REACH or i >= k - 4:
                    pairs.append(dict(source=fs[i]['id'], target=f['id'], gap=round(gap, 1), targetBody=body,
                                      wall=w['semanticId'], role='target'))
    return pairs


def policies(m, pairs):
    kinds = {f['id']: f['kind'] for f in m['fragments']}
    out = []
    for p in pairs:
        base = dict(source=p['source'], target=p['target'], budget=BUDGET)
        base.update({k: p[k] for k in ('sourceBody', 'targetBody', 'wall') if k in p})
        for pumps in PUMPS:
            for f in FRACTIONS:
                out.append(dict(base, policy='pumped', pumps=pumps, fraction=f))
                if pumps:
                    out.append(dict(base, policy='pumped', pumps=pumps, fraction=f, targetWhenInRange=True))
        for f in (.02, .98):
            for pumps in (1, 3):
                for rng in (False, True):
                    out.append(dict(base, policy='panelEnd', pumps=pumps, fraction=f, targetWhenInRange=rng))
        for drop in (1000, 2000):
            for pumps in (0, 1):
                for rng in (False, True):
                    out.append(dict(base, policy='highDrop', pumps=pumps, fraction=.5, drop=drop, targetWhenInRange=rng))
        if kinds[p['source']] == 'ceiling' and 'sourceBody' not in p:
            for f in FRACTIONS:
                for trav in (None, dict(dir=1, steps=3, stride=300, ticks=40), dict(dir=-1, steps=3, stride=300, ticks=40)):
                    for rng in (False, True):
                        o = dict(base, policy='underside', sourceSurface='underside', pumps=0, fraction=f, drop=120,
                                 holdTicks=60, targetWhenInRange=rng)
                        if trav:
                            o['traverse'] = trav
                        out.append(o)
    return out


ROW_KEYS = ('policy', 'source', 'target', 'fraction', 'pumps', 'drop', 'targetWhenInRange', 'sourceSurface', 'traverse',
            'carriedFrom', 'sourceBody', 'targetBody', 'wall')


def route_steps(m):
    """Route step per fragment: consecutive chute slabs inside the same no-grapple zone share one step."""
    def zone(f):
        if f['kind'] != 'chute':
            return None
        cx, cy = f['x'] + f['width'] / 2, f['y'] + f['height'] / 2
        return next((z['id'] for z in m.get('noGrappleZones', [])
                     if z['x'] <= cx <= z['x'] + z['width'] and z['y'] <= cy <= z['y'] + z['height']), None)
    steps, prev, n = {}, None, -1
    for f in m['fragments']:
        z = zone(f)
        if z is None or z != prev:
            n += 1
        steps[f['id']] = n
        prev = z
    return steps


def classify(r, successor, job, steps=None):
    if not r['hit']:
        return 'noLaterContact'
    pid = r['hit']['id'].split('-')[0]
    if pid == successor:
        return 'successor-' + r['hit']['kind']
    # One zone's slabs are one step: a later slab of the source's zone, or anything in the step after it,
    # does not bypass the zone or a transfer.
    if steps and steps.get(pid, 1 << 30) <= steps[job['source']] + 1:
        return 'zoneSlab-' + r['hit']['kind']
    # A highDrop fixture starts up to 2000 above the source; a hit before the player first reaches
    # the source belongs to that approach, not to the source (e.g. a start above a purple zone, beside
    # its exit ledge). Reported as preArrival, never silently dropped.
    if job['policy'] == 'highDrop' and not r['arrival']:
        return 'preArrival-' + r['hit']['kind']
    return 'SKIP-' + r['hit']['kind']


def worker(args):
    jobs, order, steps = args
    from browser_test_support import start_browser_test, wait_for_boot_run
    level = json.loads((LEVELS / 'extended-mountain.level.json').read_text())
    index = {fid: k for k, fid in enumerate(order)}
    rows = []
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        wait_for_boot_run(page)
        page.add_script_tag(path=str(TOOLS / 'probe_level_routes.js'))
        for job in jobs:
            opts = {k: v for k, v in job.items() if k not in ('policy', 'carriedFrom', 'initialState', 'wall')}
            if job.get('initialState'):
                opts['initialState'] = job['initialState']
            r = page.evaluate('([o, level]) => { const r = ROUTE_PROBE.run({...o, level}); '
                              'return {hit: r.hit, ticks: r.ticks, bounces: r.bounces, arrival: !!r.arrival, '
                              'finalState: r.hit ? r.finalState : null} }', [opts, level])
            successor = order[index[job['source']] + 1]
            outcome = classify(r, successor, job, steps)
            row = {k: job[k] for k in ROW_KEYS if k in job and job[k] not in (None, False)}
            row.update(outcome=outcome, ticks=r['ticks'], bounces=r['bounces'])
            if r['hit']:
                row['hit'] = dict(id=r['hit']['id'], kind=r['hit']['kind'], tick=r['hit']['tick'],
                                  x=round(r['hit']['x'], 1), y=round(r['hit']['y'], 1),
                                  vx=round(r['hit']['vx'], 2), vy=round(r['hit']['vy'], 2))
            state = r['finalState'] if outcome.startswith('successor') else None
            rows.append((row, state))
        rows.append(({'pageErrors': errors}, None))
    return rows


def run_parallel(jobs, order, steps):
    chunks = [jobs[k::WORKERS] for k in range(WORKERS)]
    ctx = multiprocessing.get_context('spawn')
    with ctx.Pool(WORKERS) as pool:
        parts = pool.map(worker, [(c, order, steps) for c in chunks if c])
    rows, errors = [], []
    for part in parts:
        for row, state in part:
            if 'pageErrors' in row:
                errors += row['pageErrors']
            else:
                rows.append((row, state))
    return rows, errors


class RouteShortcutMatrixTests(unittest.TestCase):
    def test_whole_route_policy_matrix(self):
        started = time.time()
        m, pairs = route()
        if WALLS:
            pairs = wall_pairs(m)
        order = [f['id'] for f in m['fragments']]
        sem = {f['id']: f['semanticId'] for f in m['fragments']}
        kinds = {f['id']: f['kind'] for f in m['fragments']}
        if ONLY and not WALLS:  # the filtered sources plus their predecessors (which supply the carried states)
            pairs = [p for p in pairs if sem[p['source']] in ONLY or sem[order[order.index(p['source']) + 1]] in ONLY]
        jobs = policies(m, pairs)
        steps = route_steps(m)
        first, errors = run_parallel(jobs, order, steps)
        # Carried momentum: restore up to 3 successor arrivals per source, then probe from the successor.
        targets = {}
        for p in pairs:
            targets.setdefault(p['source'], []).append((p['target'], {k: p[k] for k in ('targetBody', 'wall') if k in p}))
        carried, seen = [], {}
        # Deterministic carried states: the first three successor arrivals per source in a fixed policy order,
        # independent of how the jobs were split across workers.
        order_key = lambda rs: (order.index(rs[0]['source']), ['pumped', 'panelEnd', 'highDrop', 'underside'].index(rs[0]['policy']),
                                order.index(rs[0]['target']), rs[0].get('pumps', 0), rs[0].get('fraction', 0), rs[0].get('drop', 0),
                                bool(rs[0].get('targetWhenInRange')), json.dumps(rs[0].get('traverse'), sort_keys=True))
        first.sort(key=order_key)
        for row, state in first:
            if state is None:
                continue
            succ = order[order.index(row['source']) + 1]
            if seen.get(row['source'], 0) >= 3 or succ not in targets:
                continue
            seen[row['source']] = seen.get(row['source'], 0) + 1
            tag = '%s/%s/p%s/f%s' % (row['policy'], row['target'], row.get('pumps'), row.get('fraction'))
            for t, extra in targets[succ]:
                for pumps in (0, 1):
                    for rng in (False, True):
                        carried.append(dict(policy='carried', source=succ, target=t, pumps=pumps, fraction=.5,
                                            budget=BUDGET, targetWhenInRange=rng, initialState=state,
                                            carriedFrom='%s %s' % (row['source'], tag), **extra))
        second, errors2 = run_parallel(carried, order, steps) if carried else ([], [])
        rows = [r for r, _ in first] + [r for r, _ in second]
        for r in rows:
            r['sourceSemantic'] = sem[r['source']]
            r['targetSemantic'] = sem[r['target']]
            if 'hit' in r:
                r['hit']['semantic'] = sem.get(r['hit']['id'].split('-')[0], r['hit']['id'])
        skips = [r for r in rows if r['outcome'].startswith('SKIP')]
        by_policy = {}
        for r in rows:
            c = by_policy.setdefault(r['policy'], {})
            c[r['outcome']] = c.get(r['outcome'], 0) + 1
        sources = sorted({r['source'] for r in rows}, key=order.index)
        evidence = dict(
            coverage='Bounded finite policy matrix on the shipped level with production input and physics. '
                     'It is not a proof that no shortcut exists and not a proof that the full climb is possible.',
            level=dict(layoutId=json.loads((LEVELS / 'extended-mountain.level.json').read_text())['layoutId'],
                       levelSha256=sha(LEVELS / 'extended-mountain.level.json'),
                       measurementsSha256=sha(LEVELS / 'extended-mountain-measurements.json'),
                       probeSha256=sha(TOOLS / 'probe_level_routes.js'), testSha256=sha(Path(__file__))),
            physics=dict(tool='tools/probe_level_routes.js ROUTE_PROBE on importedMountainLevel()', acquisitionRadius=540,
                         budgetTicks=BUDGET, entry='zero-speed placement (or restored carried state), then document '
                         'mouse events and production physics() only'),
            skipRule='The first contact or attachment on any panel later in route order than the source must be the '
                     'successor; anything else is a SKIP and fails the test. No pump-count exemptions. Earlier panels '
                     '(falls back down the route) are not skips. The chute slabs of one no-grapple zone are one route step: '
                     'a hit on a later slab of the source zone or on the step after it is zoneSlab (listed in '
                     'zoneSlab), not a skip.',
            zoneSteps=[g for s in sorted(set(steps.values())) for g in [[sem[f] for f in order if steps[f] == s]] if len(g) > 1],
            zoneSlab=[r for r in rows if r['outcome'].startswith('zoneSlab')],
            targetSelection=dict(rule='every panel beyond the successor whose complete-polygon gap to the source is '
                                      '<= %d units, plus the next two beyond the successor' % TARGET_REACH,
                                 pairs=len(pairs), sources=len({p['source'] for p in pairs}),
                                 pairList=[[p['source'], p['target'], p['gap']] for p in pairs],
                                 wallPairs=[[p['wall'], p['role'], sem[p['source']], sem[p['target']], p['gap']]
                                            for p in pairs if 'wall' in p] if WALLS else None),
            policies=dict(
                pumped='pumps %s x fractions %s, throw at the target at once; pumps 1,2,3,5 x fractions with the '
                       'throw held until the target is within 530 (release jump)' % (list(PUMPS), list(FRACTIONS)),
                panelEnd='fractions .02/.98 x pumps 1,3 x both throw modes',
                highDrop='zero-speed drops of 1000/2000 above the source (carried fall speed) x pumps 0,1 x both modes',
                underside='ceiling sources %s: start 120 below the underside at .2/.5/.8, hold 60 ticks, then 0 or 3 '
                          'hand-over-hand re-grabs (stride 300, 40 ticks) right or left, release, both modes'
                          % [sem[f] for f in order if kinds[f] == 'ceiling'],
                carried='restored state of up to 3 probes per source that reached its successor; the successor '
                        'then runs pumps 0,1 x both modes against its own targets'),
            untested=['Closed-loop policies that react to the trajectory (beyond the in-range throw)',
                      'Mid-air re-throws at panels other than the target, and multi-transfer chains longer than one carry',
                      'Pump aims other than the source top (or underside) at the release fraction',
                      'Fractions, drops, pump counts and traverse strides between the listed grid values',
                      'Targets farther than %d units from the source' % TARGET_REACH,
                      'Touch input (mouse events only)'],
            sourceFilter=ONLY or None,
            preArrivalRule='highDrop only: a hit before the first contact with the source is classified preArrival '
                           '(the fixture approach, not a source policy) and listed in preArrival',
            preArrival=[r for r in rows if r['outcome'].startswith('preArrival')],
            counts=dict(cases=len(rows), firstPass=len(first), carried=len(second), skips=len(skips),
                        byPolicy=by_policy, sourcesProbed=len(sources),
                        outcomes={o: sum(1 for r in rows if r['outcome'] == o) for o in sorted({r['outcome'] for r in rows})}),
            pageErrors=errors + errors2, seconds=round(time.time() - started, 1),
            skips=skips, rows=rows)
        if EVIDENCE:
            Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
            (Path(EVIDENCE) / 'shortcuts.json').write_text(json.dumps(evidence, separators=(',', ':')) + '\n')
        self.assertEqual(errors + errors2, [])
        # A source filter without a ceiling source (e.g. the purple NGM neighbourhood) has no underside cases.
        ceiling = any(kinds[p['source']] == 'ceiling' for p in pairs)
        for policy in ('pumped', 'panelEnd', 'highDrop', 'underside', 'carried'):
            if policy == 'underside' and ONLY and not ceiling:
                continue
            self.assertGreater(sum(by_policy.get(policy, {}).values()), 0, policy)
        if not ONLY and not WALLS:
            self.assertEqual(set(sources), set(order[:-2]))
        self.assertEqual(skips, [], json.dumps(skips[:20]))


if __name__ == '__main__':
    unittest.main()
