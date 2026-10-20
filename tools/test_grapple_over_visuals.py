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


BASELINE_540 = '7f6af93'
ROLES_540 = ('bounce', 'solid', 'mover', 'hazard', 'drag')
# Role-vs-role and role-vs-background separation thresholds (contrast.json)
ROLE_HUE_540 = 30
ROLE_L_540 = 4
BACKGROUND_L_540 = 12
BACKGROUND_DE_540 = 20
# A test-only level holding one element per role side by side at height y0
# (the game level is not touched: floors is replaced in this page only).
# Returns the frame pixels and each element's device-pixel bounds.
SHEET_540 = '''([roleDetail, y0, pixels]) => {
    const rect = (w, h) => [{x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}]
    const level = {version: 1, bounds: {left: -400, top: y0 - 2000, right: 3000, bottom: y0 + 400},
        spawn: {x: 0, y: y0 - 1000},
        sections: [{id: GRAPPLE_OVER_LEVEL.sections[0].id, encounters: ['sheet-roles']}],
        encounters: [{id: 'sheet-roles', elements: ['sheet-bounce']}], elements: [
            {id: 'sheet-bounce', x: 60, y: y0, role: 'bounce', grapplable: true, points: rect(240, 60)},
            {id: 'sheet-solid', x: 400, y: y0, role: 'solid', grapplable: true,
                points: [{x: 0, y: 0}, {x: 200, y: 0}, {x: 200, y: -30}, {x: 240, y: -30}, {x: 240, y: 70}, {x: 0, y: 70}]},
            {id: 'sheet-mover', x: 760, y: y0, role: 'solid', grapplable: true, points: rect(220, 50)},
            {id: 'sheet-hazard', x: 1080, y: y0, role: 'hazard', grapplable: false, points: rect(240, 70)},
            {id: 'sheet-drag', x: 1420, y: y0 - 90, role: 'drag', grapplable: false, points: rect(260, 240)}],
        movers: [{id: 'sheet-mover-x', element: 'sheet-mover', axis: 'x', min: 700, max: 820, periodMs: 4000, phase: 0.25}]}
    performance.now = () => 4321
    floors = [loadFixedLevel(level)]
    ROLE_DETAIL.enabled = roleDetail
    for (let i = 0; i < 40; i++) floors[0].moveElements()
    screen.x = width / scale[version] / 2 - 840
    screen.y = height / scale[version] / 2 - (y0 + 30)
    ninja.x = -10000
    draw()
    const s = canvas.width / (width / scale[version])
    const boxes = Object.fromEntries([...floors[0].elements, ...floors[0].dragZones].map(e => {
        const b = e.writeBounds({})
        return [e.id.slice(6), [Math.floor((b.left + screen.x) * s), Math.floor((b.top + screen.y) * s),
            Math.ceil((b.right + screen.x) * s), Math.ceil((b.bottom + screen.y) * s)]]
    }))
    const frame = ROLE_DETAIL.frame
    // The detail alone: the same production call, world transform, into a
    // transparent canvas; count its painted pixels inside each element's
    // bounds and outside all of them
    let layer = null
    if (roleDetail) {
        const probe = document.createElement('canvas')
        probe.width = canvas.width; probe.height = canvas.height
        const probeCtx = probe.getContext('2d'), main = ctx
        // The world layer's transform (draw() scales by the world scale)
        probeCtx.setTransform(s, 0, 0, s, 0, 0)
        ctx = probeCtx
        try { drawGrappleOverRoleDetail(floors[0]) } finally { ctx = main }
        const alpha = probeCtx.getImageData(0, 0, probe.width, probe.height).data
        const inside = Object.fromEntries(Object.keys(boxes).map(k => [k, 0]))
        let outside = 0
        for (let y = 0; y < probe.height; y++) for (let x = 0; x < probe.width; x++) {
            if (!alpha[(y * probe.width + x) * 4 + 3]) continue
            const hit = Object.entries(boxes).find(([, b]) => x >= b[0] && x < b[2] && y >= b[1] && y < b[3])
            if (hit) inside[hit[0]]++; else outside++
        }
        layer = {inside, outside}
    }
    return {boxes, width: canvas.width, height: canvas.height, frame, layer,
        pixels: pixels ? Array.from(ctx.getImageData(0, 0, canvas.width, canvas.height).data,
            v => String.fromCharCode(v)).join('') : ''}
}'''


def _lstar(rgb):
    import numpy as np
    c = np.asarray(rgb, float) / 255
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    y = c @ np.array([0.2126, 0.7152, 0.0722])
    return np.where(y > 0.008856, 116 * np.cbrt(y) - 16, 903.3 * y)


def _lab(rgb):
    import numpy as np
    c = np.asarray(rgb, float) / 255
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]) @ c
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return [116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])]


def _hue(rgb):
    import colorsys
    return colorsys.rgb_to_hls(*[v / 255 for v in rgb])[0] * 360


