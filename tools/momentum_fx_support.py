"""Momentum lighting FX harness: deterministic reference scenes (TASK-052).

Shared by the momentum lighting tickets. A capture boots index.html under
the frozen clock of render_snapshot (CLOCK_SCRIPT + boot_frozen, seeded
Math.random), seeds the scripted R U R D R course of
test_momentum_patterns_turn (SEED_COURSE), runs startGame('momentum'), stops
the rAF loop and builds one scene by hand: obstacle/pattern floors emptied,
pieces put with window.momentumPlacePiece(kind, spec), ninja position and
speed, its trail (ninja.track.pos), the camera (screen.x/y, the TASK-044 wall
mask kept on the scene's segment) and TUTORIAL_HINT hidden. MOMENTUM_FX
.enabled is set to fx_on (trees before TASK-051 have no switch), extra_js
runs last, then one draw(). The capture is the canvas composited over black,
decoded to an RGB uint8 array (Frame, with the scene geometry in .info).

Scenes reproduce concept frames 1-4 of artifacts/lighting-concept/ (the
*-now.png there are the source screenshots named in SOURCES). Positions are
given in reference px of the 1280x720 source shot relative to an anchor (a
corridor corner or centre); one reference px is view height / 720 world
units, so a 390x844 phone (touch: the stage is the 844x390 landscape)
shows the same composition, the anchor at the same fraction of the view.

Usage:
    with FxHarness() as fx:                  # or FxHarness('HEAD~1')
        frame = fx.capture('mid-shaft', (1280, 720), fx_on=True)
    background_mask(frame), emissive_mask(frame), hud_mask((1280, 720)),
    region_luminance(frame, mask), compare_png(frame, path, out)
Module-level capture(...) uses one shared harness per revision; a single
Playwright browser serves every revision (one process cannot start two sync
Playwright instances). close() ends them.
"""
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
import io
from pathlib import Path
from threading import Thread

import numpy as np
from PIL import Image, ImageDraw

from browser_test_support import QuietHandler, start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot
from test_momentum_borders import SEED_COURSE
from test_momentum_patterns_turn import SCRIPT

ROOT = Path(__file__).resolve().parents[1]
CONCEPT_DIR = ROOT / 'artifacts' / 'lighting-concept'
SCENES = ['blue-corner', 'blue-hit', 'mid-shaft', 'run-right']
VIEWPORTS = [(1280, 720), (390, 844)]
# Source screenshot per scene (identical to lighting-concept/<n>-<name>-now.png)
SOURCES = {
    'blue-corner': ROOT / 'artifacts/TASK-017/turn-blue-corner-cut-right-up.png',
    'blue-hit': ROOT / 'artifacts/TASK-020/play-blue-hit.png',
    'mid-shaft': ROOT / 'artifacts/TASK-030/shots/1280x720-mid-shaft.png',
    'run-right': ROOT / 'artifacts/TASK-020/play-right.png',
}
CONCEPTS = {name: CONCEPT_DIR / f'{i}-{name}.png' for i, name in enumerate(SCENES, 1)}
SEED = 1
EMISSIVE_THRESHOLD = 0.55
# HUD boxes are padded by this many canvas px (glow round the text)
HUD_PAD = 6

