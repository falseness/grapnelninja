"""Browser pixel and compositing proofs for the acquisition distance guide."""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, EvidenceWriter, source_hashes
from perf_mobile import SEED_SCRIPT


class Task453Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter('TASK-453')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        hashes = source_hashes()
        name = 'tools/test_grapple_over_visuals.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.proof = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            source_hashes=hashes, browser=cls.browser.version, observations=[])
        cls.evidence.log('CONFIG ' + json.dumps(cls.proof, sort_keys=True))

    def open(self, viewport, dpr, mode='grapple_over'):
        context = self.browser.new_context(viewport=viewport, device_scale_factor=dpr)
        self.addCleanup(context.close)
        self.evidence.log('BROWSER_CONTEXT ' + json.dumps(dict(
            test=self.id(), browser=self.browser.version,
            viewport=viewport, dpr=dpr, mode=mode), sort_keys=True))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.url)
        wait_for_boot(page)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        return page

    def test_pixels_camera_dpr_and_state(self):
        for viewport in ({'width':1280,'height':720}, {'width':844,'height':390}):
            for dpr in (1,2):
                page = self.open(viewport,dpr)
                for shift in (0,73):
                    row = page.evaluate('''shift => {
                        const original=ctx;
                        // A transparent target lets us measure actual rasterized edges.
                        const probe=document.createElement('canvas');
                        probe.width=canvas.width;probe.height=canvas.height;
                        ctx=probe.getContext('2d');
                        const sx=canvas.width/width*scale[version];
                        const sy=canvas.height/height*scale[version];
                        ctx.setTransform(sx,0,0,sy,0,0);
                        ninja.x=1000; ninja.y=1000;
                        screen.x=width/scale[version]/2-1000+shift;
                        screen.y=height/scale[version]/2-1000-shift/3;
                        const snapshot=()=>JSON.stringify([ctx.globalAlpha,ctx.strokeStyle,
                            ctx.lineWidth,ctx.shadowBlur,ctx.shadowOffsetX,ctx.getLineDash(),
                            ctx.globalCompositeOperation,Array.from(ctx.getTransform().toFloat64Array())]);
                        ctx.globalAlpha=.7;ctx.strokeStyle='#ff0000';ctx.lineWidth=9;
                        ctx.shadowBlur=7;ctx.shadowOffsetX=4;ctx.setLineDash([3,5]);
                        const before=snapshot();drawAcquisitionCircle();const restored=before===snapshot();
                        const cx=(ninja.x+screen.x)*sx,cy=(ninja.y+screen.y)*sy;
                        const R=MODE_DEFINITIONS.grapple_over.acquisitionRadius;
                        const data=ctx.getImageData(0,0,probe.width,probe.height).data;
                        const x=Math.round(cx), hits=[];
                        for(let y=0;y<probe.height;y++) if(data[(y*probe.width+x)*4+3]) hits.push(y);
                        const horizontal=[];
                        for(let xx=0;xx<probe.width;xx++) if(data[(Math.round(cy)*probe.width+xx)*4+3]) horizontal.push(xx);
                        const left=horizontal.filter(xx=>xx<cx),right=horizontal.filter(xx=>xx>cx);
                        const top=hits.filter(y=>y<cy),bottom=hits.filter(y=>y>cy);
                        const middle=a=>a.reduce((s,v)=>s+v,0)/a.length;
                        const observedTop=middle(top)+.5,observedBottom=middle(bottom)+.5;
                        const centerAlpha=data[(Math.round(cy)*probe.width+x)*4+3];
                        // Observe the stroke style on the real context, without replacing its drawing.
                        let style;const stroke=ctx.stroke;
                        ctx.stroke=function(){style={alpha:this.globalAlpha,blur:this.shadowBlur,
                            color:this.strokeStyle,cssWidth:this.lineWidth*sx/(canvas.width/getCanvasCssRect().width)};
                            return stroke.apply(this,arguments)};
                        drawAcquisitionCircle();
                        ctx=original;
                        return {R,restored,centerAlpha,style,expectedCenter:[cx,cy],
                            measuredCenterY:(observedTop+observedBottom)/2,
                            measuredCenterX:(middle(left)+middle(right))/2+.5,
                            measuredRadiusX:(middle(right)-middle(left))/2,expectedRadiusX:R*sx,
                            measuredRadius:(observedBottom-observedTop)/2,expectedRadius:R*sy,
                            topPixels:top.length,bottomPixels:bottom.length};
                    }''',shift)
                    self.assertTrue(row['restored'])
                    self.assertEqual(row['centerAlpha'],0)
                    self.assertLessEqual(abs(row['measuredCenterY']-row['expectedCenter'][1]),1)
                    self.assertLessEqual(abs(row['measuredRadius']-row['expectedRadius']),1)
                    self.assertLessEqual(abs(row['measuredCenterX']-row['expectedCenter'][0]),1)
                    self.assertLessEqual(abs(row['measuredRadiusX']-row['expectedRadiusX']),1)
                    self.assertAlmostEqual(row['style']['cssWidth'],1,places=6)
                    self.assertEqual({k:v for k,v in row['style'].items() if k!='cssWidth'},
                                     dict(alpha=.2,blur=0,color='#00ffff'))
                    row.update(viewport=viewport,dpr=dpr,camera_shift=shift)
                    self.proof['observations'].append(row)
                page.evaluate('draw()')
                page.screenshot(path=str(self.evidence.path(f'screenshots/climb-{viewport["width"]}-dpr{dpr}.png')))
        self.evidence.write('circle.json', self.proof)
        print('PASS pixels: 8 camera/desktop/phone/DPR observations; center and radius within 1 rendered pixel; unfilled cyan alpha 0.20; 1 CSS pixel; no glow; canvas state restored')

    def test_modes_pause_attachment_and_shared_range(self):
        page = self.open({'width':1280,'height':720},1)
        rows=[]
        for mode in ('grapple_over','classic','bad'):
            page.evaluate('m=>{startGame(m);cancelAnimationFrame(game)}',mode)
            row=page.evaluate('''() => {
                const events=[];
                const circle=drawAcquisitionCircle,world=grapnel.draw,player=drawPlayerLayer,ui=drawUILayer;
                let arcs=0;const arc=ctx.arc;
                drawAcquisitionCircle=function(){events.push('circle');
                    ctx.arc=function(){arcs++;return arc.apply(this,arguments)};
                    try{return circle()}finally{ctx.arc=arc}};
                grapnel.draw=function(){events.push('terrain');return world.apply(this,arguments)};
                drawPlayerLayer=function(){events.push('player');return player()};
                drawUILayer=function(s){events.push('hud');return ui(s)};
                draw();
                drawAcquisitionCircle=circle;grapnel.draw=world;drawPlayerLayer=player;drawUILayer=ui;
                return {mode:version,arcs,events};
            }''')
            self.assertEqual(row['arcs'],1 if mode=='grapple_over' else 0)
            self.assertEqual(row['events'],['circle','terrain','player','hud'])
            rows.append(row)
            page.screenshot(path=str(self.evidence.path(f'screenshots/{mode}.png')))
        page.evaluate("startGame('grapple_over');cancelAnimationFrame(game)")
        row=page.evaluate('''() => {
            const R=MODE_DEFINITIONS.grapple_over.acquisitionRadius;
            // Real flight clipping must stop at the same radius that is rendered.
            grapnel.throwed=true;grapnel.grappled=false;grapnel.traveled=R-2;
            grapnel.pos=[[ninja.x,ninja.y]];grapnel.speedX=10;grapnel.speedY=0;
            grapnel.move();const traveled=grapnel.traveled;
            const anchor=new Rect({x:ninja.x+R+100,y:ninja.y,width:20,height:20});
            grapnel.pos=[[anchor.x,anchor.y,anchor]];grapnel.grappled=true;
            let radius;const arc=ctx.arc;
            ctx.arc=function(x,y,r){radius=r;return arc.apply(this,arguments)};
            drawAcquisitionCircle();ctx.arc=arc;
            draw();menu.startPause();
            let pausedRadius;ctx.arc=function(x,y,r){pausedRadius=r;return arc.apply(this,arguments)};
            drawAcquisitionCircle();ctx.arc=arc;
            redrawOverlays();
            return {traveled,radius,pausedRadius,paused:menu.gamePaused,
                attached:grapnel.grappled,anchorDistance:Math.hypot(anchor.x-ninja.x,anchor.y-ninja.y)};
        }''')
        self.assertEqual(row['traveled'],row['radius'])
        self.assertEqual(row['pausedRadius'],row['radius'])
        self.assertTrue(row['paused'] and row['attached'])
        self.assertGreater(row['anchorDistance'],row['radius'])
        page.screenshot(path=str(self.evidence.path('screenshots/paused-attached.png')))
        proof_path=self.evidence.path('circle.json')
        proof=json.loads(proof_path.read_text()) if proof_path.exists() else self.proof.copy()
        proof.update(modes=rows,attachment=row)
        self.proof.update(modes=rows,attachment=row)
        self.evidence.write('circle.json',proof)
        print('PASS modes: classic/bad zero circle arcs; world order circle/terrain/player/HUD; attached beyond R and pause visible; rendered radius equals real flight limit')


