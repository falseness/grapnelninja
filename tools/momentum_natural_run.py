"""Momentum natural run against the camera rule (ported from TASK-086).

60 s (3600 ticks at 60 fps) of momentum played by tools/momentum_natural_bot.js
through real mousedown/mouseup events, 1280x720, rAF loop stopped (one
physics() a frame, like 60 fps). No scripted ninja positions, no
invulnerability, the obstacle floor is live.

The camera rule (the user's spec, like bad mode moveScreen.js
shouldStartMoveX with X = GAMEPLAY.cameraBorderWidthPercent): the camera has
a direction of movement and moves only while the ninja moves in that
direction and is past X % of the view along it.

Per frame (trace.json rows):
[tick, dir, tx, ty, fwdFrac, ninjaVel, ninjaMove, camMove, outOfView]
- dir: 'r' / 'u' / 'd' on a straight rail piece, 'a' on an arc; (tx, ty) the
  rail tangent at the view centre (the camera's direction).
- fwdFrac: the ninja's position along (tx, ty) as a share of the view extent
  along it (W |tx| + H |ty|), from the trailing edge (right: x share of the
  width from the left edge; down: y share from the top; up: from the bottom).
- ninjaVel: the ninja's velocity along the direction (a physics cycle) at
  the end of the frame; ninjaMove / camMove: the ninja's / the camera's
  motion along it over the frame.
- outOfView: the ninja's centre is outside the view.
Per seed: maxFwdFrac, framesBeyondTrigger (fwdFrac > X + max(0, ninjaMove) /
extent + 1e-6: further ahead than one frame of its own motion),
framesMovedWithoutRule (camMove > 1e-9 while ninjaVel <= 0 or the frame's
starting fwdFrac < X - 1e-6; the camera decides on the state before it
moves), framesOutOfView. The worst (max fwdFrac) frame is replayed from the
recorded actions (the replay must give the recorded fwdFrac back), drawn and
saved with the X line as shots/worst-seed<n>.png (and the worst in-view frame
as shots/worst-inview-seed<n>.png when the worst one is out of view).

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
SEP = (',', ':')

SETUP = '''(seed) => {
    __mb.install(seed)
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false
    const W = width / scale[version], H = height / scale[version]
    const rec = window.__rec = {W, H, trigger: GAMEPLAY.cameraBorderWidthPercent / 100}
    rec.sample = () => {
        const s = screen.railS === null ? -screen.x - screen.course.x0 + W / 2 : screen.railS
        const t = screen.rail.tangentAt(s)
        const piece = screen.rail.pieces[screen.rail.pieceAt(s)]
        const dir = piece.type == 'arc' ? 'a' : Math.abs(t.x) > 0.5 ? 'r' : t.y < 0 ? 'u' : 'd'
        const extent = W * Math.abs(t.x) + H * Math.abs(t.y)
        const cx = -screen.x + W / 2, cy = -screen.y + H / 2
        const along = (x, y) => x * t.x + y * t.y
        return {dir, t, extent, cam: [-screen.x, -screen.y], pos: [ninja.x, ninja.y],
                frac: 0.5 + along(ninja.x - cx, ninja.y - cy) / extent,
                vel: along(ninja.speedX, ninja.speedY),
                out: ninja.x + screen.x < 0 || ninja.x + screen.x > W || ninja.y + screen.y < 0 || ninja.y + screen.y > H}
    }
    rec.prev = rec.sample()
    rec.ninja0 = ninja
    return {W, H, trigger: rec.trigger, cyclesPerTick}
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
        const p = rec.prev, c = rec.sample(), t = c.t
        const ninjaMove = (c.pos[0] - p.pos[0]) * t.x + (c.pos[1] - p.pos[1]) * t.y
        const camMove = (c.cam[0] - p.cam[0]) * t.x + (c.cam[1] - p.cam[1]) * t.y
        out.push([__mb.tick, c.dir, r4(t.x), r4(t.y), r4(c.frac), r4(c.vel), r4(ninjaMove), r4(camMove), c.out ? 1 : 0,
                  // not in trace.json: exact values for the counts
                  c.frac, ninjaMove, camMove, c.vel, p.frac, c.extent])
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

# the trigger line (fwdFrac = X across the view), the ninja ring (or an
# arrow toward it when it is out of view) and a caption: DOM overlay, screenshot only
OVERLAY = '''([caption]) => {
    const rec = __rec, c = rec.sample(), t = c.t
    const rect = canvas.getBoundingClientRect(), k = rect.width / rec.W
    const cx = rect.width / 2, cy = rect.height / 2
    const off = (rec.trigger - 0.5) * c.extent * k
    const lx = cx + t.x * off, ly = cy + t.y * off, L = 2 * Math.hypot(rect.width, rect.height)
    const nx = (ninja.x + screen.x) * k, ny = (ninja.y + screen.y) * k
    const f = Math.min(1, Math.abs((cx - 30) / (nx - cx || 1e-9)), Math.abs((cy - 70) / (ny - cy || 1e-9)))
    const ex = cx + (nx - cx) * f, ey = cy + (ny - cy) * f
    const div = document.createElement('div')
    div.id = 'natural-overlay'
    div.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:99999'
    div.innerHTML = `<svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
      <line x1="${lx - t.y * L}" y1="${ly + t.x * L}" x2="${lx + t.y * L}" y2="${ly - t.x * L}" stroke="#ff00ff" stroke-width="3" stroke-dasharray="12 6"/>
      <line x1="${lx}" y1="${ly}" x2="${lx + t.x * 60}" y2="${ly + t.y * 60}" stroke="#ff00ff" stroke-width="4"/>
      ${c.out ? `<line x1="${cx}" y1="${cy}" x2="${ex}" y2="${ey}" stroke="#ffd400" stroke-width="4"/><circle cx="${ex}" cy="${ey}" r="12" fill="#ffd400"/>` : ''}
      <circle cx="${nx}" cy="${ny}" r="18" fill="none" stroke="#00ffff" stroke-width="3"/>
      <rect x="8" y="${rect.height - 44}" width="${rect.width - 16}" height="36" fill="rgba(0,0,0,0.8)"/>
      <text x="16" y="${rect.height - 20}" fill="#fff" font-family="monospace" font-size="15">${caption}</text></svg>`
    document.body.appendChild(div)
    return {frac: c.frac, out: c.out}
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


def summarise(rows, trigger):
    beyond = [k for k, r in enumerate(rows) if r[9] > trigger + max(0, r[10]) / r[14] + 1e-6]
    no_vel = [k for k, r in enumerate(rows) if r[11] > 1e-9 and r[12] <= 0]
    no_frac = [k for k, r in enumerate(rows) if r[11] > 1e-9 and r[13] < trigger - 1e-6]
    without = sorted(set(no_vel) | set(no_frac))
    worst = max(range(len(rows)), key=lambda k: rows[k][9])
    in_view = [k for k, r in enumerate(rows) if not r[8]]
    worst_in = max(in_view, key=lambda k: rows[k][9]) if in_view else None
    by_dir = {}
    for k in beyond:
        by_dir[rows[k][1]] = by_dir.get(rows[k][1], 0) + 1
    return {'frames': len(rows), 'maxFwdFrac': round(rows[worst][9], 4), 'worstFrame': worst,
            'worstOutOfView': rows[worst][8],
            'maxFwdFracInView': round(rows[worst_in][9], 4) if worst_in is not None else None,
            'worstInViewFrame': worst_in,
            'framesBeyondTrigger': len(beyond), 'beyondByDir': by_dir,
            'firstBeyondTrigger': beyond[0] if beyond else None,
            'framesMovedWithoutRule': len(without),
            'movedWhileNinjaVelNotForward': len(no_vel), 'movedWhileBehindTrigger': len(no_frac),
            'framesCameraMovedForward': sum(1 for r in rows if r[11] > 1e-9),
            'framesOutOfView': sum(1 for r in rows if r[8]),
            'framesByDir': {d: sum(1 for r in rows if r[1] == d) for d in 'ruda'}}


def shoot(browser, url, seed, actions, frame, recorded, path, caption):
    """Replays the recorded actions to frame (index), draws and screenshots it."""
    context, page, errors = open_page(browser)
    try:
        boot(page, url)
        _, rows, _ = run(page, seed, actions, frame + 1)
        if len(rows) != frame + 1 or abs(rows[frame][9] - recorded) > 1e-9:
            raise AssertionError('replay of seed %d differs at frame %d: %r vs %r' % (
                seed, frame, rows[frame][9] if len(rows) > frame else None, recorded))
        page.evaluate(DRAW)
        got = page.evaluate(OVERLAY, [caption])
        page.screenshot(path=str(path))
        return {'frame': frame, 'replayFwdFrac': round(got['frac'], 4), 'outOfView': got['out'], 'pageErrors': errors}
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
        summary = summarise(rows, setup['trigger'])
        summary.update({'trigger': setup['trigger'], 'view': [setup['W'], setup['H']],
                        'death': state['dead'], 'sameNinja': state['sameNinja'], 'hpEnd': state['hp'],
                        'pauseHits': state['pauseHits'], 'throws': sum(1 for a in actions if a['type'] == 'throw'),
                        'pageErrors': errors})
        (sdir / 'trace.json').write_text(json.dumps([r[:9] for r in rows], separators=SEP))
        (sdir / 'actions.json').write_text(json.dumps(actions, separators=SEP))
        shots = {}
        targets = [('worst-seed%d.png' % seed, summary['worstFrame'])]
        if summary['worstOutOfView'] and summary['worstInViewFrame'] is not None:
            targets.append(('worst-inview-seed%d.png' % seed, summary['worstInViewFrame']))
        for name, frame in targets:
            r = rows[frame]
            caption = ('seed %d frame %d (t=%.2fs) dir %s: ninja fwdFrac %.3f vs trigger %.2f (magenta line)%s' % (
                seed, frame, frame / 60, r[1], r[9], setup['trigger'], ', OUT OF VIEW (yellow arrow)' if r[8] else ''))
            shots[name] = shoot(browser, url, seed, actions, frame, r[9], out / 'shots' / name, caption)
        summary['shots'] = shots
    summary['head'] = head
    path = out / 'baseline.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    if data.get('head') != head:
        data = {'head': head, 'seeds': {}}
    data['seeds'][str(seed)] = summary
    path.write_text(json.dumps(data, separators=SEP))
    print('seed %d head %s frames %d maxFwdFrac %.4f (frame %d%s) framesBeyondTrigger %d framesMovedWithoutRule %d '
          '(vel %d, behind %d) framesOutOfView %d death %s' % (
              seed, head[:7], summary['frames'], summary['maxFwdFrac'], summary['worstFrame'],
              ', out of view' if summary['worstOutOfView'] else '', summary['framesBeyondTrigger'],
              summary['framesMovedWithoutRule'], summary['movedWhileNinjaVelNotForward'],
              summary['movedWhileBehindTrigger'], summary['framesOutOfView'], summary['death']), flush=True)


if __name__ == '__main__':
    main(int(sys.argv[1]), Path(sys.argv[2] if len(sys.argv) > 2 else
                                os.environ.get('MOMENTUM_NATURAL_OUT', '/tmp/momentum-natural')))