# Scene specs. anchor: a corner of the scripted course ('inner'/'outer' of the
# join at the end of segment `segment`) or the centre of segment `segment` at
# `along` (0..1); at: where the anchor sits in the view (fractions); pieces,
# ninja and trail in reference px from the anchor (x right, y down); rect
# pieces are {kind, x, y, w, h} centres; fade: a used piece this far through
# its fade (0..1). trail: polyline from its oldest point to the ninja.
SCENE_SPECS = {
    # Concept 1: large blue cube in the inner corner of the right->up join,
    # under the ceiling overhang; green pieces up the shaft
    'blue-corner': {
        'segment': 0, 'anchor': 'inner', 'at': [0.5, 0.5],
        'pieces': [{'kind': 'blue', 'x': 82, 'y': 82, 'w': 165, 'h': 165},
                   {'kind': 'green', 'x': 25, 'y': -298, 'w': 46, 'h': 125},
                   {'kind': 'green', 'x': 552, 'y': 147, 'w': 71, 'h': 179}],
        'ninja': [-577, 4], 'speed': [1, 0], 'trail': [[-760, 4], [-577, 4]],
    },
    # Concept 2: ninja on a blue rect in the right corridor past the
    # down->right join, a used green fading beside it, trail down the shaft
    'blue-hit': {
        'segment': 3, 'anchor': 'inner', 'at': [440 / 1280, 60 / 720],
        'pieces': [{'kind': 'blue', 'x': 174, 'y': 307, 'w': 132, 'h': 35},
                   {'kind': 'green', 'x': 75, 'y': 330, 'w': 130, 'h': 30, 'fade': 0.5}],
        'ninja': [141, 286], 'speed': [0.6, -0.4],
        'trail': [[-360, -60], [-360, 300], [-340, 292], [40, 292], [46, 312], [138, 273], [141, 286]],
    },
    # Concept 3: middle of the first up shaft, five green rects, the ninja in
    # the centre climbing with a straight trail. The source's shaft was twice
    # today's width (TASK-030 geometry): the rects keep their place relative
    # to the shaft (0.47 of its half width off the centre line), not in px
    'mid-shaft': {
        'segment': 1, 'anchor': 'centre', 'along': 0.5, 'at': [675 / 1280, 0.5],
        'pieces': [{'kind': 'green', 'x': -138, 'y': -155, 'w': 38, 'h': 96},
                   {'kind': 'green', 'x': -138, 'y': 81, 'w': 38, 'h': 96},
                   {'kind': 'green', 'x': -138, 'y': 316, 'w': 38, 'h': 96},
                   {'kind': 'green', 'x': 139, 'y': -37, 'w': 38, 'h': 96},
                   {'kind': 'green', 'x': 139, 'y': 198, 'w': 38, 'h': 96}],
        'ninja': [1, 62], 'speed': [0, -1], 'trail': [[1, 420], [1, 62]],
    },
    # Concept 4: open right corridor before the right->down join (its outer
    # corner top right), ninja mid-screen with a long trail behind it
    'run-right': {
        'segment': 2, 'anchor': 'outer', 'at': [1190 / 1280, 70 / 720],
        'pieces': [{'kind': 'green', 'x': -670, 'y': 548, 'w': 166, 'h': 60}],
        'ninja': [-667, 295], 'speed': [1, 0],
        'trail': [[-1240, 330], [-1100, 318], [-960, 300], [-860, 292], [-667, 295]],
    },
}

