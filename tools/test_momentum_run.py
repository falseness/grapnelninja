"""Momentum obstacle spawning (TASK-018): MomentumObstacleFloor in
elements/momentumpatterns.js.

A 60 s scripted run: Math.random is replaced by a seeded generator
(MOMENTUM_RUN_SEED, default 5; course and
spawn picks are fixed), momentum starts, the rAF loop is stopped and every
frame (one physics() = one 1/60 s tick) page.evaluate puts the ninja on the
course centre line DRIVE_SPEED * height further along the course, with its
speed along the segment, then runs physics(). The ninja is invulnerable and
its hp is topped up to the start hp after each frame (blues it crosses would
otherwise end the run); every onLethalDeath call is counted anyway.
Asserts:
- the live element count (all floors) stays below LIVE_BOUND for the whole run;
- the score (scoreText.count.momentum) increases, and equals the number of
  passed groups;
- only the ported types spawn (TASK-041): >= 8 distinct horizontal
  (bad-frameN, 12 in the catalog), >= 2 distinct turn (bad-frameN-turn, 5)
  and >= min(2, fitting) distinct vertical types (bad-frameN-v, 6), where
  fitting = the vertical types that fit the room of at least one shaft the
  spawner planned (its length minus the join margins; at 1280x720 the variants of
  frames 5, 8 and 14 never fit, and seeds whose shafts are all short only
  fit bad-frame6-v); every spawned vertical type fits its shaft, every
  horizontal type is on a right segment, vertical types on their own
  direction, turns on direction-changing joins;
- no type spawned twice in a row in the same direction (turns: join)
  (TASK-027);
- every group spawned after the start is at least 2 view lengths ahead of the
  ninja along the course and outside the view;
- difficulty weighted toward the catalog's early types in the first 20 s: the
  share of difficulty <= 2 spawns is above the catalog's (uniform) share, and
  the pick weights' share of them (averaged over the window's spawns) is above
  the one in the last 20 s (since TASK-031; the drawn share of ~10 spawns per
  window flipped seeds 2, 3 and 7 with every change in the draws);
- zero lethal elements: none at spawn, none live in any floor at any sample;
- no death.

MOMENTUM_RUN_EVIDENCE_DIR (default artifacts/TASK-041) receives
run-trace.json (compact; per second [t, segDir, liveElements, score,
spawnedTypes] where spawnedTypes are the ids spawned during that second),
run-spawns.json (compact per spawn [t, id, kind, dir, difficulty, arcAhead/view])
run-no-repeat.json (compact {seed, spawns, immediateRepeatsSameDir,
typesSeen}) and shots/ with page screenshots during the run (1280x720):
run-right.png, the first second from second 5 on in a right segment with
>= 3 obstacle pieces in view; run-up.png / run-down.png, the frame in an
up / down segment with the camera moving and the most (>= 1) pieces in view,
the first with >= 3 ending the search; run-turn.png, the first frame with a
spawned turn's course vertex and >= 1 of its pieces in view. Then the same
seed is driven again in a 1280x720 and a 390x844 page up to the first frame
from second 3 on with >= 3 pieces in view: overview-desktop.png and
overview-phone.png. Screenshots draw with the seeded Math.random state
restored, so they don't change the run.
Requires Playwright Chromium. No remote requests.
"""
import json
import math
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(os.environ.get('MOMENTUM_RUN_EVIDENCE_DIR', ROOT / 'artifacts/TASK-041'))
SEED = int(os.environ.get('MOMENTUM_RUN_SEED', 5))
SECONDS = 60
FPS = 60
# Course distance per frame in heights (65 world units at h 1080). The ninja
# is teleported along the centre line, so the speed cap does not apply; this
# is above GAMEPLAY.momentumMaxSpeed * cyclesPerTick (22 at h 1080 since
# TASK-047, 89 originally) and kept for the seed-tuned spawn coverage (TASK-027)
DRIVE_SPEED = 0.06
LIVE_BOUND = 150

