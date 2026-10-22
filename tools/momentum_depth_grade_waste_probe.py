"""Momentum depth grade waste probe (TASK-162, audit TASK-158 R4/R5).

Per revision (1280x720@1, frozen clock, seeded course):
- builds: BackgroundRenderer.layerBuilds for far/farBaked/near after boot,
  startGame('momentum'), its first draw(), a restart and its first draw(),
  with BACKDROP.scale 1 and 0.5 (set before the run start); frame1Rebuilt
  is true when a first draw() after a run start built a tile again.
- worker: 'rotate' messages posted to the layer tile worker vs jobs whose
  answer was adopted (HueRotateJob.received with all bitmaps, job still
  pending) for a graded run (score 120, inside a blend: a next-step job too) whose viewport changes (1280x720 ->
  844x390 -> 1280x720, onViewportResize, one draw() each: the immediate
  rotation path), waiting for the worker between draws.
- pixels: the decoded frame after one draw() at score 0, 120 and 150, BACKDROP
  scale 1 and 0.5.

Usage: python3 momentum_depth_grade_waste_probe.py OUT_DIR PARENT_REV
(writes builds.json, worker.json, pixels.json: parent vs worktree)
"""
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
import render_snapshot

VIEWPORT = (1280, 720)
SCALES = (1, 0.5)
GRADED_SCORE = 120

COUNT_SCRIPT = r'''
window.__realNow = performance.now.bind(performance)
window.__rotatePosts = 0
const __post = Worker.prototype.postMessage
Worker.prototype.postMessage = function(message, ...rest) {
    if (message && message.type === 'rotate') ++window.__rotatePosts
    return __post.call(this, message, ...rest)
}
'''

BUILDS = r'''() => {
    const b = visualEffects.background.layerBuilds
    return {far: b.far || 0, farBaked: b.farBaked || 0, near: b.near || 0}
}'''

START = "([scale]) => { BACKDROP.scale = scale; startGame('momentum'); cancelAnimationFrame(game) }"

WORKER_SETUP = r'''async () => {
    const now = window.__realNow
    if (typeof DEPTH_GRADE_CLOCK == 'object') DEPTH_GRADE_CLOCK.now = now
    window.__consumed = 0
    const received = HueRotateJob.prototype.received
    HueRotateJob.prototype.received = function(bitmaps) {
        const adopt = !this.done && this.remote && bitmaps.every(Boolean)
        received.call(this, bitmaps)
        if (adopt && this.done) ++window.__consumed
    }
    const channel = new MessageChannel()
    const nextTask = () => new Promise(resolve => { channel.port1.onmessage = resolve; channel.port2.postMessage(0) })
    // Pending posts and answers settle (the colour reads, the posts, the
    // worker's bitmaps)
    window.__settle = async () => {
        for (const t0 = now(); now() - t0 < 10000; ) {
            await nextTask()
            if (!LAYER_TILE_WORKER.jobs.size && now() - t0 > 300) break
        }
    }
    await window.__settle()
    window.__posts0 = window.__rotatePosts
    window.__rebuilds0 = visualEffects.background.depthGrade.rebuilds
}'''

# One graded draw() (after a resize when resized), then the worker settles
WORKER_STEP = r'''async ([score, resized]) => {
    if (resized) onViewportResize()
    scoreText.count.momentum = score
    draw()
    await window.__settle()
    const grade = visualEffects.background.depthGrade
    return {canvas: [canvas.width, canvas.height], posted: window.__rotatePosts - window.__posts0,
            consumed: window.__consumed, gradeRebuilds: grade.rebuilds - window.__rebuilds0,
            hue: visualEffects.background.getDepthHue(score), pendingJobs: LAYER_TILE_WORKER.jobs.size}
}'''


