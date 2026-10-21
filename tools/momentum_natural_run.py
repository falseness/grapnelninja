"""Momentum natural run against the camera rule (ported from TASK-086).

60 s (3600 ticks at 60 fps) of momentum played by tools/momentum_natural_bot.js
through real mousedown/mouseup events, 1280x720 (MOMENTUM_NATURAL_VIEWPORT=WxH
for another), rAF loop stopped (one physics() a frame, like 60 fps). No
scripted ninja positions, no invulnerability, the obstacle floor is live.

The camera rule (elements/momentumcamera.js, user rule 2026-10-20): the ninja
stays in the vertical middle (an up shaft's camera never moves down, a down
shaft's never up: holdY); in a right corridor X keeps the ninja on the
GAMEPLAY.cameraBorderWidthPercent line while it is past it (never left); in a
shaft the view slides to the shaft's centre line; X closes its lag at up to
the ninja's x speed plus GAMEPLAY.momentumCamera.catchUpHeightRatio x H a
cycle.

Per frame (trace.json rows):
[tick, dir, fracX, fracY, ninjaStep, camStep, hold, outOfView]
- dir: the camera's segment 'r' / 'u' / 'd'.
- fracX / fracY: the ninja's position in the view as a share of its width /
  height; ninjaStep / camStep: how far the ninja / the camera moved over the
  frame; hold: the shaft rule held Y on the frame's last cycle.
Per seed: framesOutOfView; maxFracX and framesBeyondX (right frames with
fracX > X + the ninja's x step / W); maxOffCentre (max |fracY - 0.5| minus
the ninja's y step / H outside hold frames) and framesOffCentre (> 1e-6);
framesCamJump (camStep > the larger ninja step of this and the last frame +
one unit plus the X catch-up step (GAMEPLAY.momentumCamera.catchUpHeightRatio
x H) a cycle + 0.01); framesHold; framesShaftWallOut (in a shaft, one of
its wall faces is out of view). The worst off-centre frame and the
max fracX frame are replayed from the recorded actions, drawn and saved with
the X line and the middle line as shots/offcentre-seed<n>.png and
shots/maxfracx-seed<n>.png.

usage (from tools/): python3 momentum_natural_run.py <seed> [out dir]
(out dir also from MOMENTUM_NATURAL_OUT; default /tmp/momentum-natural).
Writes <out>/baseline.json (merged per seed), <out>/seed<n>/trace.json,
<out>/seed<n>/actions.json and <out>/shots/.
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
FRAMES = int(os.environ.get('MOMENTUM_NATURAL_FRAMES', 3600))
VIEWPORT = [int(v) for v in os.environ.get('MOMENTUM_NATURAL_VIEWPORT', '1280x720').split('x')]
SEP = (',', ':')

SETUP = '''(seed) => {
    __mb.install(seed)
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false
    const W = width / scale[version], H = height / scale[version]
    const rec = window.__rec = {W, H, trigger: screen.borderX / W}
    // wallOut: in a shaft, a wall face of it is out of view
    const wallOut = (seg) => {
        if (seg.dir == 'right') return false
        const hw = momentumSegmentHalfWidth(seg)
        return seg.x0 - hw + screen.x < 0 || seg.x0 + hw + screen.x > W
    }
    rec.sample = () => ({dir: screen.getSegment().dir[0], cam: [-screen.x, -screen.y], pos: [ninja.x, ninja.y],
        fx: (ninja.x + screen.x) / W, fy: (ninja.y + screen.y) / H, hold: screen.holdY, wall: wallOut(screen.getSegment()),
        out: ninja.x + screen.x < 0 || ninja.x + screen.x > W || ninja.y + screen.y < 0 || ninja.y + screen.y > H})
    rec.prev = rec.sample()
    rec.ninja0 = ninja
    return {W, H, trigger: rec.trigger, cyclesPerTick, catchUp: GAMEPLAY.momentumCamera.catchUpHeightRatio * H}
}'''

# n ticks; replay: dispatch the recorded actions instead of searching
STEP = '''([n, replay]) => {
    const rec = __rec, out = []
    const r4 = v => Math.round(v * 1e4) / 1e4
    for (let i = 0; i < n; ++i) {
        if (replay) {
            while (rec.queue.length && rec.queue[0].tick == __mb.tick)
                __mb.applyAction(rec.queue.shift())
            physics(); __mb.tick++
        } else
            __mb.step()
        const p = rec.prev, c = rec.sample()
        const nx = c.pos[0] - p.pos[0], ny = c.pos[1] - p.pos[1]
        const cx = c.cam[0] - p.cam[0], cy = c.cam[1] - p.cam[1]
        out.push([__mb.tick, c.dir, r4(c.fx), r4(c.fy), r4(Math.hypot(nx, ny)), r4(Math.hypot(cx, cy)),
                  c.hold ? 1 : 0, c.out ? 1 : 0,
                  // not in trace.json: exact values for the counts
                  c.fx, c.fy, Math.abs(nx), Math.abs(ny), Math.hypot(nx, ny), Math.hypot(cx, cy), c.wall ? 1 : 0])
        rec.prev = c
    }
    return {rows: out, dead: __mb.deathTick, sameNinja: ninja === rec.ninja0, hp: momentumState.hp,
            pauseHits: __mb.pauseHits || 0}
}'''

DRAW = '''() => {
    const st = __mb.fxRng.state
    TUTORIAL_HINT.visible = false
    visualEffects.screenEffects.landings.length = 0
    draw()
    __mb.fxRng.state = st
}'''

# the X line, the vertical middle line, the ninja ring and a caption: DOM
# overlay, screenshot only
OVERLAY = '''([caption]) => {
    const rec = __rec, c = rec.sample()
    const rect = canvas.getBoundingClientRect(), k = rect.width / rec.W
    const lx = rec.trigger * rect.width, my = rect.height / 2
    const nx = c.fx * rect.width, ny = c.fy * rect.height
    const div = document.createElement('div')
    div.id = 'natural-overlay'
    div.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:99999'
    div.innerHTML = `<svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
      <line x1="${lx}" y1="0" x2="${lx}" y2="${rect.height}" stroke="#ff00ff" stroke-width="3" stroke-dasharray="12 6"/>
      <line x1="0" y1="${my}" x2="${rect.width}" y2="${my}" stroke="#ffd400" stroke-width="2" stroke-dasharray="12 6"/>
      <circle cx="${nx}" cy="${ny}" r="18" fill="none" stroke="#00ffff" stroke-width="3"/>
      <rect x="8" y="${rect.height - 44}" width="${rect.width - 16}" height="36" fill="rgba(0,0,0,0.8)"/>
      <text x="16" y="${rect.height - 20}" fill="#fff" font-family="monospace" font-size="15">${caption}</text></svg>`
    document.body.appendChild(div)
    return {fx: c.fx, fy: c.fy, out: c.out}
}'''

APPLY = '''() => { __mb.applyAction = (a) => {
    if (a.type == 'release') document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))
    else if (a.type == 'throw') {
        if (grapnel.throwed) document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}))
        document.dispatchEvent(new MouseEvent('mousedown', {clientX: a.x, clientY: a.y, bubbles: true}))
    }
} }'''


def open_page(browser):
    context = browser.new_context(viewport={'width': VIEWPORT[0], 'height': VIEWPORT[1]})
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


def summarise(rows, setup):
    W, H, trigger, cycles = setup['W'], setup['H'], setup['trigger'], setup['cyclesPerTick']
    catch_up = setup['catchUp']
    right = [k for k, r in enumerate(rows) if r[1] == 'r']
    beyond = [k for k in right if rows[k][8] > trigger + rows[k][10] / W + 1e-6]
    max_x = max(right, key=lambda k: rows[k][8]) if right else None
    off = {k: abs(r[9] - 0.5) - r[11] / H for k, r in enumerate(rows) if not r[6]}
    worst = max(off, key=off.get)
    jumps = [k for k, r in enumerate(rows)
             if r[13] > max(r[12], rows[k - 1][12] if k else 0) + cycles * (1 + catch_up) + 0.01]
    return {'frames': len(rows), 'framesOutOfView': sum(1 for r in rows if r[7]),
            'maxFracX': round(rows[max_x][8], 4) if max_x is not None else None, 'maxFracXFrame': max_x,
            'framesBeyondX': len(beyond),
            'maxOffCentre': round(off[worst], 6), 'offCentreFrame': worst,
            'framesOffCentre': sum(1 for v in off.values() if v > 1e-6),
            'framesCamJump': len(jumps), 'firstCamJump': jumps[0] if jumps else None,
            'framesHold': sum(1 for r in rows if r[6]),
            'framesShaftWallOut': sum(1 for r in rows if r[14]),
            'framesByDir': {d: sum(1 for r in rows if r[1] == d) for d in 'rud'}}


def shoot(browser, url, seed, actions, frame, recorded, path, caption):
    """Replays the recorded actions to frame (index), draws and screenshots it."""
    context, page, errors = open_page(browser)
    try:
        boot(page, url)
        _, rows, _ = run(page, seed, actions, frame + 1)
        if len(rows) != frame + 1 or rows[frame][8:10] != recorded:
            raise AssertionError('replay of seed %d differs at frame %d: %r vs %r' % (
                seed, frame, rows[frame][8:10] if len(rows) > frame else None, recorded))
        page.evaluate(DRAW)
        got = page.evaluate(OVERLAY, [caption])
        page.screenshot(path=str(path))
        return {'frame': frame, 'fracX': round(got['fx'], 4), 'fracY': round(got['fy'], 4), 'outOfView': got['out'],
                'pageErrors': errors}
    finally:
        context.close()


def main(seed, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / 'shots').mkdir(exist_ok=True)
    sdir = out / ('seed%d' % seed)
    sdir.mkdir(exist_ok=True)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    with contextlib.ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        context, page, errors = open_page(browser)
        boot(page, url)
        setup, rows, state = run(page, seed)
        actions = page.evaluate('__mb.actions')
        context.close()
        summary = summarise(rows, setup)
        summary.update({'trigger': setup['trigger'], 'view': [setup['W'], setup['H']], 'viewport': VIEWPORT,
                        'death': state['dead'], 'sameNinja': state['sameNinja'], 'hpEnd': state['hp'],
                        'pauseHits': state['pauseHits'], 'throws': sum(1 for a in actions if a['type'] == 'throw'),
                        'pageErrors': errors})
        (sdir / 'trace.json').write_text(json.dumps([r[:8] for r in rows], separators=SEP))
        (sdir / 'actions.json').write_text(json.dumps(actions, separators=SEP))
        shots = {}
        targets = [('offcentre-seed%d.png' % seed, summary['offCentreFrame'])]
        if summary['maxFracXFrame'] is not None:
            targets.append(('maxfracx-seed%d.png' % seed, summary['maxFracXFrame']))
        for name, frame in targets:
            r = rows[frame]
            caption = ('seed %d frame %d (t=%.2fs) dir %s: ninja fracX %.3f (X line %.2f) fracY %.3f (middle line)%s%s' % (
                seed, frame, frame / 60, r[1], r[8], setup['trigger'], r[9], ' HOLD' if r[6] else '',
                ', OUT OF VIEW' if r[7] else ''))
            shots[name] = shoot(browser, url, seed, actions, frame, r[8:10], out / 'shots' / name, caption)
        summary['shots'] = shots
    summary['head'] = head
    path = out / 'baseline.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    if data.get('head') != head:
        data = {'head': head, 'seeds': {}}
    data['seeds'][str(seed)] = summary
    path.write_text(json.dumps(data, separators=SEP))
    print('seed %d head %s viewport %dx%d frames %d out of view %d maxFracX %s beyondX %d maxOffCentre %.6f '
          'offCentre %d camJump %d hold %d shaftWallOut %d byDir %s death %s' % (
              seed, head[:7], VIEWPORT[0], VIEWPORT[1], summary['frames'], summary['framesOutOfView'],
              summary['maxFracX'], summary['framesBeyondX'], summary['maxOffCentre'], summary['framesOffCentre'],
              summary['framesCamJump'], summary['framesHold'], summary['framesShaftWallOut'], summary['framesByDir'],
              summary['death']), flush=True)

if __name__ == '__main__':
    main(int(sys.argv[1]), Path(sys.argv[2] if len(sys.argv) > 2 else
                                os.environ.get('MOMENTUM_NATURAL_OUT', '/tmp/momentum-natural')))
