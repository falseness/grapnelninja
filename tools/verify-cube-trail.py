"""Frame 1 cube trail capture: records how the JumpingCube trail follows the cube.

Run a local HTTP server, then run this script with Python Playwright.
Bad mode is started with only the chosen frame(s) on the gameplay floor and the
trail enabled. The ninja (and so the camera) is held still; the game's own
physics() and draw() are stepped tick by tick so each moment can be captured.
Per tick the cube box, centre, speeds and a copy of cube.track.pos are stored;
every newly added trail point is measured against the cube centre at the cycle
that added it. The summary reports edgeFlips (consecutive trail points whose y
differs by >= 0.9 * cube height), maxTrailOffsetFromCenter, wallBounces (speedX
sign changes) and apexes (speedY sign changes). Screenshots are taken at an
apex, a left-wall bounce, a right-wall bounce and mid-flight; for vertical
cubes (speedX == 0) at an apex, a floor bounce, mid-rise and mid-fall.
Outputs are untracked evidence, defaulting to artifacts/TASK-067/before.
"""
import argparse, hashlib, json, math, subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:8067/')
parser.add_argument('--frames', default='frame1Elements')
parser.add_argument('--output', type=Path, default=Path('artifacts/TASK-067/before'))
parser.add_argument('--label', default='before')
parser.add_argument('--ticks', type=int, default=900)
parser.add_argument('--warmup', type=int, default=60, help='ticks before screenshots, so the trail is long')
args = parser.parse_args()
out = args.output
out.mkdir(parents=True, exist_ok=True)

SETUP = '''(frame) => {
    cancelAnimationFrame(game); chooseVersion();
    trackEnabled = true; QUALITY.playerTrail = true;
    // Hold the ninja (and so the camera) still; everything else is live.
    ninja.move = () => {}; ninja.speedX = 0; ninja.speedY = 0;
    floors[1].elements = []; floors[1].creations = [{type: frame, chance: 100}];
    floors[1].generatePrimaryElements();
    const cube = floors[1].elements.find(e => e instanceof JumpingCube);
    const pillars = floors[1].elements.filter(e => e instanceof Trampoline).slice(0, 2);
    const box = e => { const p = e.getPoints();
        return {left: Math.min(...p.map(p => p.x)), right: Math.max(...p.map(p => p.x)),
                top: Math.min(...p.map(p => p.y)), bottom: Math.max(...p.map(p => p.y))}; };
    const centre = () => ({x: cube.x + cube.width / 2, y: cube.y + cube.height / 2});
    // Place the ninja left of the cube's pillars, at the cube's height, so the frame is in view.
    const lp = pillars.length ? box(pillars[0]) : box(cube);
    ninja.x = lp.left - 0.1 * width; ninja.y = box(cube).top;
    const probe = {ticks: [], added: [], tick: 0};
    // Measure each new trail point against the cube centre of the move that added it.
    const move = cube.move.bind(cube);
    cube.move = () => { const before = cube.track.pos[cube.track.pos.length - 1];
        move();
        const last = cube.track.pos[cube.track.pos.length - 1];
        if (last !== before) { const c = centre();
            probe.added.push({tick: probe.tick, x: last.x, y: last.y, centre: c, speedY: cube.speedY,
                offset: Math.hypot(last.x - c.x, last.y - c.y)}); } };
    let lastX = cube.speedX, lastY = cube.speedY;
    window.trailStep = () => { probe.tick += 1; physics();
        const rec = {tick: probe.tick, box: box(cube), centre: centre(), speedX: cube.speedX, speedY: cube.speedY,
            wallBounce: Math.sign(cube.speedX) !== Math.sign(lastX), apex: lastY < 0 && cube.speedY >= 0,
            speedYFlip: Math.sign(cube.speedY) !== Math.sign(lastY), trail: cube.track.pos.map(p => ({x: p.x, y: p.y}))};
        lastX = cube.speedX; lastY = cube.speedY;
        probe.ticks.push(rec); return rec; };
    window.trailRun = (kind, warmup, maxTicks, mid) => { for (let i = 0; i < maxTicks; ++i) {
        const r = trailStep(); if (r.tick < warmup) continue;
        const cx = r.centre.x;
        if ((kind === 'apex' && r.apex) || (kind === 'wall-left' && r.wallBounce && cx < mid)
            || (kind === 'wall-right' && r.wallBounce && cx >= mid)
            || (kind === 'midflight' && Math.abs(cx - mid) < Math.abs(r.speedX) * cyclesPerTick && !r.speedYFlip)
            // Vertical cubes (speedX == 0) never hit walls: capture floor bounce and mid rise/fall instead.
            || (kind === 'floor-bounce' && r.speedYFlip && r.speedY <= 0)
            || (kind === 'rising' && i >= 10 && r.speedY < 0 && !r.speedYFlip)
            || (kind === 'falling' && i >= 10 && r.speedY > 0 && !r.speedYFlip))
            { draw(); return {tick: r.tick, centre: r.centre, box: r.box, speedX: r.speedX, speedY: r.speedY}; } }
        draw(); return null; };
    window.trailProbe = probe;
    resetPhysicsTiming(); draw();
    return {cube: box(cube), cubeWidth: cube.width, cubeHeight: cube.height, pillars: pillars.map(box),
            stepMs: physicsStepMs, cyclesPerTick, trailLineWidth: cube.track.lineWidth,
            trailPointsLimit: cube.track.pointsLimit, ninja: {x: ninja.x, y: ninja.y}, speedX: cube.speedX};
}'''