def open_page(tree):
    w, h = VIEWPORT
    context = tree.browser.new_context(viewport={'width': w, 'height': h})
    context.add_init_script(COUNT_SCRIPT)
    context.add_init_script(fx.SEED_SCRIPT % fx.SEED)
    context.add_init_script(render_snapshot.CLOCK_SCRIPT)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
    page.goto(tree.url + 'index.html', wait_until='load')
    render_snapshot.boot_frozen(page)
    page.evaluate(render_snapshot.SETUP_SCRIPT, [[], False])
    page.evaluate(fx.SEED_COURSE, fx.SCRIPT)
    page.errors = errors
    return context, page


def check_errors(page, what):
    if page.errors:
        raise RuntimeError(f'page errors in {what}: {page.errors}')


def builds(tree, scale):
    context, page = open_page(tree)
    try:
        rows = [dict(stage='boot', **page.evaluate(BUILDS))]
        for run in ('start', 'restart'):
            page.evaluate(START, [scale])
            rows.append(dict(stage=run, **page.evaluate(BUILDS)))
            page.evaluate('() => { scoreText.count.momentum = 0; draw() }')
            rows.append(dict(stage=run + '+frame1', **page.evaluate(BUILDS)))
        check_errors(page, f'builds {scale}')
    finally:
        context.close()
    rebuilt = any(rows[i][k] != rows[i - 1][k] for i in (2, 4) for k in ('far', 'farBaked', 'near'))
    return {'scale': scale, 'rows': rows, 'frame1Rebuilt': rebuilt}


def worker(tree):
    context, page = open_page(tree)
    try:
        page.evaluate(START, [1])
        page.evaluate(WORKER_SETUP)
        steps = []
        for size in (None, (844, 390), VIEWPORT):
            if size:
                page.set_viewport_size({'width': size[0], 'height': size[1]})
            steps.append(dict(viewport=list(size or VIEWPORT), **page.evaluate(WORKER_STEP, [GRADED_SCORE, bool(size)])))
        check_errors(page, 'worker')
    finally:
        context.close()
    last = steps[-1]
    return {'score': GRADED_SCORE, 'hue': last['hue'], 'posted': last['posted'], 'consumed': last['consumed'],
            'pendingJobs': last['pendingJobs'], 'steps': steps}


def frame(tree, scale, score):
    context, page = open_page(tree)
    try:
        page.evaluate(START, [scale])
        page.evaluate('([s]) => { scoreText.count.momentum = s; draw() }', [score])
        png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
        hue = page.evaluate('([s]) => visualEffects.background.getDepthHue(s)', [score])
        check_errors(page, f'frame {scale} {score}')
    finally:
        context.close()
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype(int), hue


def compact(data):
    return json.dumps(data, separators=(',', ':'))


def main(out, parent):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    trees = {'parent': fx.harness(parent), 'fix': fx.harness('worktree')}
    try:
        build_rows = {name: [builds(tree, s) for s in SCALES] for name, tree in trees.items()}
        build_rows['revs'] = {name: tree.rev for name, tree in trees.items()}
        (out / 'builds.json').write_text(compact(build_rows))
        work = {name: worker(tree) for name, tree in trees.items()}
        work['revs'] = build_rows['revs']
        (out / 'worker.json').write_text(compact(work))
        pixels = []
        for scale in SCALES:
            for score in (0, GRADED_SCORE, 150):
                (a, hue_a), (b, hue_b) = (frame(trees[n], scale, score) for n in ('parent', 'fix'))
                pixels.append({'scale': scale, 'score': score, 'hue': [hue_a, hue_b], 'shape': list(a.shape),
                               'maxDelta': int(np.abs(a - b).max()), 'revs': build_rows['revs']})
        (out / 'pixels.json').write_text(compact(pixels))
    finally:
        fx.close()
    print(compact({'builds': {n: [r['frame1Rebuilt'] for r in build_rows[n]] for n in trees},
                   'worker': {n: [work[n]['posted'], work[n]['consumed']] for n in trees},
                   'pixels': [r['maxDelta'] for r in pixels]}))


if __name__ == '__main__':
    main(*sys.argv[1:])
