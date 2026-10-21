"""Momentum natural run: the whole right corridor stays in view (TASK-131).

The tools/momentum_natural_run.py drive (tools/momentum_natural_bot.js through
real mousedown/mouseup events, 1280x720, rAF loop stopped, one physics() a
frame, no scripted positions, no invulnerability) with the tree's own camera
(elements/momentumcamera.js; TASK-118's rule keeps the ninja in the
vertical middle of the view). The ninja is in a right corridor while it is
inside a 'right' course segment: x0 <= ninja.x <= x1 and within the
segment's half width of the centre line.

Per frame in a right corridor the corridor's ceiling face (y0 - halfWidth)
and floor face (y0 + halfWidth) must both be inside the view:
framesCorridorClipped counts the frames where either is not. The ninja's
centre must be inside the view in every frame (framesOutOfView).

trace.json rows (only the fields the counts need):
[tick, corridor, ceilingFrac, floorFrac, ninjaFrac, out]
- corridor: index of the right segment the ninja is in, -1 when none;
- ceilingFrac / floorFrac / ninjaFrac: view y of the ceiling face, floor
  face and the ninja's centre as a share of the view height (0 top, 1
  bottom; null outside a corridor);
- out: the ninja's centre is outside the view.
summary (corridor.json, merged per seed): frames, segments (course segments
the ninja passed: [index, dir]), corridorFrames, framesCorridorClipped,
framesOutOfView, minFaceMargin (least view share between a face and the
view edge), death, pageErrors; nearFloor / nearCeiling: the corridor frames
with the ninja closest to the floor / ceiling (ninja offset from the
centre line in half widths; at least a half width from both segment ends
unless no such frame is half a half width or more off the centre towards
that face), replayed from the recorded actions and saved as
shots/seed<n>-floor.png / -ceiling.png when shots are asked for.

usage (from tools/): python3 momentum_corridor_view.py <seed> [out dir] [--shots]
(out dir also from MOMENTUM_CORRIDOR_OUT; default /tmp/momentum-corridor).
"""
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402

BOT = (TOOLS / 'momentum_natural_bot.js').read_text()
FRAMES = int(os.environ.get('MOMENTUM_CORRIDOR_FRAMES', 3600))
SEP = (',', ':')

SETUP = '''(seed) => {
    window.__corridorOf = course => {
        for (let i = 0; i < course.segments.length; ++i) {
            const s = course.segments[i]
            if (s.dir == 'right' && s.x0 <= ninja.x && ninja.x <= s.x1 &&
                Math.abs(ninja.y - s.y0) <= momentumSegmentHalfWidth(s))
                return i
        }
        return -1
    }
    __mb.install(seed)
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false
    const W = width / scale[version], H = height / scale[version]
    const rec = window.__rec = {W, H}
    rec.sample = () => {
        const i = __corridorOf(screen.course), top = -screen.y
        const frac = y => (y - top) / H
        const out = ninja.x + screen.x < 0 || ninja.x + screen.x > W || ninja.y + screen.y < 0 || ninja.y + screen.y > H
        if (i < 0)
            return {i, out, seg: screen.segmentIndex}
        const s = screen.course.segments[i], hw = momentumSegmentHalfWidth(s)
        return {i, out, seg: screen.segmentIndex, ceiling: frac(s.y0 - hw), floor: frac(s.y0 + hw),
                ninja: frac(ninja.y), offset: (ninja.y - s.y0) / hw, inner: Math.min(ninja.x - s.x0, s.x1 - ninja.x) / hw}
    }
    rec.ninja0 = ninja
    return {W, H, halfWidth: GAMEPLAY.momentumBorders.halfWidth, cyclesPerTick}
}'''

# n ticks; replay: dispatch the recorded actions instead of searching
STEP = '''([n, replay]) => {
    const rec = __rec, out = []
    for (let i = 0; i < n; ++i) {
        if (replay) {
            while (rec.queue.length && rec.queue[0].tick == __mb.tick)
                __mb.applyAction(rec.queue.shift())
            physics(); __mb.tick++
        } else
            __mb.step()
        const c = rec.sample()
        out.push([__mb.tick, c.i, c.ceiling ?? null, c.floor ?? null, c.ninja ?? null, c.out ? 1 : 0,
                  c.offset ?? null, c.seg, c.inner ?? null])
    }
    return {rows: out, dead: __mb.deathTick, sameNinja: ninja === rec.ninja0,
            dirs: screen.course.segments.map(s => s.dir)}
}'''

