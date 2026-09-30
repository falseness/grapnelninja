"""Live Frame 1 grapnel capture: a real mouse click tethers the rope to the cube.

Run a local HTTP server, then run this script with Python Playwright and Pillow.
Bad mode is started with only Frame 1 on the gameplay floor. The ninja and the
camera are held still (observational instrumentation only); the cube, the
grapnel and its collision/wrapping run through the live game loop. The mouse
button is pressed on the moving cube and kept down, so the rope stays attached
while the cube bounces between the pillars and wraps a second cube corner.
Outputs are untracked evidence, defaulting to artifacts/TASK-066/grapnel.
"""
import argparse, base64, hashlib, json, subprocess, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:8066/')
parser.add_argument('--output', type=Path, default=Path('artifacts/TASK-066/grapnel'))
parser.add_argument('--seconds', type=float, default=12)
args = parser.parse_args()
out = args.output
out.mkdir(parents=True, exist_ok=True)

SETUP = '''() => {
    cancelAnimationFrame(game); chooseVersion();
    // Hold the ninja (and so the camera) still; everything else is live.
    ninja.move = () => {}; ninja.speedX = 0; ninja.speedY = 0;
    floors[1].elements = []; floors[1].creations = [{type: 'frame1Elements', chance: 100}];
    floors[1].generatePrimaryElements();
    window.cube = floors[1].elements.find(e => e instanceof JumpingCube);
    const pillars = floors[1].elements.filter(e => e instanceof Trampoline).slice(0, 2);
    window.box = e => { const p = e.getPoints();
        return {left: Math.min(...p.map(p => p.x)), right: Math.max(...p.map(p => p.x)),
                top: Math.min(...p.map(p => p.y)), bottom: Math.max(...p.map(p => p.y))}; };
    const outline = (x, y, b) => (x >= b.left && x <= b.right && y >= b.top && y <= b.bottom)
        ? Math.min(x - b.left, b.right - x, y - b.top, b.bottom - y)
        : Math.hypot(Math.max(b.left - x, 0, x - b.right), Math.max(b.top - y, 0, y - b.bottom));
    // Ninja between the left pillar and the cube, inside the cube's vertical range.
    const lp = box(pillars[0]);
    ninja.x = lp.right + 0.35 * (box(cube).left - lp.right);
    ninja.y = box(cube).top - 0.05 * height;
    window.probe = {frames: [], cornerEps: screenHeightPercent(GAMEPLAY.cornerToleranceHeightPercent),
        pillars: pillars.map(box), ninja: {x: ninja.x, y: ninja.y}};
    let lastSpeedX = cube.speedX;
    const physicsTick = window.physics;
    window.physics = function () {
        physicsTick();
        const b = box(cube);
        const points = grapnel.throwed ? grapnel.pos.map(p => ({x: p[0], y: p[1], type: p[2].constructor.name,
            cube: p[2] === cube, boundaryDistance: p[2] === cube ? outline(p[0], p[1], box(cube)) : null})) : [];
        const bounce = Math.sign(cube.speedX) !== Math.sign(lastSpeedX);
        lastSpeedX = cube.speedX;
        probe.frames.push({time: performance.now(), throwed: grapnel.throwed, grappled: grapnel.isGrappled(),
            points, cubePoints: points.filter(p => p.cube).length, cube: {x: cube.x, y: cube.y,
            speedX: cube.speedX, speedY: cube.speedY, box: b}, ninja: {x: ninja.x, y: ninja.y}, wallBounce: bounce});
    };
    // Canvas pixel of a world point.
    window.toClient = (x, y) => { const r = canvas.getBoundingClientRect();
        return {x: r.left + (x + screen.x) * scale[version] * r.width / canvas.width,
                y: r.top + (y + screen.y) * scale[version] * r.height / canvas.height}; };
    resetPhysicsTiming(); draw();
    game = requestAnimationFrame(gameLoop);
    return {scale: scale[version], cornerEps: probe.cornerEps, pillars: probe.pillars, ninja: probe.ninja, cube: box(cube)};
}'''

console, errors = [], []
r = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
     'harnessSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'screens': []}
