"""Isolate light generation/composition and conservative support; diagnostic only.

Runs the existing bounded Firefox timer/no-timer ABBA protocol. Production bytes
are immutable. Coverage is computed offline so union construction is not charged
to the measured renderer. Instrumented arms include support recording overhead.
"""
import math
from pathlib import Path
import statistics

import playgama_draw_profile as profile

TIMERS = r'''() => {
 window.drawProfile = [];
 let current = null;
 const light = visualEffects.lightmap;
 const add = (name, elapsed) => {
   if (!current) return;
   const cost = current.costs[name] ||= {ms:0, calls:0};
   cost.ms += elapsed; cost.calls++;
 };
 for (const key of ['clear','draw','composite']) {
   const original = light[key];
   light[key] = function(...args) {
     if (current && key === 'composite') {
       const m = this.ctx.getTransform();
       current.light = {rects: current.lightRects,
         source: [this.lightCanvas.width,this.lightCanvas.height],
         backing: [canvas.width,canvas.height],
         destination: [LOGICAL_VIEWPORT.width/scale[version],
                       LOGICAL_VIEWPORT.height/scale[version]],
         transform: [m.a,m.b,m.c,m.d,m.e,m.f], hasLights:this.hasLights};
     }
     const start = performance.now();
     try {return original.apply(this,args)}
     finally {add('light.'+key,performance.now()-start)}
   };
 }
 // Observe the actual post-culling sprite bounds. Do not read pixels, flush,
 // replace drawing, or alter any surface/transform/blend configuration.
 const record = (x,y,w,h) => {
   if (!current) return;
   const m = light.lightCtx.getTransform();
   const points = [[x,y],[x+w,y],[x,y+h],[x+w,y+h]].map(
     ([u,v])=>[m.a*u+m.c*v+m.e,m.b*u+m.d*v+m.f]);
   current.lightRects.push([
     Math.floor(Math.min(...points.map(p=>p[0])))-2,
     Math.floor(Math.min(...points.map(p=>p[1])))-2,
     Math.ceil(Math.max(...points.map(p=>p[0])))+2,
     Math.ceil(Math.max(...points.map(p=>p[1])))+2]);
 };
 const originalImage = light.lightCtx.drawImage;
 light.lightCtx.drawImage = function(...args) {
   if (args.length !== 5) throw Error('Unexpected light sprite drawImage signature');
   record(...args.slice(1));
   return originalImage.apply(this,args);
 };
 const originalFill = light.lightCtx.fillRect;
 light.lightCtx.fillRect = function(...args) {
   record(...args); return originalFill.apply(this,args);
 };
 const original = draw;
 draw = function(...args) {
   const row = {start:performance.now(),costs:{},frameId:drawFrameId+1,lightRects:[]};
   current = row;
   try {return original.apply(this,args)}
   finally {
     row.end=performance.now(); row.ms=row.end-row.start;
     window.drawProfile.push(row); current=null;
   }
 };
}'''


def support_rects(light):
    """Map padded source rectangles through the unchanged full-image transform."""
    sw, sh = light['source']
    dw, dh = light['destination']
    width, height = light['backing']
    a, b, c, d, e, f = light['transform']
    result = []
    for left, top, right, bottom in light['rects']:
        left, top = max(0, left), max(0, top)
        right, bottom = min(sw, right), min(sh, bottom)
        if left >= right or top >= bottom:
            continue
        points = [(a*x*dw/sw+c*y*dh/sh+e, b*x*dw/sw+d*y*dh/sh+f)
                  for x in (left, right) for y in (top, bottom)]
        x0 = max(0, math.floor(min(x for x, y in points))-2)
        y0 = max(0, math.floor(min(y for x, y in points))-2)
        x1 = min(width, math.ceil(max(x for x, y in points))+2)
        y1 = min(height, math.ceil(max(y for x, y in points))+2)
        if x0 < x1 and y0 < y1:
            result.append((x0, y0, x1, y1))
    return result


def union_area(rects):
    """Exact rectangle union area using disjoint vertical slabs."""
    edges = sorted({x for r in rects for x in (r[0], r[2])})
    area = 0
    for left, right in zip(edges, edges[1:]):
        spans = sorted((y0, y1) for x0, y0, x1, y1 in rects
                       if x0 < right and x1 > left)
        end = -1
        covered = 0
        for low, high in spans:
            covered += max(0, high-max(low, end))
            end = max(end, high)
        area += (right-left)*covered
    return area


original_audit = profile.audit


def audit(out):
    original_audit(out)
    for index in (1, 2):
        raw = profile.read(out/f'{index}-B-raw.json')
        active = 0
        coverage = []
        counts = []
        for before, after in zip(raw['frames'], raw['frames'][1:]):
            if any(before['after'].values()) or any(after['before'].values()):
                continue
            if active >= 5000:
                for row in before['draws']:
                    light = row['light']
                    rects = support_rects(light)
                    fraction = union_area(rects)/math.prod(light['backing'])
                    assert 0 <= fraction <= 1
                    assert not light['hasLights'] or light['rects'], 'unobserved lights'
                    coverage.append(fraction)
                    counts.append(len(rects))
            active += after['t']-before['t']
        assert coverage
        print(f'SUPPORT B{index}: frames={len(coverage)} '
              f'coverage_min_mean_max={min(coverage):.6f}/'
              f'{statistics.mean(coverage):.6f}/{max(coverage):.6f} '
              f'rectangles_mean={statistics.mean(counts):.3f}')
    print('DIAGNOSTIC_ONLY: conservative geometric bounds, not pixel equality or adoption')


if __name__ == '__main__':
    profile.TIMERS = TIMERS
    profile.audit = audit
    # The shared driver must invoke and preserve this entry point in each arm.
    profile.__file__ = str(Path(__file__).resolve())
    profile.main()