DRAW = '''() => {
    const st = __mb.fxRng.state
    TUTORIAL_HINT.visible = false
    visualEffects.screenEffects.landings.length = 0
    draw()
    __mb.fxRng.state = st
}'''

# dashed lines on the corridor's ceiling and floor faces, a ring on the
# ninja and a caption on the side away from the corridor: DOM overlay,
# screenshot only
OVERLAY = '''([caption, captionTop]) => {
    const c = __rec.sample(), rect = canvas.getBoundingClientRect()
    const fy = f => f * rect.height, k = rect.width / __rec.W
    const nx = (ninja.x + screen.x) * k, ny = (ninja.y + screen.y) * k
    const cy = captionTop ? 8 : rect.height - 44
    const div = document.createElement('div')
    div.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:99999'
    div.innerHTML = `<svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
      <line x1="0" y1="${fy(c.ceiling)}" x2="${rect.width}" y2="${fy(c.ceiling)}" stroke="#ff00ff" stroke-width="2" stroke-dasharray="10 8"/>
      <line x1="0" y1="${fy(c.floor)}" x2="${rect.width}" y2="${fy(c.floor)}" stroke="#ffd400" stroke-width="2" stroke-dasharray="10 8"/>
      <circle cx="${nx}" cy="${ny}" r="18" fill="none" stroke="#00ffff" stroke-width="3"/>
      <rect x="8" y="${cy}" width="${rect.width - 16}" height="36" fill="rgba(0,0,0,0.8)"/>
      <text x="16" y="${cy + 24}" fill="#fff" font-family="monospace" font-size="15">${caption}</text></svg>`
    document.body.appendChild(div)
    return c
}'''

APPLY = '''() => { __mb.applyAction = (a) => {
    if (a.type == 'release') document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))
    else if (a.type == 'throw') {
        if (grapnel.throwed) document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))
        document.dispatchEvent(new MouseEvent('mousedown', {clientX: a.x, clientY: a.y, bubbles: true}))
    }
} }'''


def open_page(browser):
    context = browser.new_context(viewport={'width': 1280, 'height': 720})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    return context, page, errors


def boot(page, url):
    page.goto(url)
    wait_for_boot_run(page)
    page.evaluate(BOT)
    page.evaluate(APPLY)


def run(page, seed, actions=None, stop=FRAMES):
    setup = page.evaluate(SETUP, seed)
    if actions is not None:
        page.evaluate('(q) => { __rec.queue = q }', actions)
    rows, state = [], None
    while len(rows) < stop:
        state = page.evaluate(STEP, [min(60, stop - len(rows)), actions is not None])
        rows += state['rows']
        if state['dead'] is not None or not state['sameNinja']:
            break
    return setup, rows, state


def summarise(rows, dirs):
    eps = 1e-9
    corridor = [k for k, r in enumerate(rows) if r[1] >= 0]
    clipped = [k for k in corridor if rows[k][2] < -eps or rows[k][3] > 1 + eps]
    margins = [min(rows[k][2], 1 - rows[k][3]) for k in corridor]
    # shot frames: away from the corner boxes (a half width from both ends)
    # unless the ninja gets no closer than half a half width to that face there
    inner = [k for k in corridor if rows[k][8] >= 1]
    floor = max(inner, key=lambda k: rows[k][6]) if inner else None
    if floor is None or rows[floor][6] < 0.5:
        floor = max(corridor, key=lambda k: rows[k][6]) if corridor else None
    ceiling = min(inner, key=lambda k: rows[k][6]) if inner else None
    if ceiling is None or rows[ceiling][6] > -0.5:
        ceiling = min(corridor, key=lambda k: rows[k][6]) if corridor else None
    passed = sorted({r[7] for r in rows} | {r[1] for r in rows if r[1] >= 0})
    return {'frames': len(rows), 'segments': [[i, dirs[i]] for i in passed],
            'corridorFrames': len(corridor), 'corridorSegments': sorted({rows[k][1] for k in corridor}),
            'framesCorridorClipped': len(clipped), 'firstClipped': clipped[0] if clipped else None,
            'minFaceMargin': round(min(margins), 4) if margins else None,
            'framesOutOfView': sum(1 for r in rows if r[5]),
            'nearFloor': {'frame': floor, 'offset': round(rows[floor][6], 4)} if floor is not None else None,
            'nearCeiling': {'frame': ceiling, 'offset': round(rows[ceiling][6], 4)} if ceiling is not None else None}


