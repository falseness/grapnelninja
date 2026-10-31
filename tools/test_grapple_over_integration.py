"""Continuous mountain proofs from the base, driven only by trusted input events.

The layout-v3 joined-route classes (Task489..492, Task529..531) are retired (artifacts/TASK-835, artifacts/TASK-836);
the module keeps exit_box, LifecycleBrowser and the v3 route data that test_grapple_over_completion/audit import.
"""
import json
import unittest


class LifecycleBrowser:
    """Pass-through browser whose pages log PLATFORM lifecycle calls to the console.

    The wrapper only observes: it calls the original sendLifecycle unchanged.
    """
    SCRIPT = '''addEventListener('DOMContentLoaded', () => { const p = PLATFORM, send = p.sendLifecycle;
        p.sendLifecycle = function(name, data) {
            console.log('GRAPPLE_LIFECYCLE ' + JSON.stringify({name, data, x: typeof ninja === 'undefined' ? null : ninja.x, y: typeof ninja === 'undefined' ? null : ninja.y}));
            return send.apply(this, arguments) } })'''

    def __init__(self, browser):
        self._browser, self.calls = browser, []

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)
        context.add_init_script(self.SCRIPT)
        context.on('console', lambda m: m.text.startswith('GRAPPLE_LIFECYCLE ')
                   and self.calls.append(json.loads(m.text.split(' ', 1)[1])))
        return context


def exit_box(exit):
    # S05-01..03 author their exits as a rest point plus a width; the player stops at x.
    if 'left' in exit:
        return exit
    return dict(left=exit['x']-.01, right=exit['x']+exit['width'], top=exit['y']-1.2, bottom=exit['y']+10.8)


class Task529Tests(unittest.TestCase):
    """Retired by TASK-836 (artifacts/TASK-836/retired.md): layout-v3 lower four sections joined (base -> S01..S04 exit,
    plus a fall and rejoin) as one base-start recording of the v3 nominal routes from the v3 base spawn (2160, 0).

    Normal Grapple Over starts load the imported replacement level since ba5ca11 TASK-650 (spawn 500, -30) and the
    camera is 0.25 since c2a6743 TASK-688, so the recorded world aims are off-screen ('mandatory target outside
    viewport'), also on ?grappleFixture=legacy-v3 (TASK-834/835). The class keeps the v3 route data and trace helpers
    that tools/test_grapple_over_completion.py reads (SECTION_STARTS, nominal, players, first_exit_ticks, mechanics).
    """
    task_id = 'TASK-529'
    # Segment starts (ticks) of the v3 lower route: S01 at 0, S02 at 1495, S03 at 3245, S04 at 4545.
    SECTION_STARTS = dict(S01=0, S02=1495, S03=3245, S04=4545)

    @classmethod
    def nominal(cls):
        D, C = cls.S.DeflectorV3Checks, cls.S.DeflectorV3CompleteChecks
        # D.S03_V3_ROUTE is the TASK-548 S01 route, the TASK-551 S02 route from 1495 and the
        # TASK-554/555 S03 route from 3245; the TASK-515/516 S04 route follows from 4545.
        return D.S03_V3_ROUTE + [(t+cls.SECTION_STARTS['S04'], e, x, y) for t, e, x, y in C.S04_ROUTE_V3]

    @staticmethod
    def players(trace):
        return [r['state']['simulation']['player'] for r in trace['snapshots']]

    @staticmethod
    def inside(p, bounds):
        return all(lo <= p[k] <= hi for k, (lo, hi) in bounds.items())

    def first_exit_ticks(self, players, encounters=None, after=0):
        out = {}
        for e in encounters or self.mountain['encounters'][:16]:
            b = exit_box(e['exit'])
            out[e['id']] = next((t for t in range(after, len(players)) if b['left'] <= players[t]['x'] <= b['right']
                                 and b['top'] <= players[t]['y'] <= b['bottom']), None)
        return out

    @staticmethod
    def mechanics(trace):
        out = []
        for e in trace['events']:
            if e['type'] in ('acquisition', 'release'):
                rope = e['after']['rope'] if e['type'] == 'acquisition' else e['before']['rope']
                element = rope[0]['id'] if rope else None
            elif e['type'] == 'bounce':
                element = e['contact']['elementId']
            else:
                continue
            p = (e['after'] if e['type'] != 'bounce' else e['before'])['simulation']['player']
            out.append(dict(tick=e['tick'], type=e['type'], element=element, player={k: p[k] for k in ('x', 'y', 'speedX', 'speedY')}))
        return out


