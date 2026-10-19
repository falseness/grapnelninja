"""TASK-097: the lit backdrop size cap leaves capped-out viewports equal.

Usage: python3 momentum_lit_backdrop_cap_probe.py OUT SHOTS NEW OLD
Captures the 4 momentum_fx_support scenes with MOMENTUM_FX on and off at
1280x720@1, 844x390@3 (phone: touch, backing at DPR 2) and 1920x1080@3 in
NEW and OLD (git revs or 'worktree') and records the decoded maxDelta and
the backdrop scale sizeCap gives (1: no cap) per capture. Viewports the cap
leaves at 1 must be equal (allEqualUncapped); the capped ones (1920x1080@3,
FX on) are the documented diff: mean/p99 delta, and crops round the ninja
and round the largest delta in SHOTS (OLD | NEW | |delta| x 8). OUT gets compact JSON.
"""
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import momentum_fx_support as fx
from momentum_fx_support import FxHarness, render_snapshot, SEED, SEED_COURSE, SCRIPT, SEED_SCRIPT

VIEWPORTS = [(1280, 720, 1, False), (844, 390, 3, True), (1920, 1080, 3, False)]
CAP_JS = "() => typeof BACKDROP.sizeCap == 'function' ? BACKDROP.sizeCap() : null"
CROP = 360


class DprHarness(FxHarness):
    def open(self, viewport):
        w, h, dpr, touch = viewport
        context = self.browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=dpr,
                                           is_mobile=touch, has_touch=touch)
        context.add_init_script(SEED_SCRIPT % SEED)
        context.add_init_script(render_snapshot.CLOCK_SCRIPT)
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


def capture(harness, scene, viewport, fx_on):
    """Frame plus the sizeCap the frame was drawn with."""
    context, page = harness.open(viewport)
    try:
        page.evaluate(fx.BUILD, [fx.SCENE_SPECS[scene], bool(fx_on)])
        info = page.evaluate(fx.DRAW)
        cap = page.evaluate(CAP_JS)
        backing = page.evaluate('() => [canvas.width, canvas.height]')
        png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        if page.errors:
            raise RuntimeError(f'page errors in {scene} {viewport}: {page.errors}')
    finally:
        context.close()
    img = np.asarray(Image.open(io.BytesIO(png)).convert('RGB'))
    return img, info, cap, backing


def crop(img, centre):
    """CROP x CROP px (backing px) round centre, clamped to the frame."""
    h, w = img.shape[:2]
    cx, cy = (int(v) for v in centre)
    x0 = min(max(0, cx - CROP // 2), w - CROP)
    y0 = min(max(0, cy - CROP // 2), h - CROP)
    return img[y0:y0 + CROP, x0:x0 + CROP], [x0, y0]


def main(out, shots, new, old):
    shots = Path(shots)
    shots.mkdir(parents=True, exist_ok=True)
    first = DprHarness(new)
    second = DprHarness(old, first.browser)
    results = []
    try:
        for viewport in VIEWPORTS:
            for scene in fx.SCENES:
                for fx_on in (True, False):
                    a, ainfo, acap, abacking = capture(first, scene, viewport, fx_on)
                    b, _, bcap, bbacking = capture(second, scene, viewport, fx_on)
                    delta = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
                    row = {'new': first.rev, 'old': second.rev, 'scene': scene,
                           'viewport': list(viewport[:3]), 'touch': viewport[3], 'fx': fx_on,
                           'backing': abacking, 'oldBacking': bbacking,
                           'sizeCapNew': acap, 'sizeCapOld': bcap, 'maxDelta': int(delta.max())}
                    if row['maxDelta']:
                        row.update(meanDelta=round(float(delta.mean()), 3),
                                   p99Delta=int(np.percentile(delta, 99)),
                                   pxOver8=round(float((delta > 8).mean()), 5))
                    if acap is not None and acap < 1:
                        name = f'{scene}-{viewport[0]}x{viewport[1]}@{viewport[2]}-fx{int(fx_on)}'
                        worst = np.unravel_index(int(delta.argmax()), delta.shape)[::-1]
                        row['shots'] = []
                        for kind, centre in (('ninja', ainfo['ninja']), ('maxdelta', worst)):
                            ac, at = crop(a, centre)
                            bc, _ = crop(b, centre)
                            dc, _ = crop(np.repeat(np.minimum(255, delta * 8)[..., None], 3, axis=2).astype(np.uint8), centre)
                            gap = np.full((CROP, 8, 3), 24, np.uint8)
                            Image.fromarray(np.concatenate([bc, gap, ac, gap, dc], axis=1)) \
                                .save(shots / f'{name}-{kind}.png')
                            row['shots'].append(f'{name}-{kind}.png crop at {at}')
                    results.append(row)
                    print(row, flush=True)
    finally:
        second.close()
        first.close()
    uncapped = [r for r in results if r['sizeCapNew'] == 1]
    capped = [r for r in results if r['sizeCapNew'] != 1]
    summary = {'allEqualUncapped': all(r['maxDelta'] == 0 for r in uncapped),
               'uncapped': len(uncapped), 'capped': len(capped),
               'cappedOnlyFxOn1920x1080@3': all(r['fx'] and r['viewport'] == [1920, 1080, 3] for r in capped),
               'results': results}
    Path(out).write_text(json.dumps(summary))
    print({k: v for k, v in summary.items() if k != 'results'})
    return 0 if summary['allEqualUncapped'] else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:5]))
