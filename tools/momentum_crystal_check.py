"""Momentum Cave Crystal piece checks (TASK-122 .. TASK-127).

Scenes come from tools/momentum_fx_support.py (FxHarness: frozen clock,
seeded R U R D R course, startGame('momentum')). An M frame is placed alone
like test_momentum_frames_h/_v/_turn (momentumPlacePattern centred along the
longest right segment or its shaft, momentumPlaceCorner on its join), the
camera centred on its pieces, the ninja parked far away, the UI layer off;
neonPulse is pinned to 1 before the draw. --rev R captures git rev R
(git archive export); the other side is this checkout.

    python3 momentum_crystal_check.py geometry <out.json> [--rev R]
        getPoints + getCircumscribedCircle of every piece of the 22 M frames
        at 1280x720 and 390x844; with --rev, diffs = pieces that differ
    python3 momentum_crystal_check.py outside <out.json> --rev R
        blue-corner/blue-hit/mid-shaft/run-right at both viewports, FX on:
        pixels outside the piece masks dilated by 2 px (maxDelta,
        differingPixels) and differing pixels inside the blue masks
    python3 momentum_crystal_check.py texture <out.json> --kind blue --frames M04,M24,M66 --rev R
        luminance stddev (0..255) of each piece interior: inside its inset-copy
        polygon (the parent's flat fill) eroded 6 px; the whole piece eroded
        6 px is listed too (the parent's inset outline makes it two-tone)
    python3 momentum_crystal_check.py determinism <out.json>
        two fresh loads of M04 (maxDelta) and one blue piece at two camera
        offsets 37 px apart (crop mean/max |delta| inside the piece)
    python3 momentum_crystal_check.py cache <out.json>
        CRYSTAL_PIECES.stats after a seeded 60 s play (momentum_frames_gallery
        play setup, seed 1, a draw per frame) and builds over 120 frames of a
        static M04 scene after 10 warm-up frames
        --kind green: the piece eroded 6 px minus the lip bands (the HEAD
        free edges' bands dilated 1 px), on both sides; pass = head >= 3x parent
    python3 momentum_crystal_check.py lips <out.json>
        every green piece of the 22 M frames at 1280x720: its edges ('wall',
        'piece' or 'free': piece.crystalEdges, re-derived in Python from the
        course faces and the other pieces), and per edge the fraction of 20
        points whose luminance >= 200 at outlineHalf + 2 px inside the edge
        (in the lip band) and, for the record, at 2 px (under the unchanged
        outline's inner half). The points are spread over the part of t 0.1
        .. 0.9 that lies outside the other edges' outline and lip bands
        (tRange): a free neighbour's lip runs into the shared corner
    python3 momentum_crystal_check.py fade <out.json>
        M23's green used (passThrough) at alpha 1, 0.5 and 0 and removed
        (background): mean interior (eroded 6 px) contribution ratio, alpha 0
        maxDelta inside the piece
    python3 momentum_crystal_check.py shots <dir> --kind blue [--rev R]
        M04/M24/M66-1280x720.png, M66-390x844.png, crop4x-cube.png and
        M04-parent-vs-head.png (needs --rev)
    python3 momentum_crystal_check.py shots <dir> --kind green
        M23/M46/M24-1280x720.png, M134-390x844.png, crop4x-M23-lip.png (the
        ramp slope) and tutorial-legend.png (the momentum hint legend, 3x)
    python3 momentum_crystal_check.py twinkle <out.json>
        M04 at 1280x720, frozen clock, 16 frames at now = t0 + k * 200 ms:
        per glint (canvas px, from CRYSTAL_PIECES.drawGlints) the luminance
        contribution at its centre (glints on minus CRYSTAL_PIECES.glints =
        false, same now); pass = per glint min <= 30% and max >= 90% of its
        own max over the 16 frames, 2..4 glints per piece
    python3 momentum_crystal_check.py glintdiff <out.json>
        M04 at 1280x720: two fresh loads at the same now (maxDelta), and now
        vs now + 400 ms (a third fresh load; each frame is its page's first
        draw): differing pixels outside / inside the union of the glint boxes
        (radius 9 px x stage / 1080 + 1 px)
    python3 momentum_crystal_check.py shots <dir> --kind twinkle
        M04-dim/mid/peak.png (the twinkle times where the first blue corner
        glint is dimmest / halfway / brightest) and crop4x-glint-dim/peak.png
        (4x crop round that glint), each the first draw of a fresh page with
        the render clock held at t0 except in drawGlints; writes
        twinkle-times.json (differing pixels outside the glint boxes vs dim)
--rev BASE is the parent of the TASK-122 game commit 4c9ba46.
Every JSON is compact. Exit status 1 when a pass condition fails.
Requires Playwright Chromium, numpy and Pillow.
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import momentum_fx_support as fxs  # noqa: E402
import render_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IDS = ['M04', 'M23', 'M24', 'M46', 'M47', 'M66',
       'M11', 'M30', 'M93', 'M110', 'M11-up', 'M30-up', 'M93-up', 'M110-up',
       'M18', 'M60', 'M39', 'M117', 'M134', 'M40', 'M98', 'M136']
VIEWPORTS = [(1280, 720), (390, 844)]
DILATE = 2
ERODE = 6
TEXTURE_FLAT_MAX = 1.0
TEXTURE_HEAD_MIN = 15
GREEN_TEXTURE_HEAD_MIN = 12
GREEN_TEXTURE_RATIO = 1.5
LIT = 200
LIP_DEPTH = 2
LIP_FREE_MIN = 0.8
LIP_CONTACT_MAX = 0.1
FADE_TOLERANCE = 0.05
REVS = {'BASE': '4c9ba46~1'}
TWINKLE_FRAMES = 16
TWINKLE_STEP_MS = 200
TWINKLE_DIM_MAX = 0.3
TWINKLE_PEAK_MIN = 0.9
GLINT_BOX_RADIUS = 9
GLINT_DIFF_MS = 400
GLINT_COUNT = (2, 4)
SHIFT_PX = 37
PIN = 'updateNeonPulse = () => { neonPulse = 1 }; neonPulse = 1'

# Places M frame id alone; centres the camera on its pieces. Returns the
# placement (segment, pieces with points, circle and kind)
PLACE = r'''([id, shiftPx]) => {
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor) {
            f.elements = []
            if (f.groups) f.groups = []
        }
    const course = momentumCourse
    let segment
    if (typeof momentumCornerFrameFactories != 'undefined' && momentumCornerFrameFactories[id]) {
        const join = momentumCornerFrameFactories[id].join
        for (let i = 0; i < 5; ++i)
            if (course.segment(i).dir + '->' + course.segment(i + 1).dir == join) { segment = i; break }
        if (!momentumPlaceCorner(id, segment)) throw new Error('corner ' + id)
    } else {
        const dir = id.endsWith('-up') ? 'up' : (momentumPatternFactories[id].dirs || ['right']).includes('right') ? 'right' : 'down'
        let best = null
        for (let i = 0; i < 5; ++i) {
            const s = course.segment(i)
            if (s.dir != dir) continue
            const len = Math.abs(s.x1 - s.x0) + Math.abs(s.y1 - s.y0)
            if (!best || len > best.len) best = {i, s, len}
        }
        segment = best.i
        const s = best.s, f = momentumPatternFactories[id]
        let r
        if (dir == 'right') {
            const length = f.getLength(momentumShaftHalfWidth())
            r = momentumPlacePattern(id, (s.x0 + s.x1) / 2 - length / 2, s.y0, 'right')
        } else {
            const half = momentumSegmentHalfWidth(s), length = f.getLength(half)
            const mid = (s.y0 + s.y1) / 2
            r = momentumPlacePattern(id, s.x0, dir == 'up' ? mid + length / 2 : mid - length / 2, dir, half)
        }
        if (!r) throw new Error('pattern ' + id)
    }
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const e of floor.elements) {
        const b = getElementBounds(e)
        x0 = Math.min(x0, b.left); y0 = Math.min(y0, b.top); x1 = Math.max(x1, b.right); y1 = Math.max(y1, b.bottom)
    }
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
    const vw = width / scale[version], vh = height / scale[version]
    const k = canvas.width / width * scale[version]
    screen.x = -(cx - vw / 2) + (shiftPx || 0) / k; screen.y = -(cy - vh / 2)
    screen.segmentIndex = segment
    screen.leftWall.update(screen)
    for (const f of floors)
        if (f instanceof MomentumBorderFloor)
            f.replenishElements()
    grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
    ninja.x = cx; ninja.y = cy - 1e5; ninja.speedX = ninja.speedY = 0
    ninja.track.pos = []
    drawUILayer = drawFpsCounterLayer = () => {}
    const r2 = v => Math.round(v * 1e6) / 1e6
    return {segment: segment, pieces: floor.elements.map(e => {
        const c = e.getCircumscribedCircle()
        return {kind: e instanceof MomentumBlue ? 'blue' : 'green',
                points: e.getPoints().map(p => [r2(p.x), r2(p.y)]), circle: [r2(c.x), r2(c.y), r2(c.radius)]}
    })}
}'''

# Draw (neonPulse pinned) and the pieces' polygons in canvas px
DRAW = r'''() => {
    updateNeonPulse = () => { neonPulse = 1 }
    neonPulse = 1
    draw()
    const k = canvas.width / width * scale[version]
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    return {k: k, canvas: [canvas.width, canvas.height],
        outlineHalf: STYLE.strokes.neonOutline.width / scale[version] * k / 2,
        segments: momentumCourse.segments.map(s => ({dir: s.dir, x0: s.x0, y0: s.y0, x1: s.x1, y1: s.y1,
            halfWidth: s.dir == 'right' ? GAMEPLAY.momentumBorders.halfWidth : s.halfWidth === undefined ? null : s.halfWidth})),
        pieces: floor.elements.map(e => ({
        kind: e instanceof MomentumBlue ? 'blue' : 'green', edges: e.crystalEdges || null,
        world: e.getPoints().map(p => [p.x, p.y]),
        poly: e.getPoints().map(p => [(p.x + screen.x) * k, (p.y + screen.y) * k]),
        inner: e.getInnerPoints(STYLE.badVersionEffects.obstacles.innerCopyInsetRatio)
            .map(p => [(p.x + screen.x) * k, (p.y + screen.y) * k])}))}
}'''


def sha(rev):
    return subprocess.check_output(['git', 'rev-parse', rev], cwd=ROOT, text=True).strip()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(',', ':')))
    print(path, json.dumps(data, separators=(',', ':'))[:600])


def snap(page):
    png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGB'))


def capture_frame(rev, id, viewport, shift=0):
    """(RGB array, draw info, placement) of M frame id on a fresh page"""
    fx = fxs.harness(rev)
    context, page = fx.open(viewport)
    try:
        placed = page.evaluate(PLACE, [id, shift])
        info = page.evaluate(DRAW)
        img = snap(page)
        if page.errors:
            raise RuntimeError(f'page errors {rev} {id} {viewport}: {page.errors}')
    finally:
        context.close()
    return img, info, placed


def polygon_mask(shape, polys):
    image = Image.new('1', (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(image)
    for poly in polys:
        draw.polygon([tuple(p) for p in poly], fill=1, outline=1)
    return np.asarray(image, dtype=bool)


def dilate(mask, n):
    out = mask.copy()
    for _ in range(n):
        m = out.copy()
        m[1:] |= out[:-1]; m[:-1] |= out[1:]
        m[:, 1:] |= out[:, :-1]; m[:, :-1] |= out[:, 1:]
        out = m
    return out


def erode(mask, n):
    return ~dilate(~mask, n)


def luminance255(img):
    return np.asarray(img, dtype=np.float64)[..., :3] @ np.array([0.2126, 0.7152, 0.0722])


# Frame at now (ms; null keeps the clock) with glints on or off: the glints
# drawn (CRYSTAL_PIECES.drawGlints calls) with their alpha at now. Like
# neonPulse, the ambient motes' drift and twinkle are pinned (to the clock
# at the first call), so only the glints follow now. pinAll (the shots) holds
# the whole render clock there too, except inside CRYSTAL_PIECES.drawGlints
GLINT_DRAW = r'''([now, on, pinAll]) => {
    const particles = visualEffects.particles
    if (window.__motesPinnedAt === undefined) {
        const pinned = window.__motesPinnedAt = performance.now()
        const layout = particles.layoutAmbientMotes
        particles.layoutAmbientMotes = function(...args) {
            const real = performance.now
            performance.now = () => pinned
            try { return layout.apply(this, args) } finally { performance.now = real }
        }
    }
    if (now !== null) __snap.now = now
    updateNeonPulse = () => { neonPulse = 1 }
    neonPulse = 1
    const drawn = []
    const original = CRYSTAL_PIECES.drawGlints
    CRYSTAL_PIECES.glints = on
    CRYSTAL_PIECES.drawGlints = function(piece, sprite, alpha) {
        const pinned = performance.now
        performance.now = real
        const floor = floors.find(f => f instanceof MomentumPatternFloor)
        drawn.push({piece: floor.elements.indexOf(piece), kind: piece instanceof MomentumBlue ? 'blue' : 'green',
            glints: this.glintPoints(piece, sprite).map(g => ({x: g.x, y: g.y, period: g.period, phase: g.phase,
                alpha: alpha * this.glintAlpha([0, 0, g.period, g.phase], performance.now())}))})
        try { return original.call(this, piece, sprite, alpha) } finally { performance.now = pinned }
    }
    const real = performance.now
    if (pinAll) performance.now = () => window.__motesPinnedAt
    try { draw() } finally {
        performance.now = real; CRYSTAL_PIECES.drawGlints = original; CRYSTAL_PIECES.glints = true
    }
    return {now: performance.now(), motesPinnedAt: window.__motesPinnedAt, drawn: drawn, stage: Math.min(canvas.width, canvas.height),
        canvas: [canvas.width, canvas.height]}
}'''


def open_m04():
    context, page = fxs.harness('worktree').open((1280, 720))
    page.evaluate(PLACE, ['M04', 0])
    return context, page


def glint_frame(page, now, on=True, pin_all=False):
    info = page.evaluate(GLINT_DRAW, [now, on, pin_all])
    return snap(page), info


def twinkle_series(page, pin_all=False):
    """t0, per frame (now, on image, off image, info)"""
    t0 = page.evaluate('() => performance.now()')
    frames = []
    for k in range(TWINKLE_FRAMES):
        now = t0 + k * TWINKLE_STEP_MS
        on, info = glint_frame(page, now, True, pin_all)
        off, _ = glint_frame(page, now, False, pin_all)
        frames.append((now, on, off, info))
    return t0, frames


def glint_rows(frames):
    """Per glint: piece, kind, position, contributions and alphas over frames"""
    rows = []
    first = frames[0][3]['drawn']
    for d, piece in enumerate(first):
        for g, glint in enumerate(piece['glints']):
            x, y = int(round(glint['x'])), int(round(glint['y']))
            contrib, alphas = [], []
            for now, on, off, info in frames:
                same = info['drawn'][d]['glints'][g]
                assert (round(same['x'], 3), round(same['y'], 3)) == (round(glint['x'], 3), round(glint['y'], 3))
                contrib.append(round(float(luminance255(on[y, x]) - luminance255(off[y, x])), 3))
                alphas.append(round(same['alpha'], 4))
            rows.append({'piece': piece['piece'], 'kind': piece['kind'], 'glint': g, 'x': x, 'y': y,
                         'period': round(glint['period'], 2), 'phase': round(glint['phase'], 4),
                         'contribution': contrib, 'alpha': alphas})
    return rows


def cmd_twinkle(args):
    context, page = open_m04()
    try:
        t0, frames = twinkle_series(page)
        if page.errors:
            raise RuntimeError(page.errors)
    finally:
        context.close()
    rows = glint_rows(frames)
    ok = len(rows) > 0
    for row in rows:
        c = row['contribution']
        top = max(c)
        row.update(max=top, minFraction=round(min(c) / top, 4) if top > 0 else None,
                   dimFrame=int(np.argmin(c)), peakFrame=int(np.argmax(c)))
        row['pass'] = top > 0 and min(c) <= TWINKLE_DIM_MAX * top and \
            any(v >= TWINKLE_PEAK_MIN * top for i, v in enumerate(c) if i != row['dimFrame'])
        ok = ok and row['pass']
    counts = {}
    for row in rows:
        counts[row['piece']] = counts.get(row['piece'], 0) + 1
    count_ok = all(GLINT_COUNT[0] <= n <= GLINT_COUNT[1] for n in counts.values())
    ok = ok and count_ok and len(counts) == len(frames[0][3]['drawn'])
    write(args.out, {'rev': fxs.harness('worktree').rev, 'frame': 'M04', 'viewport': '1280x720', 't0': t0,
                     'stepMs': TWINKLE_STEP_MS, 'nows': [f[0] for f in frames],
                     'criterion': 'per glint: contribution = lum(glints on) - lum(CRYSTAL_PIECES.glints = false) at '
                                  'its centre pixel, same now; min <= %s x max and another frame >= %s x max, max = '
                                  'the glint\'s own max over the %s frames; %s..%s glints per piece'
                                  % (TWINKLE_DIM_MAX, TWINKLE_PEAK_MIN, TWINKLE_FRAMES, *GLINT_COUNT),
                     'glintsPerPiece': {str(k): v for k, v in counts.items()}, 'glintCountPass': count_ok,
                     'glints': len(rows), 'rows': rows, 'pass': ok})
    return 0 if ok else 1


def fresh_glint_frame(later_ms=0):
    """(image, info) of the first draw of a fresh M04 page at its t0 + later_ms
    (each frame its first draw: the backdrop's own per-draw state is equal)"""
    context, page = open_m04()
    try:
        now = page.evaluate('() => performance.now()')
        img, info = glint_frame(page, now + later_ms)
        if page.errors:
            raise RuntimeError(page.errors)
    finally:
        context.close()
    return img, info


def cmd_glintdiff(args):
    a, info = fresh_glint_frame()
    again, _ = fresh_glint_frame()
    later, info_later = fresh_glint_frame(GLINT_DIFF_MS)
    reload_delta = fxs.max_delta(a, again)
    radius = GLINT_BOX_RADIUS * info['stage'] / 1080 + 1
    boxes = np.zeros(a.shape[:2], dtype=bool)
    listed = []
    for d in info['drawn'] + info_later['drawn']:
        for g in d['glints']:
            x0, y0 = int(np.floor(g['x'] - radius)), int(np.floor(g['y'] - radius))
            x1, y1 = int(np.ceil(g['x'] + radius)), int(np.ceil(g['y'] + radius))
            boxes[max(0, y0):max(0, y1 + 1), max(0, x0):max(0, x1 + 1)] = True
            listed.append([round(g['x'], 2), round(g['y'], 2)])
    diff = np.abs(a.astype(np.int16) - later.astype(np.int16)).max(axis=2) > 0
    result = {'rev': fxs.harness('worktree').rev, 'frame': 'M04', 'viewport': '1280x720', 'now': info['now'],
              'later': info_later['now'], 'reloadMaxDelta': reload_delta, 'boxRadiusPx': round(radius, 3),
              'glintCentres': listed[:len(listed) // 2], 'boxPixels': int(boxes.sum()),
              'differingPixelsOutsideGlintBoxes': int((diff & ~boxes).sum()),
              'differingPixelsInside': int((diff & boxes).sum()),
              'criterion': 'reloadMaxDelta == 0 (two loads, same now); now vs now + %s ms: differing pixels outside '
                           'the glint boxes (radius %s px x stage / 1080 + 1 px) == 0, inside > 0'
                           % (GLINT_DIFF_MS, GLINT_BOX_RADIUS),
              'pinned': 'neonPulse = 1 and the ambient motes\' clock (layoutAmbientMotes) at the first frame\'s '
                        'now (pre-existing background animation, also on BASE); the glints follow now'}
    result['pass'] = reload_delta == 0 and result['differingPixelsOutsideGlintBoxes'] == 0 and \
        result['differingPixelsInside'] > 0
    write(args.out, result)
    return 0 if result['pass'] else 1


def cmd_shots_twinkle(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    context, page = open_m04()
    try:
        # Only the glints change between the shots (the rest of the render
        # clock is held at t0: the backdrop's own time animation stays put)
        t0, frames = twinkle_series(page, pin_all=True)
        if page.errors:
            raise RuntimeError(page.errors)
    finally:
        context.close()
    rows = glint_rows(frames)
    # The first blue corner glint (glints 0 and 1 of a blue are its corners)
    row = next(r for r in rows if r['kind'] == 'blue' and r['glint'] == 0)
    c = np.array(row['contribution'])
    # mid: the frame closest to halfway between the dimmest and the brightest
    picks = {'dim': int(np.argmin(c)), 'mid': int(np.argmin(np.abs(c - (c.min() + c.max()) / 2))),
             'peak': int(np.argmax(c))}
    # Each shot is the first draw of a fresh page (the series' frames carry
    # the backdrop's own per-draw state, which changes with the draw count)
    images = {}
    for name, k in picks.items():
        context, page = open_m04()
        try:
            images[name], _ = glint_frame(page, frames[k][0], True, True)
            if page.errors:
                raise RuntimeError(page.errors)
        finally:
            context.close()
        fxs.save_png(images[name], out / f'M04-{name}.png')
    half = 20
    for name in ('dim', 'peak'):
        img = images[name]
        crop = Image.fromarray(img[row['y'] - half:row['y'] + half + 1, row['x'] - half:row['x'] + half + 1])
        crop.resize((crop.width * 4, crop.height * 4), Image.NEAREST).save(out / f'crop4x-glint-{name}.png')
    times = {name: {'frame': k, 'now': frames[k][0], 'contribution': row['contribution'][k], 'alpha': row['alpha'][k]}
             for name, k in picks.items()}
    shots = [images[name] for name in picks]
    boxes = np.zeros(shots[0].shape[:2], dtype=bool)
    radius = GLINT_BOX_RADIUS * frames[0][3]['stage'] / 1080 + 1
    for d in frames[0][3]['drawn']:
        for g in d['glints']:
            boxes[int(np.floor(g['y'] - radius)):int(np.ceil(g['y'] + radius)) + 1,
                  int(np.floor(g['x'] - radius)):int(np.ceil(g['x'] + radius)) + 1] = True
    outside = [int((np.abs(shots[0].astype(np.int16) - s.astype(np.int16)).max(axis=2)[~boxes] > 0).sum())
               for s in shots[1:]]
    write(out.parent / 'twinkle-times.json', {'rev': fxs.harness('worktree').rev, 't0': t0, 'glint': row, 'picks': times,
                                              'cropHalfPx': half, 'pinAll': True,
                                              'differingOutsideGlintBoxesVsDim': dict(zip(['mid', 'peak'], outside))})
    print(sorted(p.name for p in out.glob('*.png')))
    return 0


def cmd_geometry(args):
    def collect(rev):
        out = {}
        for vp in VIEWPORTS:
            fx = fxs.harness(rev)
            context, page = fx.open(vp)
            try:
                for id in IDS:
                    out[f'{id}@{vp[0]}x{vp[1]}'] = page.evaluate(PLACE, [id, 0])['pieces']
                if page.errors:
                    raise RuntimeError(page.errors)
            finally:
                context.close()
        return out
    head = collect('worktree')
    result = {'rev': fxs.harness('worktree').rev, 'frames': len(head),
              'pieces': sum(len(v) for v in head.values()),
              'blues': sum(p['kind'] == 'blue' for v in head.values() for p in v)}
    ok = result['pieces'] >= 44 and result['frames'] == 2 * len(IDS)
    if args.rev:
        parent = collect(args.rev)
        diffs = []
        for key, pieces in head.items():
            other = parent.get(key)
            if other is None or len(other) != len(pieces):
                diffs.append([key, 'count'])
                continue
            for i, (a, b) in enumerate(zip(pieces, other)):
                if a != b:
                    diffs.append([key, i])
        result.update(parent=sha(args.rev), diffs=len(diffs), diffList=diffs[:20])
        ok = ok and not diffs
    result['pass'] = ok
    write(args.out, result)
    return 0 if ok else 1


def cmd_outside(args):
    rows = []
    ok = True
    for scene in fxs.SCENES:
        for vp in VIEWPORTS:
            a = fxs.capture(scene, vp, True, PIN)
            b = fxs.capture(scene, vp, True, PIN, rev=args.rev)
            pieces = a.info['pieces']
            mask = dilate(polygon_mask(a.shape, [p['poly'] for p in pieces]), DILATE)
            blue = polygon_mask(a.shape, [p['poly'] for p in pieces if p['kind'] == 'blue'])
            green = polygon_mask(a.shape, [p['poly'] for p in pieces if p['kind'] == 'green'])
            diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
            outside = diff[~mask]
            row = {'scene': scene, 'viewport': f'{vp[0]}x{vp[1]}',
                   'maxDelta': int(outside.max()) if outside.size else 0,
                   'differingPixels': int((outside > 0).sum()),
                   'bluePieces': sum(p['kind'] == 'blue' for p in pieces),
                   'blueMaskPixels': int(blue.sum()), 'insideBlueDiffering': int((diff[blue] > 0).sum()),
                   'greenPieces': sum(p['kind'] == 'green' for p in pieces),
                   'greenMaskPixels': int(green.sum()), 'insideGreenDiffering': int((diff[green] > 0).sum())}
            row['pass'] = row['maxDelta'] == 0 and row['differingPixels'] == 0 and \
                (row['blueMaskPixels'] == 0 or row['insideBlueDiffering'] > 0)
            ok = ok and row['pass']
            rows.append(row)
            print(row, flush=True)
    write(args.out, {'rev': fxs.harness('worktree').rev, 'parent': sha(args.rev), 'dilatePx': DILATE,
                     'captures': rows, 'pass': ok})
    return 0 if ok else 1


def interior_stddevs(img, info, kind):
    """Per piece of kind: (index, stddev inside the inset-copy polygon eroded
    6 px, its pixels, stddev of the whole piece eroded 6 px). The parent's
    blue is two-tone (outer fill, inset copy and its bright outline at
    innerCopyInsetRatio), so only inside the inset copy is it a flat fill"""
    lum = luminance255(img)
    out = []
    for i, p in enumerate(info['pieces']):
        if p['kind'] != kind:
            continue
        m = erode(polygon_mask(img.shape, [p['inner']]), ERODE)
        whole = erode(polygon_mask(img.shape, [p['poly']]), ERODE)
        out.append((i, float(lum[m].std()) if m.any() else None, int(m.sum()),
                    float(lum[whole].std()) if whole.any() else None))
    return out


def winding(poly):
    n = len(poly)
    return 1 if sum(poly[j][0] * poly[(j + 1) % n][1] - poly[(j + 1) % n][0] * poly[j][1] for j in range(n)) > 0 else -1


def inward(a, b, sign):
    u = (b - a) / np.hypot(*(b - a))
    return np.array([-u[1] * sign, u[0] * sign])


def lip_mask(shape, info, piece):
    """Lip bands of piece's free edges (HEAD info): depth outlineHalf ..
    outlineHalf + 4 px x max(1, stage / 1080) inside each edge, dilated 1 px"""
    poly = np.array(piece['poly'])
    outer = info['outlineHalf'] + 4 * max(1.0, min(info['canvas']) / 1080)
    mask = np.zeros(shape[:2], dtype=bool)
    sign = winding(poly)
    for i, kind in enumerate(piece['edges'] or []):
        if kind != 'free':
            continue
        a, b = poly[i], poly[(i + 1) % len(poly)]
        n = inward(a, b, sign)
        mask |= polygon_mask(shape, [[a + n * info['outlineHalf'], b + n * info['outlineHalf'], b + n * outer, a + n * outer]])
    return dilate(mask & polygon_mask(shape, [poly]), 1)


def cmd_texture_green(args):
    rows = []
    ok = True
    for id in args.frames.split(','):
        a, ia, _ = capture_frame('worktree', id, (1280, 720))
        b, _, _ = capture_frame(args.rev, id, (1280, 720))
        la, lb = luminance255(a), luminance255(b)
        for i, p in enumerate(ia['pieces']):
            if p['kind'] != 'green':
                continue
            m = erode(polygon_mask(a.shape, [p['poly']]), ERODE) & ~lip_mask(a.shape, ia, p)
            head, parent = round(float(la[m].std()), 3), round(float(lb[m].std()), 3)
            row = {'frame': id, 'piece': i, 'pixels': int(m.sum()), 'head': head, 'parent': parent,
                   'ratio': round(head / parent, 3) if parent else 'inf'}
            row['pass'] = head >= GREEN_TEXTURE_HEAD_MIN and head >= GREEN_TEXTURE_RATIO * parent
            ok = ok and row['pass']
            rows.append(row)
    ok = ok and len(rows) > 0
    write(args.out, {'kind': 'green', 'viewport': '1280x720', 'erodePx': ERODE,
                     'region': 'the piece eroded erodePx minus the lip bands of its free edges (dilated 1 px), same mask on both sides',
                     'criterion': 'per row: head >= %s and head >= %s x parent' % (GREEN_TEXTURE_HEAD_MIN, GREEN_TEXTURE_RATIO),
                     'rev': fxs.harness('worktree').rev, 'parent': sha(args.rev), 'rows': rows, 'pass': ok})
    return 0 if ok else 1


def edge_contacts(piece, others, segments):
    """Python re-derivation of piece.crystalEdges from world points"""
    pts = np.array(piece['world'])
    right = [s['halfWidth'] for s in segments if s['dir'] == 'right']
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        kind = 'free'
        for s in segments:
            hw = s['halfWidth']
            if hw is None:
                continue
            tol, margin = 1e-5 * 2 * hw, 4 * hw
            ax, al = (1, 0) if s['dir'] == 'right' else (0, 1)
            ends = [(s['x0'], s['x1']), (s['y0'], s['y1'])][al]
            if max(a[al], b[al]) < min(ends) - margin or min(a[al], b[al]) > max(ends) + margin:
                continue
            centre = [s['x0'], s['y0']][ax]
            if any(abs(a[ax] - f) < tol and abs(b[ax] - f) < tol for f in (centre - hw, centre + hw)):
                kind = 'wall'
        if kind == 'free':
            tol = 1e-5 * 2 * right[0]
            length = np.hypot(*(b - a))
            u = (b - a) / length
            for o in others:
                q = np.array(o['world'])
                for j in range(len(q)):
                    c, d = q[j], q[(j + 1) % len(q)]
                    if max(abs((p[0] - a[0]) * u[1] - (p[1] - a[1]) * u[0]) for p in (c, d)) > tol:
                        continue
                    tc, td = (c - a) @ u, (d - a) @ u
                    if min(length, max(tc, td)) - max(0, min(tc, td)) > tol:
                        kind = 'piece'
        out.append(kind)
    return out


def edge_samples(poly, e, depth, margin):
    """20 points depth px inside edge e of poly, evenly over the stretch whose
    points are at least margin px inside every other edge (off the other
    edges' outline and lip bands, which reach into the corners), clipped to
    t 0.1 .. 0.9; returns (points, [t0, t1])"""
    sign = winding(poly)
    a, b = poly[e], poly[(e + 1) % len(poly)]
    n = inward(a, b, sign)
    others = []
    for j in range(len(poly)):
        if j != e:
            c, d = poly[j], poly[(j + 1) % len(poly)]
            others.append((c, inward(c, d, sign)))
    ok = [t for t in np.linspace(0.1, 0.9, 801)
          if all((a + (b - a) * t + n * depth - c) @ m >= margin for c, m in others)]
    t0, t1 = (ok[0], ok[-1]) if ok else (0.5, 0.5)
    ts = [t0 + (t1 - t0) * (k + 0.5) / 20 for k in range(20)]
    return [a + (b - a) * t + n * depth for t in ts], [round(float(t0), 3), round(float(t1), 3)]


def edge_fraction(lum, points):
    """Fraction of points whose luminance >= LIT"""
    return sum(int(lum[int(q[1]), int(q[0])] >= LIT) for q in points) / len(points)


def cmd_lips(args):
    rows = []
    ok = True
    for id in IDS:
        img, info, _ = capture_frame('worktree', id, (1280, 720))
        lum = luminance255(img)
        depth = info['outlineHalf'] + LIP_DEPTH
        # Past the other edges' outline and lip bands (lip_mask's outer depth) plus 1 px
        margin = info['outlineHalf'] + 4 * max(1.0, min(info['canvas']) / 1080) + 1
        for i, p in enumerate(info['pieces']):
            if p['kind'] != 'green':
                continue
            derived = edge_contacts(p, [o for j, o in enumerate(info['pieces']) if j != i], info['segments'])
            poly = np.array(p['poly'])
            edges = []
            piece_ok = p['edges'] == derived
            for e, kind in enumerate(p['edges']):
                a, b = poly[e], poly[(e + 1) % len(poly)]
                points, span = edge_samples(poly, e, depth, margin)
                lit = edge_fraction(lum, points)
                edge = {'edge': e, 'kind': kind, 'a': [round(float(v), 2) for v in a],
                        'b': [round(float(v), 2) for v in b], 'litFraction': lit, 'tRange': span,
                        'litFraction2px': edge_fraction(lum, edge_samples(poly, e, LIP_DEPTH, margin)[0])}
                edge['pass'] = bool(lit >= LIP_FREE_MIN if kind == 'free' else lit <= LIP_CONTACT_MAX)
                piece_ok = piece_ok and edge['pass']
                edges.append(edge)
            rows.append({'frame': id, 'piece': i, 'freeEdges': [[e['a'], e['b']] for e in edges if e['kind'] == 'free'],
                         'edges': edges, 'geometryAgrees': p['edges'] == derived, 'pass': piece_ok})
            ok = ok and piece_ok
            print(id, i, [(e['kind'], e['litFraction']) for e in edges], flush=True)

    def kinds(frame):
        return [sorted(e['kind'] for e in r['edges']) for r in rows if r['frame'] == frame]
    # M23 ramp: slope and vertical side free, floor on the wall face; M46: that ramp and the cap on the blue
    expect = {'M23ramp': ['free', 'free', 'wall'] in kinds('M23'),
              'M46ramp': ['free', 'free', 'wall'] in kinds('M46'),
              'M46cap': ['free', 'free', 'free', 'piece'] in kinds('M46')}
    ok = ok and all(expect.values()) and len(rows) > 0
    write(args.out, {'rev': fxs.harness('worktree').rev, 'viewport': '1280x720', 'frames': len(IDS),
                     'framesWithGreens': len({r['frame'] for r in rows}), 'greenPieces': len(rows), 'lit': LIT,
                     'depth': 'outlineHalf + %s px; outlineHalf = %s px at 1280x720 is the inner half of the unchanged '
                              'neon outline, drawn on top of the lip, so litFraction2px reads the outline itself on '
                              'every edge' % (LIP_DEPTH, round(depth - LIP_DEPTH, 3)),
                     'criterion': 'free litFraction >= %s, wall/piece litFraction <= %s, edges == Python re-derivation; '
                                  'samples over tRange: t 0.1 .. 0.9 minus the stretch within outlineHalf + 4 px + 1 px '
                                  'of another edge' % (LIP_FREE_MIN, LIP_CONTACT_MAX),
                     'expect': expect, 'rows': rows, 'pass': ok})
    return 0 if ok else 1


FADE = r'''(alpha) => {
    const floor = floors.find(f => f instanceof MomentumPatternFloor)
    const green = floor.elements.find(e => e instanceof MomentumGreen)
    if (alpha === null) {
        floor.elements = floor.elements.filter(e => e !== green)
        return null
    }
    green.passThrough = true
    green.fadeStartMs = performance.now() - (1 - alpha) * GAMEPLAY.momentumFadeMs
    green.faded = false
    return green.getAlpha()
}'''


def cmd_fade(args):
    shots = {}
    for alpha in (None, 1.0, 0.5, 0.0):
        context, page = fxs.harness('worktree').open((1280, 720))
        try:
            page.evaluate(PLACE, ['M23', 0])
            got = page.evaluate(FADE, alpha)
            info = page.evaluate(DRAW)
            shots[alpha] = (np.asarray(snap(page), dtype=np.float64), info, got)
            if page.errors:
                raise RuntimeError(page.errors)
        finally:
            context.close()
    bg = shots[None][0]
    green = next(p for p in shots[1.0][1]['pieces'] if p['kind'] == 'green')
    piece = polygon_mask(bg.shape, [green['poly']])
    interior = erode(piece, ERODE)
    lum = {a: luminance255(v[0]) for a, v in shots.items()}
    full = float((lum[1.0][interior] - lum[None][interior]).mean())
    half = float((lum[0.5][interior] - lum[None][interior]).mean())
    full_rgb = (shots[1.0][0][interior] - bg[interior]).mean(axis=0)
    half_rgb = (shots[0.5][0][interior] - bg[interior]).mean(axis=0)
    zero = int(np.abs(shots[0.0][0] - bg).max(axis=2)[dilate(piece, DILATE)].max())
    result = {'rev': fxs.harness('worktree').rev, 'frame': 'M23', 'viewport': '1280x720',
              'alphas': {str(a): v[2] for a, v in shots.items() if a is not None},
              'interiorPixels': int(interior.sum()), 'meanContributionFull': round(full, 3),
              'meanContributionHalf': round(half, 3), 'ratio': round(half / full, 4),
              'ratioRGB': [round(float(h / f), 4) for h, f in zip(half_rgb, full_rgb)],
              'alpha0MaxDeltaInPiece': zero,
              'criterion': 'ratio = mean(lum(alpha 0.5) - lum(background)) / mean(lum(alpha 1) - lum(background)) '
                           'over the piece eroded %s px, 0.5 +- %s; alpha 0: maxDelta 0 vs the background over the '
                           'piece dilated %s px' % (ERODE, FADE_TOLERANCE, DILATE)}
    result['pass'] = abs(result['ratio'] - 0.5) <= FADE_TOLERANCE and zero == 0 and \
        shots[0.5][2] == 0.5 and shots[1.0][2] == 1 and shots[0.0][2] == 0
    write(args.out, result)
    return 0 if result['pass'] else 1


def cmd_texture(args):
    if args.kind == 'green':
        return cmd_texture_green(args)
    rows = []
    ok = True
    for id in args.frames.split(','):
        a, ia, _ = capture_frame('worktree', id, (1280, 720))
        b, ib, _ = capture_frame(args.rev, id, (1280, 720))
        for (i, head, px, head_whole), (_, parent, _, parent_whole) in zip(
                interior_stddevs(a, ia, args.kind), interior_stddevs(b, ib, args.kind)):
            head, parent = round(head, 3), round(parent, 3)
            # Region F (the parent's flat fill) has no meaningful ratio; both regions use absolute floors
            row = {'frame': id, 'piece': i, 'pixels': px, 'head': head, 'parent': parent,
                   'wholePieceHead': round(head_whole, 3), 'wholePieceParent': round(parent_whole, 3)}
            row['pass'] = parent <= TEXTURE_FLAT_MAX and head >= TEXTURE_HEAD_MIN \
                and row['wholePieceHead'] >= TEXTURE_HEAD_MIN
            ok = ok and row['pass']
            rows.append(row)
    ok = ok and len(rows) > 0
    write(args.out, {'kind': args.kind, 'viewport': '1280x720', 'erodePx': ERODE,
                     'region': 'head/parent = region F, the inset-copy polygon (innerCopyInsetRatio) eroded erodePx; '
                               'wholePiece* = region W, the piece eroded erodePx',
                     'criterion': 'per row: parent <= %s and head >= %s (region F), wholePieceHead >= %s (region W); '
                                  'no ratio to the parent' % (TEXTURE_FLAT_MAX, TEXTURE_HEAD_MIN, TEXTURE_HEAD_MIN),
                     'rev': fxs.harness('worktree').rev, 'parent': sha(args.rev), 'rows': rows, 'pass': ok})
    return 0 if ok else 1


def cmd_determinism(args):
    a, ia, _ = capture_frame('worktree', 'M04', (1280, 720))
    b, _, _ = capture_frame('worktree', 'M04', (1280, 720))
    reload_delta = fxs.max_delta(a, b)
    c, ic, _ = capture_frame('worktree', 'M04', (1280, 720), SHIFT_PX)
    blues = [i for i, p in enumerate(ia['pieces']) if p['kind'] == 'blue']
    i = blues[0]
    poly = np.array(ia['pieces'][i]['poly'])
    shifted = np.array(ic['pieces'][i]['poly'])
    dx = float(np.round((shifted - poly)[:, 0].mean()))
    x0, y0 = np.floor(poly.min(axis=0)).astype(int)
    x1, y1 = np.ceil(poly.max(axis=0)).astype(int)
    mask = polygon_mask(a.shape, [poly])[y0:y1, x0:x1]
    crop_a = a[y0:y1, x0:x1].astype(np.int16)
    crop_c = c[y0:y1, x0 + int(dx):x1 + int(dx)].astype(np.int16)
    d = np.abs(crop_a - crop_c).max(axis=2)[mask]
    result = {'rev': fxs.harness('worktree').rev, 'frame': 'M04', 'viewport': '1280x720',
              'reloadMaxDelta': reload_delta, 'piece': i, 'shiftPx': dx, 'cropBox': [int(x0), int(y0), int(x1), int(y1)],
              'cropPixels': int(mask.sum()), 'cropMeanAbsDelta': round(float(d.mean()), 4), 'cropMaxAbsDelta': int(d.max())}
    result['pass'] = reload_delta == 0 and dx == SHIFT_PX and result['cropMeanAbsDelta'] <= 1.0 \
        and result['cropMaxAbsDelta'] <= 8
    write(args.out, result)
    return 0 if result['pass'] else 1


def cmd_cache(args):
    from browser_test_support import start_browser_test, wait_for_boot_run
    from momentum_frames_gallery import SETUP
    from test_momentum_run import DRIVE, DRIVE_SPEED, FPS
    cleanups, errors = [], []
    url, browser = start_browser_test(ROOT, cleanups.append)
    try:
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(url)
        wait_for_boot_run(page)
        page.evaluate(SETUP, 1)
        step = page.evaluate('height') * DRIVE_SPEED
        play = '''([n, step]) => { const drive = ''' + DRIVE + '''
            const blues = new Set()
            for (let k = 0; k < n; ++k) {
                drive([1, step, {}])
                const s = runRngState(); draw(); runRngState(s)
                for (const f of floors) for (const e of f.elements) if (e instanceof MomentumBlue) blues.add(e)
            }
            return blues.size }'''
        blues = 0
        for second in range(10, 61, 10):
            blues += page.evaluate(play, [10 * FPS, step])
            print(f'{second} s', page.evaluate('CRYSTAL_PIECES.stats'), flush=True)
        after_play = page.evaluate('({...CRYSTAL_PIECES.stats, mapSize: CRYSTAL_PIECES.sprites.size})')
        page.evaluate(PLACE, ['M04', 0])
        static = page.evaluate('''() => {
            for (let k = 0; k < 10; ++k) draw()
            const before = {...CRYSTAL_PIECES.stats}
            for (let k = 0; k < 120; ++k) draw()
            return {before: before, after: {...CRYSTAL_PIECES.stats}} }''')
        context.close()
    finally:
        for cleanup in reversed(cleanups):
            cleanup()
    result = {'rev': fxs.harness('worktree').rev, 'playSeconds': 60, 'seed': 1, 'bluesSeenInPlay': blues,
              'afterPlay': after_play, 'static': static,
              'staticBuildsDelta': static['after']['builds'] - static['before']['builds'],
              'staticHitsDelta': static['after']['hits'] - static['before']['hits'], 'errors': errors[:10]}
    result['pass'] = after_play['size'] <= 128 and after_play['mapSize'] <= 128 and \
        result['staticBuildsDelta'] == 0 and result['staticHitsDelta'] > 0 and not errors
    write(args.out, result)
    return 0 if result['pass'] else 1


LEGEND = r'''() => {
    TUTORIAL_HINT.visible = true; TUTORIAL_HINT.done = false; TUTORIAL_HINT.pressed = false
    TUTORIAL_HINT.alpha = 1; TUTORIAL_HINT.time = 0; TUTORIAL_HINT.invalidate()
    updateNeonPulse = () => { neonPulse = 1 }; neonPulse = 1
    draw()
    return TUTORIAL_HINT.legendBoxes
}'''


def cmd_shots_green(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for id, vp in [('M23', (1280, 720)), ('M46', (1280, 720)), ('M24', (1280, 720)), ('M134', (390, 844))]:
        img, info, _ = capture_frame('worktree', id, vp)
        fxs.save_png(img, out / f'{id}-{vp[0]}x{vp[1]}.png')
        if id == 'M23':
            m23, m23_info = img, info
    # The ramp's slope: its longest edge
    poly = np.array(next(p['poly'] for p in m23_info['pieces'] if p['kind'] == 'green'))
    e = max(range(len(poly)), key=lambda i: np.hypot(*(poly[(i + 1) % len(poly)] - poly[i])))
    seg = np.array([poly[e], poly[(e + 1) % len(poly)]])
    x0, y0 = np.floor(seg.min(axis=0)).astype(int) - 12
    x1, y1 = np.ceil(seg.max(axis=0)).astype(int) + 12
    crop = Image.fromarray(m23[max(0, y0):y1, max(0, x0):x1])
    crop.resize((crop.width * 4, crop.height * 4), Image.NEAREST).save(out / 'crop4x-M23-lip.png')
    context, page = fxs.harness('worktree').open((1280, 720))
    try:
        boxes = page.evaluate(LEGEND)
        img = snap(page)
        if page.errors:
            raise RuntimeError(page.errors)
    finally:
        context.close()
    b = np.array([[x, y, x + w, y + h] for x, y, w, h in boxes])
    x0, y0 = np.floor(b[:, :2].min(axis=0)).astype(int) - 16
    x1, y1 = np.ceil(b[:, 2:].max(axis=0)).astype(int) + 16
    crop = Image.fromarray(img[max(0, y0):y1, max(0, x0):x1])
    crop.resize((crop.width * 3, crop.height * 3), Image.NEAREST).save(out / 'tutorial-legend.png')
    print(sorted(p.name for p in out.glob('*.png')))
    return 0


def cmd_shots(args):
    if args.kind == 'green':
        return cmd_shots_green(args)
    if args.kind == 'twinkle':
        return cmd_shots_twinkle(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for id, vp in [('M04', (1280, 720)), ('M24', (1280, 720)), ('M66', (1280, 720)), ('M66', (390, 844))]:
        img, info, _ = capture_frame('worktree', id, vp)
        fxs.save_png(img, out / f'{id}-{vp[0]}x{vp[1]}.png')
        if id == 'M04':
            m04, m04_info = img, info
    poly = np.array(next(p['poly'] for p in m04_info['pieces'] if p['kind'] == args.kind))
    x0, y0 = np.floor(poly.min(axis=0)).astype(int) - 8
    x1, y1 = np.ceil(poly.max(axis=0)).astype(int) + 8
    crop = Image.fromarray(m04[max(0, y0):y1, max(0, x0):x1])
    crop.resize((crop.width * 4, crop.height * 4), Image.NEAREST).save(out / 'crop4x-cube.png')
    if args.rev:
        parent, _, _ = capture_frame(args.rev, 'M04', (1280, 720))
        fxs.save_png(parent, '/tmp/crystal-parent-M04.png')
        fxs.compare_png(parent, out / 'M04-1280x720.png', out / 'M04-parent-vs-head.png',
                        labels=(f'parent {sha(args.rev)[:7]}', 'HEAD'))
    print(sorted(p.name for p in out.glob('*.png')))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['geometry', 'outside', 'texture', 'determinism', 'cache', 'shots',
                                            'lips', 'fade', 'twinkle', 'glintdiff'])
    parser.add_argument('out')
    parser.add_argument('--rev')
    parser.add_argument('--kind', default='blue')
    parser.add_argument('--frames', default='M04,M24,M66')
    args = parser.parse_args()
    if args.command in ('outside', 'texture') and not args.rev:
        parser.error('--rev is required')
    if args.rev in REVS:
        args.rev = sha(REVS[args.rev])
    try:
        return globals()['cmd_' + args.command](args)
    finally:
        fxs.close()


if __name__ == '__main__':
    sys.exit(main())
