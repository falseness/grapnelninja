"""Count runtime canvas creation while the ninja is held at the freeze spots.

Headless Chromium at the user's recording size (1706x932, DPR 1.5) in Grapple
Over. An init script wraps document.createElement('canvas') (creator stack
top + caller, size at the first getContext), getGlowSprite (misses, by key and
cache: 'glyph|' keys are HUD glyph sprites in GLYPH_SPRITES)
and BackgroundRenderer.prototype.getSmoothImage (palette image builds), and
counts rAF frames. The ninja is held (x, y, zero speed, re-set every 250 ms)
for ~1.5 s at each tools/fixtures/freeze-walk.json point for 2 passes, then
for ~1 s at each sweep point. Also reports the most canvases one frame
created per source file and the bounce contact canvases (cacheBounceContact)
per bounce board build (bounceMaterialSprite). Counts only: headless timings
mean nothing.

    python3 tools/canvas_audit.py [--mode single|double] [--out canvas-audit.json]
"""
import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402

WALK = ROOT / 'tools/fixtures/freeze-walk.json'
VIEWPORT = {'width': 1706, 'height': 932}
DPR = 1.5
HOLD_STEPS = 6       # x 250 ms at each walk point
SWEEP_STEPS = 4      # x 250 ms at each sweep point

INIT = r'''
window.__audit = {frame: 0, phase: 'boot', canvases: [], glowMisses: [], smoothBuilds: [], firstDraw: {}, smooth: null}
;(() => {
  const audit = window.__audit
  const create = document.createElement
  document.createElement = function(tag) {
    const el = create.apply(this, arguments)
    if (String(tag).toLowerCase() !== 'canvas') return el
    // creator and its caller, skipping this script's own wrappers (<anonymous>)
    const frames = (new Error().stack || '').split('\n').slice(2, 8).filter(s => !s.includes('<anonymous>'))
      .map(s => s.trim().replace(/^at /, '').replace(/https?:\/\/[^/]+\//, '').replace(/:\d+\)?$/, '').replace('(', ''))
    const entry = {frame: audit.frame, phase: audit.phase, creator: frames[0] || '?', caller: frames[1] || '', w: 0, h: 0}
    audit.canvases.push(entry)
    if (audit.smooth) audit.smooth.built = true
    const getContext = el.getContext
    el.getContext = function() {
      entry.w = el.width; entry.h = el.height
      el.getContext = getContext
      return getContext.apply(el, arguments)
    }
    return el
  }
  const raf = window.requestAnimationFrame
  window.requestAnimationFrame = cb => raf.call(window, t => { audit.frame++; cb(t) })
  document.addEventListener('DOMContentLoaded', () => {
    const glow = window.getGlowSprite
    window.getGlowSprite = function(key, build, store) {
      if (!(store || GLOW_SPRITES).cache.has(key)) audit.glowMisses.push([audit.phase, String(key)])
      return glow.apply(this, arguments)
    }
    const smooth = BackgroundRenderer.prototype.getSmoothImage
    BackgroundRenderer.prototype.getSmoothImage = function(owner, name, bounds) {
      const images = typeof drawGrappleOverPalette != 'undefined' && drawGrappleOverPalette.images
      let index = null
      if (images) for (const [i, o] of images) if (o === owner) index = i
      if (index === null) return smooth.apply(this, arguments)
      if (!(index in audit.firstDraw)) audit.firstDraw[index] = audit.frame
      const outer = audit.smooth
      audit.smooth = {built: false}
      try {
        const canvas = smooth.apply(this, arguments)
        if (audit.smooth.built)
          audit.smoothBuilds.push({frame: audit.frame, phase: audit.phase, index, w: canvas.width, h: canvas.height,
                                   firstDrawFrame: audit.firstDraw[index]})
        return canvas
      } finally { audit.smooth = outer }
    }
  })
})()
'''

HOLD = '([x, y]) => { ninja.x = x; ninja.y = y; ninja.speedX = 0; ninja.speedY = 0 }'


def hold(page, point, steps):
    for _ in range(steps):
        page.evaluate(HOLD, point)
        page.wait_for_timeout(250)


def palette_index(page):
    return page.evaluate('() => { const p = visualEffects.background.palette; return p ? [p.from, p.to] : null }')