def _hue_sep(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


class Task540Tests(unittest.TestCase):
    """Grapple Over per-role surface detail; classic/bad and geometry unchanged."""

    @classmethod
    def setUpClass(cls):
        from functools import partial
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from browser_test_support import QuietHandler
        from perf_mobile import export_rev
        cls.evidence = EvidenceWriter('TASK-540')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        root, sha = export_rev(BASELINE_540, cls.addClassCleanup)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.baseline_url = f'http://127.0.0.1:{server.server_port}/'
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_visuals.py', 'render/roledetail.js'):
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

    def sheet(self, page, on, y0, pixels=True):
        import numpy as np
        r = page.evaluate(SHEET_540, [on, y0, pixels])
        if pixels:
            r['rgb'] = np.frombuffer(r.pop('pixels').encode('latin-1'), np.uint8).reshape(
                r['height'], r['width'], 4)[..., :3].astype(float)
        return r

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

    def test_02_roles_sheet_and_contrast(self):
        import numpy as np
        from PIL import Image, ImageDraw
        rows, sheet_rows, inside = [], [], []
        for viewport in VIEWPORTS_538:
            page = self.open(self.url, viewport)
            for band in range(BANDS_538):
                y0 = -(band * BAND_538 + BAND_538 // 2)
                on = self.sheet(page, True, y0)
                self.assertEqual(on['frame']['counts'], {r: 1 for r in ROLES_540})
                # The detail stays inside each element's silhouette: every
                # pixel it paints lies inside an element's bounds
                mask = np.zeros(on['rgb'].shape[:2], bool)
                for l, t, r, b in on['boxes'].values():
                    mask[max(0, t):b, max(0, l):r] = True
                inside.append(dict(viewport=viewport, band=band, painted_outside_elements=on['layer']['outside'],
                                   painted_inside=on['layer']['inside']))
                self.assertEqual(on['layer']['outside'], 0)
                for k, v in on['layer']['inside'].items():
                    self.assertGreater(v, 0, k)
                roles = {}
                for k, (l, t, r, b) in on['boxes'].items():
                    region = on['rgb'][t:b, l:r].reshape(-1, 3)
                    lum = _lstar(region)
                    # Emissive signature: the brightest quarter of the element's pixels
                    emissive = region[lum >= np.percentile(lum, 75)].mean(0)
                    roles[k] = dict(rgb=[round(v, 1) for v in emissive], hue=round(_hue(emissive), 1),
                                    L=round(float(_lstar(emissive)), 2), lab=[round(float(v), 2) for v in _lab(emissive)])
                bg_mask = ~mask
                for l, t, r, b in on['boxes'].values():
                    bg_mask[max(0, t - 40):b + 40, max(0, l - 40):r + 40] = False
                hud = on['height'] // 5
                bg_mask[:hud, :on['width'] // 4] = False
                bg_mask[:hud, -on['width'] // 8:] = False
                bg = on['rgb'][bg_mask].mean(0)
                background = dict(rgb=[round(v, 1) for v in bg], hue=round(_hue(bg), 1), L=round(float(_lstar(bg)), 2),
                                  lab=[round(float(v), 2) for v in _lab(bg)], pixels=int(bg_mask.sum()))
                pairs = []
                for i, a in enumerate(ROLES_540):
                    for b in ROLES_540[i + 1:]:
                        hue = _hue_sep(roles[a]['hue'], roles[b]['hue'])
                        dl = abs(roles[a]['L'] - roles[b]['L'])
                        pairs.append(dict(a=a, b=b, hue_sep=round(hue, 1), L_sep=round(dl, 2),
                                          ok=hue >= ROLE_HUE_540 and dl >= ROLE_L_540))
                versus = []
                for a in ROLES_540:
                    de = float(np.linalg.norm(np.subtract(roles[a]['lab'], background['lab'])))
                    dl = roles[a]['L'] - background['L']
                    versus.append(dict(role=a, hue_sep=round(_hue_sep(roles[a]['hue'], background['hue']), 1),
                                       L_sep=round(dl, 2), delta_e76=round(de, 2),
                                       ok=dl >= BACKGROUND_L_540 and de >= BACKGROUND_DE_540))
                rows.append(dict(viewport=viewport, band=band, palette=GRAPPLE_OVER_PALETTE_NAMES_540[band],
                                 roles=roles, background=background, role_pairs=pairs, versus_background=versus))
                for p in pairs + versus:
                    self.assertTrue(p['ok'], (viewport, band, p))
                if band == 0:
                    # Sheet crop: the role row with a margin, zoomed 2x
                    boxes = list(on['boxes'].values())
                    l = max(0, min(b[0] for b in boxes) - 30)
                    t = max(0, min(b[1] for b in boxes) - 30)
                    r = min(on['width'], max(b[2] for b in boxes) + 30)
                    b = min(on['height'], max(b[3] for b in boxes) + 30)
                    full = f'sheet-{viewport["width"]}x{viewport["height"]}.png'
                    page.screenshot(path=str(self.evidence.path(full)))
                    crop = Image.fromarray(on['rgb'][t:b, l:r].astype(np.uint8)).resize(((r - l) * 2, (b - t) * 2), Image.NEAREST)
                    labels = {k: ((v[0] + v[2]) / 2 - l, v[3] - t) for k, v in on['boxes'].items()}
                    sheet_rows.append((viewport, crop, labels, full))
        # roles-sheet.png: both viewports' role rows stacked, 2x zoom, labelled
        width_px = max(c.width for _, c, _, _ in sheet_rows)
        height_px = sum(c.height + 40 for _, c, _, _ in sheet_rows)
        canvas = Image.new('RGB', (width_px, height_px), (12, 12, 16))
        draw = ImageDraw.Draw(canvas)
        y = 0
        for viewport, crop, labels, _ in sheet_rows:
            draw.text((8, y + 6), f'{viewport["width"]}x{viewport["height"]} (2x zoom of the in-game frame, band 0)',
                      fill=(230, 230, 230))
            canvas.paste(crop, (0, y + 24))
            for k, (cx, by) in labels.items():
                draw.text((cx * 2 - 18, y + 24 + by * 2 + 8), k, fill=(255, 255, 255))
            y += crop.height + 40
        canvas.save(self.evidence.path('roles-sheet.png'))
        min_pair = min(p['hue_sep'] for r in rows for p in r['role_pairs'])
        min_l = min(p['L_sep'] for r in rows for p in r['role_pairs'])
        min_bg_l = min(v['L_sep'] for r in rows for v in r['versus_background'])
        min_bg_de = min(v['delta_e76'] for r in rows for v in r['versus_background'])
        self.evidence.write('contrast.json', dict(
            method='Each role element is rendered in-game (test-only one-element-per-role level) at all 8 band '
                   'heights at 1280x720 and 844x390; role signature = mean colour of the brightest quarter (CIE L*) '
                   'of its pixels (outline + new detail); background = mean colour of the frame outside the '
                   'elements (+40 px) and HUD, i.e. the palette wash, parallax layers, crystals and motes. Hue: HLS '
                   'degrees (circular separation); luminance: CIE L* (0-100); delta_e76: CIELAB distance.',
            thresholds=dict(role_vs_role=dict(hue_sep_min_deg=ROLE_HUE_540, L_sep_min=ROLE_L_540),
                            role_vs_background=dict(L_sep_min=BACKGROUND_L_540, delta_e76_min=BACKGROUND_DE_540,
                                                    hue_note='hue separation is recorded for every role/background pair; '
                                                             'it is not thresholded because the TASK-538 backdrop sweeps the '
                                                             'whole hue circle by design (e.g. the dusk band is pink like '
                                                             'hazards); roles stand apart from it by lightness and '
                                                             'CIELAB distance')),
            minima=dict(role_hue_sep=min_pair, role_L_sep=min_l, background_L_sep=min_bg_l,
                        background_delta_e76=min_bg_de),
            all_pass=all(p['ok'] for r in rows for p in r['role_pairs'] + r['versus_background']),
            frames=rows))
        self.evidence.write('silhouette.json', dict(
            note='the production drawGrappleOverRoleDetail re-run alone (same transform) into a transparent '
                 'canvas: painted pixels per role element bounds; painted_outside_elements must be 0', frames=inside))
        print(f'PASS roles sheet: 5 roles x 8 bands x 2 viewports; role pairs hue >= {min_pair} deg (min {ROLE_HUE_540}), '
              f'L* >= {min_l} (min {ROLE_L_540}); vs background L* >= {min_bg_l} (min {BACKGROUND_L_540}), '
              f'dE76 >= {min_bg_de} (min {BACKGROUND_DE_540}); 0 detail pixels outside the elements')

    def test_03_contact_pulse_real_input(self):
        from PIL import Image, ImageDraw
        page = self.open(self.url, VIEWPORTS_538[0])
        page.evaluate('menu.unPause()')
        tick = '''() => {physics(); draw();
            const pad = floors[0].byId.get('S01-floor'), contact = ROLE_DETAIL.contacts.get(pad);
            const pulse = ROLE_DETAIL.frame.pulses.find(p => p.id === 'S01-floor');
            return {x: ninja.x, y: ninja.y, speedY: ninja.speedY, grappled: grapnel.isGrappled(),
                steps: floors[0].elapsedSteps, contactStep: contact ? contact.step : null,
                strength: contact ? contact.strength : 0, pulse: pulse ? pulse.intensity : 0,
                drawnPulses: ROLE_DETAIL.frame.pulses.length}}'''
        target = page.evaluate("()=>{const e=floors[0].byId.get('S01-hoist');return [e.x+60,e.y+15]}")
        point = page.evaluate('''([x,y])=>canvasCoordsToViewportCoords({
            x:(x+screen.x)*scale[version],y:(y+screen.y)*scale[version]})''', target)
        # Real input: a mouse press aimed at the S01 hoist, held 30 ticks, released
        page.mouse.move(point['x'], point['y'])
        page.mouse.down()
        rows, events = [], [dict(tick=0, event='mousedown', client=point, aim=target)]
        for i in range(30):
            rows.append(page.evaluate(tick))
        page.mouse.up()
        events.append(dict(tick=30, event='mouseup'))
        shots, contact_tick = {}, None
        for i in range(30, 320):
            row = page.evaluate(tick)
            rows.append(row)
            if contact_tick is None and row['contactStep'] is not None and row['strength'] > 0:
                contact_tick = i
            if contact_tick is not None and i - contact_tick in (0, 2, 5, 9, 14, 20, 27) or (
                    contact_tick is None and row['y'] > 40 and 'pre' not in shots):
                key = 'pre' if contact_tick is None else i - contact_tick
                box = page.evaluate('''() => {const r = getCanvasCssRect(), s = r.width / (width / scale[version]);
                    return [r.left + (ninja.x + screen.x) * s, r.top + (ninja.y + screen.y) * s]}''')
                path = self.evidence.path(f'pulse-frames/{key}.png')
                page.screenshot(path=str(path), clip=dict(x=box[0] - 90, y=box[1] - 60, width=180, height=100))
                shots[key] = path
            if contact_tick is not None and i - contact_tick > 30:
                break
        self.assertIsNotNone(contact_tick)
        self.assertTrue(any(r['grappled'] for r in rows[:30]))
        c = contact_tick
        before, at = rows[c - 1], rows[c]
        # The pulse starts on the contact tick: dark before, brightest on it,
        # then non-increasing and back to 0 within pulseMs (450 ms = 27 ticks)
        self.assertEqual(before['pulse'], 0)
        self.assertGreater(before['speedY'], 0)
        self.assertLess(at['speedY'], 0)
        self.assertGreater(at['pulse'], 0)
        after = [r['pulse'] for r in rows[c:c + 31]]
        self.assertEqual(max(after), after[0])
        self.assertTrue(all(b <= a for a, b in zip(after, after[1:])), after)
        self.assertEqual(after[28], 0)
        ticks = [dict(tick=i, y=round(r['y'], 3), speedY=round(r['speedY'], 4), grappled=r['grappled'],
                      pulse=round(r['pulse'], 5), contact_step=r['contactStep'])
                 for i, r in enumerate(rows) if i >= c - 5]
        self.evidence.write('pulse.json', dict(
            input='real Playwright mouse events (press at the S01-hoist, hold 30 physics ticks, release); '
                  'physics stepped one tick per evaluate, draw() after each tick',
            element='S01-floor (bounce)', events=events, contact_tick=c,
            impact_strength=round(at['strength'], 4), pulse_ms=450, ticks_per_second=60,
            pulse_before_contact=before['pulse'], pulse_on_contact=round(at['pulse'], 5),
            pulse_zero_at_tick=c + after.index(0), monotonic_fade=True,
            samples=[dict(tick=i, y=round(r['y'], 2)) for i, r in enumerate(rows[:c - 5]) if i % 10 == 0],
            ticks=ticks, filmstrip_ticks_after_contact=[k for k in shots if k != 'pre']))
        # Filmstrip: the pre-contact frame then the pulse fading
        frames = [('pre', 'before contact')] + [(k, f'contact +{k}') for k in (0, 2, 5, 9, 14, 20, 27)]
        images = [Image.open(shots[k]).convert('RGB') for k, _ in frames]
        strip = Image.new('RGB', (sum(i.width for i in images), images[0].height + 18), (0, 0, 0))
        draw = ImageDraw.Draw(strip)
        x = 0
        for (k, label), image in zip(frames, images):
            strip.paste(image, (x, 18))
            draw.text((x + 4, 3), label, fill=(255, 255, 255))
            x += image.width
        strip.save(self.evidence.path('pulse-filmstrip.jpg'), quality=90)
        print(f'PASS pulse: real mouse grapple+release; bounce on S01-floor at tick {c}; pulse 0 before, '
              f'{at["pulse"]:.3f} on the contact tick, non-increasing, 0 at tick {c + after.index(0)}')

    def test_04_level_detail_fast_backdrop_and_sprites(self):
        page = self.open(self.url, VIEWPORTS_538[0])
        result = page.evaluate('''() => {
            const counts = {bounce: 0, solid: 0, mover: 0, hazard: 0, drag: 0};
            const ys = [0, -700, -1500, -3000, -4600, -6400, -8000, -9900, -11500, -13000];
            for (const y of ys) {
                screen.y = height / scale[version] / 2 - y;
                draw();
                for (const k in counts) counts[k] += ROLE_DETAIL.frame.counts[k];
            }
            // Fast backdrop: the role detail is still drawn (world layer, full resolution)
            const original = drawGrappleOverRoleDetail, seen = [];
            drawGrappleOverRoleDetail = function(world) {
                const r = original.apply(this, arguments);
                seen.push({backdropActive: BACKDROP.active, scale: BACKDROP.scale,
                           counts: Object.values(ROLE_DETAIL.frame.counts).reduce((a, b) => a + b, 0)});
                return r};
            const scale0 = BACKDROP.scale;
            screen.y = height / scale[version] / 2;
            BACKDROP.scale = 0.5; draw(); BACKDROP.scale = scale0; draw();
            drawGrappleOverRoleDetail = original;
            const build = buildGlowSprite; let builds = 0;
            buildGlowSprite = function() {builds++; return build.apply(this, arguments)};
            let blurDraws = 0, blurStrokes = 0;
            const P = CanvasRenderingContext2D.prototype, di = P.drawImage, st = P.stroke, fi = P.fill;
            P.drawImage = function() {if (this.shadowBlur) blurDraws++; return di.apply(this, arguments)};
            P.stroke = function() {if (this.shadowBlur) blurStrokes++; return st.apply(this, arguments)};
            P.fill = function() {if (this.shadowBlur) blurStrokes++; return fi.apply(this, arguments)};
            for (let r = 0; r < 2; r++) for (const y of ys) {screen.y = height / scale[version] / 2 - y; draw();}
            const warm = builds;
            P.drawImage = di; P.stroke = st; P.fill = fi;
            buildGlowSprite = build;
            const sprites = [...GLOW_SPRITES.cache.keys()].filter(k => k.startsWith('roledetail|'));
            return {counts, seen, builds_in_warm_frames: warm, shadow_blur_draw_calls: blurDraws + blurStrokes,
                    roledetail_sprites: sprites};
        }''')
        for role in ('bounce', 'solid', 'mover', 'drag'):
            self.assertGreater(result['counts'][role], 0, role)
        self.assertTrue(result['seen'][0]['backdropActive'] or result['seen'][0]['scale'] == 0.5, result['seen'])
        self.assertTrue(all(s['counts'] > 0 for s in result['seen']), result['seen'])
        self.assertEqual(result['builds_in_warm_frames'], 0)
        self.assertEqual(result['shadow_blur_draw_calls'], 0)
        self.assertGreater(len(result['roledetail_sprites']), 0)
        self.evidence.write('level-detail.json', dict(note='real level, 10 camera heights; fast backdrop forced '
                                                           'with BACKDROP.scale = 0.5', **result))
        print(f'PASS level/fast backdrop: per-role detail drawn on the real level {result["counts"]} (no hazards '
              f'in the level); drawn with the fast backdrop forced; 0 glow sprite builds '
              f'and 0 shadowBlur draws in 20 warm frames')

    def test_05_classic_bad_pixels_unchanged(self):
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
              f'{BASELINE_540} hash and the most frequent hashes are equal (seed 1, ticks 0/90)')

    def test_06_render_cost_ab(self):
        # Matched A/B: before = BASELINE_540 (git archive), after = worktree;
        # same browser, seed and 480 scripted frames over the real level,
        # pairs alternated. PERF_PROFILE (render/perfprofile.js) world-layer
        # mean and the sum of all draw-layer means. Relative only: headless
        # timings are not device FPS.
        script = '''() => {
            const world = [], totals = [];
            for (const y of [-300, -3000, -6400, -12400]) {
                for (let i = 0; i < 120; i++) {screen.y = height / scale[version] / 2 - y - i * 2; draw();}
                const entries = PERF_PROFILE.snapshot().entries;
                world.push(entries.find(e => e.name === 'world').meanMs);
                totals.push(entries.filter(e => e.name !== 'update' && e.name !== 'backdrop')
                    .reduce((s, e) => s + (e.meanMs || 0), 0));
            }
            return {world, totals, detail: typeof ROLE_DETAIL !== 'undefined'};
        }'''
        pairs = []
        for rep in range(5):
            pair = {}
            order = (('before', self.baseline_url), ('after', self.url))
            for label, url in (order if rep % 2 == 0 else order[::-1]):
                page = self.open(url, VIEWPORTS_538[0], query='?perf=1')
                result = page.evaluate(script)
                self.assertEqual(result['detail'], label == 'after')
                pair[label] = sum(result['world'])
                pair[label + '_all_layers'] = sum(result['totals'])
                page.close()
            pair['ratio'] = pair['after'] / pair['before']
            pair['all_layers_ratio'] = pair['after_all_layers'] / pair['before_all_layers']
            pairs.append(pair)
        ratios = sorted(p['ratio'] for p in pairs)
        all_ratios = sorted(p['all_layers_ratio'] for p in pairs)
        self.evidence.write('cost.json', dict(
            note='relative A/B only (matched headless pages, same browser, seed 1, same 480 scripted frames); '
                 'not device FPS', before=f'{BASELINE_540} (git archive, no role detail)', after='worktree',
            layer='world (PERF_PROFILE)', browser=self.browser.version, viewport=VIEWPORTS_538[0], dpr=1, seed=1,
            frames_per_run=480, camera_y=[-300, -3000, -6400, -12400], query='?perf=1',
            pairs=[{k: round(v, 5) for k, v in p.items()} for p in pairs],
            median_after_over_before=round(ratios[2], 4), median_all_layers_after_over_before=round(all_ratios[2], 4),
            columns='before/after: sum of the world-layer means at the 4 camera ys (ms); *_all_layers: sum of all '
                    'draw-layer means'))
        print(f'PASS cost A/B: after/before median ratio {ratios[2]:.3f} (world layer), {all_ratios[2]:.3f} '
              f'(all draw layers) over 5 matched pairs (relative, headless)')


GRAPPLE_OVER_PALETTE_NAMES_540 = ('dusk quarry', 'ember works', 'magenta haze', 'violet ridge', 'indigo cliffs',
                                  'cyan frost', 'teal aurora', 'night sky')


BASELINE_541 = 'be2ae6b'
# Desktop mouse and a touch phone (is_mobile, has_touch), both at DPR 1
VIEWPORTS_541 = (dict(name='desktop', viewport={'width': 1280, 'height': 720}, touch=False),
                 dict(name='touch', viewport={'width': 844, 'height': 390}, touch=True))
# Section entry pose (first encounter start, snapped camera), then one frame;
# the section's own landmark as drawn (logical and client rects) and how many
# of its pixels the landmark changes (same frame with LANDMARKS.enabled off)
ENTRY_541 = '''i => {
    const section = GRAPPLE_OVER_MOUNTAIN.sections[i];
    const first = GRAPPLE_OVER_MOUNTAIN.encounters.find(e => e.id === section.encounters[0]);
    const entry = first.start || first;
    ninja.x = entry.x; ninja.y = entry.y; ninja.speedX = ninja.speedY = 0;
    screen.trackGrappleOver(true);
    const grab = () => ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    LANDMARKS.enabled = false; draw(); const off = grab();
    LANDMARKS.enabled = true; draw(); const on = grab();
    const own = LANDMARKS.frame.drawn.find(d => d.id === section.landmark.id);
    const client = own && [canvasCoordsToViewportCoords({x: own.rect[0], y: own.rect[1]}),
                           canvasCoordsToViewportCoords({x: own.rect[2], y: own.rect[3]})];
    let changed = 0, total = 0;
    if (own) {
        const sx = canvas.width / width, sy = canvas.height / height;
        for (let y = Math.max(0, Math.floor(own.rect[1] * sy)); y < Math.min(canvas.height, own.rect[3] * sy); y++)
            for (let x = Math.max(0, Math.floor(own.rect[0] * sx)); x < Math.min(canvas.width, own.rect[2] * sx); x++) {
                const p = (y * canvas.width + x) * 4;
                total++;
                if (Math.abs(on[p] - off[p]) + Math.abs(on[p + 1] - off[p + 1]) + Math.abs(on[p + 2] - off[p + 2]) > 24) changed++;
            }
    }
    return {section: section.id, landmark: section.landmark, entry: {x: entry.x, y: entry.y},
        camera: {x: screen.x, y: screen.y}, logical: {width, height}, canvas: [canvas.width, canvas.height],
        rect: own ? own.rect.map(v => Math.round(v * 100) / 100) : null, weight: own ? own.weight : 0,
        client: client && [client[0].x, client[0].y, client[1].x, client[1].y].map(v => Math.round(v * 100) / 100),
        others: LANDMARKS.frame.drawn.filter(d => d !== own).map(d => ({id: d.id, weight: Math.round(d.weight * 1000) / 1000})),
        changed, total, colliders: floors[0].elements.filter(e => /landmark/i.test(e.id)).length +
            floors[0].dragZones.filter(e => /landmark/i.test(e.id)).length};
}'''
# Aim through the landmark: grid points in its rect (world units now) within
# 0.9 of the range, whose full-range line from the ninja (also +-60 up/down,
# for its fall during the shot) crosses no surface; nearest the rect centre.
# Shot pose: the entry pose if the landmark is in range there, else the first
# free pose (no surface within 120 of the ninja) on rings of 450/650 world
# units around the landmark's drawn centre, with a snapped camera and a frame.
ARM_541 = '''id => {
    const k = scale[version], radius = grappleOverAcquisitionRadius();
    const own = () => LANDMARKS.frame.drawn.find(d => d.id === id);
    const aimFrom = () => {
        const rect = own().rect, candidates = [];
        for (let i = 1; i < 12; i++) for (let j = 1; j < 12; j++) {
            const lx = rect[0] + (rect[2] - rect[0]) * i / 12, ly = rect[1] + (rect[3] - rect[1]) * j / 12;
            const wx = lx / k - screen.x, wy = ly / k - screen.y;
            const d = Math.hypot(wx - ninja.x, wy - ninja.y);
            if (d < 150 || d > radius * 0.9) continue;
            const clear = [-60, 0, 60].every(o => !grapnel.nearestCrossing({x: ninja.x, y: ninja.y + o},
                [ninja.x + (wx - ninja.x) / d * radius, ninja.y + o + (wy - ninja.y) / d * radius]));
            if (clear) candidates.push({lx, ly, wx, wy, d,
                c: Math.hypot(lx - (rect[0] + rect[2]) / 2, ly - (rect[1] + rect[3]) / 2)});
        }
        candidates.sort((a, b) => a.c - b.c);
        return candidates;
    };
    const free = (x, y) => {
        const box = {left: x - 120, right: x + 120, top: y - 120, bottom: y + 120};
        return ![...floors[0].elements, ...floors[0].dragZones].some(e =>
            boundsOverlap(box, elementBounds(e, {left: 0, right: 0, top: 0, bottom: 0})));
    };
    const entry = {x: ninja.x, y: ninja.y};
    let candidates = aimFrom(), pose = 'entry';
    if (!candidates.length) {
        const rect = own().rect;
        const cx = (rect[0] + rect[2]) / 2 / k - screen.x, cy = (rect[1] + rect[3]) / 2 / k - screen.y;
        search: for (const r of [450, 650])
            for (let a = 0; a < 16; a++) {
                const x = cx + Math.cos(a * Math.PI / 8 + Math.PI / 2) * r, y = cy + Math.sin(a * Math.PI / 8 + Math.PI / 2) * r;
                const b = floors[0].level.bounds;
                if (x < b.left + 150 || x > b.right - 150 || !free(x, y)) continue;
                ninja.x = x; ninja.y = y; ninja.speedX = ninja.speedY = 0;
                screen.trackGrappleOver(true); draw();
                if (!own()) continue;
                candidates = aimFrom();
                if (candidates.length) {pose = 'near landmark (ring ' + r + ', step ' + a + ')'; break search;}
            }
    }
    const best = candidates[0];
    return best ? {...best, client: canvasCoordsToViewportCoords({x: best.lx, y: best.ly}), radius, pose, entry,
        rect: own().rect, candidates: candidates.length, ninja: {x: ninja.x, y: ninja.y}} : {candidates: 0};
}'''
# One physics tick and frame; grapnel state and whether its tip lies in the
# landmark's current rect (world units)
SHOT_TICK_541 = '''id => {
    physics(); draw();
    const own = LANDMARKS.frame.drawn.find(d => d.id === id), k = scale[version];
    const tip = grapnel.pos[0];
    const inside = !!(own && tip && grapnel.throwed && !grapnel.grappled &&
        tip[0] >= own.rect[0] / k - screen.x && tip[0] <= own.rect[2] / k - screen.x &&
        tip[1] >= own.rect[1] / k - screen.y && tip[1] <= own.rect[3] / k - screen.y);
    return {throwed: grapnel.throwed, grappled: grapnel.isGrappled(), clip: grapnel.clip,
        traveled: Math.round(grapnel.traveled * 10) / 10, tip: tip ? [Math.round(tip[0]), Math.round(tip[1])] : null,
        inside, ninja: [Math.round(ninja.x), Math.round(ninja.y)]};
}'''


class Task541Tests(unittest.TestCase):
    """Grapple Over section landmarks as visible goals; classic/bad and geometry unchanged."""

    @classmethod
    def setUpClass(cls):
        from functools import partial
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from browser_test_support import QuietHandler
        from perf_mobile import export_rev
        cls.evidence = EvidenceWriter('TASK-541')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        root, sha = export_rev(BASELINE_541, cls.addClassCleanup)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.baseline_url = f'http://127.0.0.1:{server.server_port}/'
        hashes = source_hashes()
        for name in ('tools/test_grapple_over_visuals.py', 'render/landmarks.js'):
            hashes[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.config = dict(revision=subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            dirty=bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                                cwd=ROOT, text=True).strip()),
            baseline_revision=sha, source_hashes=hashes, browser=cls.browser.version,
            viewports=VIEWPORTS_541, device_scale_factor=1, seed=1)
        cls.evidence.log('CONFIG ' + json.dumps(cls.config, sort_keys=True))

    def open(self, url, viewport, touch=False, mode='grapple_over', query=''):
        context = self.browser.new_context(viewport=viewport, device_scale_factor=1,
                                           is_mobile=touch, has_touch=touch)
        self.addCleanup(context.close)
        self.evidence.log('BROWSER_CONTEXT ' + json.dumps(dict(
            test=self.id(), url='baseline' if url == self.baseline_url else 'worktree',
            viewport=viewport, dpr=1, is_mobile=touch, has_touch=touch, mode=mode, query=query), sort_keys=True))
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
            page = self.open(url, VIEWPORTS_541[0]['viewport'])
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

    def press(self, page, touch, point):
        if touch:
            cdp = page.context.new_cdp_session(page)
            cdp.send('Input.dispatchTouchEvent', dict(type='touchStart', touchPoints=[dict(x=point['x'], y=point['y'])]))
            return lambda: cdp.send('Input.dispatchTouchEvent', dict(type='touchEnd', touchPoints=[]))
        page.mouse.move(point['x'], point['y'])
        page.mouse.down()
        return page.mouse.up

    def test_02_landmarks_entry_frames_and_shots(self):
        rows = []
        for config in VIEWPORTS_541:
            viewport, touch = config['viewport'], config['touch']
            size = f'{viewport["width"]}x{viewport["height"]}'
            for i in range(8):
                # A fresh page per section: the shot is real play from the entry pose
                page = self.open(self.url, viewport, touch)
                row = page.evaluate(ENTRY_541, i)
                sid = row['section']
                self.assertIsNotNone(row['rect'], row)
                self.assertEqual(row['weight'], 1, row)
                l, t, r, b = row['client']
                row['inside_viewport'] = 0 <= l and 0 <= t and r <= viewport['width'] and b <= viewport['height']
                row['inside_canvas'] = (row['rect'][0] >= 0 and row['rect'][1] >= 0 and
                                        row['rect'][2] <= row['logical']['width'] and row['rect'][3] <= row['logical']['height'])
                row['changed_fraction'] = round(row['changed'] / row['total'], 4)
                self.assertTrue(row['inside_viewport'] and row['inside_canvas'], row)
                self.assertGreater(row['changed_fraction'], 0.05, row)
                self.assertEqual(row['colliders'], 0)
                entry_png = f'landmarks/{sid}-entry-{config["name"]}-{size}.png'
                close_png = f'landmarks/{sid}-close-{config["name"]}-{size}.png'
                page.screenshot(path=str(self.evidence.path(entry_png)))
                page.screenshot(path=str(self.evidence.path(close_png)),
                                clip=dict(x=l, y=t, width=r - l, height=b - t), scale='css')
                # Trusted input aimed through the landmark decoration
                page.evaluate('menu.unPause()')
                aim = page.evaluate(ARM_541, row['landmark']['id'])
                self.assertGreater(aim['candidates'], 0, (sid, size))
                release = self.press(page, touch, aim['client'])
                ticks = []
                for _ in range(90):
                    tick = page.evaluate(SHOT_TICK_541, row['landmark']['id'])
                    ticks.append(tick)
                    if tick['throwed'] and tick['traveled'] >= aim['radius']:
                        break
                release()
                ticks.append(page.evaluate(SHOT_TICK_541, row['landmark']['id']))
                shot = dict(input='CDP touchStart/touchEnd' if touch else 'Playwright mouse down/up',
                            aim_client={k: round(v, 2) for k, v in aim['client'].items()},
                            aim_world=[round(aim['wx'], 1), round(aim['wy'], 1)],
                            aim_distance=round(aim['d'], 1), radius=aim['radius'], clear_candidates=aim['candidates'],
                            pose=aim['pose'], ninja_at_press=[round(v, 1) for v in aim['ninja'].values()],
                            landmark_rect_at_press=[round(v, 2) for v in aim['rect']],
                            ticks=len(ticks), thrown=any(x['throwed'] for x in ticks),
                            grappled_ticks=sum(x['grappled'] for x in ticks),
                            clipped_ticks=sum(x['clip'] is not None for x in ticks),
                            tip_inside_landmark_ticks=sum(x['inside'] for x in ticks),
                            max_traveled=max(x['traveled'] for x in ticks),
                            released_shot_ended=not ticks[-1]['throwed'],
                            samples=[x for j, x in enumerate(ticks) if j % 5 == 0 or j == len(ticks) - 1])
                shot['passed_through'] = (shot['thrown'] and shot['grappled_ticks'] == 0 and shot['clipped_ticks'] == 0
                                          and shot['tip_inside_landmark_ticks'] > 0
                                          and shot['max_traveled'] >= aim['radius'])
                self.assertTrue(shot['passed_through'], (sid, size, shot))
                row.update(viewport=config, entry_screenshot=entry_png, close_screenshot=close_png, shot=shot)
                del row['changed'], row['total']
                rows.append(row)
                page.close()
        self.assertEqual(len(rows), 16)
        self.evidence.write('landmarks.json', dict(
            method='per section: ninja at its entry pose (first encounter start), real snapped Grapple Over camera, '
                   'one draw(); rect = the landmark sprite rect drawn this frame (logical canvas units; client = CSS '
                   'px); changed_fraction = share of rect device pixels changed by >24 (RGB sum) against the same '
                   'frame with LANDMARKS.enabled off; shot = a trusted press aimed through the landmark, physics '
                   'stepped one tick per evaluate until the tip used the whole range, then released; the shot starts '
                   'from the entry pose when the landmark is within grapnel range there, else from a free pose near '
                   'the landmark (shot.pose)',
            all_inside_viewport=all(r['inside_viewport'] for r in rows),
            all_shots_passed_through=all(r['shot']['passed_through'] for r in rows),
            landmark_colliders=sum(r['colliders'] for r in rows), sections=rows))
        print(f'PASS landmarks: 8 sections x 2 viewports (desktop 1280x720, touch 844x390): own landmark at full '
              f'strength inside the viewport from the entry pose (min changed {min(r["changed_fraction"] for r in rows):.3f} '
              f'of its rect); 16 trusted shots through each landmark with 0 grapples and 0 clips; 32 screenshots')

    def test_03_fast_backdrop_and_sprites(self):
        page = self.open(self.url, VIEWPORTS_541[0]['viewport'])
        result = page.evaluate('''() => {
            const poses = GRAPPLE_OVER_MOUNTAIN.sections.map(s => {
                const e = GRAPPLE_OVER_MOUNTAIN.encounters.find(e => e.id === s.encounters[0]);
                return e.start || e});
            const at = p => {ninja.x = p.x; ninja.y = p.y; screen.trackGrappleOver(true); draw()};
            for (const p of poses) at(p);
            const original = drawGrappleOverLandmarks, seen = [];
            drawGrappleOverLandmarks = function(renderer) {
                const r = original.apply(this, arguments);
                seen.push({backdrop: renderer.ctx === BACKDROP.ctx, drawn: r ? r.length : 0});
                return r};
            const scale0 = BACKDROP.scale;
            at(poses[0]); seen.length = 0;
            BACKDROP.scale = 0.5; draw(); BACKDROP.scale = scale0; draw();
            drawGrappleOverLandmarks = original;
            const build = buildGlowSprite; let builds = 0;
            buildGlowSprite = function() {builds++; return build.apply(this, arguments)};
            let blur = 0;
            const P = CanvasRenderingContext2D.prototype, di = P.drawImage, st = P.stroke, fi = P.fill;
            P.drawImage = function() {if (this.shadowBlur) blur++; return di.apply(this, arguments)};
            P.stroke = function() {if (this.shadowBlur) blur++; return st.apply(this, arguments)};
            P.fill = function() {if (this.shadowBlur) blur++; return fi.apply(this, arguments)};
            for (let r = 0; r < 2; r++) for (const p of poses) at(p);
            P.drawImage = di; P.stroke = st; P.fill = fi;
            buildGlowSprite = build;
            return {seen, builds_in_warm_frames: builds, shadow_blur_draw_calls: blur,
                landmark_sprites: [...GLOW_SPRITES.cache.keys()].filter(k => k.startsWith('landmark|'))};
        }''')
        self.assertTrue(result['seen'][0]['backdrop'] and result['seen'][0]['drawn'] > 0, result['seen'])
        self.assertTrue(any(not s['backdrop'] and s['drawn'] > 0 for s in result['seen'][1:]), result['seen'])
        self.assertEqual(result['builds_in_warm_frames'], 0)
        self.assertEqual(result['shadow_blur_draw_calls'], 0)
        self.assertGreaterEqual(len(result['landmark_sprites']), 8)
        self.evidence.write('fast-backdrop.json', dict(note='fast backdrop forced with BACKDROP.scale = 0.5; warm '
                                                            'frames = 16 entry-pose frames after every sprite was built', **result))
        print(f'PASS fast backdrop/sprites: landmarks drawn into BACKDROP.ctx when the fast backdrop is on; '
              f'{len(result["landmark_sprites"])} cached landmark sprites; 0 builds and 0 shadowBlur draws in 16 warm frames')

    def test_04_classic_bad_pixels_unchanged(self):
        from collections import Counter
        rows = []
        for mode in ('classic', 'bad'):
            for ticks in (0, 90):
                frames = {}
                for label, url in (('before', self.baseline_url), ('after', self.url)):
                    captures = []
                    for _ in range(3):
                        page = self.open(url, VIEWPORTS_541[0]['viewport'], mode=mode)
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
            viewport=VIEWPORTS_541[0]['viewport'], dpr=1, captures_per_revision=3,
            clock='performance.now frozen at 4321 before startGame; particle system emptied; Math.random re-seeded',
            frames=rows, all_equal=all(r['equal'] for r in rows)))
        print(f'PASS classic/bad: {len(rows)} frames x 3 captures per revision; every worktree pixel hash is a '
              f'{BASELINE_541} hash and the most frequent hashes are equal (seed 1, ticks 0/90)')

    def test_05_render_cost_ab(self):
        # Matched A/B of the background layer (PERF_PROFILE) at the 8 entry
        # poses, pairs alternated; relative only, headless is not device FPS
        script = '''() => {
            const means = [];
            for (const s of GRAPPLE_OVER_MOUNTAIN.sections) {
                const e = GRAPPLE_OVER_MOUNTAIN.encounters.find(e => e.id === s.encounters[0]), p = e.start || e;
                ninja.x = p.x; ninja.y = p.y; screen.trackGrappleOver(true);
                for (let i = 0; i < 60; i++) draw();
                means.push(PERF_PROFILE.snapshot().entries.find(e => e.name === 'background').meanMs);
            }
            return {means, landmarks: typeof LANDMARKS !== 'undefined'};
        }'''
        pairs = []
        for rep in range(3):
            pair = {}
            order = (('before', self.baseline_url), ('after', self.url))
            for label, url in (order if rep % 2 == 0 else order[::-1]):
                page = self.open(url, VIEWPORTS_541[0]['viewport'], query='?perf=1')
                result = page.evaluate(script)
                self.assertEqual(result['landmarks'], label == 'after')
                pair[label] = sum(result['means'])
                page.close()
            pair['ratio'] = pair['after'] / pair['before']
            pairs.append(pair)
        ratios = sorted(p['ratio'] for p in pairs)
        self.evidence.write('cost.json', dict(
            note='relative A/B only (matched headless pages, same browser, seed 1, 480 frames at the 8 entry poses); '
                 'not device FPS', before=f'{BASELINE_541} (git archive, no landmarks)', after='worktree',
            layer='background (PERF_PROFILE)', viewport=VIEWPORTS_541[0]['viewport'], dpr=1, query='?perf=1',
            pairs=[{k: round(v, 5) for k, v in p.items()} for p in pairs], median_after_over_before=round(ratios[1], 4)))
        print(f'PASS cost A/B: background layer after/before median ratio {ratios[1]:.3f} over 3 matched pairs '
              f'(relative, headless)')


