"""TASK-700: per-layer draw() profile of the Grapple Over frame at camera scale 0.25 vs 0.375.

Measurement only. One headless Chromium at 1920x1080, DPR 1, ?perf=1&backdrop=1 (the
backdrop forced to full quality, so the adaptive switch never steps down). The game loop is
frozen and draw() is called directly with the camera snapped to fixed poses on the shipped
level; scale.grapple_over is overridden at runtime only (gameoptions.js is untouched).
Each draw() layer that render/perfprofile.js wraps is timed again per call (median over the
measured frames). Scales are alternated in two rounds per pose (0.375, 0.25 then 0.25,
0.375), each round WARMUP frames after the switch and then MEASURED // 2 frames. A separate
single frame per pose and scale counts canvas draw calls per layer (CanvasRenderingContext2D
prototype methods, offscreen canvases included), so counting never costs timed frames.
Headless timings are only meaningful relative to each other.

Example: python3 tools/profile_camera_scale.py --out artifacts/TASK-700/profile.json
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCALES = (0.375, 0.25)
WARMUP = 10
MEASURED = 60
SOURCES = ('gameoptions.js', 'render/draw.js', 'render/perfprofile.js', 'render/backdrop.js',
           'render/culling.js', 'render/parallax.js', 'render/effects.js', 'style.js', 'sprites/floor.js',
           'fixedlevel.js', 'index.html', 'tools/profile_camera_scale.py')

HELPER = r'''
window.T700 = (() => {
  const LAYERS = ['drawBackgroundLayer', 'drawLightsLayer', 'drawBehindForegroundParticlesLayer',
    'drawPlayerTrailLayer', 'drawWorldLayer', 'drawParticlesAndTrailsLayer', 'drawBloomLayer',
    'drawPlayerGlowLayer', 'drawColorGradeLayer', 'drawPlayerLayer', 'drawTutorialHintLayer',
    'drawFallMessageLayer', 'drawUILayer', 'drawFpsCounterLayer'];
  const METHODS = ['fill', 'stroke', 'fillRect', 'strokeRect', 'clearRect', 'drawImage', 'fillText',
    'strokeText', 'putImageData'];
  const name = g => { const n = g.replace(/^draw/, '').replace(/Layer$/, ''); return n === 'UI' ? 'ui' : n[0].toLowerCase() + n.slice(1); };
  let current = null, counting = false;
  const times = {}, calls = {};
  for (const g of LAYERS) {
    const fn = window[g];
    if (typeof fn !== 'function') continue;
    const n = name(g);
    window[g] = function() {
      const outer = current; current = n;
      const start = performance.now();
      try { return fn.apply(this, arguments); }
      finally { (times[n] = times[n] || []).push(performance.now() - start); current = outer; }
    };
  }
  const proto = CanvasRenderingContext2D.prototype;
  for (const m of METHODS) {
    const fn = proto[m];
    proto[m] = function() {
      if (counting) { const k = current || 'outside'; calls[k] = (calls[k] || 0) + 1; }
      return fn.apply(this, arguments);
    };
  }
  const median = a => { const s = a.slice().sort((x, y) => x - y), h = s.length >> 1;
    return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2; };
  const r3 = v => Math.round(v * 1000) / 1000;
  const api = {
    freeze() {
      window.requestAnimationFrame = () => 0; cancelAnimationFrame(game);
      PERF_OVERLAY.enabled = false; TUTORIAL_HINT.visible = false;
    },
    setScale(s) { scale.grapple_over = s; screen.updateWidthLayout(); layoutHud(); TUTORIAL_HINT.invalidate(); },
    poses() {
      const f = floors[0], center = z => { const p = z.getPoints(), xs = p.map(q => q.x), ys = p.map(q => q.y);
        return {x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2}; };
      const out = [{name: 'spawn', ...f.level.spawn}];
      for (const z of f.noGrappleZones) out.push({name: z.id, ...center(z)});
      const fin = f.level.finish;
      out.push({name: 'finish', x: (fin.left + fin.right) / 2, y: (fin.top + fin.bottom) / 2});
      return out.map(p => ({name: p.name, x: r3(p.x), y: r3(p.y)}));
    },
    place(p) {
      ninja.x = p.x; ninja.y = p.y; ninja.speedX = ninja.speedY = 0;
      grapnel.endShot(); screen.trackGrappleOver(true);
    },
    visible() {
      const f = floors[0], rect = getCullRect();
      const els = f.elements.filter(e => isCullBoxVisible(getElementCullBox(e), rect)).length;
      const zones = f.noGrappleZones.concat(f.dragZones).filter(z => isCullBoxVisible(getElementCullBox(z), rect)).length;
      return {elements: els, totalElements: f.elements.length, zones,
        cullRect: {left: r3(rect.left), top: r3(rect.top), right: r3(rect.right), bottom: r3(rect.bottom)}};
    },
    // frames draw() calls; the first warmup are not kept
    run(warmup, frames) {
      for (const k in times) delete times[k];
      const totals = [];
      for (let i = 0; i < warmup + frames; ++i) {
        if (i === warmup) for (const k in times) delete times[k];
        const start = performance.now(); draw(); const t = performance.now() - start;
        if (i >= warmup) totals.push(t);
      }
      return {totals, layers: Object.fromEntries(Object.entries(times))};
    },
    countCalls() {
      for (const k in calls) delete calls[k];
      counting = true; try { draw(); } finally { counting = false; }
      return Object.assign({}, calls);
    },
    summarize(runs) {
      const layers = {}, totals = [];
      for (const run of runs) {
        totals.push(...run.totals);
        for (const [k, v] of Object.entries(run.layers)) (layers[k] = layers[k] || []).push(...v);
      }
      return {frames: totals.length, totalMedianMs: r3(median(totals)),
        layers: Object.fromEntries(Object.entries(layers).map(([k, v]) => [k, {medianMs: r3(median(v)), samples: v.length}]))};
    },
    state() { return {version, scale: scale[version], backdropScale: BACKDROP.scale, backdropAdaptive: BACKDROP.adaptive,
      resolution: BACKDROP.resolution, canvas: [canvas.width, canvas.height], logical: [width, height], dpr: devicePixelRatio,
      perfProfile: typeof PERF_PROFILE === 'object'}; },
  };
  return api;
})();
'''


def sha256(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def profile(out):
    cleanups = []
    try:
        url, browser = start_browser_test(ROOT, cleanups.append)
        context = browser.new_context(viewport=dict(width=1920, height=1080), device_scale_factor=1)
        cleanups.append(context.close)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html?perf=1&backdrop=1')
        wait_for_boot_run(page)
        page.evaluate(HELPER)
        page.evaluate('T700.freeze()')
        shipped = page.evaluate('T700.state()')
        poses = page.evaluate('T700.poses()')
        rows = []
        for pose in poses:
            page.evaluate('p => T700.place(p)', pose)
            runs = {s: [] for s in SCALES}
            for order in (SCALES, tuple(reversed(SCALES))):
                for s in order:
                    page.evaluate('s => T700.setScale(s)', s)
                    page.evaluate('p => T700.place(p)', pose)
                    runs[s].append(page.evaluate('([w, n]) => T700.run(w, n)', [WARMUP, MEASURED // 2]))
            per_scale = {}
            for s in SCALES:
                page.evaluate('s => T700.setScale(s)', s)
                page.evaluate('p => T700.place(p)', pose)
                summary = page.evaluate('r => T700.summarize(r)', runs[s])
                summary.update(visible=page.evaluate('T700.visible()'),
                               cullPadding=round(page.evaluate('getCullPadding()'), 3),
                               drawCalls=page.evaluate('T700.countCalls()'),
                               perfProfileTop=[{k: e[k] for k in ('name', 'meanMs', 'samples')}
                                               for e in page.evaluate('PERF_PROFILE.snapshot()')['entries'][:5]])
                per_scale[str(s)] = summary
            rows.append(dict(pose=pose, scales=per_scale))
        page.evaluate('T700.setScale(%r)' % shipped['scale'])
        after = page.evaluate('T700.state()')
    finally:
        while cleanups:
            cleanups.pop()()

    # Ranking: layers by median ms at 0.25, summed over poses (median of per-pose medians
    # would hide a pose-specific cost; both are given).
    low, high = str(SCALES[1]), str(SCALES[0])
    names = sorted({k for r in rows for k in r['scales'][low]['layers']})
    agg = []
    for n in names:
        lo = [r['scales'][low]['layers'].get(n, {}).get('medianMs', 0) for r in rows]
        hi = [r['scales'][high]['layers'].get(n, {}).get('medianMs', 0) for r in rows]
        lo_sorted = sorted(lo)
        agg.append(dict(layer=n, medianMsAt025=round(lo_sorted[len(lo) // 2], 3), sumMsAt025=round(sum(lo), 3),
                        sumMsAt0375=round(sum(hi), 3), ratio025over0375=round(sum(lo) / sum(hi), 3) if sum(hi) else None,
                        perPoseRatio={r['pose']['name']: (round(a / b, 3) if b else None)
                                      for r, a, b in zip(rows, lo, hi)}))
    agg.sort(key=lambda a: -a['sumMsAt025'])
    result = dict(
        task='TASK-700', baselineSha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        url='index.html?perf=1&backdrop=1', viewport=[1920, 1080], dpr=1, warmupFrames=WARMUP,
        measuredFramesPerScale=MEASURED, scales=list(SCALES), shippedState=shipped, stateAfterRestore=after,
        pageErrors=errors, poses=rows, ranking=dict(scale=0.25, by='sum over poses of per-layer median ms',
                                                    top2=agg[:2], all=agg,
                                                    top2ByMedianAcrossPoses=sorted(agg, key=lambda a: -a['medianMsAt025'])[:2]),
        totals={r['pose']['name']: {s: r['scales'][s]['totalMedianMs'] for s in (high, low)} for r in rows},
        sourceSha256={p: sha256(p) for p in SOURCES},
        note='Headless Chromium timings: valid only relative to each other.')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = profile(args.out)
    for a in result['ranking']['top2']:
        print('TOP', a['layer'], 'sum@0.25=%.3f' % a['sumMsAt025'], 'ratio=%s' % a['ratio025over0375'])
    for name, t in result['totals'].items():
        print('TOTAL', name, t)
    if result['pageErrors']:
        print('PAGE ERRORS', result['pageErrors'])
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