# Scene builder (in the page). Returns the scene geometry in canvas px.
BUILD = r'''([spec, fxOn]) => {
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const course = momentumCourse
    const seg = course.segment(spec.segment), next = course.segment(spec.segment + 1)
    const prev = spec.segment > 0 ? course.segment(spec.segment - 1) : null
    const vw = width / scale[version], vh = height / scale[version]
    const u = vh / 720
    // Anchor: corner point of the two corridor faces at the join, or a centre
    let ax, ay
    if (spec.anchor == 'centre') {
        ax = seg.x0 + (seg.x1 - seg.x0) * spec.along
        ay = seg.y0 + (seg.y1 - seg.y0) * spec.along
    } else {
        const dIn = momentumDirection(seg.dir), dOut = momentumDirection(next.dir)
        const hIn = momentumSegmentHalfWidth(seg), hOut = momentumSegmentHalfWidth(next)
        // Inner corner: back against the outgoing direction by the incoming
        // half width... the faces: incoming side towards dOut, outgoing side
        // against dIn; outer corner the opposite faces
        const s = spec.anchor == 'inner' ? 1 : -1
        ax = seg.x1 + s * dOut.x * hIn - s * dIn.x * hOut
        ay = seg.y1 + s * dOut.y * hIn - s * dIn.y * hOut
    }
    const world = p => [ax + p[0] * u, ay + p[1] * u]
    screen.x = -(ax - spec.at[0] * vw); screen.y = -(ay - spec.at[1] * vh)
    screen.leftWall.update(screen)
    screen.segmentIndex = spec.segment
    // Border strips round the camera (built for the camera position)
    for (const f of floors)
        if (f instanceof MomentumBorderFloor)
            f.replenishElements()
    for (const f of floors)
        if (f instanceof MomentumObstacleFloor || f instanceof MomentumPatternFloor) {
            f.elements = []
            if (f.groups) f.groups = []
        }
    grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
    const pieces = []
    for (const p of spec.pieces) {
        const [x, y] = world([p.x, p.y])
        const placed = momentumPlacePiece(p.kind, {shape: 'rect', x: x, y: y, w: p.w * u, h: p.h * u})
        if (p.fade !== undefined) {
            placed.element.use()
            placed.element.fadeStartMs = performance.now() - p.fade * GAMEPLAY.momentumFadeMs
        }
        pieces.push({kind: p.kind, shape: 'rect', element: placed.element})
    }
    const [nx, ny] = world(spec.ninja)
    ninja.x = nx; ninja.y = ny
    const v = GAMEPLAY.momentumMaxSpeed ? GAMEPLAY.momentumMaxSpeed * 0.9 : 2.5
    ninja.speedX = spec.speed[0] * v; ninja.speedY = spec.speed[1] * v
    // Trail: the polyline resampled at the ninja's per-tick step
    const pts = spec.trail.map(world), trail = []
    const step = Math.max(1, v * cyclesPerTick)
    for (let i = 0; i + 1 < pts.length; ++i) {
        const [x0, y0] = pts[i], [x1, y1] = pts[i + 1]
        const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / step))
        for (let k = 0; k < n; ++k)
            trail.push({x: x0 + (x1 - x0) * k / n, y: y0 + (y1 - y0) * k / n})
    }
    trail.push({x: nx, y: ny})
    ninja.track.pos = trail.slice(-ninja.track.pointsLimit)
    if (typeof MOMENTUM_FX != 'undefined')
        MOMENTUM_FX.enabled = fxOn
    return {anchor: [ax, ay]}
}'''

# One frame with the HUD layout probe on, then the geometry in canvas px
DRAW = r'''() => {
    LAYOUT_PROBE.boxes = []
    draw()
    const boxes = LAYOUT_PROBE.boxes
    LAYOUT_PROBE.boxes = null
    const css = getCanvasCssRect()
    const k = canvas.width / width * scale[version], c = canvas.width / css.width
    const px = p => [(p.x + screen.x) * k, (p.y + screen.y) * k]
    const bbox = pts => {
        const xs = pts.map(p => p[0]), ys = pts.map(p => p[1])
        return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)].map(v => Math.round(v * 100) / 100)
    }
    const pieces = []
    for (const f of floors)
        if (f instanceof MomentumPatternFloor)
            for (const e of f.elements) {
                const poly = e.getPoints().map(px)
                pieces.push({kind: e instanceof MomentumBlue ? 'blue' : 'green', shape: 'rect',
                             poly: poly, bbox: bbox(poly), used: !!e.passThrough})
            }
    // Corridor interiors (each segment with its end squares) round the view
    const corridors = []
    const segs = momentumCourse.segments
    for (let i = 0; i < segs.length; ++i) {
        const s = segs[i], h = momentumSegmentHalfWidth(s)
        const hp = i > 0 ? momentumSegmentHalfWidth(segs[i - 1]) : h
        const hn = i + 1 < segs.length ? momentumSegmentHalfWidth(segs[i + 1]) : h
        let r
        if (s.dir == 'right')
            r = [{x: s.x0 - hp, y: s.y0 - h}, {x: s.x1 + hn, y: s.y1 + h}]
        else
            r = [{x: s.x0 - h, y: Math.min(s.y0, s.y1) - hp}, {x: s.x0 + h, y: Math.max(s.y0, s.y1) + hn}]
        corridors.push([...px(r[0]), ...px(r[1])])
    }
    const walls = []
    for (const f of floors)
        if (f instanceof MomentumBorderFloor)
            for (const e of f.elements) {
                const b = bbox(e.getPoints().map(px))
                if (b[2] > 0 && b[3] > 0 && b[0] < canvas.width && b[1] < canvas.height)
                    walls.push(b.map(v => Math.round(Math.max(-1, Math.min(v, Math.max(canvas.width, canvas.height) + 1)))))
            }
    const hud = boxes.map(b => [b.x * c, b.y * c, b.width * c, b.height * c].map(v => Math.round(v * 100) / 100))
    return {canvas: [canvas.width, canvas.height], k: k, screen: [screen.x, screen.y, screen.segmentIndex],
            ninja: px(ninja), ninjaRadius: ninja.radius * k, trailPoints: ninja.track.pos.length,
            trail: ninja.track.pos.map(px), pieces: pieces, walls: walls, corridors: corridors, hud: hud,
            fx: typeof MOMENTUM_FX != 'undefined' ? MOMENTUM_FX.enabled : null}
}'''