BASELINE_538 = '530d25b'
BANDS_538 = 8
BAND_538 = 1620
HALF_SPAN_538 = 400
VIEWPORTS_538 = ({'width': 1280, 'height': 720}, {'width': 844, 'height': 390})
GEOMETRY_538 = '''() => {
    const level = validateMountainManifest(GRAPPLE_OVER_MOUNTAIN);
    return JSON.stringify({elements: level.elements.map(e => ({id: e.id, role: e.role,
        grapplable: e.grapplable, x: e.x, y: e.y, points: e.points})), movers: level.movers});
}'''
# The same seeded frame in both revisions: the animation clock is frozen before
# the run starts and physics is stepped explicitly (no rAF).
FRAME_538 = '''([mode, ticks]) => {
    performance.now = () => 4321;
    // Particles left by the title screen and the first start (their count
    // depends on real frame timing) go, in both revisions alike
    Object.assign(visualEffects.particles, {particles: [], pool: [], lastTime: 0,
        lastWorldEmitTime: 0, trailSparkBudget: 0, sparkSeed: 181});
    startGame(mode); cancelAnimationFrame(game);
    for (let i = 0; i < ticks; i++) physics();
    draw();
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    return {mode: version, width: canvas.width, height: canvas.height,
        pixels: Array.from(data, v => String.fromCharCode(v)).join('')};
}'''


