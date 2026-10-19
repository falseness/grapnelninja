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
    python3 momentum_crystal_check.py shots <dir> --kind blue [--rev R]
        M04/M24/M66-1280x720.png, M66-390x844.png, crop4x-cube.png and
        M04-parent-vs-head.png (needs --rev)
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
    return {k: k, canvas: [canvas.width, canvas.height], pieces: floor.elements.map(e => ({
        kind: e instanceof MomentumBlue ? 'blue' : 'green',
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
            diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
            outside = diff[~mask]
            row = {'scene': scene, 'viewport': f'{vp[0]}x{vp[1]}',
                   'maxDelta': int(outside.max()) if outside.size else 0,
                   'differingPixels': int((outside > 0).sum()),
                   'bluePieces': sum(p['kind'] == 'blue' for p in pieces),
                   'blueMaskPixels': int(blue.sum()), 'insideBlueDiffering': int((diff[blue] > 0).sum())}
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


def cmd_texture(args):
    rows = []
    ok = True
    for id in args.frames.split(','):
        a, ia, _ = capture_frame('worktree', id, (1280, 720))
        b, ib, _ = capture_frame(args.rev, id, (1280, 720))
        for (i, head, px, head_whole), (_, parent, _, parent_whole) in zip(
                interior_stddevs(a, ia, args.kind), interior_stddevs(b, ib, args.kind)):
            head, parent = round(head, 3), round(parent, 3)
            # A flat parent (stddev 0) gives an infinite ratio
            row = {'frame': id, 'piece': i, 'pixels': px, 'head': head, 'parent': parent,
                   'ratio': round(head / parent, 2) if parent else 'inf',
                   'wholePieceHead': round(head_whole, 3), 'wholePieceParent': round(parent_whole, 3)}
            row['pass'] = head > 0 and head >= 3.0 * parent
            ok = ok and row['pass']
            rows.append(row)
    ok = ok and len(rows) > 0
    write(args.out, {'kind': args.kind, 'viewport': '1280x720', 'erodePx': ERODE,
                     'region': 'inset-copy polygon (innerCopyInsetRatio) eroded erodePx; wholePiece* = piece eroded erodePx',
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


def cmd_shots(args):
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
    parser.add_argument('command', choices=['geometry', 'outside', 'texture', 'determinism', 'cache', 'shots'])
    parser.add_argument('out')
    parser.add_argument('--rev')
    parser.add_argument('--kind', default='blue')
    parser.add_argument('--frames', default='M04,M24,M66')
    args = parser.parse_args()
    if args.command in ('outside', 'texture') and not args.rev:
        parser.error('--rev is required')
    try:
        return globals()['cmd_' + args.command](args)
    finally:
        fxs.close()


if __name__ == '__main__':
    sys.exit(main())