def shoot(browser, url, seed, actions, frame, recorded, path, caption, caption_top):
    """Replays the recorded actions to frame (index), draws and screenshots it."""
    context, page, errors = open_page(browser)
    try:
        boot(page, url)
        _, rows, _ = run(page, seed, actions, frame + 1)
        if len(rows) != frame + 1 or rows[frame][:6] != recorded[:6]:
            raise AssertionError('replay of seed %d differs at frame %d: %r vs %r' % (
                seed, frame, rows[frame] if len(rows) > frame else None, recorded))
        page.evaluate(DRAW)
        got = page.evaluate(OVERLAY, [caption, caption_top])
        page.screenshot(path=str(path))
        return {'frame': frame, 'ceilingFrac': round(got['ceiling'], 4), 'floorFrac': round(got['floor'], 4),
                'ninjaFrac': round(got['ninja'], 4), 'out': got['out'], 'pageErrors': errors}
    finally:
        context.close()


def main(seed, out, shots):
    sdir = out / ('seed%d' % seed)
    sdir.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    with contextlib.ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        context, page, errors = open_page(browser)
        boot(page, url)
        setup, rows, state = run(page, seed)
        actions = page.evaluate('__mb.actions')
        context.close()
        summary = summarise(rows, state['dirs'])
        summary.update({'view': [setup['W'], setup['H']], 'halfWidth': setup['halfWidth'],
                        'death': state['dead'], 'sameNinja': state['sameNinja'],
                        'throws': sum(1 for a in actions if a['type'] == 'throw'), 'pageErrors': errors})
        (sdir / 'trace.json').write_text(json.dumps([r[:6] for r in rows], separators=SEP))
        (sdir / 'actions.json').write_text(json.dumps(actions, separators=SEP))
        if shots:
            (out / 'shots').mkdir(exist_ok=True)
            summary['shots'] = {}
            for where, key in (('floor', 'nearFloor'), ('ceiling', 'nearCeiling')):
                frame = summary[key]['frame']
                r = rows[frame]
                name = 'seed%d-%s.png' % (seed, where)
                caption = ('seed %d frame %d (t=%.2fs) corridor seg %d, ninja near the %s: ceiling face %.3f (magenta), '
                           'floor face %.3f (yellow) of view height' % (seed, frame, frame / 60, r[1], where, r[2], r[3]))
                summary['shots'][name] = shoot(browser, url, seed, actions, frame, r, out / 'shots' / name,
                                               caption, where == 'ceiling')
    summary['head'] = head + ('+dirty' if dirty else '')
    path = out / 'corridor.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    if data.get('head') != summary['head']:
        data = {'head': summary['head'], 'seeds': {}}
    data['seeds'][str(seed)] = summary
    path.write_text(json.dumps(data, separators=SEP))
    print('seed %d head %s frames %d corridorFrames %d framesCorridorClipped %d minFaceMargin %s framesOutOfView %d '
          'segments %d death %s errors %d' % (
              seed, summary['head'][:7], summary['frames'], summary['corridorFrames'],
              summary['framesCorridorClipped'], summary['minFaceMargin'], summary['framesOutOfView'],
              len(summary['segments']), summary['death'], len(errors)), flush=True)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--shots']
    main(int(args[0]), Path(args[1] if len(args) > 1 else os.environ.get('MOMENTUM_CORRIDOR_OUT', '/tmp/momentum-corridor')),
         '--shots' in sys.argv)