class Task530Tests(unittest.TestCase):
    """Retired by TASK-836 (artifacts/TASK-836/retired.md): layout-v3 upper four sections joined (v3 S04-exit fixture ->
    S05..S08 summit finish). Its setUpClass built the fixture by replaying the v3 lower routes (Task529Tests.nominal) from
    the v3 base spawn: off-screen aims since ba5ca11 TASK-650 / c2a6743 TASK-688, so none of its cases can start.
    The class keeps the v3 upper route data that tools/test_grapple_over_completion.py reads (FIXTURE_TICK, SECTION_STARTS,
    UPPER, TICKS, in_box).
    """
    task_id = 'TASK-530'
    FIXTURE_TICK = 5787
    # Section starts (ticks from the fixture): S05 at the isolated S04 exit pose tick (6545-5787), then the isolated
    # chain spacing (S05 1400, S06 1300, S07 1400 ticks).
    SECTION_STARTS = dict(S05=758, S06=2158, S07=3458, S08=4858)
    PERIOD = 240
    # The v3 section routes (TASK-517/518 S05, TASK-520/521 S06, TASK-523/524 S07, TASK-526/527 S08), ticks relative to each
    # section start, re-aimed to the continuous camera: every press is the integer pixel nearest the isolated aim that keeps
    # the run on the isolated chain (aim moved 2.1..5.5 world units, at most 1.4 px). Retimed: S06-02 pressed 4 ticks early
    # and released 6 late (200/264, was 204/258), S06-03 pressed at 321 (319), S06-04 at 627/717 (628/718), S07-02..04 one
    # tick later (291/323, 631/701, 737/762). S08-04 is held until the finish, as in TASK-527.
    S05_UPPER = [(5,'mousedown',2544.0,-12453.554618784061),(150,'mouseup',2544.0,-12453.554618784061),
                 (304,'mousedown',3860.0,-10850.298590759949),(365,'mouseup',3860.0,-10850.298590759949),
                 (410,'mousedown',5263.585711890056,-9305.585082877235),(650,'mouseup',5263.585711890056,-9305.585082877235),
                 (655,'mousedown',4978.056484272573,-9093.539714470548),(775,'mouseup',4978.056484272573,-9093.539714470548)]
    S06_UPPER = [(5,'mousedown',4704.0,-9112.199723935715),(125,'mouseup',4704.0,-9112.199723935715),
                 (200,'mousedown',1988.0,-9660.294050566703),(264,'mouseup',1988.0,-9660.294050566703),
                 (321,'mousedown',1124.0,-10450.410099734427),(494,'mouseup',1124.0,-10450.410099734427),
                 (627,'mousedown',2644.0,-11503.996354718722),(717,'mouseup',2644.0,-11503.996354718722)]
    S07_UPPER = [(5,'mousedown',308.0,-11930.140890103135),(245,'mouseup',308.0,-11930.140890103135),
                 (291,'mousedown',1992.0,-12880.388956174498),(323,'mouseup',1992.0,-12880.388956174498),
                 (631,'mousedown',1432.0,-12944.0),(701,'mouseup',1432.0,-12944.0),
                 (737,'mousedown',2348.0,-11960.0),(762,'mouseup',2348.0,-11960.0)]
    S08_UPPER = [(185,'mousedown',2060.0,-13296.0),(303,'mouseup',2060.0,-13296.0),
                 (390,'mousedown',432.0,-13330.616848123203),(550,'mouseup',432.0,-13330.616848123203),
                 (627,'mousedown',4180.0,-13444.0),(672,'mouseup',4180.0,-13444.0),
                 (740,'mousedown',1398.3078238591097,-13469.42904665146)]
    UPPER = (lambda starts, plans: [(t+starts[k], e, x, y) for k, plan in plans for t, e, x, y in plan])(
        SECTION_STARTS, (('S05',S05_UPPER),('S06',S06_UPPER),('S07',S07_UPPER),('S08',S08_UPPER)))
    # The finish comes at 4858+809 (as in TASK-527's S08-full); the run continues 53 ticks into the frozen ending.
    TICKS = 5720

    @staticmethod
    def in_box(p, b, pad=0):
        return b['left']-pad <= p['x'] <= b['right']+pad and b['top']-pad <= p['y'] <= b['bottom']+pad


class Task489Tests(unittest.TestCase):
    """Retired by TASK-835 (artifacts/TASK-835/retired.md): the TASK-533 layout-v3 lower-join alias of Task529Tests.

    Its cases replayed the v3 S01..S04 nominal routes from the v3 base spawn (2160, 0). Normal Grapple Over starts load the
    imported replacement level since ba5ca11 TASK-650 (spawn 500, -30) and the camera is 0.25 since c2a6743 TASK-688, so the
    recorded world aims are off-screen ('mandatory target outside viewport'), also on ?grappleFixture=legacy-v3 (TASK-834).
    """
    task_id = 'TASK-489'


class Task490Tests(unittest.TestCase):
    """Retired by TASK-835 (artifacts/TASK-835/retired.md): the TASK-533 layout-v3 upper-join alias of Task530Tests.

    Its setUpClass built the v3 S04-exit fixture by replaying the v3 lower routes (off-screen aims since ba5ca11 TASK-650 /
    c2a6743 TASK-688), so none of its cases can start.
    """
    task_id = 'TASK-490'


class Task531Tests(unittest.TestCase):
    """Retired by TASK-836 (artifacts/TASK-836/retired.md): layout-v3 fall chain, controlled replays, bypass search and
    restart-from-1620 proof, all started from the v3 section-start chain (one base-start run of the v3 S01..S04 routes
    from the v3 base spawn 2160, 0; replaced by the imported level in ba5ca11 TASK-650). The restart-returns-range rule
    is still covered on the shipped level by tools/test_grapple_over_save.py and tools/test_grapple_over_modes.py.
    """
    task_id = 'TASK-531'


class Task491Tests(unittest.TestCase):
    """Retired by TASK-835 (artifacts/TASK-835/retired.md): layout-v3 whole-mountain pocket map, local misses, long falls
    and recovery map. The pockets, escapes (tools/grapple_over_recovery_routes.json) and v3 section-start chain (base spawn
    2160, 0) belong to the v3 mountain that normal starts replaced in ba5ca11 TASK-650.
    """
    task_id = 'TASK-491'


class Task492Tests(unittest.TestCase):
    """Retired by TASK-835 (artifacts/TASK-835/retired.md): layout-v3 bypass audit and S03/S07 shortcut proofs, all started
    from the v3 section-start chain (v3 base spawn 2160, 0; replaced by the imported level in ba5ca11 TASK-650).
    """
    task_id = 'TASK-492'


if __name__ == '__main__':
    unittest.main()
