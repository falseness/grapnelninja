"""Gameplay and UI telemetry (TASK-862), through ANALYTICS.

Documented in docs/platform-sdk.md ("Gameplay and UI telemetry"). Boots the
real index.html, freezes the frame loop (test_go_back SETUP) and drives the
production code: physics(), CLIMB_UI.trackSection() (the frame loop's
section check), real keys and a real mouse throw. Each scripted page's
gameplay/UI entries of ANALYTICS.debugLog (progression events and the design
ids below; env/perf/playtime/mode_time are TASK-861's) must equal the
expected lists stored here, ids and buckets exact.

test_01 (one page): boot (run Start, first section Start, tutorial shown),
the first throw (tutorial completed), a climb through two sections (teleports
over their terrain, section heights in 1000-unit buckets), a restart, a pause
(P key) with grapnel mode switches, language switches and the fps checkbox,
then a long fall under a real high go-back checkpoint: the dialog, Keep
falling (Escape), the second offer 10000 further down, Go back (Enter) with
a rewarded ad that answers 'rewarded', then a 6000 fall and pagehide at
once: quit_long_fall with that fall's bucket and section.
test_02: a counted fall (below the recovery depth: fall:<section>), a
long fall, then pagehide 31 s later (clock shifted): no quit_long_fall;
the session's longest fall still goes out.
test_03: the summit sends the run Complete (score: active seconds) and
longest_fall:complete.

TELEMETRY_GAMEPLAY_EVIDENCE_DIR, when set, receives sequences.json (the
recorded and expected sequences of every test).

    python3 tools/test_telemetry_gameplay.py -v
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402
from test_go_back import SETUP, CANDIDATES, CATCH, AFTER  # noqa: E402
from test_go_back_dialog import START, FALL, HOOKS  # noqa: E402

EVIDENCE = os.environ.get('TELEMETRY_GAMEPLAY_EVIDENCE_DIR')
OUT = {}

# Gameplay/UI entries of ANALYTICS.debugLog from index `from`, compact:
# ['P', status, level1, level2?, score?] or ['D', id, value?] or ['A', action, type, placement]
PREFIXES = ['best_height:', 'section_height:', 'fall:', 'goback', 'longest_fall:', 'quit_long_fall:',
            'quit:', 'restart:', 'ui:', 'tutorial:']
LOG = '''([from, prefixes]) => ANALYTICS.debugLog.slice(from).flatMap(e => {
    const a = e.args.map(v => v === undefined ? null : v)
    if (e.fn === 'addProgressionEvent') return [['P', a[0], ...a.slice(1, 4).filter(v => v !== null)]
        .concat(a[4] === null ? [] : [a[4]])]
    if (e.fn === 'addAdEvent') return [['A', a[0], a[1], a[3]]]
    if (e.fn === 'addDesignEvent' && prefixes.some(p => a[0].startsWith(p)))
        return [['D', a[0]].concat(a[1] === null ? [] : [a[1]])]
    return []
})'''
PAGEHIDE = "() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))"

# Put the player 150 units under the lowest vertex of the first terrain
# element of section `index` (open air), one production tick, then the frame
# loop's section check. Returns the HUD section and the climb height.
CLIMB = '''(index) => {
    const w = floors[0], section = w.level.sections[index]
    const blocked = (x, y) => w.elements.some(e => pointInPolygon(e.getPoints(), x, y))
    for (const eid of section.encounters.flatMap(id => w.level.encounters.find(e => e.id === id).elements)) {
        const e = w.byId.get(eid)
        if (!e) continue
        const pts = e.getPoints(), ys = pts.map(p => p.y), p = pts[ys.indexOf(Math.max(...ys))]
        if ([150, 160, 200].some(d => blocked(p.x, p.y + d))) continue
        Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null,
            traveled: 0, speedX: 0, speedY: 0})
        ninja.x = p.x; ninja.y = p.y + 150; ninja.speedX = ninja.speedY = 0
        ninja.track.pos = []
        ninja.track.addPos(ninja.x, ninja.y, true)
        LONG_FALL.restartTracking()
        screen.trackGrappleOver(true)
        physics()
        CLIMB_UI.trackSection()
        return {section: CLIMB_UI.currentSection().id, height: w.climbStats.currentHeight}
    }
    return null
}'''

# The rewarded ad of the go-back dialog answers 'rewarded' (local backend stub)
REWARDED = '''() => {
    PLATFORM_BACKEND.isRewardedSupported = () => true
    PLATFORM_BACKEND.showRewarded = () => Promise.resolve('rewarded')
}'''

SEC = ['SEC-baseline', 'SEC-chain1', 'SEC-jump44']
# The section of the high go-back checkpoint test_01 catches (and of its falls)
CP_SEC = 'SEC-ext-summit'
LAST_SEC = 'SEC-sky-spire'
RUN = 'grapple_over'


def best_heights(mode, top):
    return [['D', 'best_height:' + mode, h] for h in range(500, top + 1, 500)]


class GameplayTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.url, cls.browser = start_browser_test(ROOT, cls.stack.callback)

    def open(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda e: page.errors.append('pageerror: %s' % e))
        page.goto(self.url)
        wait_for_boot_run(page)
        self.assertEqual(page.evaluate('version'), RUN)
        self.addCleanup(lambda: self.assertEqual(page.errors, []))
        return page

    def freeze(self, page):
        page.evaluate(SETUP)
        page.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
        page.evaluate(HOOKS)

    def log(self, page, start=0):
        return page.evaluate(LOG, [start, PREFIXES])

    def mark(self, page):
        return page.evaluate('ANALYTICS.debugLog.length')

    def check(self, name, page, got, want):
        OUT[name] = {'got': got, 'expected': want}
        self.assertEqual(got, want, name)
        ids = [e[1] for e in got if e[0] == 'D']
        # Every id is already clean: the facade's sanitizer leaves it unchanged
        self.assertEqual(page.evaluate('ids => ids.map(ANALYTICS.sanitizeId)', ids), ids)
        for i in ids:
            self.assertLessEqual(len(i.split(':')), 5, i)
            self.assertTrue(all(len(s) <= 32 for s in i.split(':')), i)

    def catch(self, page, target):
        """Real mouse throw from 400 units under target (test_go_back_dialog.catch)."""
        page.mouse.up()
        page.evaluate(CATCH, [target['x'], target['y']])
        p = page.evaluate('''([x, y]) => canvasCoordsToViewportCoords({
            x: (x + screen.x) * scale[version], y: (y + screen.y) * scale[version]})''', [target['x'], target['y']])
        page.mouse.move(p['x'], p['y'])
        page.mouse.down()
        row = page.evaluate(AFTER)
        if row['grappled'] and row['target'] == target['id']:
            page.evaluate('() => { ninja.speedX = ninja.speedY = 0; physics() }')
        page.mouse.up()
        return row

    def high_checkpoint(self, page, height=60000):
        spawn = page.evaluate('floors[0].level.spawn.y')
        for target in page.evaluate(CANDIDATES)['static']:
            if spawn - target['y'] <= height:
                continue
            row = self.catch(page, target)
            if row['grappled'] and row['target'] == target['id'] and row['checkpoint']:
                return row['checkpoint'], spawn
        self.fail('no catchable high checkpoint')

    def test_01_scripted_session(self):
        page = self.open()
        boot = self.log(page)
        self.check('boot', page, boot, [['D', 'tutorial:grapple:shown'], ['P', 'Start', RUN],
                                         ['P', 'Start', RUN, SEC[0]]])
        self.freeze(page)
        page.evaluate('floors[0].doubleOfferShown = true')

        # The first throw completes the tutorial step (once)
        start = self.mark(page)
        for _ in range(2):
            page.mouse.move(900, 200)
            page.mouse.down()
            page.mouse.up()
        self.check('tutorial', page, self.log(page, start), [['D', 'tutorial:grapple:completed']])

        # Climb two sections
        start = self.mark(page)
        first = page.evaluate(CLIMB, 1)
        second = page.evaluate(CLIMB, 2)
        self.assertEqual([first['section'], second['section']], SEC[1:])
        OUT['climb_positions'] = [first, second]
        climb = self.log(page, start)
        # Climb heights 25366 and 27038 (the terrain the teleports go to)
        self.assertEqual([int(first['height']) // 500 * 500, int(second['height']) // 500 * 500], [25000, 27000])
        top1, top2 = 25000, 27000
        self.check('climb', page, climb,
                   best_heights('single', top1) +
                   [['P', 'Complete', RUN, SEC[0]], ['D', 'section_height:' + SEC[0], 0],
                    ['P', 'Start', RUN, SEC[1]]] +
                   [e for e in best_heights('single', top2) if e[2] > top1] +
                   [['P', 'Complete', RUN, SEC[1]],
                    ['D', 'section_height:' + SEC[1], 25000],
                    ['P', 'Start', RUN, SEC[2]]])

        # Restart: the run fails (with the section's height), a new run starts
        start = self.mark(page)
        page.evaluate('() => { CLIMB_UI.restart(); floors[0].doubleOfferShown = true; CLIMB_UI.trackSection() }')
        self.check('restart', page, self.log(page, start),
                   [['D', 'section_height:' + SEC[2], 27000], ['P', 'Fail', RUN], ['D', 'restart:' + RUN],
                    ['P', 'Start', RUN], ['P', 'Start', RUN, SEC[0]]])

        # Pause screen (P key): grapnel mode, language and fps switches, close (P)
        start = self.mark(page)
        page.keyboard.press('p')
        self.assertTrue(page.evaluate('menu.gamePaused'))
        page.evaluate('() => { CLIMB_UI.toggleGrapnel(); CLIMB_UI.toggleGrapnel() }')
        page.evaluate("() => { setLanguage('ru'); setLanguage('en') }")
        page.evaluate('() => { menu.pauseFpsCounterCheckbox.click(); menu.pauseFpsCounterCheckbox.click() }')
        page.keyboard.press('p')
        self.assertFalse(page.evaluate('menu.gamePaused'))
        self.check('pause_ui', page, self.log(page, start),
                   [['D', 'ui:pause:open:user'], ['D', 'ui:grapnel:double'], ['D', 'ui:grapnel:single'],
                    ['D', 'ui:lang:ru'], ['D', 'ui:lang:en'], ['D', 'ui:fps:on'], ['D', 'ui:fps:off'],
                    ['D', 'ui:pause:close']])

        # Long fall under a real high checkpoint: Keep falling, then Go back
        cp, spawn = self.high_checkpoint(page)
        fall_section = page.evaluate('climbFallSection()')
        OUT['checkpoint'] = {'checkpoint': cp, 'fall_section': fall_section}
        self.assertEqual([cp['section'], fall_section], [CP_SEC, CP_SEC])
        page.evaluate(REWARDED)
        start = self.mark(page)
        height = spawn - cp['anchorY'] - 1000
        page.evaluate(START, height)
        opened = page.evaluate(FALL, [4000, None])
        self.assertTrue(opened['dialog'], opened)
        page.keyboard.press('Escape')
        again = page.evaluate(FALL, [4000, None])
        self.assertTrue(again['dialog'], again)
        self.assertGreater(again['displacement'], 20000)
        page.keyboard.press('Enter')
        page.wait_for_function('!CLIMB_UI.goBackAdPending && !menu.gamePaused')
        self.assertEqual(page.evaluate('floors[0].climbStats.goBacks'), 1)
        self.check('go_back', page, self.log(page, start),
                   [['D', 'goback_offer:' + CP_SEC, 10000], ['D', 'goback_choice:keep:' + CP_SEC],
                    ['D', 'goback_offer:' + CP_SEC, 20000], ['D', 'goback_choice:back:' + CP_SEC],
                    ['A', 'reward_received', 'rewarded', 'go_back'], ['D', 'goback_ad:rewarded'],
                    ['D', 'goback:' + CP_SEC]])

        # A 6000 fall, then the page closes at once
        start = self.mark(page)
        page.evaluate(START, height)
        short = page.evaluate(FALL, [4000, 6000])
        self.assertFalse(short['paused'], short)
        self.assertTrue(6000 <= short['displacement'] < 10000, short)
        page.evaluate(PAGEHIDE)
        self.check('pagehide', page, self.log(page, start),
                   [['D', 'quit:pause:' + CP_SEC], ['D', 'longest_fall:session', 20000],
                    ['D', 'quit_long_fall:' + CP_SEC, 6000],
                    ['D', 'section_height:' + SEC[0], 0], ['P', 'Fail', RUN, SEC[0]], ['P', 'Fail', RUN]])
        OUT['test_01_full'] = self.log(page)

    def test_02_long_fall_then_late_pagehide(self):
        page = self.open()
        self.freeze(page)
        page.evaluate('floors[0].doubleOfferShown = true')
        start = self.mark(page)
        # A counted fall: below the recovery depth, back to the spawn
        page.evaluate(START, 1000)
        fell = page.evaluate(FALL, [4000, None])
        self.assertEqual([fell['falls'], fell['recoveries']], [1, 1], fell)
        page.evaluate(START, 7000)
        row = page.evaluate(FALL, [4000, 5000])
        self.assertTrue(5000 <= row['displacement'] < 6000, row)
        self.assertFalse(row['paused'])
        # 31 s later (wall clock) the page closes: not a quit after a long fall
        page.evaluate('() => { const now = Date.now.bind(Date); Date.now = () => now() + 31000 }')
        page.evaluate(PAGEHIDE)
        self.check('late_pagehide', page, [e for e in self.log(page, start) if not e[1].startswith('best_height:')],
                   [['D', 'fall:' + SEC[0]], ['D', 'quit:fall:' + SEC[0]], ['D', 'longest_fall:session', 4000],
                    ['D', 'section_height:' + SEC[0], 0], ['P', 'Fail', RUN, SEC[0]], ['P', 'Fail', RUN]])

    def test_03_summit(self):
        page = self.open()
        self.freeze(page)
        page.evaluate('floors[0].doubleOfferShown = true')
        page.evaluate(START, 7000)
        page.evaluate(FALL, [4000, 4500])
        start = self.mark(page)
        done = page.evaluate('''() => {
            const f = floors[0].level.finish
            floors[0].climbStats.elapsedActiveMs = 123456
            ninja.x = (f.left + f.right) / 2; ninja.y = (f.top + f.bottom) / 2; ninja.speedX = ninja.speedY = 0
            physics()
            return [floors[0].climbStats.completed, floors[0].climbStats.elapsedActiveMs]
        }''')
        self.assertTrue(done[0])
        score = round(done[1] / 1000)
        got = [e for e in self.log(page, start) if not e[1].startswith('best_height:')]
        last = LAST_SEC
        self.assertEqual(page.evaluate('floors[0].level.sections.at(-1).id'), last)
        self.check('summit', page, got,
                   [['P', 'Complete', RUN, SEC[0]], ['D', 'section_height:' + SEC[0], 0],
                    ['P', 'Start', RUN, last], ['P', 'Complete', RUN, last],
                    ['D', 'section_height:' + last, 201000], ['P', 'Complete', RUN, score],
                    ['D', 'longest_fall:complete', 4000]])


def tearDownModule():
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / 'sequences.json').write_text(json.dumps(OUT, indent=1) + '\n')


if __name__ == '__main__':
    unittest.main()