# Ninja centre in canvas px of the current page
NINJA_SCREEN_POS = '''() => { const k = canvas.width / width * scale[version]
    return [(ninja.x + screen.x) * k, (ninja.y + screen.y) * k] }'''

_HUD_BOXES = {}


class Frame(np.ndarray):
    """Decoded RGB uint8 capture; .info holds the scene geometry (canvas px)."""
    def __new__(cls, array, info=None):
        obj = np.asarray(array).view(cls)
        obj.info = info
        return obj

    def __array_finalize__(self, obj):
        self.info = getattr(obj, 'info', None)


class FxHarness:
    """Captures scenes of one revision ('worktree' or a git rev).

    browser: share another harness's browser (one Playwright per process).
    style_patch: [(old, new), ...] text replacements served in style.js (a
    STYLE override; each old must occur exactly once).
    """
    def __init__(self, rev='worktree', browser=None, style_patch=None):
        self.stack = ExitStack()
        self.style_patch = style_patch
        self.root, self.rev = export_rev(rev, self.stack.callback)
        if browser is None:
            self.url, self.browser = start_browser_test(self.root, self.stack.callback)
        else:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(self.root)))
            self.stack.callback(server.server_close)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.stack.callback(thread.join)
            self.stack.callback(server.shutdown)
            self.url = f'http://127.0.0.1:{server.server_port}/'
            self.browser = browser

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.stack.close()

    def patch_context(self, context):
        """Serve the style_patch'ed style.js to context's pages (no-op without a patch)."""
        if self.style_patch:
            style = (self.root / 'style.js').read_text()
            for old, new in self.style_patch:
                if style.count(old) != 1:
                    raise ValueError(f'style_patch: {old!r} occurs {style.count(old)} times')
                style = style.replace(old, new)
            context.route('**/style.js', lambda route: route.fulfill(
                body=style, content_type='application/javascript'))

    def open(self, viewport):
        """Booted page (frozen clock, seeded course) at viewport; caller closes its context."""
        w, h = viewport
        touch = h > w
        context = self.browser.new_context(viewport={'width': w, 'height': h}, is_mobile=touch, has_touch=touch)
        context.add_init_script(SEED_SCRIPT % SEED)
        context.add_init_script(render_snapshot.CLOCK_SCRIPT)
        self.patch_context(context)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(self.url + 'index.html', wait_until='load')
        render_snapshot.boot_frozen(page)
        page.evaluate(render_snapshot.SETUP_SCRIPT, [[], touch])
        page.evaluate(SEED_COURSE, SCRIPT)
        page.evaluate("() => startGame('momentum')")
        page.errors = errors
        return context, page

    def capture(self, scene, viewport, fx_on=True, extra_js=None):
        """One frame of scene at viewport (w, h) as a Frame."""
        context, page = self.open(viewport)
        try:
            page.evaluate(BUILD, [SCENE_SPECS[scene], bool(fx_on)])
            if extra_js:
                page.evaluate(extra_js)
            info = page.evaluate(DRAW)
            png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
            if page.errors:
                raise RuntimeError(f'page errors in {scene} {viewport}: {page.errors}')
        finally:
            context.close()
        info.update(scene=scene, viewport=list(viewport), rev=self.rev)
        _HUD_BOXES[tuple(viewport)] = (info['canvas'], info['hud'])
        return Frame(np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info)


_HARNESSES = {}


def harness(rev='worktree'):
    """Shared harness for rev (one browser for all revisions)."""
    if rev not in _HARNESSES:
        first = next(iter(_HARNESSES.values()), None)
        _HARNESSES[rev] = FxHarness(rev, first.browser if first else None)
    return _HARNESSES[rev]


