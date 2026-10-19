"""Centre-box diff of the last-heart frame (TASK-099).

Captures the blue-corner scene (1280x720) at hp 1 and hp 2 on each rev
(argv, 'worktree' allowed) with the scene's own ninja speed and with the
speed light pinned at the scene's pre-TASK-073 fraction (ninja speed 0.9 x
the effective cap), with the suite's SET_HP (pulse phase 0), and records the centre box (1/10 of the view each way)
maxDelta, the differing px bbox/count, the frame's speedLight.s/radius and
the ninja light circle's distance to the box. --shots DIR saves the hp 1 /
hp 2 centre crops x4 of the first rev.
"""
import argparse
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_low_hp_fx import SCENE, VIEWPORT, centre_box

# The suite's SET_HP before TASK-099 (hp, pulse phase, periods; no speed pin)
SET_HP = '''() => { momentumState.hp = %d
    const lowHp = visualEffects.lightmap && visualEffects.lightmap.lowHp
    if (lowHp) {
        const P = STYLE.momentumFx.lowHpPulseMs, now = Math.round(performance.now())
        lowHp.pulseShiftMs = Math.round(%r * P) - now %% P + %d * P
        lowHp.time = -1
    } }'''

PIN_SPEED = '''() => { if (typeof momentumMotionScale == 'function') {
    const v = GAMEPLAY.momentumMaxSpeed * momentumMotionScale(1) * 0.9
    ninja.speedX = v; ninja.speedY = 0 } }'''
STATE = '''() => { const l = visualEffects.lightmap, s = l && l.speedLight
    return s ? {s: s.s, radius: s.radius, alpha: s.alpha, speedX: ninja.speedX,
                hazeScale: s.hazeScale, lowHp: l.lowHp ? {blend: l.lowHp.blend, gain: l.lowHp.gain} : null,
                cap: GAMEPLAY.momentumMaxSpeed * (typeof momentumMotionScale == 'function' ? momentumMotionScale(1) : 1),
                k: canvas.width / width * scale[version]} : null }'''


def frame(h, hp, pin):
    context, page = h.open(VIEWPORT)
    try:
        page.evaluate(fx.BUILD, [fx.SCENE_SPECS[SCENE], True])
        if pin:
            page.evaluate(PIN_SPEED)
        page.evaluate(SET_HP % (hp, 0, 0))
        info = page.evaluate(fx.DRAW)
        state = page.evaluate(STATE)
        png = fx.render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        assert not page.errors, page.errors
    finally:
        context.close()
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGB')), info, state


def crop_png(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).resize((img.shape[1] * 4, img.shape[0] * 4), Image.NEAREST).save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('revs', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--shots')
    args = ap.parse_args()
    rows = []
    for i, rev in enumerate(args.revs):
        h = fx.harness(rev)
        for pin in (False, True):
            f1, info, s1 = frame(h, 1, pin)
            f2, _, s2 = frame(h, 2, pin)
            cy, cx = centre_box(f1)
            a, b = f1[cy, cx].astype(np.int16), f2[cy, cx].astype(np.int16)
            d = np.abs(a - b).max(axis=2)
            ys, xs = np.nonzero(d)
            nx, ny = info['ninja']
            # nearest box px to the ninja centre, vs the light radius in canvas px
            qx = min(max(nx, cx.start), cx.stop - 1)
            qy = min(max(ny, cy.start), cy.stop - 1)
            pix = [[int(x + cx.start), int(y + cy.start), d[y, x].item(), a[y, x].tolist(), b[y, x].tolist()]
                   for y, x in zip(ys, xs)]
            rows.append({'rev': h.rev, 'pinnedSpeed': pin, 'box': [cx.start, cy.start, cx.stop, cy.stop],
                         'maxDelta': int(d.max()), 'diffPixels': int(len(xs)),
                         'diffBbox': [int(xs.min() + cx.start), int(ys.min() + cy.start), int(xs.max() + cx.start),
                                      int(ys.max() + cy.start)] if len(xs) else None,
                         'deltaHistogram': {str(v): int((d == v).sum()) for v in range(1, int(d.max()) + 1)},
                         'pixelsSample': pix[:12],
                         'ninjaPx': [round(nx, 1), round(ny, 1)],
                         'boxDistanceFromNinjaPx': round(float(np.hypot(qx - nx, qy - ny)), 1),
                         'lightRadiusPx': round(s1['radius'] * s1['k'], 1) if s1 else None,
                         'speedLightHp1': s1, 'speedLightHp2': s2})
            print(json.dumps(rows[-1])[:600])
            if args.shots and i == 0 and not pin:
                short = h.rev.split('@')[-1][:7]
                crop_png(f1[cy, cx], Path(args.shots) / f'centre-hp1-x4-{short}.png')
                crop_png(f2[cy, cx], Path(args.shots) / f'centre-hp2-x4-{short}.png')
                amp = np.clip(d * 60, 0, 255).astype(np.uint8)
                crop_png(np.stack([amp] * 3, axis=2), Path(args.shots) / 'centre-delta-x60-x4.png')
    Path(args.out).write_text(json.dumps({'scene': SCENE, 'viewport': list(VIEWPORT), 'rows': rows},
                                         separators=(',', ':')))
    fx.close()


if __name__ == '__main__':
    main()