console, errors, report = [], [], {}
r = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
     'harnessSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'label': args.label, 'frames': {}}
with sync_playwright() as p:
    b = p.chromium.launch(args=['--no-sandbox'])
    page = b.new_page(viewport={'width': 772, 'height': 630})
    page.on('console', lambda m: console.append(m.type + ': ' + m.text))
    page.on('pageerror', lambda e: errors.append(str(e)))
    for frame in args.frames.split(','):
        page.goto(args.url)
        page.evaluate("startGame('bad'); cancelAnimationFrame(game)")
        setup = page.evaluate(SETUP, frame)
        pl = setup['pillars']
        mid = (pl[0]['right'] + pl[1]['left']) / 2 if len(pl) >= 2 else (setup['cube']['left'] + setup['cube']['right']) / 2
        shots = []
        kinds = ('apex', 'wall-left', 'wall-right', 'midflight') if setup['speedX'] else ('apex', 'floor-bounce', 'rising', 'falling')
        for kind in kinds:
            hit = page.evaluate('([k, w, m, mid]) => trailRun(k, w, m, mid)', [kind, args.warmup, 1200, mid])
            assert hit, f'{frame}: no {kind} moment found'
            t = hit['tick'] * setup['stepMs'] / 1000
            name = f'{args.label}-{frame}-{kind}-tick{hit["tick"]:04}-t{t:06.3f}s.png'
            page.screenshot(path=str(out / name))
            shots.append(dict(hit, moment=kind, seconds=t, path=str(out / name)))
        page.evaluate('([n]) => { for (let i = trailProbe.tick; i < n; ++i) trailStep(); }', [args.ticks])
        probe = page.evaluate('trailProbe')
        h = setup['cubeHeight']
        flips = []
        for a, c in zip(probe['added'], probe['added'][1:]):
            if abs(c['y'] - a['y']) >= 0.9 * h:
                flips.append({'tick': c['tick'], 'fromY': a['y'], 'toY': c['y'], 'dy': c['y'] - a['y']})
        summary = {'frame': frame, 'ticks': len(probe['ticks']), 'trailPointsAdded': len(probe['added']),
                   'cubeWidth': setup['cubeWidth'], 'cubeHeight': h, 'trailLineWidth': setup['trailLineWidth'],
                   'edgeFlips': len(flips), 'maxTrailOffsetFromCenter': max(a['offset'] for a in probe['added']),
                   'minTrailOffsetFromCenter': min(a['offset'] for a in probe['added']),
                   'halfCubeHeight': h / 2,
                   'wallBounces': sum(t['wallBounce'] for t in probe['ticks']),
                   'apexes': sum(t['speedYFlip'] for t in probe['ticks']),
                   'screenshots': [s['path'] for s in shots]}
        summary['offsetMinusHalfHeight'] = summary['maxTrailOffsetFromCenter'] - h / 2
        r['frames'][frame] = {'summary': summary, 'setup': setup, 'screens': shots, 'edgeFlipList': flips,
                              'addedPoints': probe['added'], 'ticks': probe['ticks']}
        report[frame] = summary
    b.close()

r.update(console=console, errors=errors)
first = r['frames'][args.frames.split(',')[0]]
# Top-level summary fields mirror the first (default Frame 1) frame for quick reading.
r['summary'] = first['summary']
r['perTick'] = first['ticks']
(out / 'trail.json').write_text(json.dumps(r, indent=1))
(out / 'console.log').write_text('\n'.join(console))
(out / 'page-errors.log').write_text('\n'.join(errors))
for frame, s in report.items():
    print(json.dumps(s))
    print(f"{frame}: edgeFlips={s['edgeFlips']} maxTrailOffsetFromCenter={s['maxTrailOffsetFromCenter']:.9f} "
          f"cubeHeight/2={s['halfCubeHeight']:.9f} wallBounces={s['wallBounces']} apexes={s['apexes']} "
          f"cubeWidth={s['cubeWidth']:.6f} cubeHeight={s['cubeHeight']:.6f} trailLineWidth={s['trailLineWidth']:.6f}")
print(f'console messages={len(console)} page errors={len(errors)}')
assert not errors and not any(m.startswith('error:') for m in console)