def audit(mode):
    walk = json.loads(WALK.read_text())
    errors = []
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=DPR)
        stack.callback(context.close)
        context.add_init_script(INIT)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)[:300]))
        page.goto(url + 'index.html', wait_until='load')
        wait_for_boot_run(page)
        if page.evaluate('version') != 'grapple_over':
            errors.append('not booted into grapple_over: ' + page.evaluate('version'))
        if mode == 'double':
            page.evaluate("setGrapnelMode('double')")
        page.wait_for_timeout(3000)
        for n in (1, 2):
            page.evaluate('p => { __audit.phase = p }', 'pass%d' % n)
            for point in walk['points']:
                hold(page, point, HOLD_STEPS)
        page.evaluate("() => { __audit.phase = 'sweep' }")
        sweep_palettes = []
        for point in walk['sweep']:
            hold(page, point, SWEEP_STEPS)
            sweep_palettes.append(palette_index(page))
        page.evaluate("() => { __audit.phase = 'done' }")
        raw = page.evaluate('''() => ({canvases: __audit.canvases, glowMisses: __audit.glowMisses,
            smoothBuilds: __audit.smoothBuilds, frames: __audit.frame, grapnelMode: floors[0].grapnelMode,
            caches: {glow: GLOW_SPRITES.cache.size, glowLimit: GLOW_SPRITES.limit,
                     glyph: typeof GLYPH_SPRITES != 'undefined' ? GLYPH_SPRITES.cache.size : null,
                     glyphLimit: typeof GLYPH_SPRITES != 'undefined' ? GLYPH_SPRITES.limit : null,
                     bounce: typeof BOUNCE_MATERIAL != 'undefined' ? BOUNCE_MATERIAL.sprites.size : null,
                     paletteImages: drawGrappleOverPalette.images ? drawGrappleOverPalette.images.size : 0}})''')
    if raw['grapnelMode'] != mode:
        errors.append('grapnelMode %s, expected %s' % (raw['grapnelMode'], mode))

    walked = [c for c in raw['canvases'] if c['phase'] != 'boot']
    creators, frames, by_file = {}, {}, {}
    contact = {'created': 0, 'materialBuilds': 0, 'frames': {}}
    for c in walked:
        row = creators.setdefault(c['creator'], {'n': 0, 'px': 0, 'caller': c['caller']})
        row['n'] += 1
        row['px'] += c['w'] * c['h']
        frames[c['frame']] = frames.get(c['frame'], 0) + 1
        source = c['creator'].split(' ')[-1].rsplit(':', 1)[0]
        per_frame = by_file.setdefault(source, {})
        per_frame[c['frame']] = per_frame.get(c['frame'], 0) + 1
        # Bounce contact canvases against the board sprites they belong to
        if c['creator'].startswith('cacheBounceContact '):
            contact['created'] += 1
            contact['frames'][c['frame']] = contact['frames'].get(c['frame'], 0) + 1
        elif c['creator'].startswith('bounceMaterialSprite '):
            contact['materialBuilds'] += 1
    contact['perBuild'] = round(contact['created'] / contact['materialBuilds'], 3) if contact['materialBuilds'] else None
    contact['maxPerFrame'] = max(contact.pop('frames').values(), default=0)
    glow = {kind: {'pass1': 0, 'pass2': 0} for kind in ('text', 'glyph', 'other')}
    text_keys = []
    for phase, key in raw['glowMisses']:
        if phase not in ('pass1', 'pass2'):
            continue
        kind = key.split('|')[0] if key.startswith(('text|', 'glyph|')) else 'other'
        glow[kind][phase] += 1
        if kind == 'text' and len(text_keys) < 8:
            text_keys.append(key.split('|')[1])
    return {
        'mode': mode,
        'viewport': [VIEWPORT['width'], VIEWPORT['height'], DPR],
        'frames': raw['frames'],
        'creators': dict(sorted(creators.items(), key=lambda kv: -kv[1]['n'])),
        'perPass': [sum(c['phase'] == p for c in walked) for p in ('pass1', 'pass2')],
        'sweepCreated': sum(c['phase'] == 'sweep' for c in walked),
        'maxPerFrame': max(frames.values(), default=0),
        'maxPerFrameByFile': {f: max(v.values()) for f, v in sorted(by_file.items())},
        'bounceContact': contact,
        'glowMisses': glow,
        'glowTextSample': text_keys,
        'smoothBuilds': [{k: b[k] for k in ('frame', 'phase', 'index', 'w', 'h', 'firstDrawFrame')}
                         for b in raw['smoothBuilds'] if b['phase'] != 'boot'],
        'sweepPalettes': sweep_palettes,
        'caches': raw['caches'],
        'errors': errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--mode', choices=('single', 'double'), default='single')
    parser.add_argument('--out', default='canvas-audit.json')
    args = parser.parse_args()
    result = audit(args.mode)
    Path(args.out).write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print('mode %s: perPass %s, maxPerFrame %d, glow text misses %s, glyph misses %s, smoothBuilds %d, errors %d -> %s' % (
        args.mode, result['perPass'], result['maxPerFrame'], result['glowMisses']['text'], result['glowMisses']['glyph'],
        len(result['smoothBuilds']), len(result['errors']), args.out))
    print('bounce contact %s; maxPerFrameByFile %s' % (
        json.dumps(result['bounceContact']), json.dumps(result['maxPerFrameByFile'])))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
