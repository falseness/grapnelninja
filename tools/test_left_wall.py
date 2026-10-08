"""Production-path regression for the persistent camera boundary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / os.environ.get('LEFT_WALL_EVIDENCE_DIR', 'artifacts/TASK-225')

PROBE = r'''() => {
    const wall = screen.leftWall;
    const contacts = [];
    const camera = () => ({x: screen.x, y: screen.y});
    const clear = () => {for (const f of floors) if (!(f instanceof SideFloor)) f.elements = []};
    const state = () => ({camera: camera(), face: wall.x, radius: ninja.radius,
        x: ninja.x, y: ninja.y, vx: ninja.speedX, vy: ninja.speedY});
    for (const [name, distance, speed, move] of [
        ['normal', 1.5, -1, true], ['high-speed', 4, -120, true],
        ['deep-overlap', -400, -3, false], ['overlap-outgoing', -2, 3, false]]) {
        clear();
        ninja.x = wall.x + distance * ninja.radius;
        ninja.y = height * 0.5 / scale[version] - screen.y;
        ninja.speedX = speed * ninja.radius; ninja.speedY = 0;
        const player = ninja;
        const before = state();
        if (move) ninja.move(); else ninja.collision();
        const after = state();
        ninja.collision();
        contacts.push({name, before, after, repeatVx: ninja.speedX,
            alive: player === ninja && !isRunFrozen(),
            nonpenetration: after.x - after.radius >= wall.x - GAMEPLAY.cubeContactEpsilon,
            rightward: after.vx > 0, noRepeatedReflection: ninja.speedX === after.vx});
    }
    clear();
    ninja.x = wall.x + 10 * ninja.radius; ninja.y = height * 0.5;
    ninja.speedX = ninja.speedY = 0;
    grapnel.throwed = true; grapnel.speedX = -1; grapnel.speedY = 0;
    grapnel.pos = [[wall.x - 1, ninja.y, new Empty()]];
    grapnel.collision();
    const attached = grapnel.isGrappled() && grapnel.pos[0][2] === wall;
    const local = [grapnel.pos[0][0] - wall.x, grapnel.pos[0][1] - wall.y];
    const anchors = [];
    // calcPhysics invokes Screen.shouldStartMove/move, wall update and Grapnel.move.
    for (const [vx, vy] of [[4, 0], [5, -3], [0, 4], [0, 0], [0, 0]]) {
        clear();
        screen.yAxisMotion = true; screen.min = -1e6; screen.max = 1e6;
        ninja.x = screen.borderX - screen.x + 100;
        ninja.y = height * 0.5 - screen.y;
        ninja.speedX = vx; ninja.speedY = vy - GRAVITY;
        const before = camera();
        calcPhysics();
        const p = grapnel.pos[0];
        anchors.push({before, camera: camera(), dx: wall.dx, dy: wall.dy,
            anchor: p.slice(0, 2), face: wall.x, wallY: wall.y,
            errorX: p[0] - wall.x - local[0], errorY: p[1] - wall.y - local[1],
            attached: grapnel.isGrappled() && p[2] === wall});
    }
    // Capture the actual transform inside drawWorldLayer, including mode zoom
    // and backing-store scaling. Express the face in CSS pixels.
    const measure = () => {
        let m;
        const original = wall.draw;
        wall.draw = function() {m = ctx.getTransform(); original.call(this)};
        draw(); wall.draw = original;
        const rect = canvas.getBoundingClientRect();
        const cssFace = ((wall.x + screen.x) * m.a + m.e) * rect.width / canvas.width;
        return {camera: camera(), face: wall.x, zoom: scale[version],
            transform: {a: m.a, d: m.d, e: m.e, f: m.f}, cssFace,
            expected: rect.height * 0.01, error: cssFace - rect.height * 0.01};
    };
    // Avoid transient landing shake while measuring the fixed camera transform.
    visualEffects.screenEffects.landings.length = 0;
    const transforms = [measure()];
    for (const [dx, dy] of [[-137, 53], [-81, -97]]) {
        screen.speedX = dx; screen.speedY = dy; screen.move();
        wall.update(screen); grapnel.move(); transforms.push(measure());
    }
    return {mode: version, width, height, zoom: scale[version], contacts,
        attached, anchors, transforms};
}'''

LIFECYCLE = r'''() => {
    const old = screen.leftWall;
    continueRun(); cancelAnimationFrame(game);
    const continued = screen.leftWall === old && !grapnel.throwed && grapnel.pos.length === 0;
    const continuationGeometry = {face: old.x, cameraX: screen.x};
    chooseVersion(); cancelAnimationFrame(game);
    const wall = screen.leftWall;
    const restarted = wall !== old && grapnel.pos.length === 0;
    screen.speedX = -10 * width; screen.speedY = 73; screen.move();
    wall.update(screen);
    const countsBefore = floors.map(f => f.elements.length);
    const oldElements = floors.flatMap(f => f.elements);
    for (const f of floors) {f.replenishElements(); f.deleteElements()}
    const elements = floors.flatMap(f => f.elements);
    return {continued, continuationGeometry, restarted, countsBefore,
        countsAfter: floors.map(f => f.elements.length),
        removedCount: oldElements.filter(e => !elements.includes(e)).length,
        activeBoundaries: [screen.leftWall, ...elements].filter(e => e instanceof LeftWall).length,
        persistent: screen.leftWall === wall, outsideProcedural: !elements.includes(wall),
        staleAnchors: grapnel.pos.some(p => p[2] === old),
        face: wall.x, cameraX: screen.x, offset: (wall.x + screen.x) * scale[version]};
}'''


RENDER_SETUP = r"""() => {
    screen.x = screen.y = 0; screen.leftWall.update(screen);
    const u = scale[version], h = height / u;
    window.greenReference = new Trampoline({x: width * 0.28 / u, y: h * 0.3,
        points: [{x: 0,y: 0},{x: h * 0.1,y: 0},
                 {x: h * 0.1,y: h * 0.4},{x: 0,y: h * 0.4}]});
    floors[1].elements.push(greenReference);
    return {fill: screen.leftWall.fill, stroke: screen.leftWall.stroke,
        badFill: screen.leftWall.wallFill, core: screen.leftWall.wallCore,
        referenceFill: greenReference.fill, referenceStroke: greenReference.stroke,
        greenFill: STYLE.badVersionEffects.obstacles.greenFill,
        greenCore: STYLE.strokes.neonOutline.coreColors[greenReference.stroke]};
}"""

RENDER_MEASURE = r"""() => {
    const wall = screen.leftWall;
    wall.update(screen);
    visualEffects.screenEffects.landings.length = 0;
    let m;
    const original = wall.draw;
    wall.draw = function() {m = ctx.getTransform(); original.call(this)};
    draw(); wall.draw = original;
    const rect = canvas.getBoundingClientRect();
    const face = (wall.x + screen.x) * m.a + m.e;
    // Isolate the wall using the very same draw transform to locate its raster edge.
    const main = ctx, probe = document.createElement('canvas');
    probe.width = canvas.width; probe.height = canvas.height;
    ctx = probe.getContext('2d'); ctx.setTransform(m);
    wall.draw();
    const raster = ctx.getImageData(0, Math.floor(canvas.height / 2), canvas.width, 1).data;
    let rasterRight = -1;
    for (let x = 0; x < canvas.width; ++x) if (raster[x*4+3]) rasterRight = x + 1;
    ctx = main;
    const ref = (greenReference.x + greenReference.rightPointX + screen.x) * m.a + m.e;
    const y = Math.floor(canvas.height * 0.5);
    const sample = x => Array.from(ctx.getImageData(Math.floor(x), y, 1, 1).data);
    return {camera: {x: screen.x, y: screen.y},
        backing: {width: canvas.width, height: canvas.height},
        canvasRect: {x: rect.x,y: rect.y,width: rect.width,height: rect.height},
        transform: {a: m.a,d: m.d,e: m.e,f: m.f},
        face, rasterRight, expected: canvas.height * 0.01,
        collisionFace: (wall.getLines()[0].x1 + screen.x) * m.a + m.e,
        hiddenEdges: {left: (wall.x + wall.points[0].x + screen.x)*m.a+m.e,
            top: (wall.y + wall.points[0].y + screen.y)*m.d+m.f,
            bottom: (wall.y + wall.points[2].y + screen.y)*m.d+m.f},
        samples: {wall: sample(face - 2 * canvas.height/1080),
                  green: sample(ref - 2 * canvas.height/1080)},
        sampleCoordinates: {wallX: Math.floor(face - 2*canvas.height/1080),
            greenX: Math.floor(ref - 2*canvas.height/1080), y},
        referenceFace: ref};
}"""


class LeftWallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)

    def test_modes_viewports_physics_grapple_and_lifecycle(self):
        results = []
        for mode in ('bad', 'classic'):
            for label, w, h, touch in [('desktop', 1920, 1080, False), ('phone', 844, 390, True)]:
                with self.subTest(mode=mode, viewport=label):
                    page = self.browser.new_page(viewport={'width': w, 'height': h},
                                                 is_mobile=touch, has_touch=touch)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    try:
                        page.goto(self.url)
                        wait_for_boot(page)
                        page.evaluate('(mode) => {startGame(mode); cancelAnimationFrame(game)}', mode)
                        row = page.evaluate(PROBE)
                        row['viewport'] = {'label': label, 'width': w, 'height': h, 'touch': touch}
                        row['lifecycle'] = page.evaluate(LIFECYCLE)
                        page.evaluate('''() => {
                            window.resizeWall = screen.leftWall;
                            ninja.x = resizeWall.x + 10 * ninja.radius;
                            ninja.y = resizeWall.y + height * 0.5;
                            grapnel.throwed = true;
                            grapnel.pos = [[resizeWall.x - 1, ninja.y, new Empty()]];
                            grapnel.collision();
                            window.resizeAnchor = grapnel.pos[0].slice(0, 2);
                        }''')
                        page.set_viewport_size({'width': w - 123, 'height': h - 31})
                        page.wait_for_timeout(200)
                        row['resize'] = page.evaluate('''() => ({
                            same: screen.leftWall === window.resizeWall,
                            anchorAttached: grapnel.isGrappled() && grapnel.pos[0][2] === screen.leftWall,
                            anchorError: Math.hypot(grapnel.pos[0][0] - resizeAnchor[0],
                                                   grapnel.pos[0][1] - resizeAnchor[1]),
                            activeBoundaries: [screen.leftWall, ...floors.flatMap(f => f.elements)]
                                .filter(e => e instanceof LeftWall).length,
                            width, bodyWidth: -screen.leftWall.points[0].x,
                            expectedWidth: width / scale[version],
                            faceOffset: (screen.leftWall.x + screen.x) * scale[version],
                            expectedOffset: height * 0.01,
                            linesFace: screen.leftWall.getLines()[0].x1,
                            face: screen.leftWall.x})''')
                        row['pageErrors'] = errors
                        results.append(row)
                        (EVIDENCE / 'physics.json').write_text(json.dumps(results, indent=2) + '\n')
                        for contact in row['contacts']:
                            for key in ('alive', 'nonpenetration', 'rightward', 'noRepeatedReflection'):
                                self.assertTrue(contact[key], (mode, label, contact))
                            self.assertEqual(contact['after']['vx'], abs(contact['before']['vx']))
                        self.assertTrue(row['attached'])
                        for anchor in row['anchors']:
                            self.assertTrue(anchor['attached'])
                            self.assertAlmostEqual(anchor['errorX'], 0, places=7)
                            self.assertAlmostEqual(anchor['errorY'], 0, places=7)
                        self.assertTrue(any(a['dx'] != 0 for a in row['anchors']))
                        self.assertTrue(any(a['dy'] != 0 for a in row['anchors']))
                        self.assertEqual([(a['dx'], a['dy']) for a in row['anchors'][-2:]], [(0, 0), (0, 0)])
                        for transform in row['transforms']:
                            # CSS layout quantizes canvas dimensions to fractional pixels.
                            self.assertLess(abs(transform['error']), 0.001)
                        life = row['lifecycle']
                        for key in ('continued', 'restarted', 'persistent', 'outsideProcedural'):
                            self.assertTrue(life[key], life)
                        self.assertFalse(life['staleAnchors'])
                        self.assertEqual(life['activeBoundaries'], 1)
                        self.assertGreater(life['removedCount'], 0)
                        resize = row['resize']
                        self.assertTrue(resize['same'])
                        self.assertTrue(resize['anchorAttached'])
                        self.assertEqual(resize['anchorError'], 0)
                        self.assertEqual(resize['activeBoundaries'], 1)
                        self.assertEqual(resize['bodyWidth'], resize['expectedWidth'])
                        self.assertAlmostEqual(resize['faceOffset'], resize['expectedOffset'])
                        self.assertEqual(resize['linesFace'], resize['face'])
                        self.assertEqual(errors, [])
                        row['assertions'] = 'PASS contacts, nonpenetration, camera transforms, anchor tracking, stationary displacement, continue, restart, procedural deletion, resize'
                        print(f'PASS {mode} {label}: {row["assertions"]}', flush=True)
                    finally:
                        page.close()
        (EVIDENCE / 'physics.json').write_text(json.dumps(results, indent=2) + '\n')
        files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        files = sorted(set(f for f in files if f.endswith(('.js', '.html'))) |
                       {'sprites/leftwall.js', 'tools/test_left_wall.py', 'tools/browser_test_support.py'})
        manifest = {
            'sourceRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
            'sourceState': 'worktree; exact tested file hashes below',
            'sha256': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files},
            'settings': [{'mode': r['mode'], 'viewport': r['viewport'], 'zoom': r['zoom']} for r in results],
            'evidence': [str(p.relative_to(ROOT)) for p in sorted(EVIDENCE.iterdir()) if p.is_file()],
            'assertions': 'PASS all four mode/viewport combinations; no skipped scenarios'}
        (EVIDENCE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


    def test_render_native_motion_and_resize(self):
        results = []
        for mode in ('bad', 'classic'):
            for label, w, h, touch in [('desktop', 1920, 1080, False), ('phone', 844, 390, True)]:
                with self.subTest(mode=mode, viewport=label):
                    page = self.browser.new_page(viewport={'width': w, 'height': h},
                                                 is_mobile=touch, has_touch=touch)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    try:
                        page.goto(self.url)
                        wait_for_boot(page)
                        page.evaluate("mode => {startGame(mode); cancelAnimationFrame(game); performance.now = () => 1000}", mode)
                        styles = page.evaluate(RENDER_SETUP)
                        # Assert independently against the corresponding unchanged green palette.
                        def rgba(value):
                            if value.startswith('#'):
                                return [int(value[i:i+2], 16) for i in (1, 3, 5)] + [1]
                            return [float(v.strip()) for v in value[5:-1].split(',')]
                        for wall_key, green_key in [('fill', 'referenceFill'), ('stroke', 'referenceStroke'),
                                                    ('badFill', 'greenFill'), ('core', 'greenCore')]:
                            a, b = rgba(styles[wall_key]), rgba(styles[green_key])
                            self.assertEqual(a[:3], [int(v / 2 + 0.5) for v in b[:3]])
                            self.assertEqual(a[3], b[3])
                        captures = []
                        for name, dx, dy in [('native', 0, 0), ('motion-1', -37, 21), ('motion-2', -49, -33), ('resize', 0, 0)]:
                            if name == 'resize':
                                page.set_viewport_size({'width': w - 123, 'height': h - 31})
                                page.wait_for_timeout(200)
                            page.evaluate("""([dx,dy]) => {screen.speedX=dx; screen.speedY=dy; screen.move()}""", [dx, dy])
                            row = page.evaluate(RENDER_MEASURE)
                            filename = f'{mode}-{label}-{name}.png'
                            page.screenshot(path=str(EVIDENCE / filename))
                            row['capture'] = filename
                            self.assertLessEqual(abs(row['face'] - row['expected']), 1)
                            self.assertEqual(row['collisionFace'], row['face'])
                            self.assertLessEqual(abs(row['rasterRight'] - row['collisionFace']), 1)
                            self.assertLess(row['hiddenEdges']['left'], -row['backing']['width'] * 0.9)
                            self.assertLess(row['hiddenEdges']['top'], -row['backing']['height'] * 0.9)
                            self.assertGreater(row['hiddenEdges']['bottom'], row['backing']['height'] * 1.9)
                            # Actual final framebuffer samples include grade and neon, not constants.
                            self.assertLess(row['samples']['wall'][1], row['samples']['green'][1], row)
                            self.assertGreater(row['samples']['wall'][1], row['samples']['wall'][0], row)
                            self.assertGreater(row['samples']['wall'][1], row['samples']['wall'][2], row)
                            if name.startswith('motion'):
                                self.assertLess(abs(row['face'] - captures[0]['face']), 0.001)
                            row['assertions'] = 'PASS boundary within one backing pixel, collision aligned, hidden edges, rendered darker green, stable motion/resize'
                            captures.append(row)
                        self.assertEqual(errors, [])
                        results.append({'mode': mode, 'viewport': label, 'styles': styles, 'captures': captures})
                        print(f'PASS render {mode} {label}: native, consecutive motion, resize, half RGB/unchanged alpha, darker rendered pixels', flush=True)
                    finally:
                        page.close()
        (EVIDENCE / 'render.json').write_text(json.dumps(results, indent=2) + '\n')
        manifest = json.loads((EVIDENCE / 'manifest.json').read_text())
        manifest['renderSettings'] = {'deviceScaleFactor': 1, 'clockMs': 1000,
            'pipeline': 'production draw(), green Trampoline reference added to gameplay',
            'captures': [c['capture'] for r in results for c in r['captures']]}
        manifest['evidence'] = [str(p.relative_to(ROOT)) for p in sorted(EVIDENCE.iterdir()) if p.is_file()]
        (EVIDENCE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
