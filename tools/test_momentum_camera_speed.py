"""Momentum camera speed through corners (TASK-082 reproduction, TASK-084 fix).

User report (2026-10-18): "The camera moves fast on corners. I don't want
such jumps. I want the same speed of the camera all the time, just change the
direction of the camera in time." The new rule: the camera moves at the
ninja's forward speed like bad mode (moveScreen.js Screen.shouldStartMoveX,
no catch-up bursts) and at a corner its direction turns along a rounded arc
(the rail, TASK-083: the course centre line with every join replaced by a
quarter circle of radius GAMEPLAY.momentumCamera.railRadius view heights,
0.5 until that option exists) with no change of speed caused by the turn.

Course scripts right -> up -> right and right -> down -> right
(test_momentum_shaft_view) give the joins right->up, up->right, right->down
and down->right. With the rAF loop stopped and the obstacle floor emptied,
the invulnerable ninja is held on a path walked at the effective speed cap
(GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1)) per physics cycle,
one calcPhysics() per point: 'centre' along the course centre line through
the join, 'diagonal' along the centre line to a quarter view before the
corner box, then across the box from the old corridor's outer side to the
new one's far side (the TASK-034 shortcut), then on along the next corridor.
An earlier join of the course is taken along the centre line.

Physics is fixed-step (60 ticks of cyclesPerTick cycles a second), so a
frame at 60 fps is one tick and at 30 fps two (maxPhysicsStepsPerFrame): the
per-cycle camera positions of one drive are sampled at both frame rates.
Per frame: the camera velocity (camVx, camVy: the camera top-left world
corner -screen.x/-screen.y, delta over the frame), its speed and direction,
and ninjaAlong, the ninja's forward speed along the course: the most of its
velocity's projections on the rail tangent at its nearest rail point and on
the direction of the course segment it is on (the one whose join arc middle
it has not passed), summed over the frame's cycles (world units a frame). On
the centre drive it is the ninja's speed all the way through the corner.

Assertions over the 3 s around the corner (the frame where the ninja's rail
position passes the join's arc middle, +-1.5 s, WINDOW_S: wider than the
2 s of the ticket so the HEAD burst after a shaft exit is inside; frames before the camera has
moved for a quarter second are skipped, the bad-mode start is a jump from
rest by design), the new rule:
1. no catch-up: |v_cam| <= ninjaAlong * 1.05 + 1 on every frame;
2. no jump: | |v_cam| - previous | <= 0.10 * the ninja's speed (it is
   constant, the cap) plus the change of ninjaAlong itself (on the diagonal
   the projection on the rail changes as the ninja crosses the box);
3. direction turns continuously: with the camera moving (>= 1 unit a frame
   on both frames) its direction angle changes by at most
   90 deg / arcFrames * 1.5 a frame (arcFrames: the quarter arc's length
   over the ninja's speed a frame), and only while the camera is on an arc:
   the rail position of the view centre within [arc start - one frame, arc
   end + one frame]; elsewhere by at most 1 deg;
4. the ninja stays in view with a 0.10 margin of each view dimension;
5. flat through the corner (TASK-084 verification): on the centre drive
   (the ninja's speed along the course is constant) |v_cam| varies by at most
   0.05 x the ninja's speed over the window (the camera moves along the rail,
   shorter than the centre line by the arcs, so it is a few percent slower
   than the ninja all through a segment, not just at its corner); on both
   drives it never stalls: |v_cam| >= ninjaAlong * 0.5 - 1 on every frame
   (across the corner box on the diagonal the ninja moves along the course
   slower than its speed).

All 16 cases failed rules 1-4 on the damped-follow camera (artifacts/
TASK-082/head-fail.log); since TASK-084 the camera rides the rail and they
must pass.
MOMENTUM_CAMERA_SPEED_EVIDENCE_DIR (default
/tmp/momentum-camera-speed: a bare run must not rewrite the TASK-082/084
evidence) receives speed-trace.json (compact {case: {cornerFrame,
fps, window, rows: [[frame, camVx, camVy, camSpeed, ninjaAlong]]}} over the
window)
and camera-speed.json (per case: pass flags, peak |v_cam| / ninjaAlong ratio,
peak speed change, peak turn rate with their frames).
Requires Playwright Chromium.
"""
import json
import math
import os
from pathlib import Path
import sys
import unittest

from browser_test_support import start_browser_test, wait_for_boot_run
from test_momentum_camera import SEED_COURSE
from test_momentum_shaft_view import SCRIPTS