def close():
    # The browser owner (the first) last
    for rev in list(_HARNESSES)[::-1]:
        _HARNESSES.pop(rev).close()


def capture(scene, viewport, fx_on=True, extra_js=None, rev='worktree'):
    """Frame of scene at viewport; rev 'HEAD~1' captures the parent commit (git archive export)."""
    return harness(rev).capture(scene, viewport, fx_on, extra_js)


def parent_capture(scene, viewport, fx_on=True, extra_js=None):
    return capture(scene, viewport, fx_on, extra_js, rev='HEAD~1')


def ninja_screen_pos(frame_or_page):
    """Ninja centre in canvas px: from a Frame's info or a live page."""
    if isinstance(frame_or_page, Frame):
        return tuple(frame_or_page.info['ninja'])
    return tuple(frame_or_page.evaluate(NINJA_SCREEN_POS))


def luminance(img):
    """Rec. 709 luminance in 0..1 per pixel."""
    return np.asarray(img, dtype=np.float64)[..., :3] @ np.array([0.2126, 0.7152, 0.0722]) / 255


def region_luminance(img, mask):
    """Mean luminance (0..1) of img over mask; None for an empty mask."""
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return None
    return float(luminance(img)[mask].mean())


def emissive_mask(img):
    """Neon outlines, HUD text, motes: max channel > 0.55."""
    return np.asarray(img)[..., :3].max(axis=2) > EMISSIVE_THRESHOLD * 255


def hud_mask(viewport, shape=None):
    """HUD boxes (LAYOUT_PROBE of the last capture at viewport), padded."""
    canvas, boxes = _HUD_BOXES[tuple(viewport)]
    h, w = shape[:2] if shape is not None else (canvas[1], canvas[0])
    mask = np.zeros((h, w), dtype=bool)
    for x, y, bw, bh in boxes:
        x0, y0 = max(0, int(x - HUD_PAD)), max(0, int(y - HUD_PAD))
        mask[y0:int(np.ceil(y + bh + HUD_PAD)), x0:int(np.ceil(x + bw + HUD_PAD))] = True
    return mask


def _polygon_mask(shape, polygons):
    image = Image.new('1', (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(image)
    for poly in polygons:
        draw.polygon([tuple(p) for p in poly], fill=1, outline=1)
    return np.asarray(image, dtype=bool)


def piece_mask(frame):
    return _polygon_mask(frame.shape, [p['poly'] for p in frame.info['pieces']])


def wall_mask(frame):
    """Everything outside the corridor interiors (the walls and their mass)."""
    h, w = frame.shape[:2]
    inside = np.zeros((h, w), dtype=bool)
    for x0, y0, x1, y1 in frame.info['corridors']:
        inside[max(0, int(np.ceil(y0))):max(0, int(np.floor(y1))),
               max(0, int(np.ceil(x0))):max(0, int(np.floor(x1)))] = True
    return ~inside


def background_mask(frame):
    """Not emissive, not HUD, not inside a piece or a wall."""
    return ~(emissive_mask(frame) | hud_mask(frame.info['viewport'], frame.shape) |
             piece_mask(frame) | wall_mask(frame))


def max_delta(a, b):
    return int(np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).max())


def save_png(img, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(img, dtype=np.uint8)).save(path)


def compare_png(left, right_path, out, labels=('new frame', 'source')):
    """Side-by-side image: left (array or path) | right_path, both at the left's height."""
    a = Image.fromarray(np.asarray(left, dtype=np.uint8)) if not isinstance(left, (str, Path)) \
        else Image.open(left).convert('RGB')
    b = Image.open(right_path).convert('RGB')
    if b.height != a.height:
        b = b.resize((round(b.width * a.height / b.height), a.height), Image.LANCZOS)
    gap, bar = 8, 22
    sheet = Image.new('RGB', (a.width + gap + b.width, a.height + bar), (24, 24, 24))
    sheet.paste(a, (0, bar))
    sheet.paste(b, (a.width + gap, bar))
    draw = ImageDraw.Draw(sheet)
    draw.text((6, 5), labels[0], fill=(255, 255, 255))
    draw.text((a.width + gap + 6, 5), f'{labels[1]}: {Path(right_path).name}', fill=(255, 255, 255))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
