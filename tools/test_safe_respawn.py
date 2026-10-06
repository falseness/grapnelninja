"""Safe respawn after a continue (TASK-081).

Each case drives physics by hand (no requestAnimationFrame, no input after
the continue): advance the run, die for real through ninja.move(), answer the
continue offer and then run RESPAWN_INVULNERABLE_MS + 500 ms of physics.

Env: RESPAWN_EVIDENCE_DIR receives frames/<case>/t*.png, contact.png,
respawn-cases.json, replenish-check.json and console/page-errors.log.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
# t300 is an extra mid-blink frame (full alpha) between the dim ones
FRAMES_MS = (0, 300, 500, 1000, 2000, 2500)

# window.__rs: seeded runs, a manual camera advance with deaths disabled,
# real lethal deaths, the continue and per-tick measurements.
SETUP = r'''() => {
    // The itch.io build has no rewarded ads, so the continue (and its safe
    // respawn in respawn.js) is unreachable in play; a stub ad that always
    // rewards keeps the respawn path under test.
    PLATFORM.isRewardedSupported = () => true
    PLATFORM.requestRewarded = () => Promise.resolve({status: 'rewarded'})
    const realLethal = window.onLethalDeath
    const realRestart = window.reStart
    const rs = window.__rs = {deaths: 0, reStarts: 0, lethalCalls: 0, deathsEnabled: true}
    window.onLethalDeath = function() {
        rs.lethalCalls++
        if (!rs.deathsEnabled) return
        if (!continueOffer.visible && !ninja.isInvulnerable()) rs.deaths++
        return realLethal.apply(this, arguments)
    }
    window.reStart = function() {
        rs.reStarts++
        return realRestart.apply(this, arguments)
    }
    rs.seed = s => {
        let seed = s >>> 0
        Math.random = () => (seed = (1664525 * seed + 1013904223) >>> 0) / 4294967296
    }
    rs.start = (mode, template, seed) => {
        rs.seed(seed)
        startGame(mode)
        cancelAnimationFrame(game)
        if (template) {
            floors[1].creations = [{type: template, chance: 100}]
            floors[1].generatePrimaryElements()
        }
        rs.score0 = scoreText.count[version]
    }
    rs.visible = () => ({w: width / scale[version], h: height / scale[version]})
    // Camera forced forward; the ninja is held at a fixed screen point.
    rs.advance = (ticks, viewports, holdY) => {
        rs.deathsEnabled = false
        const step = viewports * rs.visible().w / ticks
        for (let i = 0; i < ticks; ++i) {
            screen.x -= step
            ninja.x = -screen.x + 0.3 * rs.visible().w
            ninja.y = holdY
            ninja.speedX = 0
            ninja.speedY = 0
            physics()
        }
        rs.deathsEnabled = true
    }
    rs.isLethal = e => e.collision === Element.prototype.collision ||
        (version == 'classic' && e instanceof Side)
    rs.lethalElements = () => floors.flatMap(f => f.elements).filter(rs.isLethal)
    const segDist = (px, py, a, b) => {
        const dx = b.x - a.x, dy = b.y - a.y
        const t = Math.max(0, Math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / (dx * dx + dy * dy || 1)))
        return Math.hypot(px - a.x - t * dx, py - a.y - t * dy)
    }
    const inside = (px, py, pts) => {
        let s = 0
        for (let i = 0; i < pts.length; ++i) {
            const a = pts[i], b = pts[(i + 1) % pts.length]
            const c = Math.sign((b.x - a.x) * (py - a.y) - (b.y - a.y) * (px - a.x))
            if (c && s && c != s) return false
            if (c) s = c
        }
        return true
    }
    // Gap between the ninja circle and the nearest lethal polygon (< 0: overlap).
    rs.minLethalGap = () => {
        let best = Infinity, which = null
        for (const e of rs.lethalElements()) {
            const pts = e.getPoints()
            let d = inside(ninja.x, ninja.y, pts) ? 0 :
                Math.min(...pts.map((a, i) => segDist(ninja.x, ninja.y, a, pts[(i + 1) % pts.length])))
            d -= ninja.radius
            if (d < best) { best = d; which = e.constructor.name }
        }
        return {gap: best, element: which}
    }
    rs.inVisible = () => {
        const v = rs.visible(), sx = ninja.x + screen.x, sy = ninja.y + screen.y
        return sx - ninja.radius >= 0 && sx + ninja.radius <= v.w &&
               sy - ninja.radius >= 0 && sy + ninja.radius <= v.h
    }
    rs.state = () => ({x: ninja.x, y: ninja.y, speedX: ninja.speedX, speedY: ninja.speedY,
        screenX: screen.x, screenY: screen.y, score: scoreText.count[version],
        invulnerableMs: ninja.invulnerableMs, offer: continueOffer.visible,
        continueUsed: continueUsed, deaths: rs.deaths, reStarts: rs.reStarts,
        throwed: grapnel.throwed, grappled: grapnel.isGrappled(), blinkAlpha: ninja.getBlinkAlpha()})
    // A real lethal death: obstacle contact or falling behind the left border.
    rs.die = (cause, score) => {
        let element = null
        const v = rs.visible()
        const lethalOnScreen = () => floors[1].elements
            .filter(e => e.collision === Element.prototype.collision)
            .filter(e => e.getLeftPointX() + screen.x > 0.3 * v.w && e.getRightPointX() + screen.x < v.w)
        // Obstacle deaths need a lethal element on screen: move the camera on
        // until one shows up (some templates, e.g. frame5Rects, have none).
        if (cause == 'obstacle') {
            rs.deathsEnabled = false
            for (let i = 0; i < 600 && !lethalOnScreen().length; ++i) {
                screen.x -= 0.01 * v.w
                ninja.x = -screen.x + 0.1 * v.w
                ninja.speedX = 0
                ninja.speedY = 0
                physics()
            }
            rs.deathsEnabled = true
            if (!lethalOnScreen().length) cause = 'behind-border'
        }
        scoreText.count[version] = score
        if (cause == 'behind-border') {
            ninja.x = screen.getDeletionBorder() - screen.x - 10 * ninja.radius
        } else {
            const candidates = lethalOnScreen()
            element = candidates.find(e => !(e instanceof JumpingCube) && e.speedY == 0) || candidates[0]
            // centred on a vertex, the circle crosses two of its edges
            const vertex = element.getPoints()[0]
            ninja.x = vertex.x
            ninja.y = vertex.y
        }
        ninja.speedX = 0
        ninja.speedY = 0
        grapnel.throwed = true
        grapnel.setGrappled(true)
        grapnel.pos = [[ninja.x + 50, ninja.y - 50, new Empty()]]
        const before = rs.deaths
        physics()
        if (!continueOffer.visible || rs.deaths != before + 1) throw Error('death did not open the offer')
        return {cause: cause == 'behind-border' ? cause : 'obstacle:' + element.constructor.name,
                deathX: ninja.x, deathY: ninja.y, score: scoreText.count[version]}
    }
    // The continue arrives with the stub rewarded ad's result
    rs.pressContinue = async () => {
        const b = continueOffer.continueButton.background
        if (!continueOffer.click({x: b.x + b.width / 2, y: b.y + b.height / 2}))
            throw Error('continue click ignored')
        for (let i = 0; i < 200 && continueOffer.visible; ++i)
            await new Promise(resolve => setTimeout(resolve, 10))
        if (continueOffer.visible) throw Error('rewarded ad did not finish')
        rs.deaths = 0
        const p = lastRespawn
        const s = scale[version]
        return {x: p.x, y: p.y, screenX: (p.x + screen.x) * s, screenY: (p.y + screen.y) * s,
                visibleWidth: width, visibleHeight: height,
                gap: p.gap, fall: p.fall, zone: p.zone, removed: p.removed.length,
                removedTypes: p.removed.map(r => r.type)}
    }
    // One physics tick plus the measurements the test asserts on.
    rs.tick = () => {
        physics()
        const g = rs.minLethalGap()
        return {inv: ninja.invulnerableMs, gap: g.gap, element: g.element, visible: rs.inVisible(),
                deaths: rs.deaths, reStarts: rs.reStarts, score: scoreText.count[version],
                x: ninja.x, y: ninja.y}
    }
}'''

# Records every group the play floor generates: the anchor x, the preceding
# right edge and the new group's bounds.
SPAWN_HOOK = r'''() => {
    const rs = window.__rs
    rs.spawns = []
    const f = floors[1]
    const original = f.generateElements
    f.generateElements = function(x) {
        const prevRight = this.elements.length ? Math.max(...this.elements.map(e => e.getRightPointX())) : null
        const lastGroupRight = this.elements.length && version == 'bad'
            ? this.getGenerationGroup(this.elements.length - 1).rightPointX : null
        const begin = this.elements.length
        const n = original.apply(this, arguments)
        const group = this.elements.slice(begin)
        if (group.length)
            rs.spawns.push({tick: rs.tickNo || 0, phase: rs.phase, anchor: x, prevRight, lastGroupRight,
                left: Math.min(...group.map(e => e.getLeftPointX())),
                right: Math.max(...group.map(e => e.getRightPointX())),
                types: group.map(e => e.constructor.name),
                // TriangleFactory adds radius * sqrt(3) to the sampled x, so a lone
                // triangle's left edge sits side / 2 past the interval.
                triangleShift: group.length == 1 && group[0] instanceof Triangle ? group[0].side / 2 : 0})
        return n
    }
}'''


class SafeRespawnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('RESPAWN_EVIDENCE_DIR')
        cls.errors = []
        cls.cases = []
        cls.replenish = []

    @classmethod
    def tearDownClass(cls):
        if not cls.evidence:
            return
        out = Path(cls.evidence)
        out.mkdir(parents=True, exist_ok=True)
        for kind in ('console', 'page'):
            lines = [f'{name}: {msg}' for name, errors in cls.errors for msg in errors[kind]]
            (out / f'{kind}-errors.log').write_text(''.join(line + '\n' for line in lines))
        if cls.cases:
            (out / 'respawn-cases.json').write_text(json.dumps(cls.cases, indent=1) + '\n')
            cls.contact_sheet(out)
        if cls.replenish:
            (out / 'replenish-check.json').write_text(json.dumps(cls.replenish, indent=1) + '\n')

    @classmethod
    def contact_sheet(cls, out):
        from PIL import Image, ImageDraw
        # Each frame: the full screenshot and a 4x zoom around the ninja
        tw, th, zoom, label = 320, 180, 180, 18
        cw = tw + zoom
        sheet = Image.new('RGB', (cw * len(FRAMES_MS) + 170, (th + label) * len(cls.cases)), 'black')
        draw = ImageDraw.Draw(sheet)
        for row, case in enumerate(cls.cases):
            name = case['case']
            y = row * (th + label)
            draw.text((4, y + th // 2), name, fill='white')
            for col, info in enumerate(case['frames']):
                img = Image.open(out / 'frames' / name / f't{info["ms"]}.png').convert('RGB')
                x = 170 + col * cw
                sheet.paste(img.resize((tw, th)), (x, y + label))
                cx, cy, r = round(info['cssX']), round(info['cssY']), zoom // 8
                sheet.paste(img.crop((cx - r, cy - r, cx + r, cy + r)).resize((zoom - 4, th)), (x + tw + 2, y + label))
                draw.text((x + 4, y + 2), f't{info["ms"]}  alpha {info["blinkAlpha"]:.2f}', fill='white')
        sheet.save(out / 'contact.png')

    def boot(self):
        context, page, errors = open_game(self.browser, self.url + 'index.html', VIEWPORT)
        self.addCleanup(context.close)
        self.errors.append((self.id(), errors))
        self.addCleanup(lambda: self.assertEqual((errors['console'], errors['page']), ([], [])))
        page.wait_for_function('PLATFORM.environment === "itch" && menu.visible')
        page.evaluate(SETUP)
        return page

    def snap(self, page, name, ms, frames):
        if not self.evidence:
            return
        path = Path(self.evidence) / 'frames' / name / f't{ms}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        info = page.evaluate('''() => {
            draw()
            const r = canvas.getBoundingClientRect()
            const p = {x: r.left + (ninja.x + screen.x) * scale[version] * r.width / width,
                       y: r.top + (ninja.y + screen.y) * scale[version] * r.height / height}
            return {ms: 0, cssX: p.x, cssY: p.y, blinkAlpha: ninja.getBlinkAlpha(), invulnerableMs: ninja.invulnerableMs}
        }''')
        info['ms'] = ms
        frames.append(info)
        page.screenshot(path=str(path))

    def run_case(self, name, mode, template, seed, cause):
        page = self.boot()
        page.evaluate('([m, t, s]) => window.__rs.start(m, t, s)', [mode, template, seed])
        hold_y = 0.2 * 1080 if mode == 'classic' else 1.2 * 1080
        page.evaluate('([v, y]) => window.__rs.advance(90, v, y)', [0.8, hold_y])
        death = page.evaluate('([c, s]) => window.__rs.die(c, s)', [cause, 7])
        respawn = page.evaluate('() => window.__rs.pressContinue()')
        after = page.evaluate('() => window.__rs.state()')

        inv_ms, step_ms = page.evaluate('[RESPAWN_INVULNERABLE_MS, physicsStepMs]')
        self.assertEqual(inv_ms, 2000)
        self.assertEqual((after['speedX'], after['speedY'], after['throwed'], after['grappled']),
                         (0, 0, False, False))
        self.assertEqual(after['score'], death['score'])
        self.assertTrue(after['continueUsed'])
        self.assertLess(after['blinkAlpha'], 1)

        window_ticks = round((inv_ms + 500) / step_ms)
        frame_ticks = {round(ms / step_ms): ms for ms in FRAMES_MS}
        self.assertEqual(len(frame_ticks), len(FRAMES_MS))
        frames = []
        self.snap(page, name, 0, frames)
        samples = []
        end_sample = None
        for tick in range(1, window_ticks + 1):
            s = page.evaluate('() => window.__rs.tick()')
            samples.append(s)
            if end_sample is None and s['inv'] == 0:
                end_sample = dict(s, tick=tick, ms=tick * step_ms)
            if tick in frame_ticks:
                self.snap(page, name, frame_ticks[tick], frames)
            self.assertEqual((s['deaths'], s['reStarts']), (0, 0), f'{name}: died at tick {tick}')
            self.assertTrue(s['visible'], f'{name}: ninja left the visible area at tick {tick}')
        self.assertIsNotNone(end_sample)
        self.assertGreater(end_sample['gap'], 0, f'{name}: overlaps a lethal element as invulnerability ends')
        self.assertGreaterEqual(samples[-1]['score'], death['score'])

        # Alive time: keep going without input until the first death (cap 10 s)
        alive_ticks = window_ticks
        while alive_ticks < round(10000 / step_ms):
            s = page.evaluate('() => window.__rs.tick()')
            if s['deaths'] or s['reStarts']:
                break
            alive_ticks += 1

        min_gap = min(samples, key=lambda s: s['gap'])
        record = {
            'case': name, 'mode': mode, 'template': template or 'mixed', 'seed': seed,
            'deathCause': death['cause'], 'scoreAtDeath': death['score'],
            'scoreAfterWindow': samples[-1]['score'],
            'respawnLogical': {'x': respawn['x'], 'y': respawn['y']},
            'respawnScreen': {'x': respawn['screenX'], 'y': respawn['screenY'],
                              'canvasLogical': [respawn['visibleWidth'], respawn['visibleHeight']]},
            'chosenGap': respawn['gap'], 'fallDistance': respawn['fall'],
            'removedElements': respawn['removedTypes'],
            'windowMs': window_ticks * step_ms,
            'deathsInWindow': samples[-1]['deaths'],
            'minLethalGapOverWindow': min_gap['gap'], 'nearestLethalElement': min_gap['element'],
            'gapWhenInvulnerabilityEnds': end_sample['gap'], 'invulnerabilityEndedMs': end_sample['ms'],
            'frames': frames,
            'aliveMsAfterRespawn': alive_ticks * step_ms, 'aliveCappedAt10s': alive_ticks >= round(10000 / step_ms),
        }
        self.cases.append(record)
        print(f'\n  {name}: cause {death["cause"]}; respawn ({respawn["x"]:.1f}, {respawn["y"]:.1f})'
              f' screen ({respawn["screenX"]:.1f}, {respawn["screenY"]:.1f}); removed {len(respawn["removedTypes"])};'
              f' 0 deaths in {window_ticks * step_ms:.0f} ms; min gap {min_gap["gap"]:.1f};'
              f' gap at invulnerability end {end_sample["gap"]:.1f}; score {death["score"]} kept;'
              f' alive {alive_ticks * step_ms:.0f} ms: pass', file=sys.stderr)

    def test_classic_obstacle(self):
        self.run_case('classic-obstacle', 'classic', None, 101, 'obstacle')

    def test_classic_behind_border(self):
        self.run_case('classic-behind-border', 'classic', None, 202, 'behind-border')

    def test_bad_frame1(self):
        self.run_case('bad-frame1Elements', 'bad', 'frame1Elements', 11, 'obstacle')

    def test_bad_frame5(self):
        self.run_case('bad-frame5Rects', 'bad', 'frame5Rects', 22, 'obstacle')

    def test_bad_frame14(self):
        self.run_case('bad-frame14Rects', 'bad', 'frame14Rects', 33, 'obstacle')

    def test_bad_frame3_triangles(self):
        self.run_case('bad-frame3Triangle', 'bad', 'frame3Triangle', 44, 'obstacle')

    def test_bad_mixed(self):
        self.run_case('bad-mixed', 'bad', None, 55, 'obstacle')

    def replenish_check(self, mode, seed):
        page = self.boot()
        page.evaluate('([m, s]) => window.__rs.start(m, null, s)', [mode, seed])
        hold_y = 0.2 * 1080 if mode == 'classic' else 1.2 * 1080
        page.evaluate('([v, y]) => window.__rs.advance(90, v, y)', [0.8, hold_y])
        page.evaluate(SPAWN_HOOK)
        page.evaluate("() => { window.__rs.phase = 'before-continue' }")
        page.evaluate('([c, s]) => window.__rs.die(c, s)', ['behind-border', 7])
        page.evaluate("() => { window.__rs.phase = 'continue' }")
        respawn = page.evaluate('() => window.__rs.pressContinue()')
        # 30 s of physics with no input and the camera forced forward
        result = page.evaluate(r'''() => {
            const rs = window.__rs
            rs.phase = 'after-continue'
            rs.deathsEnabled = false
            const ticks = Math.round(30000 / physicsStepMs)
            const step = 12 * rs.visible().w / ticks
            let minAhead = Infinity
            for (rs.tickNo = 1; rs.tickNo <= ticks; ++rs.tickNo) {
                screen.x -= step
                ninja.x = -screen.x + 0.25 * rs.visible().w
                ninja.speedX = 0
                ninja.speedY = 0
                physics()
                const right = Math.max(...floors[1].elements.map(e => e.getRightPointX()))
                minAhead = Math.min(minAhead, right + screen.x - rs.visible().w)
            }
            return {ticks, ms: ticks * physicsStepMs, cameraDistance: 12 * rs.visible().w,
                    minRightEdgeBeyondViewport: minAhead, interval: floors[1].elementsIntervalX,
                    elementsAtEnd: floors[1].elements.length, width, scaleBad: scale.bad,
                    spawns: rs.spawns, lethalCallsIgnored: rs.lethalCalls}
        }''')
        width = result['width']
        checks = []
        for s in result['spawns']:
            if mode == 'bad':
                # same check as test_obstacle_spacing.py: random(20%, 30%) of the canvas width
                gap = (s['left'] - s['lastGroupRight']) * result['scaleBad']
                lo, hi = 0.20 * width, 0.30 * width
            else:
                # classic: the group is placed within the floor interval past the anchor
                gap = s['left'] - s['triangleShift'] - s['anchor']
                lo, hi = result['interval']['min'], result['interval']['max']
            ok = lo - 1e-6 <= gap <= hi + 1e-6
            checks.append(dict(s, measuredGap=gap, min=lo, max=hi, passed=ok))
        after = [c for c in checks if c['phase'] != 'before-continue']
        record = {'mode': mode, 'seed': seed, 'respawn': respawn,
                  'physicsMs': result['ms'], 'cameraDistance': result['cameraDistance'],
                  'groupsSpawnedAfterContinue': len(after),
                  'spacingFailures': [c for c in after if not c['passed']],
                  'minRightEdgeBeyondViewport': result['minRightEdgeBeyondViewport'],
                  'elementsAtEnd': result['elementsAtEnd'], 'spawns': after}
        self.replenish.append(record)
        self.assertGreaterEqual(len(after), 5)
        self.assertEqual(record['spacingFailures'], [])
        self.assertGreater(result['minRightEdgeBeyondViewport'], 0)
        print(f'\n  replenish {mode}: {len(after)} groups spawned in 30 s after the continue, '
              f'all gaps within [{after[0]["min"]:.1f}, {after[0]["max"]:.1f}]; floor always reaches '
              f'{result["minRightEdgeBeyondViewport"]:.1f} past the viewport: pass', file=sys.stderr)

    def test_replenish_classic(self):
        self.replenish_check('classic', 303)

    def test_replenish_bad(self):
        self.replenish_check('bad', 404)


if __name__ == '__main__':
    unittest.main()