ROOT = Path(__file__).resolve().parents[1]
# join: (course script, index of the segment before the join)
JOINS = {'right-up': ('up', 0), 'right-down': ('down', 0), 'up-right': ('up', 1), 'down-right': ('down', 1)}
DRIVES = ('centre', 'diagonal')
FPS = (60, 30)
# Rule constants (module docstring)
CATCH_UP_RATIO, CATCH_UP_SLACK = 1.05, 1.0
JUMP_RATIO = 0.10
TURN_RATIO = 1.5
STRAIGHT_TURN_DEG = 1.0
MIN_MOVING = 1.0
FLAT_RANGE = 0.05
STALL_RATIO = 0.5
# Seconds either side of the corner checked and traced
WINDOW_S = 1.5
VIEW_MARGIN = 0.10
DEFAULT_RAIL_RADIUS = 0.5
SEGMENT_DIRECTIONS = {'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}

# Builds the course and the path (one point per physics cycle, the effective
# speed cap apart along it, with the unit direction of the path piece)
SETUP = '''([index, route]) => {
    resetCourseScript()
    startGame('momentum')
    cancelAnimationFrame(game)
    floors.find(f => f instanceof MomentumObstacleFloor).elements = []
    const segs = []
    for (let i = 0; i <= index + 2; ++i) {
        const s = momentumCourse.segment(i)
        segs.push({dir: s.dir, x0: s.x0, y0: s.y0, x1: s.x1, y1: s.y1, hw: momentumSegmentHalfWidth(s)})
    }
    const a = segs[index], b = segs[index + 1]
    const vertical = a.dir == 'right' ? b : a
    const W = vertical.hw, H = GAMEPLAY.momentumBorders.halfWidth
    const jx = a.x1, jy = a.y1
    const da = segmentDirection(a.dir), db = segmentDirection(b.dir)
    const view = height / scale[version], viewW = width / scale[version]
    const v = GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1)
    const options = GAMEPLAY.momentumCamera
    const railRadius = (options.railRadius === undefined ? %(radius)s : options.railRadius) * view
    // Polyline: the start, earlier joins, then the join (centre) or the
    // shortcut across the corner box (diagonal), then on along b up to a
    // view short of its end (or 1.7 s of travel)
    const pts = [[ninja.x, segs[0].y0]]
    for (let i = 0; i < index; ++i)
        pts.push([segs[i].x1, segs[i].y1])
    if (route == 'centre')
        pts.push([jx, jy])
    else {
        const sx = da.x + db.x, sy = da.y + db.y
        pts.push([jx - da.x * (W + view / 4), jy - da.y * (H + view / 4)])
        pts.push(a.dir == 'right' ? [jx - W, jy - sy * 0.8 * H] : [jx - sx * 0.8 * W, jy - da.y * H])
        pts.push(b.dir == 'right' ? [jx + W, jy + sy * 0.8 * H] : [jx + sx * 0.8 * W, jy + db.y * H])
    }
    const bLength = Math.hypot(b.x1 - b.x0, b.y1 - b.y0)
    const [ex, ey] = pts[pts.length - 1]
    const on = Math.min(1.7 * physicsTicksPerSecond * cyclesPerTick * v, bLength - view)
    pts.push([ex + db.x * on, ey + db.y * on])
    const path = []
    let carry = 0
    for (let k = 0; k + 1 < pts.length; ++k) {
        const [x0, y0] = pts[k], [x1, y1] = pts[k + 1]
        const len = Math.hypot(x1 - x0, y1 - y0)
        if (len <= 0)
            continue
        const ux = (x1 - x0) / len, uy = (y1 - y0) / len
        let d = carry
        for (; d < len; d += v)
            path.push([x0 + ux * d, y0 + uy * d, ux, uy])
        carry = d - len
    }
    window.speedState = {path, v, n0: ninja, deaths0: lethalDeaths}
    return {segs, join: [jx, jy], pts, view, viewW, v, railRadius, borderX: screen.borderX,
            cyclesPerTick, ticksPerSecond: physicsTicksPerSecond, pathLength: path.length}
}'''

# Holds the ninja on the path, one calcPhysics() per point; per cycle the
# camera top-left world corner and the ninja; stops at cycle 'stop'
RUN = '''(stop) => {
    const st = window.speedState, rows = []
    const end = stop === null ? st.path.length : Math.min(stop + 1, st.path.length)
    for (let i = 0; i < end; ++i) {
        const [x, y, ux, uy] = st.path[i]
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = x; ninja.y = y; ninja.speedX = ux * st.v; ninja.speedY = uy * st.v - GRAVITY
        calcPhysics()
        if (ninja !== st.n0)
            return {gameOver: i, rows}
        rows.push([-screen.x, -screen.y, x, y])
    }
    return {gameOver: null, deaths: lethalDeaths - st.deaths0, rows}
}'''

DRAW = '(() => { visualEffects.screenEffects.landings.length = 0; draw() })()'
# DOM overlay (screenshot only): the ninja and a label
OVERLAY = '''(label) => {
    const rect = canvas.getBoundingClientRect(), k = scale[version] * rect.width / width
    const nx = rect.left + (ninja.x + screen.x) * k, ny = rect.top + (ninja.y + screen.y) * k
    const div = document.createElement('div')
    div.id = 'speed-overlay'
    div.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:99999'
    div.innerHTML = `<svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <circle cx="${nx}" cy="${ny}" r="16" fill="none" stroke="#00ffff" stroke-width="3"/>
        <rect x="8" y="${rect.top + rect.height - 44}" width="1240" height="36" fill="rgba(0,0,0,0.75)"/>
        <text x="16" y="${rect.top + rect.height - 18}" fill="#ffffff" font-family="monospace" font-size="16">${label}</text>
    </svg>`
    document.body.appendChild(div)
}'''
# Camera speed and ninja speed along the rail over the window, drawn on a
# page canvas (no matplotlib here)
PLOT = '''([title, rows, cornerFrame, marks]) => {
    document.body.innerHTML = ''
    const c = document.createElement('canvas')
    c.width = 1280; c.height = 720
    document.body.style.margin = '0'
    document.body.appendChild(c)
    const g = c.getContext('2d')
    g.fillStyle = '#fff'; g.fillRect(0, 0, 1280, 720)
    const L = 90, R = 1240, T = 70, B = 640
    const f0 = rows[0][0], f1 = rows[rows.length - 1][0]
    const top = Math.max(...rows.map(r => Math.max(r[3], r[4]))) * 1.15
    const X = f => L + (f - f0) / (f1 - f0) * (R - L), Y = s => B - s / top * (B - T)
    g.strokeStyle = '#ccc'; g.lineWidth = 1; g.font = '16px monospace'; g.fillStyle = '#333'
    for (let k = 0; k <= 5; ++k) {
        const s = top * k / 5
        g.beginPath(); g.moveTo(L, Y(s)); g.lineTo(R, Y(s)); g.stroke()
        g.fillText(s.toFixed(1), 10, Y(s) + 5)
    }
    for (let f = Math.ceil(f0 / 10) * 10; f <= f1; f += 10)
        g.fillText(String(f), X(f) - 12, B + 22)
    g.fillText('frame (60 fps)   speed: world units / frame', L, B + 50)
    g.strokeStyle = '#888'; g.setLineDash([6, 6])
    g.beginPath(); g.moveTo(X(cornerFrame), T); g.lineTo(X(cornerFrame), B); g.stroke()
    g.fillText('corner', X(cornerFrame) + 4, T + 16)
    g.setLineDash([])
    const line = (k, color) => {
        g.strokeStyle = color; g.lineWidth = 3; g.beginPath()
        rows.forEach((r, i) => i ? g.lineTo(X(r[0]), Y(r[k])) : g.moveTo(X(r[0]), Y(r[k])))
        g.stroke()
    }
    line(4, '#2a7de1'); line(3, '#e1462a')
    for (const [f, s, text] of marks) {
        g.strokeStyle = '#000'; g.lineWidth = 2
        g.beginPath(); g.arc(X(f), Y(s), 9, 0, 2 * Math.PI); g.stroke()
        g.fillStyle = '#000'; g.fillText(text, Math.min(X(f) + 12, 1270 - g.measureText(text).width), Y(s) - 14)
    }
    g.font = 'bold 22px sans-serif'; g.fillStyle = '#000'; g.fillText(title, L, 40)
    g.font = '16px monospace'
    g.fillStyle = '#e1462a'; g.fillRect(R - 330, 82, 24, 6); g.fillStyle = '#333'; g.fillText('camera |v_cam|', R - 300, 90)
    g.fillStyle = '#2a7de1'; g.fillRect(R - 330, 106, 24, 6); g.fillStyle = '#333'; g.fillText('ninja speed along rail', R - 300, 114)
}'''


class Rail:
    """Course centre line through the given vertices, every join replaced by
    a quarter circle of radius r (at most half the shorter adjacent piece)."""

    def __init__(self, vertices, radius):
        self.pieces = []  # ('line', s0, p0, u, length) / ('arc', s0, c, u, w, r)
        self.arcs = []  # (s start, s end, s middle)
        s = 0.0
        prev = vertices[0]
        for k in range(1, len(vertices) - 1):
            a, j, b = vertices[k - 1], vertices[k], vertices[k + 1]
            u, la = self.unit(a, j)
            w, lb = self.unit(j, b)
            r = min(radius, la / 2, lb / 2)
            t1 = (j[0] - u[0] * r, j[1] - u[1] * r)
            s = self.line(s, prev, t1)
            c = (t1[0] + w[0] * r, t1[1] + w[1] * r)
            self.pieces.append(('arc', s, c, u, w, r))
            self.arcs.append((s, s + math.pi / 2 * r, s + math.pi / 4 * r))
            s += math.pi / 2 * r
            prev = (j[0] + w[0] * r, j[1] + w[1] * r)
        self.line(s, prev, vertices[-1])

    @staticmethod
    def unit(p, q):
        length = math.hypot(q[0] - p[0], q[1] - p[1])
        return ((q[0] - p[0]) / length, (q[1] - p[1]) / length), length

    def line(self, s, p, q):
        u, length = self.unit(p, q)
        self.pieces.append(('line', s, p, u, length))
        return s + length

    def project(self, p):
        """(distance, s, tangent) of the nearest rail point"""
        best = None
        for piece in self.pieces:
            if piece[0] == 'line':
                _, s0, a, u, length = piece
                d = min(length, max(0.0, (p[0] - a[0]) * u[0] + (p[1] - a[1]) * u[1]))
                q, s, t = (a[0] + u[0] * d, a[1] + u[1] * d), s0 + d, u
            else:
                _, s0, c, u, w, r = piece
                dx, dy = p[0] - c[0], p[1] - c[1]
                phi = min(math.pi / 2, max(0.0, math.atan2(dx * u[0] + dy * u[1], -(dx * w[0] + dy * w[1]))))
                q = (c[0] + r * (-w[0] * math.cos(phi) + u[0] * math.sin(phi)),
                     c[1] + r * (-w[1] * math.cos(phi) + u[1] * math.sin(phi)))
                s, t = s0 + r * phi, (w[0] * math.sin(phi) + u[0] * math.cos(phi),
                                      w[1] * math.sin(phi) + u[1] * math.cos(phi))
            dist = math.hypot(p[0] - q[0], p[1] - q[1])
            if best is None or dist < best[0] - 1e-9:
                best = (dist, s, t)
        return best


def course_vertices(setup, index):
    """The course segments' vertices from the course start to the end of the
    segment after the join: the game's rail (elements/momentumcamerarail.js)
    caps each arc radius at half of the real adjacent segments, not of the
    driven part of them"""
    segs = setup['segs']
    return [[segs[0]['x0'], segs[0]['y0']]] + [[s['x1'], s['y1']] for s in segs[:index + 2]]


def angle_diff(a, b):
    d = (a - b + 180) % 360 - 180
    return abs(d)


def analyse(setup, index, cycles, fps, route):
    """Per-frame rows and the rule checks over the window around the join"""
    cpf = setup['cyclesPerTick'] * setup['ticksPerSecond'] // fps
    v, view, viewW = setup['v'], setup['view'], setup['viewW']
    rail = Rail(course_vertices(setup, index), setup['railRadius'])
    path = cycles['path']
    rows = cycles['rows']
    segs = setup['segs']
    along, rail_s, centre_s = [], [], []
    for (x, y, ux, uy), row in zip(path, rows):
        _, s, t = rail.project((x, y))
        k = sum(1 for _, _, middle in rail.arcs if s >= middle)
        d = SEGMENT_DIRECTIONS[segs[k]['dir']]
        along.append(max(0.0, (ux * t[0] + uy * t[1]) * v, (ux * d[0] + uy * d[1]) * v))
        rail_s.append(s)
        centre_s.append(rail.project((row[0] + viewW / 2, row[1] + view / 2))[1])
    frames = []
    for k in range(1, len(rows) // cpf):
        e, p = (k + 1) * cpf - 1, k * cpf - 1
        vx, vy = rows[e][0] - rows[p][0], rows[e][1] - rows[p][1]
        frames.append({'frame': k, 'vx': vx, 'vy': vy, 'speed': math.hypot(vx, vy),
                       'along': sum(along[p + 1:e + 1]), 's': rail_s[e], 'cs': centre_s[e],
                       'nx': (rows[e][2] - rows[e][0]) / viewW, 'ny': (rows[e][3] - rows[e][1]) / view})
    ninja_speed = cpf * v
    arc = rail.arcs[index]
    corner = next(f['frame'] for f in frames if f['s'] >= arc[2])
    moving = next(f['frame'] for f in frames if f['speed'] >= MIN_MOVING)
    first = max(corner - WINDOW_S * fps, moving + fps // 4)
    window = [f for f in frames if first <= f['frame'] <= corner + WINDOW_S * fps]
    arc_frames = (math.pi / 2 * setup['railRadius']) / ninja_speed
    turn_limit = 90 / arc_frames * TURN_RATIO
    zones = [(a0 - ninja_speed, a1 + ninja_speed) for a0, a1, _ in rail.arcs]
    result = {'fps': fps, 'cornerFrame': corner, 'window': [window[0]['frame'], window[-1]['frame']],
              'ninjaSpeed': round(ninja_speed, 4), 'turnLimitDeg': round(turn_limit, 3),
              'railRadius': round(setup['railRadius'], 3)}
    catch, jump, turn, out, slow = [], [], [], [], []
    first_out = None
    peak_ratio = peak_jump = peak_turn = min_ratio = None
    for i, f in enumerate(window):
        ratio = f['speed'] / max(f['along'], 1e-9)
        if peak_ratio is None or ratio > peak_ratio[0]:
            peak_ratio = (ratio, f['frame'])
        if min_ratio is None or ratio < min_ratio[0]:
            min_ratio = (ratio, f['frame'])
        if f['speed'] > f['along'] * CATCH_UP_RATIO + CATCH_UP_SLACK:
            catch.append(f['frame'])
        if f['speed'] < f['along'] * STALL_RATIO - CATCH_UP_SLACK:
            slow.append(f['frame'])
        if not (VIEW_MARGIN <= f['nx'] <= 1 - VIEW_MARGIN and VIEW_MARGIN <= f['ny'] <= 1 - VIEW_MARGIN):
            out.append(f['frame'])
            first_out = first_out or [f['frame'], round(f['nx'], 4), round(f['ny'], 4)]
        if not i:
            continue
        g = window[i - 1]
        change = abs(f['speed'] - g['speed'])
        if peak_jump is None or change / ninja_speed > peak_jump[0]:
            peak_jump = (change / ninja_speed, f['frame'])
        if change > JUMP_RATIO * ninja_speed + abs(f['along'] - g['along']) + 1e-9:
            jump.append(f['frame'])
        if f['speed'] >= MIN_MOVING and g['speed'] >= MIN_MOVING:
            d = angle_diff(math.degrees(math.atan2(f['vy'], f['vx'])), math.degrees(math.atan2(g['vy'], g['vx'])))
            on_arc = any(z0 <= f['cs'] <= z1 for z0, z1 in zones)
            if peak_turn is None or d > peak_turn[0]:
                peak_turn = (d, f['frame'], on_arc)
            if d > (turn_limit if on_arc else STRAIGHT_TURN_DEG) + 1e-9:
                turn.append(f['frame'])
    result.update({
        'peakRatio': [round(peak_ratio[0], 4), peak_ratio[1]],
        'minRatio': [round(min_ratio[0], 4), min_ratio[1]],
        'minViewY': round(min(f['ny'] for f in window), 4), 'maxViewY': round(max(f['ny'] for f in window), 4),
        'minViewX': round(min(f['nx'] for f in window), 4), 'maxViewX': round(max(f['nx'] for f in window), 4),
        'peakJump': [round(peak_jump[0], 4), peak_jump[1]],
        'peakTurnDeg': [round(peak_turn[0], 3), peak_turn[1], peak_turn[2]] if peak_turn else None,
        'lastFrame': frames[-1]['frame'], 'firstOutOfView': first_out, 'catchUpFrames': catch, 'jumpFrames': jump, 'turnFrames': turn, 'outOfViewFrames': out,
        'slowFrames': slow, 'speedRange': [round(min(f['speed'] for f in window), 3),
                                           round(max(f['speed'] for f in window), 3)]})
    spread = (result['speedRange'][1] - result['speedRange'][0]) / ninja_speed
    result['speedSpread'] = round(spread, 4)
    result['flat'] = route != 'centre' or spread <= FLAT_RANGE
    trace = [[f['frame'], round(f['vx'], 3), round(f['vy'], 3), round(f['speed'], 3), round(f['along'], 3)]
             for f in window]
    return result, trace


class MomentumCameraSpeedTests(unittest.TestCase):
    drives = {}
    results = {}
    traces = {}

    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('MOMENTUM_CAMERA_SPEED_EVIDENCE_DIR', '/tmp/momentum-camera-speed'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    @classmethod
    def tearDownClass(cls):
        (cls.out / 'speed-trace.json').write_text(json.dumps(cls.traces, separators=(',', ':')) + '\n')
        (cls.out / 'camera-speed.json').write_text(json.dumps(cls.results, separators=(',', ':')) + '\n')

    def open_page(self):
        context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(self.url)
        wait_for_boot_run(page)
        page.evaluate(SEED_COURSE, SCRIPTS[JOINS[self.join][0]])
        return page, errors

    def drive(self, join, route):
        key = (join, route)
        if key not in self.drives:
            self.join = join
            page, errors = self.open_page()
            setup = page.evaluate(SETUP % {'radius': DEFAULT_RAIL_RADIUS}, [JOINS[join][1], route])
            run = page.evaluate(RUN, None)
            run['path'] = page.evaluate('window.speedState.path')
            self.drives[key] = (setup, run, errors)
        return self.drives[key]

    def check(self, join, route, fps):
        setup, run, errors = self.drive(join, route)
        index = JOINS[join][1]
        name = f'{join}-{route}-{fps}'
        self.assertEqual('-'.join(s['dir'] for s in setup['segs'][index:index + 2]), join)
        result, trace = analyse(setup, index, run, fps, route)
        self.results[name] = result
        self.traces[name] = {'cornerFrame': result['cornerFrame'], 'fps': fps, 'window': result['window'],
                             'rows': trace}
        ok = not (result['catchUpFrames'] or result['jumpFrames'] or result['turnFrames'] or result['outOfViewFrames']
                  or result['slowFrames'] or not result['flat'])
        print(f'{name}: {"PASS" if ok else "FAIL"} peak |v_cam|/ninjaAlong {result["peakRatio"][0]} at frame '
              f'{result["peakRatio"][1]}, min {result["minRatio"][0]} at frame {result["minRatio"][1]}, peak speed change {result["peakJump"][0]} x ninja speed at frame '
              f'{result["peakJump"][1]}, peak turn {result["peakTurnDeg"]} deg (limit {result["turnLimitDeg"]}), '
              f'corner frame {result["cornerFrame"]}, window {result["window"]}, frames failing: catch-up '
              f'{len(result["catchUpFrames"])}, jump {len(result["jumpFrames"])}, turn {len(result["turnFrames"])}, '
              f'out of view {len(result["outOfViewFrames"])}, stall {len(result["slowFrames"])}, |v_cam| range '
              f'{result["speedRange"]} = {result["speedSpread"]} x ninja speed, ninja view x '
              f'{result["minViewX"]}..{result["maxViewX"]} y {result["minViewY"]}..{result["maxViewY"]}', file=sys.stderr)
        self.assertEqual(errors, [])
        self.assertIsNone(run['gameOver'])
        self.assertEqual(run['deaths'], 0)
        self.assertEqual(result['catchUpFrames'], [], f'{name}: camera faster than the ninja along the rail '
                                                      f'(peak ratio {result["peakRatio"]})')
        self.assertEqual(result['jumpFrames'], [], f'{name}: camera speed jumps (peak {result["peakJump"]})')
        self.assertEqual(result['turnFrames'], [], f'{name}: camera direction turns too fast or off the arc '
                                                   f'(peak {result["peakTurnDeg"]})')
        self.assertEqual(result['outOfViewFrames'], [], f'{name}: ninja within {VIEW_MARGIN} of the view edge '
                                                        f'(first {result["firstOutOfView"]})')
        self.assertEqual(result['slowFrames'], [], f'{name}: camera stalls (min ratio {result["minRatio"]})')
        self.assertTrue(result['flat'], f'{name}: camera speed not flat through the corner on the centre line '
                                        f'(range {result["speedRange"]}, {result["speedSpread"]} x ninja speed)')


def make_test(join, route, fps):
    def test(self):
        self.check(join, route, fps)
    return test


for i, join in enumerate(JOINS):
    for route in DRIVES:
        for fps in FPS:
            setattr(MomentumCameraSpeedTests, f'test_{chr(97 + i)}_{join.replace("-", "_")}_{route}_{fps}',
                    make_test(join, route, fps))


if __name__ == '__main__':
    unittest.main(verbosity=2)
