"""Boot profile and time to READY at 1920x1080@3 (no touch) for a tree.

usage: momentum_boot_profile_probe.py <tree> <label> <runs> <times.jsonl> [profile.json]

Each run opens a fresh page, lighting on (default) and stored off
('grapnelninja.lighting' read as 'false'), and records the seconds from the
end of page.goto to READY (the probe_boot.py measure, artifacts/TASK-080).
With profile.json, one extra lighting-on run is sampled by the CDP Profiler
from navigation to READY; every function's inclusive ms (samples whose stack
holds it) goes in, keyed 'name file' (no line: the trees differ), for the
game's own scripts, plus STEPS (the lighting caches/passes by name) and the
gameLoop frames through READY (ms each, from a requestAnimationFrame hook,
read right after READY, so the last one may follow it).
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

tree = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(tree / 'tools'))
from game_harness import READY, open_game, start_game_test  # noqa: E402

LIGHTING_OFF = ("(() => { const g = Storage.prototype.getItem; Storage.prototype.getItem ="
                " function (k) { return k === 'grapnelninja.lighting' ? 'false' : g.call(this, k) } })()")
VIEW = {'width': 1920, 'height': 1080}
# Lighting caches and passes: 'name file' keys summed into a step
STEPS = {
    'lightsLayer (all lighting composites)': ['drawLightsLayer draw.js'],
    'momentumLight (ambient multiply + rim)': ['compositeMomentumLight effects.js'],
    'crystalRim': ['addCrystalRim effects.js'],
    'crystalRim.edgeTiles': ['drawLayerEdges effects.js'],
    'shadowedLights': ['addShadowedLight effects.js'],
    'deepShadows': ['addDeepShadows effects.js'],
    'haze': ['addMomentumHaze effects.js'],
    'wallVeins': ['draw wallveins.js'],
    'wallVeins.tiles': ['getTile wallveins.js'],
    'foreground': ['draw foreground.js'],
    'depthGrade.prepare': ['prepareDepthGrade effects.js'],
    'litMotes': ['drawAmbientMotes effects.js'],
    'glowSprites.warm': ['warmGlowSprites draw.js'],
    'backdrop.end (copy up)': ['end backdrop.js'],
    'background layer': ['drawBackgroundLayer draw.js'],
    'draw (all)': ['draw draw.js'],
}
RAF_HOOK = """(() => { const raf = window.requestAnimationFrame.bind(window); window.__frames = []
window.requestAnimationFrame = cb => raf(t => { const s = performance.now(); try { cb(t) } finally {
 if (cb.name == 'gameLoop') window.__frames.push(Math.round(performance.now() - s)) } }) })()"""
STATE = ("({fx: typeof MOMENTUM_FX !== 'undefined' ? MOMENTUM_FX.enabled : null,"
         " backing: [canvas.width, canvas.height]})")


def timed_boot(browser, url, lighting):
    context = browser.new_context(viewport=VIEW, device_scale_factor=3)
    if lighting == 'off':
        context.add_init_script(LIGHTING_OFF)
    page = context.new_page()
    page.goto(url)
    t0 = time.time()
    ok = True
    try:
        page.wait_for_function(READY, timeout=120000)
    except Exception:
        ok = False
    secs = time.time() - t0
    state = page.evaluate(STATE)
    context.close()
    return {'ready': ok, 'secs': round(secs, 2), **state}


def profiled_boot(browser, url):
    context = browser.new_context(viewport=VIEW, device_scale_factor=3)
    context.add_init_script(RAF_HOOK)
    page = context.new_page()
    cdp = context.new_cdp_session(page)
    cdp.send('Profiler.enable')
    cdp.send('Profiler.setSamplingInterval', {'interval': 200})
    cdp.send('Profiler.start')
    page.goto(url)
    t0 = time.time()
    page.wait_for_function(READY, timeout=120000)
    secs = time.time() - t0
    profile = cdp.send('Profiler.stop')['profile']
    frames = page.evaluate('window.__frames')
    context.close()
    nodes = {n['id']: n for n in profile['nodes']}
    parent = {}
    for n in profile['nodes']:
        for c in n.get('children', []):
            parent[c] = n['id']

    def key(n):
        f = n['callFrame']
        name = f['functionName'] or '(anonymous)'
        src = f['url'].split('/')[-1] if f['url'] else ''
        return f"{name} {src}" if src else name

    own = url.rstrip('/')
    inclusive = defaultdict(float)
    total = 0.0
    for sid, dt in zip(profile['samples'], profile['timeDeltas'][1:] + [0]):
        ms = dt / 1000
        total += ms
        seen = set()
        n = sid
        while n is not None:
            node = nodes[n]
            if node['callFrame']['url'].startswith(own):
                seen.add(key(node))
            n = parent.get(n)
        for k in seen:
            inclusive[k] += ms
    top = sorted(inclusive.items(), key=lambda kv: -kv[1])
    steps = {step: round(sum(inclusive.get(k, 0) for k in keys), 1) for step, keys in STEPS.items()}
    return {'readySecs': round(secs, 2), 'profiledMs': round(total, 1),
            'gameLoopFramesBeforeReadyMs': frames, 'stepsMs': steps,
            'inclusiveMs': {k: round(v, 1) for k, v in top if v >= 5}}


def main():
    label, runs, out = sys.argv[2], int(sys.argv[3]), sys.argv[4]
    cleanups = []
    url, browser = start_game_test(tree, cleanups.append)
    try:
        with open(out, 'a') as f:
            for run in range(runs):
                for lighting in ('on', 'off'):
                    row = {'label': label, 'lighting': lighting, 'run': run,
                           **timed_boot(browser, url, lighting)}
                    f.write(json.dumps(row) + '\n')
                    f.flush()
                    print(row, flush=True)
        if len(sys.argv) > 5:
            prof = {'label': label, **profiled_boot(browser, url)}
            path = Path(sys.argv[5])
            data = json.loads(path.read_text()) if path.exists() else {}
            data[label] = prof
            path.write_text(json.dumps(data))
            print(json.dumps(prof)[:3000])
    finally:
        for c in reversed(cleanups):
            try:
                c()
            except Exception:
                pass


if __name__ == '__main__':
    main()