BASELINE_542 = '1e2ad62'
# The revision before TASK-538: no Grapple Over art (palettes, parallax,
# role detail, landmarks)
PRE_ART_542 = '530d25b'
VIEWPORT_542 = {'width': 1280, 'height': 720}
# Frame-to-frame change of the mean background colour (Euclidean RGB
# distance, 0..255 channels). A seam or pop is an isolated step: a frame whose
# change exceeds the larger of its two neighbours' changes by more than
# SPIKE_LIMIT_542 (a smooth cross-fade rises and falls over many frames; a
# hard palette cut steps by ~45, a whole layer appearing by several units).
# Any change above JUMP_LIMIT_542 also fails: the fastest smooth cross-fade is
# the band change (~45) x the smoothstep's peak slope (1.5 / 800 world units)
# x the fastest camera motion (~44 world units per frame) = ~3.7.
JUMP_LIMIT_542 = 4.0
SPIKE_LIMIT_542 = 1.0
# Negative control: camera-centre sweep across the y -3240 boundary at the
# fall's camera speed, production vs a hard palette cut at the boundary vs the
# parallax layers switched on at once in the band core (y -2700)
CONTROL_542 = '''([frameSource, mode]) => {
    const frame = (0, eval)(frameSource), rows = [];
    const palette = grappleOverBackdropPalette;
    if (mode === 'hard-cut')
        grappleOverBackdropPalette = y => {const p = palette(y), i = p.t < 0.5 ? p.from : p.to; return {from: i, to: i, t: 0}};
    try {
        for (let i = 0, y = -2640; y >= -3840; y -= 30, i++) {
            if (mode === 'parallax-pop') visualEffects.background.parallaxEnabled = y < -2700;
            ninja.x = 3240; ninja.y = y; ninja.speedX = ninja.speedY = 0;
            screen.y = height / scale[version] / 2 - y;
            rows.push([i + 1, ...frame([i + 1, 1000, -1, false]).row]);
        }
    } finally {
        grappleOverBackdropPalette = palette;
        visualEffects.background.parallaxEnabled = true;
    }
    return rows;
}'''
# Frames for the video and filmstrips: every CAPTURE_EVERY_542th tick while
# the camera centre is within CAPTURE_NEAR_542 world units of a band boundary
# (every FALL_EVERY_542th tick of the fall)
CAPTURE_NEAR_542 = 150
CAPTURE_EVERY_542 = 4
FALL_EVERY_542 = 3
COST_RUNS_542 = 5
COST_POSES_542 = 40
COST_LIMIT_542 = 1.15
# The TASK-530 S04-exit fixture (the TASK-529 run at tick 5787) and its S05 route,
# then the S06-01 carriage, the TASK-530 press at tick 2163, released after FALL_HOLD_542
# ticks instead of 120: the player drops from the S06 entrance (y about -9019) through
# five band boundaries to the base and comes to rest there
FALL_PRESS_542 = 2163
FALL_HOLD_542 = 110
FALL_TICKS_542 = 2163 + 110 + 2600
FALL_REST_542 = dict(y=[0, 200])
# One replayed frame: draw() with the production renderer, then the frame's
# background layer painted again by the production background renderer
# (visualEffects.background.paint: cave layers, palette wash, parallax,
# landmarks, with this frame's camera and palette) into a 1/8-resolution CPU
# probe canvas, the way the fast backdrop swaps its target, and its mean
# colour. A full-resolution frame raster here costs ~130 ms per readback, so
# the full frame's background is read only every FULL_EVERY_542th tick, to
# record how closely the probe follows it. Also the camera-centre y, the
# palette, and a 480x270 JPEG of the finished frame when asked.
FULL_EVERY_542 = 60
FRAME_542 = '''([tick, every, near, full]) => {
    const mean = d => {
        let r = 0, g = 0, b = 0;
        for (let i = 0; i < d.length; i += 4) {r += d[i]; g += d[i + 1]; b += d[i + 2]}
        const n = d.length / 4;
        return [r / n, g / n, b / n];
    };
    if (!window.__t542) {
        const original = drawBackgroundLayer;
        const thumb = document.createElement('canvas'), probe = document.createElement('canvas');
        thumb.width = 480; thumb.height = 270;
        probe.width = Math.round(LOGICAL_VIEWPORT.width / 8); probe.height = Math.round(LOGICAL_VIEWPORT.height / 8);
        window.__t542 = {full: false, fullMean: null, thumb, probe,
            probeCtx: probe.getContext('2d', {willReadFrequently: true})};
        drawBackgroundLayer = function() {
            const result = original.apply(this, arguments);
            if (__t542.full && !BACKDROP.active)
                __t542.fullMean = mean(ctx.getImageData(0, 0, canvas.width, canvas.height).data);
            return result;
        };
    }
    const T = __t542;
    T.full = full; T.fullMean = null;
    draw();
    const bg = visualEffects.background, saved = [bg.ctx, bg.canvas, bg.parallaxFrame, LANDMARKS.frame];
    T.probeCtx.setTransform(T.probe.width / LOGICAL_VIEWPORT.width, 0, 0, T.probe.height / LOGICAL_VIEWPORT.height, 0, 0);
    bg.ctx = T.probeCtx; bg.canvas = T.probe;
    try { bg.paint() } finally { [bg.ctx, bg.canvas, bg.parallaxFrame, LANDMARKS.frame] = saved }
    const probeMean = mean(T.probeCtx.getImageData(0, 0, T.probe.width, T.probe.height).data);
    const theme = GRAPPLE_OVER_THEME, camY = height / scale[version] / 2 - screen.y;
    const p = bg.palette, k = Math.round(-camY / theme.bandHeight);
    const nearBoundary = k >= 1 && k < theme.palettes.length && Math.abs(-camY - k * theme.bandHeight) <= near;
    let jpeg = null;
    if (tick % every === 0 && (near < 0 || nearBoundary)) {
        T.thumb.getContext('2d').drawImage(canvas, 0, 0, 480, 270);
        jpeg = T.thumb.toDataURL('image/jpeg', 0.8);
    }
    const r3 = v => Math.round(v * 1000) / 1000;
    return {row: [Math.round(camY * 100) / 100, p.from, p.to, Math.round(p.t * 1e4) / 1e4, ...probeMean.map(r3)],
        full: T.fullMean && T.fullMean.map(r3), jpeg};
}'''
# Per-frame draw() time (ms) at each pose (player x, y; snapped camera)
COST_CHUNK_542 = '''ps => {
    const out = [];
    for (const [x, y] of ps) {
        ninja.x = x; ninja.y = y; ninja.speedX = ninja.speedY = 0;
        screen.trackGrappleOver(true);
        const a = performance.now(); draw(); out.push(performance.now() - a);
    }
    return out;
}'''
# Which context each new layer drew into, with the fast backdrop forced
FAST_542 = '''() => {
    const poses = GRAPPLE_OVER_MOUNTAIN.sections.map(s => {
        const e = GRAPPLE_OVER_MOUNTAIN.encounters.find(e => e.id === s.encounters[0]);
        return {section: s.id, ...(e.start || e)}});
    const seen = {}, wrap = (name, target) => {
        const original = window[name];
        window[name] = function() {
            const result = original.apply(this, arguments);
            seen[name].push(target(arguments, result));
            return result};
        return () => {window[name] = original}};
    const unwrap = [
        wrap('drawGrappleOverPalette', a => ({backdrop: a[0] === BACKDROP.ctx})),
        wrap('drawGrappleOverParallax', (a, r) => ({backdrop: a[0].ctx === BACKDROP.ctx, layers: r.length})),
        wrap('drawGrappleOverLandmarks', (a, r) => ({backdrop: a[0].ctx === BACKDROP.ctx, drawn: r ? r.length : 0})),
        wrap('drawGrappleOverRoleDetail', () => ({backdrop: ctx === BACKDROP.ctx, backdropActive: BACKDROP.active,
            counts: Object.values(ROLE_DETAIL.frame.counts).reduce((a, b) => a + b, 0)}))];
    const rows = [];
    for (const p of poses) {
        for (const k of ['drawGrappleOverPalette', 'drawGrappleOverParallax', 'drawGrappleOverLandmarks',
                         'drawGrappleOverRoleDetail']) seen[k] = [];
        ninja.x = p.x; ninja.y = p.y; screen.trackGrappleOver(true); draw();
        rows.push({section: p.section, pose: [p.x, p.y], scale: BACKDROP.scale,
            backdrop: [BACKDROP.canvas.width, BACKDROP.canvas.height], ...structuredClone(seen)});
    }
    unwrap.forEach(f => f());
    return rows;
}'''