with sync_playwright() as p:
    b = p.chromium.launch(args=['--no-sandbox'])
    page = b.new_page(viewport={'width': 772, 'height': 630})
    page.on('console', lambda m: console.append(m.type + ': ' + m.text))
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(args.url)
    page.evaluate("startGame('bad'); cancelAnimationFrame(game)")
    r['setup'] = page.evaluate(SETUP)
    # Wait until the cube heads back toward the ninja, then press on its centre
    # (real mousedown, kept down) so the hook lands on the cube's near face.
    page.wait_for_function('cube.speedX < 0 && box(cube).left - probe.ninja.x > 0.3 * height', timeout=15000)
    target = page.evaluate('''() => { const b = box(cube);
        const x = (b.left + b.right) / 2, y = (b.top + b.bottom) / 2;
        return {world: {x, y}, client: toClient(x, y), cube: b, time: performance.now()}; }''')
    r['click'] = target
    page.mouse.move(target['client']['x'], target['client']['y'])
    page.mouse.down()
    start = page.evaluate('performance.now()')
    shots = 0
    while True:
        page.wait_for_timeout(1000)
        snap = page.evaluate('''() => ({time: performance.now(), cube: box(cube), speedX: cube.speedX,
            points: grapnel.pos.map(p => [p[0], p[1], p[2].constructor.name, p[2] === cube]), png: canvas.toDataURL('image/png')})''')
        t = (snap['time'] - start) / 1000
        name = f'grapnel-{shots:02}-t{t:05.2f}s.png'
        (out / name).write_bytes(base64.b64decode(snap.pop('png').split(',')[1]))
        snap.update(path=str(out / name), secondsSincePress=t)
        r['screens'].append(snap)
        shots += 1
        if t >= args.seconds and shots >= 5:
            break
    page.mouse.up()
    page.evaluate('cancelAnimationFrame(game)')
    probe = page.evaluate('probe')
    b.close()

frames = [f for f in probe['frames'] if f['time'] >= r['click']['time']]
tethered = [f for f in frames if f['cubePoints'] >= 1]
first = next(i for i, f in enumerate(frames) if f['cubePoints'] >= 1)
# The hook itself must land on the cube: no other element is hit before it.
firstHit = next(f for f in frames if any(p['type'] != 'Empty' for p in f['points']))
dists = [p['boundaryDistance'] for f in frames for p in f['points'] if p['cube']]
bounces = [f for f in frames[first:] if f['wallBounce'] and f['cubePoints'] >= 1]
mid = (probe['pillars'][0]['right'] + probe['pillars'][1]['left']) / 2
sides = sorted({'left' if f['cube']['box']['left'] < mid else 'right' for f in bounces})
wrapped = [f for f in frames if f['cubePoints'] >= 2]
# Once attached, the rope must stay on the cube until the button is released.
dropped = [f for f in frames[first:] if f['cubePoints'] < 1 and f['time'] < r['screens'][-1]['time']]
summary = {'frames': len(frames), 'tetheredFrames': len(tethered), 'maxBoundaryDistance': max(dists),
           'cornerEps': probe['cornerEps'], 'wallBouncesWhileTethered': len(bounces), 'bounceSides': sides,
           'firstHitTypes': [p['type'] for p in firstHit['points']],
           'secondsFromPressToAttach': (frames[first]['time'] - r['click']['time']) / 1000,
           'framesWithTwoOrMoreCubePoints': len(wrapped), 'maxCubePoints': max(f['cubePoints'] for f in frames),
           'framesDroppedAfterAttach': len(dropped), 'screenshots': len(r['screens'])}
r.update(summary=summary, probe=probe, frames=frames, console=console, errors=errors)
(out / 'grapnel-live.json').write_text(json.dumps(r, indent=1))
(out / 'console.log').write_text('\n'.join(console))
(out / 'page-errors.log').write_text('\n'.join(errors))
print(json.dumps(summary))
assert max(dists) <= probe['cornerEps'], 'tethered point left the cube boundary'
assert firstHit['points'][-1]['cube'] and all(p['type'] in ('Empty', 'JumpingCube') for p in firstHit['points']), 'hook did not land on the cube'
assert len(bounces) >= 2 and sides == ['left', 'right'], 'cube did not bounce off both pillars while tethered'
assert wrapped, 'rope never wrapped to 2 cube points'
assert not dropped, 'rope detached from the cube while the button was held'
attachedShots = [s for s in r['screens'] if any(p[3] for p in s['points'])]
assert len(attachedShots) >= 5 and all(any(p[3] for p in s['points']) for s in r['screens'] if s['time'] > frames[first]['time'])
assert not errors and not any(m.startswith('error:') for m in console)

sheet = Image.new('RGB', (4 * 386, ((len(r['screens']) + 3) // 4) * 335), '#202020')
d = ImageDraw.Draw(sheet)
for i, s in enumerate(r['screens']):
    im = Image.open(s['path']).convert('RGB'); im.thumbnail((386, 315))
    x, y = i % 4 * 386, i // 4 * 335
    sheet.paste(im, (x, y + 20))
    d.text((x + 5, y + 3), f"t={s['secondsSincePress']:.2f}s cubePts={sum(p[3] for p in s['points'])} vx={s['speedX']:+.3f}", fill='white')
sheet.save(out / 'grapnel-contact-sheet.png')
print(f"PASS frame1 grapnel: screenshots={len(r['screens'])}; tetheredFrames={len(tethered)}; "
      f"hookLandedOn={firstHit['points'][-1]['type']}; attachedScreenshots={len(attachedShots)}; "
      f"wallBouncesWhileTethered={len(bounces)} sides={sides}; framesWith>=2CubePoints={len(wrapped)}; "
      f"maxBoundaryDistance={max(dists):.3e} <= cornerEps={probe['cornerEps']:.4f}; console errors=0; page errors=0")