SETUP = '''(seed) => {
    let a = seed >>> 0
    Math.random = () => {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    window.runRngState = (v) => v === undefined ? a : (a = v)
    window.lethalCalls = 0
    const lethal = onLethalDeath
    onLethalDeath = function() { lethalCalls++; return lethal.apply(this, arguments) }
    window.runFrame = 0
    window.runSpawns = []
    // Spawned turns (group id, course vertex) and vertical patterns (group
    // id -> direction), for the screenshots
    window.runTurns = []
    window.runShaftGroups = {}
    MomentumObstacleFloor.onSpawn = (s) => {
        if (s.kind == 'turn')
            runTurns.push({group: s.group.id, vertex: floors.find(f => f instanceof MomentumObstacleFloor).plan.vertex})
        if (s.kind == 'vertical')
            runShaftGroups[s.group.id] = s.dir
        const g = s.group, w = width / scale[version], h = height / scale[version]
        const view = Math.max(width, height) / scale[version]
        const inView = g.right > -screen.x && g.left < -screen.x + w && g.bottom > -screen.y && g.top < -screen.y + h
        // Share of difficulty <= 2 in the pick weights for this spawn (the
        // ramp of MomentumObstacleFloor.pickType at the current score)
        const options = GAMEPLAY.momentumSpawn
        const turn = s.kind == 'turn'
        const ids = turn ? momentumTurnsByJoin[s.dir] : momentumPatternsByDir[s.dir]
        const ramp = Math.min(1, scoreText.count[version] / options.rampScore)
        let easy = 0, total = 0
        for (const id of ids) {
            const d = (turn ? momentumTurnFactories : momentumPatternFactories)[id].pattern.difficulty
            const k = Math.min(d, options.earlyWeights.length) - 1
            const w = Math.max(1, Math.round(options.earlyWeights[k] + (options.lateWeights[k] - options.earlyWeights[k]) * ramp))
            total += w
            if (d <= 2) easy += w
        }
        runSpawns.push([runFrame / 60, s.id, s.kind, s.dir, s.difficulty, s.arcAhead / view, s.lethal, inView,
                        easy / total])
    }
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    const view = floor.getViewLength()
    window.runArc = floor.getNinjaArc()
    return {view, startArc: runArc, lethalCalls}
}'''

# Draws for a screenshot without using up the seeded Math.random (render code
# draws from it too), so screenshots don't change the run's spawns
DRAW = '(() => { const state = runRngState(); draw(); runRngState(state) })()'

# Obstacle pieces inside the view
VISIBLE = '''floors.find(f => f instanceof MomentumObstacleFloor).elements.filter(e => {
    const b = getElementBounds(e), w = width / scale[version], h = height / scale[version]
    return b.right > -screen.x && b.left < -screen.x + w && b.bottom > -screen.y && b.top < -screen.y + h
}).length'''

# Drives up to frames frames; stops after the first frame matching want
# (each key optional): want.up / want.down > 0: in an up / down segment with
# the camera moving and >= that many pieces of that direction's vertical
# patterns fully in view; want.turn: a turn's course vertex and all of its
# pieces fully in view; want.any > 0: >= that many pieces in view from frame
# want.anyFrom on. Returns the frames driven, the matched key (hit) and the
# pieces counted.
DRIVE = '''([frames, step, want]) => {
    const samples = []
    const v = step / cyclesPerTick
    const startHp = GAMEPLAY.momentumHp.startHp
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    for (let k = 0; k < frames; ++k) {
        runArc += step
        let i = screen.segmentIndex
        while (floor.getArcStart(i + 1) <= runArc) ++i
        const s = momentumCourse.segment(i), d = momentumDirection(s.dir)
        const along = runArc - floor.getArcStart(i)
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = s.x0 + d.x * along; ninja.y = s.y0 + d.y * along
        ninja.speedX = d.x * v; ninja.speedY = d.y * v
        physics()
        if (momentumState.hp < startHp) momentumState.hp = startHp
        ++runFrame
        if (runFrame % 60 == 0) {
            let live = 0, lethal = 0
            for (const f of floors) {
                live += f.elements.length
                for (const e of f.elements) if (isLethalElement(e)) ++lethal
            }
            samples.push([runFrame / 60, screen.getSegment().dir, live, scoreText.count.momentum, lethal,
                          screen.segmentIndex])
        }
        const w = width / scale[version], h = height / scale[version]
        const inside = e => {
            const b = getElementBounds(e)
            return b.left >= -screen.x && b.right <= -screen.x + w && b.top >= -screen.y && b.bottom <= -screen.y + h
        }
        const dir = screen.getSegment().dir
        if (want[dir] > 0 && screen.speedY != 0) {
            const pieces = floor.elements.filter(e => runShaftGroups[e.generationGroupId] == dir && inside(e)).length
            if (pieces >= want[dir])
                return {samples, frames: k + 1, hit: dir, pieces}
        }
        if (want.any > 0 && runFrame >= want.anyFrom) {
            const pieces = ''' + VISIBLE + '''
            if (pieces >= want.any)
                return {samples, frames: k + 1, hit: 'any', pieces}
        }
        if (want.turn) {
            for (const turn of runTurns) {
                const v = turn.vertex
                if (v.x < -screen.x || v.x > -screen.x + w || v.y < -screen.y || v.y > -screen.y + h)
                    continue
                const group = floor.elements.filter(e => e.generationGroupId === turn.group)
                if (group.length && group.every(inside))
                    return {samples, frames: k + 1, hit: 'turn', pieces: group.length}
            }
        }
    }
    return {samples, frames, hit: null, pieces: 0}
}'''


class MomentumRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = EVIDENCE_DIR
        cls.shots_dir = cls.out / 'shots'
        cls.shots_dir.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        context = cls.browser.new_context(viewport={'width': 1280, 'height': 720})
        cls.addClassCleanup(context.close)
        page = cls.page = context.new_page()
        cls.errors = []
        page.on('pageerror', lambda e: cls.errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
        page.goto(cls.url)
        wait_for_boot_run(page)
        cls.setup = page.evaluate(SETUP, SEED)
        step = page.evaluate('height') * DRIVE_SPEED
        cls.samples = []
        shots = {}
        shaft_pieces = {'up': 0, 'down': 0}
        for second in range(SECONDS):
            # Up / down: any frame with more pieces in view than the last shot
            # of that direction, until one has >= 3 (some seeds leave every
            # later shaft empty); turn: the first one in view
            left = FPS
            while left:
                want = {d: n + 1 for d, n in shaft_pieces.items() if n < 3}
                want['turn'] = 'run-turn.png' not in shots
                driven = page.evaluate(DRIVE, [left, step, want])
                cls.samples += driven['samples']
                left -= driven['frames']
                if driven['hit']:
                    name = f'run-{driven["hit"]}.png'
                    page.evaluate(DRAW)
                    page.screenshot(path=str(cls.shots_dir / name))
                    shots[name] = second + 1
                    if driven['hit'] in shaft_pieces:
                        shaft_pieces[driven['hit']] = driven['pieces']
            seg = cls.samples[-1][1]
            # Right: mid-segment and with the run under way
            if second >= 5 and seg == 'right' and 'run-right.png' not in shots and page.evaluate(VISIBLE) >= 3:
                page.evaluate(DRAW)
                page.screenshot(path=str(cls.shots_dir / 'run-right.png'))
                shots['run-right.png'] = second + 1
        cls.shots = shots
        cls.shaft_pieces = shaft_pieces
        cls.spawns = page.evaluate('runSpawns')
        cls.final = page.evaluate('''({score: scoreText.count.momentum, lethalCalls, version, runInProgress,
            course: momentumCourse.segments.slice(0, screen.segmentIndex + 1).map(s => s.dir[0] + Math.round(s.length)),
            fitting: (() => {
                // Vertical types that fit the room of a shaft the spawner
                // has planned (its stretch length minus the join margins at
                // both ends): spawning runs ahead of the camera
                const floor = floors.find(f => f instanceof MomentumObstacleFloor)
                const fits = new Set()
                const planned = floor.getStretchEnd(floor.segmentIndex)
                for (let i = 0; i <= planned; ++i) {
                    const s = momentumCourse.segment(i)
                    if (s.dir == 'right' || (i && momentumCourse.segment(i - 1).dir == s.dir))
                        continue
                    const last = floor.getStretchEnd(i)
                    const room = floor.getArcStart(last + 1) - floor.getArcStart(i) -
                        floor.getJoinMargin(momentumCourse.segment(i - 1)) - floor.getJoinMargin(momentumCourse.segment(last + 1))
                    for (const id of momentumPatternsByDir[s.dir])
                        if (momentumPatternFactories[id].getLength(momentumSegmentHalfWidth(s)) <= room)
                            fits.add(id)
                }
                return [...fits].sort()
            })(),
            passed: floors.find(f => f instanceof MomentumObstacleFloor).nextGenerationGroupId -
                    floors.find(f => f instanceof MomentumObstacleFloor).groups.filter(g => !g.scored).length,
            catalog: {h: MOMENTUM_PATTERNS_PORT_H.map(p => [p.id, p.difficulty]),
                      v: MOMENTUM_PATTERNS_PORT_V.map(p => [p.id, p.difficulty]),
                      turn: MOMENTUM_PATTERNS_TURN.map(p => [p.id, p.difficulty])}})''')
        by_second = {}
        for s in cls.spawns:
            by_second.setdefault(math.ceil(s[0]), []).append(s[1])
        trace = [[t, seg, live, score, by_second.get(int(t), [])]
                 for t, seg, live, score, _lethal, _index in cls.samples]
        (cls.out / 'run-trace.json').write_text(json.dumps(
            {'fields': ['t', 'segDir', 'liveElements', 'score', 'spawnedTypes'], 'seed': SEED,
             'course': cls.final['course'], 'initialSpawns': by_second.get(0, []), 'samples': trace}, separators=(',', ':')))
        (cls.out / 'run-spawns.json').write_text(json.dumps(
            {'fields': ['t', 'id', 'kind', 'dir', 'difficulty', 'arcAheadViews'],
             'spawns': [[round(s[0], 3), s[1], s[2], s[3], s[4], round(s[5], 3)] for s in cls.spawns]},
            separators=(',', ':')))
        last, repeats = {}, []
        for s in cls.spawns:
            key = (s[2], s[3])
            if last.get(key) == s[1]:
                repeats.append([round(s[0], 3), s[1], s[2], s[3]])
            last[key] = s[1]
        cls.repeats = repeats
        (cls.out / 'run-no-repeat.json').write_text(json.dumps(
            {'seed': SEED, 'spawns': len(cls.spawns), 'immediateRepeatsSameDir': len(repeats),
             'typesSeen': sorted({s[1] for s in cls.spawns})}, separators=(',', ':')))
        # Overviews: the same seed driven again at desktop and phone size
        cls.overviews = {}
        for name, viewport in (('overview-desktop.png', {'width': 1280, 'height': 720}),
                               ('overview-phone.png', {'width': 390, 'height': 844})):
            ctx = cls.browser.new_context(viewport=viewport)
            cls.addClassCleanup(ctx.close)
            p = ctx.new_page()
            p.on('pageerror', lambda e: cls.errors.append(str(e)))
            p.on('console', lambda m: m.type == 'error' and cls.errors.append(m.text))
            p.goto(cls.url)
            wait_for_boot_run(p)
            p.evaluate(SETUP, SEED)
            driven = p.evaluate(DRIVE, [SECONDS * FPS, p.evaluate('height') * DRIVE_SPEED,
                                        {'any': 3, 'anyFrom': 3 * FPS}])
            if driven['hit']:
                p.evaluate(DRAW)
                p.screenshot(path=str(cls.shots_dir / name))
                cls.overviews[name] = {'second': round(p.evaluate('runFrame') / FPS, 2), 'pieces': driven['pieces'],
                                       'viewport': viewport}
        print('course segments driven:', ' '.join(cls.final['course']), file=sys.stderr)
        print('spawns:', len(cls.spawns), 'at start:', sum(1 for s in cls.spawns if s[0] == 0), 'final:', {k: v for k, v in cls.final.items() if k not in ('catalog', 'course')},
              'screenshots (second):', shots, file=sys.stderr)

    def kinds(self, kind):
        return sorted({s[1] for s in self.spawns if s[2] == kind})

    def test_1_live_elements_bounded(self):
        live = [s[2] for s in self.samples]
        print(f'live elements: min {min(live)} max {max(live)} bound {LIVE_BOUND}', file=sys.stderr)
        self.assertEqual(len(self.samples), SECONDS)
        self.assertLess(max(live), LIVE_BOUND)

    def test_2_score_increases(self):
        scores = [s[3] for s in self.samples]
        print(f'score at 10 s {scores[9]}, 20 s {scores[19]}, 40 s {scores[39]}, 60 s {scores[-1]}; '
              f'passed groups {self.final["passed"]}', file=sys.stderr)
        self.assertGreater(scores[-1], scores[9])
        self.assertGreater(scores[9], 0)
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(self.final['score'], self.final['passed'])

    def test_3_distinct_types(self):
        h, v, turn = self.kinds('horizontal'), self.kinds('vertical'), self.kinds('turn')
        fitting = self.final['fitting']
        print(f'distinct horizontal {len(h)} {h}', file=sys.stderr)
        print(f'distinct vertical {len(v)} {v} (fitting a planned shaft {len(fitting)} {fitting})', file=sys.stderr)
        print(f'distinct turn {len(turn)} {turn}', file=sys.stderr)
        print(f'spawns {len(self.spawns)}, immediate repeats in the same direction {len(self.repeats)} '
              f'{self.repeats}', file=sys.stderr)
        self.assertEqual(self.repeats, [])
        self.assertGreaterEqual(len(h), 8)
        self.assertGreaterEqual(len(v), min(2, len(fitting)))
        self.assertGreaterEqual(len(fitting), 1)
        self.assertLessEqual(set(v), set(fitting))
        self.assertGreaterEqual(len(turn), 2)
        catalog = self.final['catalog']
        for t, id_, kind, dir_, *_ in self.spawns:
            if kind == 'horizontal':
                self.assertEqual(dir_, 'right')
                self.assertIn(id_, dict(catalog['h']))
            elif kind == 'vertical':
                self.assertIn(dir_, ('up', 'down'))
                self.assertIn(id_, dict(catalog['v']))
            else:
                a, b = dir_.split('->')
                self.assertNotEqual(a, b)
                self.assertIn(id_, dict(catalog['turn']))

    def test_4_spawned_ahead(self):
        later = [s for s in self.spawns if s[0] > 0]
        nearest = min(s[5] for s in later)
        in_view = [s for s in later if s[7]]
        print(f'spawns after start {len(later)}: nearest {nearest:.3f} view lengths ahead, '
              f'in view at spawn {len(in_view)}', file=sys.stderr)
        self.assertGreater(len(later), 20)
        self.assertGreaterEqual(nearest, 2)
        self.assertEqual(in_view, [])

    def test_5_early_types_first(self):
        def share(spawns):
            return sum(1 for s in spawns if s[4] <= 2) / len(spawns)
        catalog = [d for kind in self.final['catalog'].values() for _id, d in kind]
        uniform = sum(1 for d in catalog if d <= 2) / len(catalog)
        first = [s for s in self.spawns if s[0] < 20]
        last = [s for s in self.spawns if s[0] >= SECONDS - 20]
        mean = lambda spawns: sum(s[4] for s in spawns) / len(spawns)
        # Pick-weight share of difficulty <= 2, averaged over the window's
        # spawns: the ramp itself, without the sampling noise of ~10 picks
        weighted = lambda spawns: sum(s[8] for s in spawns) / len(spawns)
        print(f'difficulty <= 2 share: first 20 s {share(first):.3f} ({len(first)} spawns, mean d '
              f'{mean(first):.2f}, weights {weighted(first):.3f}), last 20 s {share(last):.3f} ({len(last)} spawns,'
              f' mean d {mean(last):.2f}, weights {weighted(last):.3f}), catalog {uniform:.3f}', file=sys.stderr)
        self.assertGreater(share(first), uniform)
        self.assertGreater(weighted(first), weighted(last))

    def test_6_nothing_lethal(self):
        at_spawn = sum(s[6] for s in self.spawns)
        live = sum(s[4] for s in self.samples)
        print(f'lethal elements: at spawn {at_spawn}, live samples {live}; lethal calls '
              f'{self.final["lethalCalls"]}; errors {self.errors}', file=sys.stderr)
        self.assertEqual(at_spawn, 0)
        self.assertEqual(live, 0)
        self.assertEqual(self.final['lethalCalls'], 0)
        self.assertEqual(self.final['version'], 'momentum')
        self.assertTrue(self.final['runInProgress'])
        self.assertEqual(self.errors, [])

    def test_7_screenshots(self):
        print('screenshots taken at second:', self.shots, 'shaft pieces in view:', self.shaft_pieces,
              'overviews:', self.overviews, file=sys.stderr)
        self.assertEqual(set(self.shots), {'run-up.png', 'run-down.png', 'run-right.png', 'run-turn.png'})
        self.assertGreaterEqual(min(self.shaft_pieces.values()), 1)
        self.assertEqual(set(self.overviews), {'overview-desktop.png', 'overview-phone.png'})


if __name__ == '__main__':
    unittest.main()