class Task542Tests(unittest.TestCase):
    """Smooth band transitions over the archived continuous climbs and a long fall, and the render cost of the
    whole Grapple Over art (TASK-538..541) against the pre-art revision; geometry and classic/bad unchanged."""

    @classmethod
    def setUpClass(cls):
        from functools import partial
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from browser_test_support import QuietHandler
        from grapple_over_verify import hashes
        from perf_mobile import export_rev
        cls.evidence = EvidenceWriter('TASK-542')
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.urls, cls.revisions = {}, {}
        for label, rev in (('before', BASELINE_542), ('pre_art', PRE_ART_542)):
            root, sha = export_rev(rev, cls.addClassCleanup)
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
            cls.addClassCleanup(server.server_close)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.addClassCleanup(thread.join)
            cls.addClassCleanup(server.shutdown)
            cls.urls[label], cls.revisions[label] = f'http://127.0.0.1:{server.server_port}/', sha
        cls.urls['final'] = cls.url
        files = hashes()
        for name in ('tools/test_grapple_over_visuals.py', 'tools/test_grapple_over_integration.py'):
            files[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        cls.config = dict(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            dirty_paths=subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no', '--', '.',
                                                 ':!artifacts'], cwd=ROOT, text=True).splitlines(),
            baseline_revision=cls.revisions['before'], pre_art_revision=cls.revisions['pre_art'], source_hashes=files,
            browser=cls.browser.version, viewport=VIEWPORT_542, device_scale_factor=1, seed=1, hz=60)
        cls.evidence.log('CONFIG ' + json.dumps(cls.config, sort_keys=True))

    def open(self, label, query='', mode='grapple_over'):
        context = self.browser.new_context(viewport=VIEWPORT_542, device_scale_factor=1)
        self.addCleanup(context.close)
        self.evidence.log('BROWSER_CONTEXT ' + json.dumps(dict(test=self.id(), revision=label, viewport=VIEWPORT_542,
                                                               dpr=1, mode=mode, query=query), sort_keys=True))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        self.addCleanup(lambda: self.assertEqual(errors, []))
        page.add_init_script(SEED_SCRIPT % 1)
        page.goto(self.urls[label] + query)
        wait_for_boot(page)
        page.evaluate('m => {startGame(m); cancelAnimationFrame(game)}', mode)
        page.wait_for_function('!unTouch')
        return page

    def test_01_geometry_hash_unchanged(self):
        row = {}
        for label in ('before', 'final', 'pre_art'):
            page = self.open(label)
            geometry = page.evaluate(GEOMETRY_538)
            row[label] = dict(sha256=hashlib.sha256(geometry.encode()).hexdigest(),
                              elements=len(json.loads(geometry)['elements']), movers=len(json.loads(geometry)['movers']))
            page.close()
        after = row.pop('final')
        row = dict(before=row['before'], after=after, pre_art=row['pre_art'],
                   baseline_revision=self.revisions['before'], pre_art_revision=self.revisions['pre_art'],
                   fields='elements: id, role, grapplable, x, y, points; movers: full',
                   equal=row['before'] == after, equal_to_pre_art=row['pre_art'] == after)
        self.evidence.write('geometry-hash.json', row)
        self.assertEqual(row['before'], row['after'])
        self.assertEqual(row['pre_art'], row['after'])
        self.assertGreater(after['elements'], 0)
        print(f'PASS geometry: hash {after["sha256"][:16]} before ({BASELINE_542}) == after == pre-art '
              f'({PRE_ART_542}) ({after["elements"]} elements, {after["movers"]} movers)', flush=True)

    # ---- replays --------------------------------------------------------------------------------
    def archived(self, task):
        return (json.loads((ROOT / f'artifacts/{task}/inputs.json').read_text()),
                json.loads((ROOT / f'artifacts/{task}/trace.json').read_text()))

    def manifest(self, kind, ticks, inputs, expected_exit, required_events, snapshot=None):
        from grapple_over_verify import metadata, validate
        m = dict(metadata=metadata(kind), ticks=ticks, inputs=inputs, expected_exit=expected_exit,
                 required_events=required_events)
        if snapshot is not None:
            m['initial_snapshot'] = snapshot
        m['metadata']['compact_contacts'] = True
        validate(m)
        return m

    def replay(self, name, manifest, every, near, start=1):
        """Every tick from start on drawn by the production renderer; the raw recording is deleted after use."""
        import base64
        import shutil
        from grapple_over_verify import execute, check_trace
        rows, frames = [], []
        self.fidelity = getattr(self, 'fidelity', {})
        fidelity = self.fidelity.setdefault(name, [])

        def on_frame(page, tick):
            if tick < start:
                return
            frame = page.evaluate(FRAME_542, [tick, every, near, tick % FULL_EVERY_542 == 0])
            rows.append([tick] + frame['row'])
            if frame['full']:
                fidelity.append([tick] + frame['row'][4:] + frame['full'])
            if frame['jpeg']:
                frames.append(dict(run=name, tick=tick, camera_y=frame['row'][0],
                                   jpeg=base64.b64decode(frame['jpeg'].split(',', 1)[1])))
        trace = execute(manifest, self.browser, self.url, str(self.evidence.path('runs/' + name)), on_frame=on_frame)
        check_trace(manifest, trace)
        shutil.rmtree(self.evidence.path('runs/' + name))
        self.assertEqual([r[0] for r in rows], list(range(start, manifest['ticks'] + 1)))
        return trace, rows, frames

    @staticmethod
    def physics_rows(trace):
        # The archived TASK-529/530 compact rows (Task529Tests.compact)
        rows = []
        for r in trace['snapshots']:
            s = r['state']['simulation']; p = s['player']
            rows.append([r['tick'], s['simulationTick'], p['x'], p['y'], p['speedX'], p['speedY'], int(s['upgrades']['range']),
                         s['stats']['maxHeight'], int(bool(s['grapple'].get('grappled')))])
        return rows

    def compare(self, task, trace, archived):
        from test_grapple_over_integration import Task529Tests
        old = archived['trace']
        rows = self.physics_rows(trace)
        inputs = [{k: e[k] for k in ('tick', 'event', 'world', 'client', 'trusted')} for e in trace['events'] if e['type'] == 'input']
        mechanics = Task529Tests.mechanics(trace)
        row = dict(task=task, archived=f'artifacts/{task}/trace.json', fields=old['fields'], ticks=len(rows) - 1,
                   rows_compared=len(rows), archived_rows=len(old['rows']),
                   rows_differing=sum(a != b for a, b in zip(rows, old['rows'])),
                   rows_identical=rows == old['rows'], inputs_identical=inputs == old['inputs'], trusted_inputs=len(inputs),
                   mechanics_identical=json.loads(json.dumps(mechanics)) == old['mechanics'], mechanic_events=len(mechanics),
                   full_snapshot_sha256_equal=sum(r['sha256'] == h for r, h in zip(trace['snapshots'], old['snapshot_sha256'])),
                   full_snapshot_note='full per-tick snapshot hashes include the level element list, which TASK-531 '
                                      'changed after these recordings (S05-transfer-canopy deleted); the archived '
                                      'trace keeps the per-tick physics rows, compared here exactly (float equality)')
        self.assertTrue(row['rows_identical'] and row['inputs_identical'] and row['mechanics_identical'],
                        {k: v for k, v in row.items() if k != 'fields'})
        return row

    def test_02_replays_and_transitions(self):
        from grapple_over_support import state_hash
        lower_in, lower_old = self.archived('TASK-529')
        upper_in, upper_old = self.archived('TASK-530')
        runs, frames, traces = {}, [], {}
        # TASK-529: base start, the archived trusted inputs
        m = self.manifest('base-start', lower_in['ticks'], lower_in['inputs'], lower_in['expected_exit'],
                          lower_in['required_events'])
        self.assertNotIn('initial_snapshot', m)
        trace, rows, shots = self.replay('climb-lower', m, CAPTURE_EVERY_542, CAPTURE_NEAR_542)
        traces['climb-lower'] = self.compare('TASK-529', trace, lower_old)
        runs['climb-lower'], frames = rows, frames + shots
        # TASK-530: its S04-exit fixture is the TASK-529 run's real state at tick 5787 (the archived
        # snapshot predates TASK-531's element list); it equals the archived one but for that list
        from test_grapple_over_integration import Task530Tests
        fixture = trace['snapshots'][Task530Tests.FIXTURE_TICK]['state']['simulation']
        del trace
        old = upper_in['initial_snapshot']
        ids = {e['id'] for e in fixture['elements']}
        same = {k: fixture[k] == old[k] for k in fixture}
        kept = [e for e in old['elements'] if e['id'] in ids]
        fixture_row = dict(tick=Task530Tests.FIXTURE_TICK, equal_fields=[k for k, v in same.items() if v],
                           differing_fields=[k for k, v in same.items() if not v],
                           archived_elements=len(old['elements']), elements=len(fixture['elements']),
                           archived_elements_not_in_level=[e['id'] for e in old['elements'] if e['id'] not in ids],
                           elements_equal_after_dropping_those=kept == fixture['elements'])
        self.assertTrue(fixture_row['elements_equal_after_dropping_those'] and
                        fixture_row['differing_fields'] in ([], ['elements']), fixture_row)
        m = self.manifest('isolated', upper_in['ticks'], upper_in['inputs'], upper_in['expected_exit'],
                          upper_in['required_events'], fixture)
        trace, rows, shots = self.replay('climb-upper', m, CAPTURE_EVERY_542, CAPTURE_NEAR_542)
        traces['climb-upper'] = dict(self.compare('TASK-530', trace, upper_old), fixture=fixture_row)
        runs['climb-upper'], frames = rows, frames + shots
        del trace
        # The long fall: recorded with every frame drawn, then replayed without frames (identical trace)
        from grapple_over_verify import execute, check_trace
        press = next(e for e in upper_in['inputs'] if e['tick'] == FALL_PRESS_542)
        inputs = [e for e in upper_in['inputs'] if e['tick'] < FALL_PRESS_542] + \
                 [press, dict(tick=FALL_PRESS_542 + FALL_HOLD_542, event='mouseup', world=press['world'])]
        m = self.manifest('isolated', FALL_TICKS_542, inputs, FALL_REST_542, ['acquisition', 'release', 'bounce'], fixture)
        self.evidence.write('fall-inputs.json', dict(m, initial_snapshot=dict(
            source='TASK-529 archived inputs replayed from the base start, state at tick %d (the TASK-530 fixture)'
                   % Task530Tests.FIXTURE_TICK, sha256=state_hash(fixture)),
            scope='TASK-530 S05 route and the S06-01 carriage press at tick %d released after %d ticks (nominal 120); '
                  'trusted mouse input only; no placement after the fixture, no checkpoint or reset'
                  % (FALL_PRESS_542, FALL_HOLD_542)))
        # Its frames from 30 ticks before the release (the ticks before replay the TASK-530 climb, drawn above)
        release = FALL_PRESS_542 + FALL_HOLD_542
        trace, rows, shots = self.replay('fall', m, FALL_EVERY_542, -1, start=release - 30)
        replay = execute(m, self.browser, self.url, str(self.evidence.path('runs/fall-replay')))
        check_trace(m, replay)
        import shutil
        shutil.rmtree(self.evidence.path('runs/fall-replay'))
        self.assertEqual(trace, replay)
        fall_rows = self.physics_rows(trace)
        mech = [x for x in __import__('test_grapple_over_integration').Task529Tests.mechanics(trace)]
        after = [x for x in mech if x['tick'] > release and x['type'] == 'acquisition']
        self.assertEqual(after, [], 'no rope after the release: a free fall')
        top = min(fall_rows[release:], key=lambda r: r[3])
        traces['fall'] = dict(recorded_sha256=state_hash(trace), replayed_sha256=state_hash(replay), identical=True,
            ticks=FALL_TICKS_542, release_tick=release, apex=dict(tick=top[0], y=top[3]),
            final=dict(x=fall_rows[-1][2], y=fall_rows[-1][3], speedX=fall_rows[-1][4], speedY=fall_rows[-1][5]),
            acquisitions_after_release=0, inputs='fall-inputs.json',
            rows=dict(fields=['tick', 'simulationTick', 'x', 'y', 'speedX', 'speedY', 'rangeUpgraded', 'maxHeight', 'grappled'],
                      every=5, rows=[r for r in fall_rows if r[0] % 5 == 0 or r[0] >= release - 1 and r[0] <= release + 1]))
        del trace, replay
        runs['fall'], frames = [r for r in rows if r[0] >= release - 1], frames + shots
        self.evidence.write('traces.json', traces)
        self.transitions(runs, frames, release)

    @staticmethod
    def add_deltas(rows):
        # Appends delta (to the previous frame) and spike (delta minus the larger neighbouring delta)
        deltas = [0] + [round(sum((a[i] - b[i]) ** 2 for i in (5, 6, 7)) ** 0.5, 4) for a, b in zip(rows, rows[1:])]
        for i, r in enumerate(rows):
            near = [deltas[j] for j in (i - 1, i + 1) if 0 < j < len(rows)]
            r += [deltas[i], round(deltas[i] - max(near), 4) if i and near else 0]

    def control(self):
        page = self.open('final')
        result = {}
        for mode in ('production', 'hard-cut', 'parallax-pop'):
            rows = page.evaluate(CONTROL_542, [FRAME_542, mode])
            self.add_deltas(rows)
            top = max(rows, key=lambda r: r[-1])
            result[mode] = dict(frames=len(rows), max_delta=max(r[-2] for r in rows), max_spike=top[-1], at_camera_y=top[1],
                                detected=top[-1] > SPIKE_LIMIT_542 or max(r[-2] for r in rows) > JUMP_LIMIT_542)
        page.close()
        self.assertFalse(result['production']['detected'], result)
        self.assertTrue(result['hard-cut']['detected'] and result['parallax-pop']['detected'], result)
        return dict(method='camera centre swept -2640..-3840 in 30-unit frames (the fall\'s camera speed) across the y -3240 '
                           'boundary, ninja at the camera centre, the same per-frame probe; hard-cut: the palette switches at '
                           'the boundary instead of blending; parallax-pop: the parallax layers appear at once at y -2700 (band core)', **result)

    def transitions(self, runs, frames, release):
        theme = self.theme()
        control = self.control()
        band, half, count = theme['bandHeight'], theme['blendHalfSpan'], len(theme['palettes'])
        boundaries = [-k * band for k in range(1, count)]
        analysis, worst = {}, {}
        for name, rows in runs.items():
            self.add_deltas(rows)
            crossings = [dict(boundary=b, tick=r[0]) for a, r in zip(rows, rows[1:]) for b in boundaries
                         if (a[1] - b) * (r[1] - b) < 0 or (r[1] == b)]
            per = []
            for b in boundaries:
                window = [r for r in rows[1:] if abs(r[1] - b) <= half]
                if not window:
                    continue
                biggest = max(window, key=lambda r: r[-2])
                spike = max(window, key=lambda r: r[-1])
                per.append(dict(boundary=b, frames_in_blend_span=len(window), max_spike=spike[-1], spike_tick=spike[0],
                                crossings=[c['tick'] for c in crossings if c['boundary'] == b],
                                max_delta=biggest[-2], at_tick=biggest[0], camera_y=biggest[1],
                                palette_t_range=[min(r[4] for r in window if r[2] != r[3] or r[4]),
                                                 max(r[4] for r in window)] if any(r[2] != r[3] for r in window) else None))
            biggest = max(rows[1:], key=lambda r: r[-2])
            spike = max(rows[1:], key=lambda r: r[-1])
            analysis[name] = dict(frames=len(rows), camera_y_range=[min(r[1] for r in rows), max(r[1] for r in rows)],
                                  boundaries=per, crossings=crossings,
                                  max_delta_any_frame=dict(delta=biggest[-2], tick=biggest[0], camera_y=biggest[1]),
                                  max_spike_any_frame=dict(spike=spike[-1], tick=spike[0], camera_y=spike[1]))
            worst[name] = dict(delta=max(p['max_delta'] for p in per), spike=max(p['max_spike'] for p in per)) if per else None
        # The probe against the full-resolution frame background: absolute difference of the means, and of
        # their changes between consecutive samples (FULL_EVERY_542 ticks apart)
        fidelity = {}
        for name, samples in self.fidelity.items():
            dist = lambda a, b: sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
            change = [abs(dist(a[1:4], b[1:4]) - dist(a[4:7], b[4:7])) for a, b in zip(samples, samples[1:])]
            fidelity[name] = dict(samples=len(samples), columns=['tick', 'probe_r', 'probe_g', 'probe_b', 'full_r', 'full_g', 'full_b'],
                                  max_mean_distance=round(max(dist(r[1:4], r[4:7]) for r in samples), 3),
                                  max_change_difference=round(max(change), 3) if change else None,
                                  full_change_max=round(max((dist(a[4:7], b[4:7]) for a, b in zip(samples, samples[1:])), default=0), 3),
                                  rows=samples)
        climbed = sorted({c['boundary'] for n in ('climb-lower', 'climb-upper') for c in analysis[n]['crossings']})
        fallen = sorted({c['boundary'] for c in analysis['fall']['crossings'] if c['tick'] > release})
        result = dict(
            method='every replay tick drawn by the production draw(); mean background colour = mean RGB of that '
                   'frame\'s background layer, painted by the production background renderer (visualEffects.background.'
                   'paint: cave layers, palette wash, parallax, landmarks; this frame\'s camera and palette) into a '
                   '1/8-resolution probe canvas; every %dth tick the full-resolution background as drawn into the frame '
                   '(read right after drawBackgroundLayer) is also read (probe_fidelity); delta = Euclidean RGB distance '
                   'between consecutive frames of the same run (0..255 channels); a boundary frame is one whose '
                   'camera-centre y is within the palette blend span (+/-%d) of the boundary' % (FULL_EVERY_542, half),
            probe_fidelity=fidelity,
            threshold=dict(max_frame_delta=JUMP_LIMIT_542, max_spike=SPIKE_LIMIT_542,
                           unit='Euclidean RGB distance of the frame mean, 0..255 channels',
                           spike='delta of a frame minus the larger delta of its two neighbouring frames (an isolated step)',
                           meaning='a seam or pop is a frame whose spike exceeds max_spike, or any delta above '
                                   'max_frame_delta; derivation of both in the JUMP_LIMIT_542 comment of the test file: the '
                                   'fastest smooth cross-fade (band change ~45 x smoothstep peak slope 1.5/800 per world unit '
                                   'x ~44 world units of camera motion per frame) is ~3.7 per frame; a hard palette cut is '
                                   '~45 in one frame (control)'),
            control=control,
            boundaries=boundaries, blend_half_span=half, viewport=VIEWPORT_542, dpr=1,
            climb_boundaries_crossed=climbed, fall_boundaries_crossed=fallen, worst_boundary_delta=worst,
            runs=analysis,
            columns=['tick', 'camera_y', 'palette_from', 'palette_to', 'palette_t', 'mean_r', 'mean_g', 'mean_b', 'delta', 'spike'],
            frames={name: rows for name, rows in runs.items()},
            fall_note='the fall frames start one tick before the carriage release (tick %d); the climb run frames start at tick 1' % release)
        self.evidence.write('transitions.json', result)
        self.assertEqual(climbed, sorted(boundaries))
        self.assertGreaterEqual(len(fallen), 2)
        for name, value in worst.items():
            self.assertIsNotNone(value, name)
            self.assertLessEqual(value['delta'], JUMP_LIMIT_542, (name, analysis[name]['boundaries']))
            self.assertLessEqual(value['spike'], SPIKE_LIMIT_542, (name, analysis[name]['boundaries']))
        self.media(frames, analysis, boundaries, release)
        print(f'PASS transitions: climbs (TASK-529/530 replays, rows identical to the archived traces) cross all '
              f'{len(boundaries)} boundaries, the fall crosses {fallen}; worst boundary frame delta/spike {worst} '
              f'(limits {JUMP_LIMIT_542}/{SPIKE_LIMIT_542}); control: hard palette cut spike '
              f'{control["hard-cut"]["max_spike"]}, parallax pop spike {control["parallax-pop"]["max_spike"]} detected; '
              f'{len(frames)} captured frames', flush=True)

    def theme(self):
        page = self.open('final')
        theme = page.evaluate('() => ({bandHeight: GRAPPLE_OVER_THEME.bandHeight, blendHalfSpan: GRAPPLE_OVER_THEME.blendHalfSpan, '
                              'palettes: GRAPPLE_OVER_THEME.palettes.map(p => p.name)})')
        page.close()
        return theme

    def media(self, frames, analysis, boundaries, release):
        """transitions.webm (every captured frame, labelled), one filmstrip per boundary crossing and the fall."""
        import io
        from PIL import Image, ImageDraw
        strips = []

        def strip(name, chosen, title):
            w, h = 240, 135
            sheet = Image.new('RGB', (w * len(chosen), h + 18), (0, 0, 0))
            draw = ImageDraw.Draw(sheet)
            for i, f in enumerate(chosen):
                with Image.open(io.BytesIO(f['jpeg'])) as img:
                    sheet.paste(img.convert('RGB').resize((w, h)), (i * w, 18))
                draw.text((i * w + 4, 3), f'{f["run"]} t{f["tick"]} y{f["camera_y"]:.0f}', fill=(255, 255, 255))
            path = f'transitions/{name}.jpg'
            sheet.save(self.evidence.path(path), quality=82)
            strips.append(dict(name=name, file=path, title=title, ticks=[f['tick'] for f in chosen]))

        for k, b in enumerate(boundaries, 1):
            for run in ('climb-lower', 'climb-upper', 'fall'):
                ticks = [c['tick'] for c in analysis[run]['crossings'] if c['boundary'] == b and (run != 'fall' or c['tick'] > release)]
                if not ticks:
                    continue
                around = [f for f in frames if f['run'] == run and abs(f['tick'] - ticks[0]) <= 600
                          and abs(f['camera_y'] - b) <= CAPTURE_NEAR_542 + 1]
                if len(around) < 2:
                    continue
                chosen = [around[round(i * (len(around) - 1) / 7)] for i in range(8)] if len(around) >= 8 else around
                strip(f'boundary{k}-{run}', chosen, f'boundary {k} (y {b}) first crossing in {run} at tick {ticks[0]}')
        fall = [f for f in frames if f['run'] == 'fall' and f['tick'] >= release]
        strip('fall', [fall[round(i * (len(fall) - 1) / 9)] for i in range(10)], 'the whole fall from the release')
        covered = {s['name'].split('-')[0] for s in strips if 'climb' in s['name']}
        self.assertEqual(covered, {f'boundary{k}' for k in range(1, len(boundaries) + 1)}, strips)
        # The video: every captured frame, in run order, with its run, tick and camera y
        video_frames = frames
        context = self.browser.new_context(viewport={'width': 480, 'height': 290}, device_scale_factor=1,
                                           record_video_dir=str(self.evidence.path('video/.keep').parent),
                                           record_video_size={'width': 480, 'height': 290})
        page = context.new_page()
        page.set_content('<body style="margin:0;background:#000;color:#fff;font:13px monospace">'
                         '<img id="f" width="480" height="270" style="display:block"><div id="c"></div></body>')
        import base64
        for f in video_frames:
            label = f'{f["run"]}  tick {f["tick"]}  camera y {f["camera_y"]:.0f}'
            page.evaluate('async ([s, l]) => {const i = document.getElementById("f"); i.src = s; await i.decode(); '
                          'document.getElementById("c").textContent = l}',
                          ['data:image/jpeg;base64,' + base64.b64encode(f['jpeg']).decode(), label])
            page.wait_for_timeout(1000 / 30)
        video = page.video
        context.close()
        video.save_as(str(self.evidence.path('transitions.webm')))
        video.delete()
        import shutil
        shutil.rmtree(self.evidence.path('video'), ignore_errors=True)
        self.assertGreater(self.evidence.path('transitions.webm').stat().st_size, 0)
        rows = []
        for name in ('climb-lower', 'climb-upper', 'fall'):
            for p in analysis[name]['boundaries']:
                rows.append(f'| {name} | {p["boundary"]} | {p["crossings"][:3]} | {p["frames_in_blend_span"]} | '
                            f'{p["max_delta"]} (tick {p["at_tick"]}) | {p["max_spike"]} (tick {p["spike_tick"]}) |')
        lines = ['# TASK-542 transitions review', '',
                 'Generated by Task542Tests.test_02 from this run; frames are the production renderer at 1280x720 '
                 '(thumbnails 480x270).', '',
                 f'- transitions.webm: {len(video_frames)} labelled frames (camera within {CAPTURE_NEAR_542} world units of a '
                 f'band boundary, every {CAPTURE_EVERY_542}th tick of the climbs; every {FALL_EVERY_542}rd tick of the fall '
                 f'from 30 ticks before the release at tick {release}).',
                 f'- Mean background colour per frame: frame-to-frame delta limit {JUMP_LIMIT_542}, isolated spike limit '
                 f'{SPIKE_LIMIT_542} (transitions.json threshold).', '',
                 '| run | boundary y | crossing ticks | frames in blend span | max delta | max spike |',
                 '|---|---|---|---|---|---|', *rows, '',
                 '## Filmstrips', '', *[f'- {s["file"]}: {s["title"]}, ticks {s["ticks"]}' for s in strips], '']
        self.evidence.path('review.md').write_text('\n'.join(lines))

    # ---- cost -----------------------------------------------------------------------------------
    def test_03_render_cost_ab(self):
        import statistics
        poses = {}
        for task in ('TASK-529', 'TASK-530'):
            inputs, trace = self.archived(task)
            rows = trace['trace']['rows']
            for s in inputs['segments']:
                n = s['end'] - s['start']
                poses[s['section']] = [rows[s['start'] + k * n // COST_POSES_542][2:4] for k in range(COST_POSES_542)]
        labels = ('pre_art', 'before', 'final')
        runs = []
        for run in range(COST_RUNS_542):
            pages = {}
            for label in labels:
                page = self.open(label, query='?perf=1')
                page.evaluate('() => Object.assign(TUTORIAL_HINT, {pressed: true, done: true, visible: false, alpha: 0})')
                for ps in poses.values():
                    page.evaluate(COST_CHUNK_542, ps)
                pages[label] = page
            sections = {}
            for section, ps in poses.items():
                # Frame by frame: each pose drawn once by each revision in turn (order rotated), twice over,
                # so load changes on the machine hit the three revisions alike
                times = {label: [] for label in labels}
                for k, pose in enumerate(ps * 2):
                    order = labels[(k + run) % 3:] + labels[:(k + run) % 3]
                    for label in order:
                        times[label] += pages[label].evaluate(COST_CHUNK_542, [pose])
                layers = {label: {e['name']: round(e['meanMs'], 4) for e in pages[label].evaluate('PERF_PROFILE.snapshot().entries')
                                  if e['name'] in ('background', 'world')} for label in labels}
                median = {label: statistics.median(v) for label, v in times.items()}
                sections[section] = dict(median_frame_ms={k: round(v, 4) for k, v in median.items()}, frames=len(times['final']),
                                         final_over_pre_art=round(median['final'] / median['pre_art'], 4),
                                         before_over_pre_art=round(median['before'] / median['pre_art'], 4), layers_mean_ms=layers)
            for page in pages.values():
                page.context.close()
            runs.append(sections)
            print(f'cost run {run + 1}: final/pre-art ' + json.dumps({s: v['final_over_pre_art'] for s, v in sections.items()}), flush=True)
        summary = {s: dict(final_over_pre_art_median=round(statistics.median(r[s]['final_over_pre_art'] for r in runs), 4),
                           before_over_pre_art_median=round(statistics.median(r[s]['before_over_pre_art'] for r in runs), 4),
                           runs=COST_RUNS_542) for s in poses}
        fast = self.fast_backdrop()
        self.evidence.write('cost.json', dict(
            note='relative A/B only (matched headless pages in one browser, seed 1, 1280x720, dpr 1); not device FPS',
            method='per section 40 poses = the player position every 1/40 of the section in the TASK-529/530 continuous '
                   'replays (same ticks for every revision), camera snapped; three revisions open side by side, each pose '
                   'drawn by each revision in turn (order rotated per frame), all poses twice = 80 frames per section; '
                   'cost = median draw() ms per frame (performance.now around draw: the main-thread render work; '
                   '?perf=1 so render/perfprofile.js times the layers: its background/world means over the last 120 frames are kept per section)',
            limit=COST_LIMIT_542, revisions=dict(pre_art=f'{self.revisions["pre_art"]} (before TASK-538, no art)',
                before=f'{self.revisions["before"]} (TASK-541 HEAD, before this ticket)', final='worktree'),
            sections=summary, runs=runs, fast_backdrop=fast,
            all_sections_within_limit=all(v['final_over_pre_art_median'] <= COST_LIMIT_542 for v in summary.values())))
        for s, v in summary.items():
            self.assertLessEqual(v['final_over_pre_art_median'], COST_LIMIT_542, s)
        print('PASS cost A/B: final/pre-art median per section ' +
              json.dumps({s: v['final_over_pre_art_median'] for s, v in summary.items()}) +
              f' (limit {COST_LIMIT_542}, {COST_RUNS_542} runs; before this ticket ' +
              json.dumps({s: v['before_over_pre_art_median'] for s, v in summary.items()}) + '); fast backdrop draws all new layers',
              flush=True)

    def fast_backdrop(self):
        page = self.open('final', query='?backdrop=0.5')
        rows = page.evaluate(FAST_542)
        for row in rows:
            self.assertEqual(row['scale'], 0.5)
            self.assertEqual(row['backdrop'], [640, 360])
            self.assertTrue(row['drawGrappleOverPalette'] and all(x['backdrop'] for x in row['drawGrappleOverPalette']), row)
            self.assertTrue(row['drawGrappleOverParallax'] and all(x['backdrop'] and x['layers'] == 2
                                                                   for x in row['drawGrappleOverParallax']), row)
            self.assertTrue(any(x['backdrop'] and x['drawn'] > 0 for x in row['drawGrappleOverLandmarks']), row)
            self.assertTrue(row['drawGrappleOverRoleDetail'] and all(not x['backdrop'] and x['counts'] > 0
                                                                     for x in row['drawGrappleOverRoleDetail']), row)
        # Pixels: the reduced backdrop with and without the parallax and landmark layers
        changed = page.evaluate('''() => {
            const read = () => Array.from(BACKDROP.ctx.getImageData(0, 0, BACKDROP.canvas.width, BACKDROP.canvas.height).data);
            const e = GRAPPLE_OVER_MOUNTAIN.encounters.find(e => e.id === GRAPPLE_OVER_MOUNTAIN.sections[0].encounters[0]);
            ninja.x = (e.start || e).x; ninja.y = (e.start || e).y; screen.trackGrappleOver(true);
            draw(); const on = read();
            visualEffects.background.parallaxEnabled = false; LANDMARKS.enabled = false;
            draw(); const off = read();
            visualEffects.background.parallaxEnabled = true; LANDMARKS.enabled = true;
            let n = 0;
            for (let i = 0; i < on.length; i += 4) if (Math.abs(on[i] - off[i]) + Math.abs(on[i + 1] - off[i + 1]) + Math.abs(on[i + 2] - off[i + 2]) > 24) n++;
            return {changed: n, total: on.length / 4};
        }''')
        self.assertGreater(changed['changed'] / changed['total'], 0.05, changed)
        page.screenshot(path=str(self.evidence.path('fast-backdrop-S01.jpg')), type='jpeg', quality=80)
        return dict(query='?backdrop=0.5', sections=rows, s01_backdrop_pixels_changed_by_parallax_and_landmarks=changed,
                    screenshot='fast-backdrop-S01.jpg')

    def test_04_classic_bad_pixels_unchanged(self):
        from collections import Counter
        rows = []
        for mode in ('classic', 'bad'):
            for ticks in (0, 90):
                frames = {}
                for label in ('before', 'final'):
                    captures = []
                    for _ in range(5):
                        page = self.open(label, mode=mode)
                        page.evaluate(SEED_SCRIPT % 1)
                        frame = page.evaluate(FRAME_538, [mode, ticks])
                        self.assertEqual(frame['mode'], mode)
                        captures.append(f"{frame['width']}x{frame['height']}:" +
                                        hashlib.sha256(frame['pixels'].encode('latin-1')).hexdigest())
                        page.close()
                    frames[label] = captures
                common = {k: Counter(v).most_common(1)[0][0] for k, v in frames.items()}
                # A rare odd title-screen capture occurs in either revision (TASK-539/541 notes): the
                # majority pixel hash of each revision is compared, the odd captures are kept
                majority = {k: Counter(v).most_common(1)[0][1] for k, v in frames.items()}
                row = dict(mode=mode, seed=1, ticks=ticks, before=frames['before'], after=frames['final'],
                           most_common=common, majority_counts=majority,
                           odd_captures={k: [h for h in v if h != common[k]] for k, v in frames.items()},
                           equal=common['before'] == common['final'] and min(majority.values()) >= 3)
                rows.append(row)
                self.assertTrue(row['equal'], row)
        self.evidence.write('classic-bad.json', dict(baseline_revision=self.revisions['before'], viewport=VIEWPORT_542, dpr=1,
            captures_per_revision=5, comparison='majority pixel hash per revision equal (each a majority of 5)', frames=rows, all_equal=all(r['equal'] for r in rows)))
        print(f'PASS classic/bad: {len(rows)} frames x 5 captures per revision; majority pixel hashes equal to {BASELINE_542}', flush=True)