class Task538Tests(unittest.TestCase):
    """Per-section Grapple Over backdrop palettes; classic/bad and geometry unchanged."""

    @classmethod
    def setUpClass(cls):
        from functools import partial
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from browser_test_support import QuietHandler
        from perf_mobile import export_rev
        cls.evidence = EvidenceWriter('TASK-538')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        # The pre-ticket revision, served from a git archive copy, for the
        # before/after geometry hash and the classic/bad pixel baseline
        root, sha = export_rev(BASELINE_538, cls.addClassCleanup)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.baseline_url = f'http://127.0.0.1:{server.server_port}/'
        hashes = source_hashes()
        name = 'tools/test_grapple_over_visuals.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.config = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            dirty=bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                                cwd=ROOT, text=True).strip()),
            baseline_revision=sha, source_hashes=hashes, browser=cls.browser.version,
            viewports=VIEWPORTS_538, device_scale_factor=1, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.config, sort_keys=True))

    def open(self, url, viewport, mode='grapple_over', query=''):
        context = self.browser.new_context(viewport=viewport, device_scale_factor=1)
        self.addCleanup(context.close)
        self.evidence.log('BROWSER_CONTEXT ' + json.dumps(dict(
            test=self.id(), url='baseline' if url == self.baseline_url else 'worktree',
            viewport=viewport, dpr=1, mode=mode, query=query), sort_keys=True))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(url + query)
        wait_for_boot(page)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        return page

    def test_01_geometry_hash_unchanged(self):
        row = {}
        for label, url in (('before', self.baseline_url), ('after', self.url)):
            page = self.open(url, VIEWPORTS_538[0])
            geometry = page.evaluate(GEOMETRY_538)
            row[label] = dict(sha256=hashlib.sha256(geometry.encode()).hexdigest(),
                              elements=len(json.loads(geometry)['elements']),
                              movers=len(json.loads(geometry)['movers']))
        row.update(baseline_revision=self.config['baseline_revision'],
                   fields='elements: id, role, grapplable, x, y, points; movers: full',
                   equal=row['before'] == row['after'])
        self.evidence.write('geometry-hash.json', row)
        self.assertEqual(row['before'], row['after'])
        self.assertGreater(row['after']['elements'], 0)
        print(f'PASS geometry: hash {row["after"]["sha256"][:16]} before == after '
              f'({row["after"]["elements"]} elements, {row["after"]["movers"]} movers)')

    def test_02_palette_sweep(self):
        page = self.open(self.url, VIEWPORTS_538[0])
        # Each sample sets the camera centre, runs the production
        # drawBackgroundLayer, then renders the palette it chose with the
        # production drawGrappleOverPalette into an opaque black probe and
        # reads back the mean colour of its rows.
        sweep = page.evaluate('''([bands, band]) => {
            const H = LOGICAL_VIEWPORT.height, probe = document.createElement('canvas');
            probe.width = 4; probe.height = H;
            const p = probe.getContext('2d', {willReadFrequently: true});
            const rows = [];
            let shadowed = 0;
            for (let y = 0; y >= -bands * band; y -= 10) {
                screen.y = height / scale[version] / 2 - y;
                drawBackgroundLayer();
                const palette = visualEffects.background.palette;
                p.setTransform(1, 0, 0, 1, 0, 0);
                p.globalAlpha = 1; p.globalCompositeOperation = 'source-over';
                p.fillStyle = '#000'; p.fillRect(0, 0, 4, H);
                drawGrappleOverPalette(p, {x: 0, y: 0, width: 4, height: H}, palette);
                if (p.shadowBlur) shadowed++;
                const d = p.getImageData(0, 0, 1, H).data, m = [0, 0, 0];
                for (let i = 0; i < d.length; i += 4) {m[0] += d[i]; m[1] += d[i + 1]; m[2] += d[i + 2]}
                rows.push([y, ...m.map(v => Math.round(v / H * 1000) / 1000)]);
            }
            return {rows, shadowed, height: H,
                palettes: GRAPPLE_OVER_THEME.palettes, theme: {bandHeight: GRAPPLE_OVER_THEME.bandHeight,
                blendHalfSpan: GRAPPLE_OVER_THEME.blendHalfSpan, tintAlpha: GRAPPLE_OVER_THEME.tintAlpha,
                glowAlpha: GRAPPLE_OVER_THEME.glowAlpha, glowTop: GRAPPLE_OVER_THEME.glowTop}};
        }''', [BANDS_538, BAND_538])
        rows = sweep['rows']
        self.assertEqual(len(rows), BANDS_538 * BAND_538 // 10 + 1)
        self.assertEqual(rows[-1][0], -12960)
        self.assertEqual(sweep['shadowed'], 0)
        dist = lambda a, b: sum((a[i] - b[i]) ** 2 for i in (1, 2, 3)) ** 0.5
        cores, spans = [], []
        for band in range(BANDS_538):
            low, high = band * BAND_538, (band + 1) * BAND_538
            core = [r for r in rows if low <= -r[0] <= high and
                    all(abs(-r[0] - k * BAND_538) >= HALF_SPAN_538 for k in range(1, BANDS_538))]
            colours = {tuple(r[1:]) for r in core}
            self.assertEqual(len(colours), 1, f'band {band + 1} core not constant')
            cores.append(dict(band=band + 1, name=sweep['palettes'][band]['name'],
                              from_y=-core[0][0], to_y=-core[-1][0], samples=len(core),
                              colour=list(colours.pop())))
        for a, b in zip(cores, cores[1:]):
            self.assertGreater(dist([0] + a['colour'], [0] + b['colour']), 20)
        for k in range(1, BANDS_538):
            span = [r for r in rows if abs(-r[0] - k * BAND_538) <= HALF_SPAN_538]
            self.assertEqual(len(span), 2 * HALF_SPAN_538 // 10 + 1)
            total = dist(span[0], span[-1])
            steps = [dist(a, b) for a, b in zip(span, span[1:])]
            spans.append(dict(boundary=-k * BAND_538, from_y=span[0][0], to_y=span[-1][0],
                              total_change=round(total, 3), max_step=round(max(steps), 3),
                              max_step_ratio=round(max(steps) / total, 5)))
            self.assertGreater(total, 0)
            self.assertLessEqual(max(steps), 0.02 * total, f'boundary {-k * BAND_538}')
        self.evidence.write('palette-sweep.json', dict(
            method='camera-centre y every 10 world units 0..-12960; production drawBackgroundLayer chooses '
                   'the palette, production drawGrappleOverPalette renders it into an opaque black 4xH probe; '
                   'colour = mean RGB over the probe rows; distances are Euclidean RGB',
            theme=sweep['theme'], palettes=sweep['palettes'], probe_height=sweep['height'],
            shadow_blur_draws=sweep['shadowed'], cores=cores, spans=spans,
            all_cores_constant=True, worst_span_ratio=max(s['max_step_ratio'] for s in spans),
            samples_columns=['y', 'r', 'g', 'b'], samples=rows))
        print(f'PASS sweep: {len(rows)} samples; 8 constant band cores; 7 blend spans, '
              f'worst max step {max(s["max_step_ratio"] for s in spans) * 100:.3f}% of span change (limit 2%)')

    def test_03_band_screenshots_and_fast_backdrop(self):
        targets = [(f'band{i + 1}-centre', -(i * BAND_538 + BAND_538 // 2)) for i in range(BANDS_538)]
        targets += [(f'boundary{k}-{k + 1}', -k * BAND_538) for k in range(1, BANDS_538)]
        shots = []
        for viewport in VIEWPORTS_538:
            page = self.open(self.url, viewport)
            for name, y in targets:
                row = page.evaluate('''y => {
                    ninja.x = 3240; ninja.y = y; ninja.speedX = ninja.speedY = 0;
                    screen.trackGrappleOver(true);
                    screen.y = height / scale[version] / 2 - y;
                    draw();
                    const p = visualEffects.background.palette;
                    return {camera_y: height / scale[version] / 2 - screen.y,
                        palette: {from: p.from, to: p.to, t: Math.round(p.t * 1e4) / 1e4},
                        names: [GRAPPLE_OVER_THEME.palettes[p.from].name, GRAPPLE_OVER_THEME.palettes[p.to].name],
                        bars: Array.from(document.getElementsByClassName('window-bar')).filter(c => c.box)
                            .map(c => c.barsKey.split(',').at(-1))};
                }''', y)
                path = f'bands/{name}-{viewport["width"]}x{viewport["height"]}.png'
                page.screenshot(path=str(self.evidence.path(path)))
                self.assertAlmostEqual(row['camera_y'], y, places=6)
                # Window bars (wider than 16:9) were repainted with this palette
                p = row['palette']
                self.assertTrue(all(b == f'{p["from"]}:{p["to"]}:{round(p["t"] * 20)}' for b in row['bars']), row)
                if name.endswith('centre'):
                    band = int(name[4:name.index('-')]) - 1
                    self.assertEqual(row['palette'], {'from': band, 'to': band, 't': 0})
                else:
                    k = int(name[8:name.index('-')])
                    self.assertEqual(row['palette'], {'from': k - 1, 'to': k, 't': 0.5})
                row.update(name=name, target_y=y, viewport=viewport, screenshot=path)
                shots.append(row)
            # Fast backdrop path (render/backdrop.js) still draws the palette,
            # into the reduced-resolution backdrop canvas, without shadowBlur
            fast = page.evaluate('''() => {
                const original = drawGrappleOverPalette, seen = [];
                drawGrappleOverPalette = function(context, bounds, palette) {
                    seen.push({backdrop: context === BACKDROP.ctx, blur: context.shadowBlur});
                    return original.apply(this, arguments)};
                const scale0 = BACKDROP.scale;
                BACKDROP.scale = 0.5; draw(); BACKDROP.scale = scale0; draw();
                drawGrappleOverPalette = original;
                return seen;
            }''')
            self.assertTrue(fast and fast[0]['backdrop'], fast)
            self.assertTrue(any(not s['backdrop'] for s in fast[1:]), fast)
            shots.append(dict(viewport=viewport, fast_backdrop_calls=fast))
        centres = [s for s in shots if s.get('name', '').endswith('centre') and s['viewport'] == VIEWPORTS_538[0]]
        self.assertEqual(len({json.dumps(s['palette']) for s in centres}), BANDS_538)
        self.assertEqual(len([s for s in shots if 'screenshot' in s]), 30)
        self.assertTrue(any(s.get('bars') for s in shots))
        self.evidence.write('bands.json', shots)
        print('PASS bands: 30 screenshots (8 band centres + 7 boundaries at 1280x720 and 844x390); '
              '8 distinct centre palettes; window bars repainted with each palette; fast backdrop draws the palette into BACKDROP.ctx')

    def test_04_classic_bad_pixels_unchanged(self):
        rows = []
        for mode in ('classic', 'bad'):
            for ticks in (0, 90):
                frames = {}
                for label, url in (('before', self.baseline_url), ('after', self.url)):
                    page = self.open(url, VIEWPORTS_538[0], mode)
                    # Title-screen frames use a varying share of the seeded
                    # stream: re-seed right before the measured run
                    page.evaluate(SEED_SCRIPT % 1)
                    frame = page.evaluate(FRAME_538, [mode, ticks])
                    self.assertEqual(frame['mode'], mode)
                    frames[label] = dict(width=frame['width'], height=frame['height'],
                        sha256=hashlib.sha256(frame['pixels'].encode('latin-1')).hexdigest())
                    page.close()
                row = dict(mode=mode, seed=1, reseeded_before_start=True, ticks=ticks, **frames, equal=frames['before'] == frames['after'])
                rows.append(row)
                self.assertEqual(frames['before'], frames['after'], row)
        self.evidence.write('classic-bad.json', dict(baseline_revision=self.config['baseline_revision'],
            viewport=VIEWPORTS_538[0], dpr=1, clock='performance.now frozen at 4321 before startGame; particle system emptied before startGame',
            frames=rows, all_equal=all(r['equal'] for r in rows)))
        print(f'PASS classic/bad: {len(rows)} frame pixel hashes equal to the {BASELINE_538} frames (seed 1, ticks 0/90)')

    def test_05_render_cost_ab(self):
        # Relative A/B of the background layer (render/perfprofile.js) in
        # matched pages; headless timings are not device FPS
        result = {}
        for label, url in (('before', self.baseline_url), ('after', self.url)):
            page = self.open(url, VIEWPORTS_538[0], query='?perf=1')
            result[label] = page.evaluate('''() => {
                const means = [];
                for (const y of [-810, -1620, -6480, -12150]) {
                    screen.y = height / scale[version] / 2 - y;
                    for (let i = 0; i < 120; i++) draw();
                    means.push(PERF_PROFILE.snapshot().entries.find(e => e.name === 'background').meanMs);
                }
                return means;
            }''')
        ratio = sum(result['after']) / sum(result['before'])
        self.evidence.write('perf-ab.json', dict(note='relative A/B only, matched headless pages; not device FPS',
                                                 layer='background', camera_y=[-810, -1620, -6480, -12150],
                                                 mean_ms=result, after_over_before=round(ratio, 3)))
        print(f'PASS cost A/B: background layer after/before = {ratio:.3f} (relative, headless)')


BASELINE_539 = 'a428389'
# Configurations the tile-coverage proof must hold at
COVERAGE_539 = (({'width': 1280, 'height': 720}, 1), ({'width': 844, 'height': 390}, 1),
                ({'width': 1280, 'height': 720}, 2), ({'width': 844, 'height': 390}, 2))
# Device rects of every parallax tile copy drawn into the game canvas by one
# draw(), grouped per tile (layer and motif), plus the parallax state used
TILE_DRAWS_539 = '''() => {
    const original = CanvasRenderingContext2D.prototype.drawImage, draws = [];
    CanvasRenderingContext2D.prototype.drawImage = function(image, ...args) {
        if (this.canvas === canvas && image.tagName === 'CANVAS' && args.length === 4) {
            const m = this.getTransform();
            const [x, y, w, h] = args;
            draws.push({image, rect: [m.a * x + m.e, m.d * y + m.f, m.a * (x + w) + m.e, m.d * (y + h) + m.f],
                logical: [x, y], blur: this.shadowBlur, alpha: this.globalAlpha});
        }
        return original.call(this, image, ...args);
    };
    try { draw(); } finally { CanvasRenderingContext2D.prototype.drawImage = original; }
    const names = new Map();
    for (const [key, sprite] of GLOW_SPRITES.cache)
        if (key.startsWith('parallax|')) names.set(sprite, key);
    const groups = {};
    for (const d of draws) {
        const key = names.get(d.image);
        if (!key) continue;
        (groups[key] = groups[key] || []).push({rect: d.rect, logical: d.logical, blur: d.blur, alpha: d.alpha});
    }
    return {groups, frame: visualEffects.background.parallaxFrame, palette: visualEffects.background.palette,
        width: canvas.width, height: canvas.height};
}'''


class Task539Tests(unittest.TestCase):
    """Grapple Over parallax silhouette layers; classic/bad and geometry unchanged."""

    @classmethod
    def setUpClass(cls):
        from functools import partial
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from browser_test_support import QuietHandler
        from perf_mobile import export_rev
        cls.evidence = EvidenceWriter('TASK-539')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        # The pre-ticket revision from a git archive copy: geometry hash and
        # classic/bad pixel baseline
        root, sha = export_rev(BASELINE_539, cls.addClassCleanup)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.baseline_url = f'http://127.0.0.1:{server.server_port}/'
        hashes = source_hashes()
        name = 'tools/test_grapple_over_visuals.py'
        hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.config = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            dirty=bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                                cwd=ROOT, text=True).strip()),
            baseline_revision=sha, source_hashes=hashes, browser=cls.browser.version,
            configurations=[dict(viewport=v, dpr=d) for v, d in COVERAGE_539], seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.config, sort_keys=True))

    def open(self, url, viewport, dpr=1, mode='grapple_over', query=''):
        context = self.browser.new_context(viewport=viewport, device_scale_factor=dpr)
        self.addCleanup(context.close)
        self.evidence.log('BROWSER_CONTEXT ' + json.dumps(dict(
            test=self.id(), url='baseline' if url == self.baseline_url else 'worktree',
            viewport=viewport, dpr=dpr, mode=mode, query=query), sort_keys=True))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(url + query)
        wait_for_boot(page)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        return page

    def test_01_geometry_hash_unchanged(self):
        row = {}
        for label, url in (('before', self.baseline_url), ('after', self.url)):
            page = self.open(url, VIEWPORTS_538[0])
            geometry = page.evaluate(GEOMETRY_538)
            row[label] = dict(sha256=hashlib.sha256(geometry.encode()).hexdigest(),
                              elements=len(json.loads(geometry)['elements']),
                              movers=len(json.loads(geometry)['movers']))
        row.update(baseline_revision=self.config['baseline_revision'],
                   fields='elements: id, role, grapplable, x, y, points; movers: full',
                   equal=row['before'] == row['after'])
        self.evidence.write('geometry-hash.json', row)
        self.assertEqual(row['before'], row['after'])
        self.assertGreater(row['after']['elements'], 0)
        print(f'PASS geometry: hash {row["after"]["sha256"][:16]} before == after '
              f'({row["after"]["elements"]} elements, {row["after"]["movers"]} movers)')

    def test_02_parallax_climb_and_coverage(self):
        # Recorded climb: the ninja is moved up a weaving path 6 units a tick
        # from the spawn through the first band boundary, the production
        # camera (screen.trackGrappleOver) follows it and the production draw()
        # renders each frame; the renderer reports the offsets it used and
        # the drawn tile rects must sit at those offsets.
        page = self.open(self.url, VIEWPORTS_538[0])
        climb = page.evaluate('''() => {
            const frames = [], x0 = ninja.x, y0 = ninja.y;
            const stats = {drawn_offset_mismatch: 0, frames_with_layers: 0};
            for (let i = 0; i <= 900; i++) {
                ninja.x = x0 + 260 * Math.sin(i / 37); ninja.y = y0 - 6 * i;
                ninja.speedX = 260 / 37 * Math.cos(i / 37) / cyclesPerTick; ninja.speedY = -6 / cyclesPerTick;
                screen.trackGrappleOver();
                draw();
                const f = visualEffects.background.parallaxFrame;
                frames.push({i, screen: [screen.x, screen.y], ninja_y: ninja.y,
                    layers: f.map(l => [l.name, l.factor, l.cameraX, l.cameraY, l.x, l.y, l.motifs])});
            }
            return {frames, scale: scale[version]};
        }''')
        factors = {}
        rows, ratios = [], []
        prev = None
        for f in climb['frames']:
            layers = {l[0]: l for l in f['layers']}
            for name, l in layers.items():
                factors[name] = l[1]
            if prev is not None:
                dcx = layers['ridges'][2] - prev['ridges'][2]
                dcy = layers['ridges'][3] - prev['ridges'][3]
                row = [f['i'], round(dcx, 9), round(dcy, 9)]
                for name in ('ridges', 'skyline'):
                    l, p = layers[name], prev[name]
                    dx, dy = l[4] - p[4], l[5] - p[5]
                    self.assertEqual((l[2], l[3]), (layers['ridges'][2], layers['ridges'][3]))
                    rx = dx / dcx if abs(dcx) > 1e-3 else None
                    ry = dy / dcy if abs(dcy) > 1e-3 else None
                    for r in (rx, ry):
                        if r is not None:
                            self.assertLessEqual(abs(r - l[1]), 1e-6, (name, f['i'], r))
                            ratios.append(abs(r - l[1]))
                    # Stationary axis: the layer does not move either
                    if rx is None:
                        self.assertLessEqual(abs(dx), l[1] * 1e-3 + 1e-9)
                    if ry is None:
                        self.assertLessEqual(abs(dy), l[1] * 1e-3 + 1e-9)
                    row += [round(dx, 9), round(dy, 9),
                            None if rx is None else round(rx, 9), None if ry is None else round(ry, 9)]
                rows.append(row)
            prev = layers
        rise = climb['frames'][-1]['screen'][1] - climb['frames'][0]['screen'][1]
        self.assertGreater(rise, 1000)
        moving = [r for r in rows if abs(r[2]) > 1e-3]
        self.assertGreater(len(moving), 300)
        motifs_seen = sorted({json.dumps(f['layers'][1][6]) for f in climb['frames']})
        # The climb crosses band boundaries: blend frames, at least 3 skyline motifs
        self.assertTrue(any(len(f['layers'][1][6]) == 2 for f in climb['frames']))
        self.assertEqual(climb['frames'][0]['layers'][1][6][0][0], 'cranes')
        self.assertGreaterEqual(len({m[0] for f in climb['frames'] for m in f['layers'][1][6]}), 3)

        # Tile coverage: device rects of each tile copy, per configuration and
        # camera position (a band core, a blend and an odd sub-pixel offset)
        coverage = []
        for viewport, dpr in COVERAGE_539:
            page = self.open(self.url, viewport, dpr)
            for y in (-810, -1620 + 157, -4860 - 333.37):
                page.evaluate('''y => {
                    ninja.x = 3240 + 61.3; ninja.y = y; ninja.speedX = ninja.speedY = 0;
                    screen.trackGrappleOver(true);
                    draw();
                }''', y)
                result = page.evaluate(TILE_DRAWS_539)
                W, H = result['width'], result['height']
                frame = {l['name']: l for l in result['frame']}
                expected = sum(len(l['motifs']) for l in result['frame'])
                self.assertEqual(len(result['groups']), expected, list(result['groups']))
                checks = []
                for key, draws in result['groups'].items():
                    layer = key.split('|')[1]
                    xs = sorted({(round(d['rect'][0], 6), round(d['rect'][2], 6)) for d in draws})
                    ys = sorted({(round(d['rect'][1], 6), round(d['rect'][3], 6)) for d in draws})
                    integral = all(abs(v - round(v)) < 1e-6 for d in draws for v in d['rect'])
                    contiguous_x = all(abs(a[1] - b[0]) < 1e-6 for a, b in zip(xs, xs[1:]))
                    contiguous_y = all(abs(a[1] - b[0]) < 1e-6 for a, b in zip(ys, ys[1:]))
                    covers = xs[0][0] <= 0 and xs[-1][1] >= W and ys[0][0] <= 0 and ys[-1][1] >= H
                    grid = len(draws) == len(xs) * len(ys) and len({(tuple(d['rect'])) for d in draws}) == len(draws)
                    # The drawn origin sits on the layer offset (modulo a tile)
                    cfg = dict(ridges=(1920, 720), skyline=(1440, 600))[layer]
                    l = frame[layer]
                    lx = [d['logical'][0] for d in draws]
                    ly = [d['logical'][1] for d in draws]
                    phase_x = min(abs(((v - l['x']) / cfg[0]) - round((v - l['x']) / cfg[0])) * cfg[0] for v in lx)
                    phase_y = min(abs(((v - l['y']) / cfg[1]) - round((v - l['y']) / cfg[1])) * cfg[1] for v in ly)
                    blur = max(d['blur'] for d in draws)
                    check = dict(tile=key, copies=len(draws), columns=len(xs), rows=len(ys),
                                 device_x_edges=[xs[0][0]] + [b for a, b in xs],
                                 device_y_edges=[ys[0][0]] + [b for a, b in ys],
                                 integral_edges=integral, contiguous_x=contiguous_x, contiguous_y=contiguous_y,
                                 covers_canvas=covers, full_grid=grid, max_shadow_blur=blur,
                                 origin_phase_logical=[round(phase_x, 4), round(phase_y, 4)])
                    self.assertTrue(integral and contiguous_x and contiguous_y and covers and grid, check)
                    self.assertEqual(blur, 0)
                    # Snapping moves an origin by at most half a device pixel
                    device_per_logical = result['width'] / page.evaluate('LOGICAL_VIEWPORT.width')
                    self.assertLessEqual(phase_x, 0.5 / device_per_logical + 1e-6, check)
                    self.assertLessEqual(phase_y, 0.5 / device_per_logical + 1e-6, check)
                    checks.append(check)
                coverage.append(dict(viewport=viewport, dpr=dpr, camera_y=y, canvas=[W, H],
                                     palette=result['palette'], tiles=checks,
                                     no_gaps_or_seams=True))
        self.evidence.write('parallax.json', dict(
            method='recorded climb: ninja moved 6 units/tick up a weaving path (x +-260) for 900 ticks from the '
                   'spawn across band boundaries, production screen.trackGrappleOver() camera, production draw() '
                   'per frame; camera and layer offsets are those the renderer used, in logical units '
                   '(world translation * scale). Coverage: every parallax tile drawImage into the game canvas '
                   'in one draw(), as device rects.',
            factors=factors, scale=climb['scale'], tolerance=1e-6,
            max_abs_ratio_error=max(ratios), ratio_samples=len(ratios), camera_rise_logical=round(rise * climb['scale'], 3),
            motifs_seen=[json.loads(m) for m in motifs_seen],
            frame_columns=['tick', 'camera_dx', 'camera_dy', 'ridges_dx', 'ridges_dy', 'ridges_ratio_x',
                           'ridges_ratio_y', 'skyline_dx', 'skyline_dy', 'skyline_ratio_x', 'skyline_ratio_y'],
            frames=rows, coverage=coverage,
            coverage_configurations=[f'{v["width"]}x{v["height"]}@dpr{d}' for v, d in COVERAGE_539]))
        print(f'PASS parallax: {len(rows)} climb frames, factors {factors}, {len(ratios)} ratio samples, '
              f'max |ratio - factor| {max(ratios):.2e} (<= 1e-6); coverage {len(coverage)} frames at '
              f'1280x720/844x390 DPR 1 and 2: contiguous integral device rects, full grid, no gaps or seams')

    def test_03_crossfade_screenshots_and_fast_backdrop(self):
        page = self.open(self.url, VIEWPORTS_538[0])
        shots = []
        offsets = (-400, -200, 0, 200, 400)
        for k in range(1, BANDS_538):
            for off in (offsets if k == 1 else (-400, 0, 400)):
                y = -k * BAND_538 - off
                row = page.evaluate('''y => {
                    ninja.x = 3240; ninja.y = y; ninja.speedX = ninja.speedY = 0;
                    screen.trackGrappleOver(true);
                    screen.y = height / scale[version] / 2 - y;
                    draw();
                    const p = visualEffects.background.palette;
                    return {camera_y: height / scale[version] / 2 - screen.y,
                        palette: {from: p.from, to: p.to, t: p.t},
                        layers: visualEffects.background.parallaxFrame.map(l => ({name: l.name, motifs: l.motifs}))};
                }''', y)
                path = f'crossfade/boundary{k}-{k + 1}-offset{off:+d}.png'
                page.screenshot(path=str(self.evidence.path(path)))
                p = row['palette']
                for layer in row['layers']:
                    weights = [w for _, w in layer['motifs']]
                    if p['t'] > 0:
                        self.assertEqual(len(weights), 2)
                        self.assertAlmostEqual(weights[0], 1 - p['t'], places=12)
                        self.assertAlmostEqual(weights[1], p['t'], places=12)
                    else:
                        self.assertEqual(weights, [1])
                if off == 0:
                    self.assertAlmostEqual(p['t'], 0.5, places=9)
                if abs(off) == 400:
                    self.assertEqual(p['t'], 0)
                    self.assertEqual(p['from'], k if off > 0 else k - 1)
                row.update(boundary=-k * BAND_538, offset=off, screenshot=path)
                shots.append(row)
        # Motifs differ across each boundary for at least one layer
        for k in range(1, BANDS_538):
            below = next(s for s in shots if s['boundary'] == -k * BAND_538 and s['offset'] == -400)
            above = next(s for s in shots if s['boundary'] == -k * BAND_538 and s['offset'] == 400)
            self.assertNotEqual([l['motifs'] for l in below['layers']], [l['motifs'] for l in above['layers']])
        # Fast backdrop draws the layers into BACKDROP.ctx; tiles are built
        # once (glow sprite builder), later frames copy them with no shadowBlur
        fast = page.evaluate('''() => {
            const original = drawGrappleOverParallax, seen = [];
            drawGrappleOverParallax = function(renderer) {
                seen.push({backdrop: renderer.ctx === BACKDROP.ctx, blur: renderer.ctx.shadowBlur});
                return original.apply(this, arguments)};
            const scale0 = BACKDROP.scale;
            BACKDROP.scale = 0.5; draw(); BACKDROP.scale = scale0; draw();
            drawGrappleOverParallax = original;
            const build = buildGlowSprite; let builds = 0, buildBlur = 0;
            buildGlowSprite = function() {builds++; return build.apply(this, arguments)};
            let frameBlur = 0;
            const di = CanvasRenderingContext2D.prototype.drawImage;
            CanvasRenderingContext2D.prototype.drawImage = function() {
                if (this.shadowBlur) frameBlur++; return di.apply(this, arguments)};
            const ys = [-700, -900, -1100, -1300];
            for (let i = 0; i < 120; i++) {screen.y = height / scale[version] / 2 - ys[i % 4] - i; draw();}
            CanvasRenderingContext2D.prototype.drawImage = di;
            buildGlowSprite = build;
            return {seen, builds_in_120_warm_frames: builds, draw_image_with_shadow_blur: frameBlur};
        }''')
        self.assertTrue(fast['seen'] and fast['seen'][0]['backdrop'], fast)
        self.assertTrue(any(not s['backdrop'] for s in fast['seen'][1:]), fast)
        self.assertEqual(fast['builds_in_120_warm_frames'], 0, fast)
        self.assertEqual(fast['draw_image_with_shadow_blur'], 0, fast)
        self.evidence.write('crossfade/crossfade.json', dict(
            note='smoothstep t is the palette blend (TASK-538: +/-400 around each boundary); each layer draws the '
                 'lower motif at alpha*(1-t) and the upper at alpha*t', shots=shots, fast_backdrop=fast))
        print(f'PASS crossfade: {len(shots)} boundary screenshots; motif weights (1-t, t) equal the palette blend; '
              f'motifs change across all 7 boundaries; fast backdrop draws the layers; 0 tile builds and 0 '
              f'shadowBlur drawImage calls in 120 warm frames')

    def test_04_classic_bad_pixels_unchanged(self):
        # Each frame is captured on 3 fresh pages per revision: the baseline
        # itself occasionally yields a second 'bad' tick-0 hash (title-screen
        # timing, seen in TASK-538 too), so every worktree hash must be one
        # the baseline produced and the most frequent hashes must be equal
        from collections import Counter
        rows = []
        for mode in ('classic', 'bad'):
            for ticks in (0, 90):
                frames = {}
                for label, url in (('before', self.baseline_url), ('after', self.url)):
                    captures = []
                    for _ in range(3):
                        page = self.open(url, VIEWPORTS_538[0], mode=mode)
                        page.evaluate(SEED_SCRIPT % 1)
                        frame = page.evaluate(FRAME_538, [mode, ticks])
                        self.assertEqual(frame['mode'], mode)
                        captures.append(f"{frame['width']}x{frame['height']}:" +
                                        hashlib.sha256(frame['pixels'].encode('latin-1')).hexdigest())
                        page.close()
                    frames[label] = captures
                common = {k: Counter(v).most_common(1)[0][0] for k, v in frames.items()}
                row = dict(mode=mode, seed=1, ticks=ticks, before=frames['before'], after=frames['after'],
                           most_common=common, after_subset_of_before=set(frames['after']) <= set(frames['before']),
                           equal=common['before'] == common['after'] and set(frames['after']) <= set(frames['before']))
                rows.append(row)
                self.assertTrue(row['equal'], row)
        self.evidence.write('classic-bad.json', dict(baseline_revision=self.config['baseline_revision'],
            viewport=VIEWPORTS_538[0], dpr=1, captures_per_revision=3,
            clock='performance.now frozen at 4321 before startGame; particle system emptied; Math.random re-seeded',
            frames=rows, all_equal=all(r['equal'] for r in rows)))
        print(f'PASS classic/bad: {len(rows)} frames x 3 captures per revision; every worktree pixel hash is a '
              f'{BASELINE_539} hash and the most frequent hashes are equal (seed 1, ticks 0/90)')

    def test_05_render_cost_ab(self):
        # Matched A/B in the same browser: the same seed and the same scripted
        # 480-frame climb, ?parallax=0 (layers off) vs default (on), pairs
        # alternated; PERF_PROFILE background-layer mean (render/perfprofile.js).
        # Relative only: headless timings are not device FPS.
        script = '''() => {
            const means = [], totals = [];
            for (const y of [-810, -1620, -6480, -12150]) {
                for (let i = 0; i < 120; i++) {screen.y = height / scale[version] / 2 - y - i * 2; draw();}
                const entries = PERF_PROFILE.snapshot().entries;
                means.push(entries.find(e => e.name === 'background').meanMs);
                totals.push(entries.filter(e => e.name !== 'update' && e.name !== 'backdrop')
                    .reduce((s, e) => s + (e.meanMs || 0), 0));
            }
            return {means, totals, layers: !!visualEffects.background.parallaxFrame && visualEffects.background.parallaxEnabled};
        }'''
        pairs = []
        for rep in range(5):
            pair = {}
            for label, query in ((('off', '?perf=1&parallax=0'), ('on', '?perf=1')) if rep % 2 == 0
                                 else (('on', '?perf=1'), ('off', '?perf=1&parallax=0'))):
                page = self.open(self.url, VIEWPORTS_538[0], query=query)
                result = page.evaluate(script)
                self.assertEqual(result['layers'], label == 'on')
                pair[label] = sum(result['means'])
                pair[label + '_all_layers'] = sum(result['totals'])
                page.close()
            pair['ratio'] = pair['on'] / pair['off']
            pair['all_layers_ratio'] = pair['on_all_layers'] / pair['off_all_layers']
            pairs.append(pair)
        ratios = sorted(p['ratio'] for p in pairs)
        median = ratios[len(ratios) // 2]
        self.evidence.write('cost.json', dict(
            note='relative A/B only (matched headless pages, same browser, seed 1, same 480 scripted frames); '
                 'not device FPS', layer='background (PERF_PROFILE)', browser=self.browser.version,
            viewport=VIEWPORTS_538[0], dpr=1, seed=1, frames_per_run=480,
            camera_y=[-810, -1620, -6480, -12150], off_query='?perf=1&parallax=0', on_query='?perf=1',
            pairs=[{k: round(v, 5) for k, v in p.items()} for p in pairs],
            median_on_over_off=round(median, 4),
            median_all_layers_on_over_off=round(sorted(p['all_layers_ratio'] for p in pairs)[len(pairs) // 2], 4),
            columns='on/off: sum of the background-layer means at the 4 camera ys (ms); *_all_layers: sum of all '
                    'draw-layer means'))
        print(f'PASS cost A/B: layers on/off median ratio {median:.3f} (background layer), '
              f'{sorted(p["all_layers_ratio"] for p in pairs)[2]:.3f} (all draw layers) over 5 matched pairs (relative, headless)')
