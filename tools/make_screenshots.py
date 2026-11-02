"""TASK-867: Grapple Over store screenshots from the single-mode release build.

Capture (--capture): the GamePix release zip (single mode: grapple_over only,
no analytics backend) is extracted to a temp dir and served over local http;
its SDK URL gets the fake GamePix SDK of tools/test_gamepix_backend.py and
every other external request is aborted (recorded as an error). Chromium,
device scale factor 2, two viewports: 1920x1080 (16:9) and 1440x1080 (4:3;
the game lays out its HUD for that aspect, so 4:3 slots are not crops). The
recorded replays run at 16:9; the page is then resized to 4:3 (same moment).

Each scene is a real game state reached with production physics():
- transfer scenes replay a recorded climb transfer (tools/probe_level_routes.js
  ROUTE_PROBE, document mouse events) and stop after a chosen physics tick
  (the last TRAIL ticks are drawn so the trail and particles are live), with
  the press still held;
- 'goback' continues from a high transfer state: the rope is dropped, the
  player is moved into open air beside the mountain (as tools/
  test_go_back_dialog.py) and falls with physics() until the game itself
  opens the 'Go back?' dialog (CLIMB_UI.goBackOpen());
- 'pause' continues from a transfer state and presses the real Escape key.
Then the game's own camera is snapped to the player (screen.trackGrappleOver),
the FPS counter is checked off, and for each language (setLanguage) one draw()
is made and the page is screenshotted (what the player sees: canvas + DOM).

Compose (default): every portal screenshot slot of PLAN is cut from those
frames: the whole frame of the slot's aspect, LANCZOS downscale (>= 2x, never
upscaled), a mild unsharp mask (as make_covers.py --grapple-over), PNG (JPEG
only if a byte cap needs it). Output: <release>/<portal>/screenshots/ and
<release>/screenshots.json.

    python3 tools/make_screenshots.py --capture --frames DIR [--scenes a,b] [--errors-dir DIR]
    python3 tools/make_screenshots.py --frames DIR [--release DIR]
"""
import argparse
import base64
import contextlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / 'artifacts' / 'release-grapple-over'
BUILD_ZIP = RELEASE / 'gamepix' / 'grapple-over-gamepix.zip'
GAMEPIX_SDK_URL = 'https://integration.gamepix.com/sdk/v3/gamepix.sdk.js'
MEASUREMENTS = ROOT / 'artifacts/levels/extended-mountain-measurements.json'
POLICY_KEYS = ('pumps', 'fraction', 'lastAimOffset', 'targetWhenInRange', 'targetFraction', 'drop', 'budget',
               'aimOffset', 'holdTicks')
DPR = 2
VIEWPORTS = {'16x9': (1920, 1080), '4x3': (1440, 1080)}
LANGS = ('en', 'ru')
TRAIL = 90
EARLY = 30
LATE = 60

# fixture/transfer/tick: the recorded transfer and the physics tick to stop after
SCENES = {
    'opening': {'label': 'opening climb (Lower Ridge): first hook from P1 onto P2 above the spawn',
                'fixture': None, 'source': 'P1', 'target': 'P2', 'tick': 860},
    'swing': {'label': 'grapple swing out of the Z2 approach (gauntlet)',
              'fixture': 'gauntlet', 'transfer': 5, 'tick': 577},
    'purple': {'label': 'purple no-grapple zone Z1 (gauntlet): hook onto the panel beside it',
               'fixture': 'gauntlet', 'transfer': 2, 'tick': 810},
    'spire': {'label': 'Sky Spire (about 115k up): hanging on the rope under a T1 panel',
              'fixture': 'spire', 'transfer': 4, 'tick': 1056},
    'summit': {'label': 'high view near the summit (Sky Spire top)',
               'fixture': 'spire', 'transfer': 26, 'tick': 738},
    'goback': {'label': "'Go back?' dialog after a long fall",
               'after': 'summit', 'kind': 'goback'},
    'pause': {'label': 'pause menu (Escape) during a climb',
              'after': 'swing', 'kind': 'pause'},
}

# portal -> slots: (slot name, width, height, viewport, scenes, langs, formats, max_bytes)
GAMEPLAY = ('opening', 'swing', 'purple', 'spire', 'summit')
ALL = GAMEPLAY + ('goback', 'pause')
# 4:3 frames are only used by the Y8 standard slot (gameplay only)
VIEWPORT_SCENES = {'4x3': GAMEPLAY}
PLAN = {
    # itch: 'Screenshots can be any size, it's recommended to upload between 3 and 5'; English store page
    'itch': [('screenshot-1920x1080', 1920, 1080, '16x9', GAMEPLAY, ('en',), ('png',), None)],
    # GamePix: localized portal; old kit had gameplay + pause at both sizes
    'gamepix': [('screenshot-1280x720', 1280, 720, '16x9', ALL, LANGS, ('png',), None),
                ('screenshot-1920x1080', 1920, 1080, '16x9', ALL, LANGS, ('png',), None)],
    # Y8: up to 6 per slot, exact size, 'actual gameplay, no menus/title screens'; localized portal
    'y8': [('standard-screenshot-760x570', 760, 570, '4x3', GAMEPLAY, LANGS, ('png', 'jpg'), 2097152),
           ('widescreen-screenshot-1280x720', 1280, 720, '16x9', GAMEPLAY, LANGS, ('png', 'jpg'), 5242880)],
}

SETUP_JS = '''() => {
    window.requestAnimationFrame = () => 0
    cancelAnimationFrame(game)
    floors[0].doubleOfferShown = true
    window.__shotFx = visualEffects; window.__shotMark = ROLE_DETAIL.markContact
}'''

AFTER_PROBE_JS = '''() => { visualEffects = window.__shotFx; ROLE_DETAIL.markContact = window.__shotMark }'''

# Stops after tick `stop` if the player hangs on the rope there; else on the
# first tick in [stop - early, stop + late] on which the player hangs on a body
# other than the source (pointer aims are rounded to client px,
# so the catch tick moves a little with the viewport), else after stop + late.
REPLAY_JS = '''([o, stop, trail, early, late]) => {
    const real = physics
    let n = 0
    window.physics = function() {
        real()
        n++
        TUTORIAL_HINT.advance(physicsStepMs)   // as the frame loop does per simulated step
        if (n > stop - trail - early) draw()
        const id = grapnel.grappled ? (grapnel.pos.at(-1)?.[2]?.id || '') : ''
        if (n === stop + late || (n === stop && id) || (n >= stop - early && id && !id.startsWith(o.source + '-')))
            throw new Error('SHOT_STOP')
    }
    let result = null
    try { result = ROUTE_PROBE.run(o) } catch (e) { if (e.message !== 'SHOT_STOP') throw e } finally { window.physics = real }
    return {tick: n, hit: result && result.hit, ticks: result && result.ticks}
}'''

# Rope dropped, player moved into open air beside the mountain at its height
# (tools/test_go_back_dialog.py TO_OPEN_AIR), then production physics until
# the game pauses on the dialog; the last `trail` ticks are drawn.
GOBACK_JS = '''(trail) => {
    const w = floors[0], minX = Math.min(...w.elements.flatMap(e => e.getPoints().map(p => p.x)))
    const press = (type, p) => {
        const q = canvasCoordsToViewportCoords({x: (p.x + screen.x) * scale[version], y: (p.y + screen.y) * scale[version]})
        document.dispatchEvent(new MouseEvent(type, {clientX: q.x, clientY: q.y, bubbles: true, button: 0}))
    }
    press('mouseup', ninja)
    // Climb catches land on panel tops; a go-back checkpoint needs an anchor the player can hang under
    // (recordClimbCheckpoint). As tools/test_go_back.py CANDIDATES/CATCH: the static bodies nearest the
    // player's height with open air under its lowest vertex; the player 400 under it, a real press at it.
    let caught = null, tried = []
    if (!w.climbCheckpoint) {
        const moverIds = new Set(w.level.movers.map(m => m.element))
        const blocked = (x, y) => w.elements.some(e => pointInPolygon(e.getPoints(), x, y))
        const list = []
        for (const e of w.elements) {
            if (e.grapplable === false || moverIds.has(e.id)) continue
            const pts = e.getPoints(), ys = pts.map(p => p.y)
            const {x, y} = pts[ys.indexOf(Math.max(...ys))]
            if ([0, 100, 200, 300, 400].some(d => blocked(x + 1e-3, y + 20 + d))) continue
            list.push({id: e.id, x, y})
        }
        const y0 = ninja.y
        list.sort((a, b) => Math.abs(a.y - y0) - Math.abs(b.y - y0))
        for (const c of list.slice(0, 12)) {
            Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null,
                traveled: 0, speedX: 0, speedY: 0})
            ninja.x = c.x + 1e-3; ninja.y = c.y + 400; ninja.speedX = ninja.speedY = 0
            screen.trackGrappleOver(true)
            press('mousedown', {x: c.x, y: c.y})
            for (let i = 0; i < 400 && grapnel.throwed && !grapnel.grappled && !grapnel.isParked(); i++) {
                grapnel.move(); grapnel.collision()
            }
            tried.push({...c, grappled: grapnel.grappled, anchor: grapnel.pos[0] ? grapnel.pos[0].slice(0, 2) : null})
            press('mouseup', ninja)
            if (w.climbCheckpoint) { caught = c; break }
        }
    }
    const checkpoint = w.climbCheckpoint
    if (!checkpoint) return {error: 'no checkpoint', tried, mode: w.grapnelMode, pressHeld, gameplayPressOwned}
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null, aim: null, clip: null,
        traveled: 0, speedX: 0, speedY: 0})
    ninja.x = minX - 1600; ninja.speedX = 0; ninja.speedY = 0
    ninja.track.pos = []
    ninja.track.addPos(ninja.x, ninja.y, true)
    LONG_FALL.restartTracking()
    const ys = []
    let n = 0
    for (; n < 6000 && !menu.gamePaused; n++) {
        physics(); TUTORIAL_HINT.advance(physicsStepMs); ys.push(ninja.y)
        if (n % 2 === 0) { screen.trackGrappleOver(true); draw() }
    }
    return {ticks: n, open: CLIMB_UI.goBackOpen(), displacement: LONG_FALL.tracking().displacement,
            checkpoint, caught, ninja: [ninja.x, ninja.y]}
}'''

FACTS_JS = '''() => ({version, modes: typeof BUILD_CONFIG !== 'undefined' ? BUILD_CONFIG.modes || null : null,
    canvas: [canvas.width, canvas.height], logical: [width, height], dpr: devicePixelRatio,
    backdrop: {scale: BACKDROP.scale, resolution: BACKDROP.resolution, adaptive: BACKDROP.adaptive},
    fps: fpsCounter.enabled, language: I18N.language, paused: menu.gamePaused, goBackOpen: CLIMB_UI.goBackOpen(),
    hint: TUTORIAL_HINT.visible, grappled: grapnel.grappled, ninja: [ninja.x, ninja.y],
    height: Math.round(floors[0].climbStats.currentHeight), section: CLIMB_UI.currentSection().id,
    layoutId: floors[0].level.layoutId})'''


def transfer_options(scene, ids):
    if scene['fixture'] is None:
        options = {'source': ids[scene['source']], 'target': ids[scene['target']]}
        options.update(scene.get('options', {}))
        return options, {'source': scene['source'], 'target': scene['target'], 'fixture': None}
    data = json.loads((ROOT / f'tools/fixtures/{scene["fixture"]}-climb-inputs.json').read_text())
    t = data['transfers'][scene['transfer']]
    options = {k: t[k] for k in POLICY_KEYS if k in t}
    options.update(source=ids[t['source']], target=ids[t['target']])
    return options, {'source': t['source'], 'target': t['target'], 'fixture': scene['fixture'] + '-climb-inputs.json',
                     'transfer': scene['transfer']}


def serve_build(stack, zip_path):
    from browser_test_support import start_browser_test
    from test_gamepix_backend import FAKE_SDK
    tmp = Path(tempfile.mkdtemp(prefix='grapple-shots-'))
    stack.callback(shutil.rmtree, tmp, True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    url, browser = start_browser_test(tmp, stack.callback)
    return url, browser, FAKE_SDK


def capture(frames_dir, zip_path=BUILD_ZIP, scenes=None, viewports=None, explore=None):
    """Write frames_dir/<viewport>/<scene>-<lang>.png and frames.json; return error lines."""
    measurements = json.loads(MEASUREMENTS.read_text())
    ids = {f['semanticId']: f['id'] for f in measurements['fragments'] if f.get('semanticId')}
    frames_dir.mkdir(parents=True, exist_ok=True)
    meta_path = frames_dir / 'frames.json'
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update(build_zip=str(zip_path.relative_to(ROOT)) if zip_path.is_relative_to(ROOT) else str(zip_path),
                dpr=DPR, method=__doc__.split('\n\n')[1].replace('\n', ' '))
    meta.setdefault('frames', {})
    errors, blocked = [], []
    wanted = [s for s in SCENES if not scenes or s in scenes]
    with contextlib.ExitStack() as stack:
        url, browser, fake_sdk = serve_build(stack, zip_path)

        def route(r):
            if r.request.url == GAMEPIX_SDK_URL:
                return r.fulfill(content_type='application/javascript', body=fake_sdk)
            blocked.append(r.request.url)
            return r.abort()

        # The open-loop replays are recorded at 16:9: pointer aims are rounded to client px, so another
        # viewport diverges. Each state is reached once at 16:9; the page is then resized (the game re-lays
        # out its canvas and HUD for 4:3 as on any window resize) so both aspects show the same moment.
        first_vp = next(iter(VIEWPORTS))
        for name in wanted:
            vps = [vp for vp in VIEWPORTS if name in VIEWPORT_SCENES.get(vp, SCENES) and (not viewports or vp in viewports)]
            if not vps:
                continue
            scene = SCENES[name]
            vw, vh = VIEWPORTS[first_vp]
            context = browser.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=DPR, locale='en-US')
            context.route('https://**/*', route)
            page = context.new_page()
            page.set_default_timeout(0)
            page.on('console', lambda m, n=name: m.type == 'error' and errors.append(f'[{n}] console: {m.text}'))
            page.on('pageerror', lambda e, n=name: errors.append(f'[{n}] page: {e}'))
            page.goto(url + 'index.html')
            page.wait_for_function('() => typeof PLATFORM !== "undefined" && PLATFORM.environment !== "pending"'
                                   ' && typeof bootComplete !== "undefined" && bootComplete && runInProgress'
                                   ' && document.getElementById("loading").hidden')
            if page.evaluate('version') != 'grapple_over':
                raise SystemExit(f'{name}: boot mode is not grapple_over')
            page.evaluate(SETUP_JS)
            page.add_script_tag(content=(ROOT / 'tools/probe_level_routes.js').read_text())
            page.evaluate(AFTER_PROBE_JS)
            base = SCENES[scene['after']] if 'after' in scene else scene
            options, source = transfer_options(base, ids)
            if explore:
                (frames_dir / first_vp).mkdir(exist_ok=True)
                rows = page.evaluate('''([o, ticks]) => { const real = physics, out = []; let n = 0
                    window.physics = function() { real(); n++; TUTORIAL_HINT.advance(physicsStepMs); if (ticks.includes(n)) {
                        screen.trackGrappleOver(true); draw()
                        out.push({tick: n, grappled: grapnel.grappled, ninja: [ninja.x, ninja.y],
                                  h: Math.round(floors[0].climbStats.currentHeight), url: canvas.toDataURL('image/jpeg', 0.7)}) } }
                    let r; try { r = ROUTE_PROBE.run(o) } finally { window.physics = real }
                    return {rows: out, hit: r.hit, ticks: r.ticks} }''', [options, explore])
                for row in rows['rows']:
                    (frames_dir / first_vp / f'{name}-t{row["tick"]}.jpg').write_bytes(base64.b64decode(row.pop('url').split(',', 1)[1]))
                print(name, json.dumps({'hit': rows['hit'], 'ticks': rows['ticks'], 'rows': rows['rows']}), flush=True)
                context.close()
                continue
            replay = page.evaluate(REPLAY_JS, [options, base['tick'], TRAIL, EARLY, LATE])
            if not base['tick'] - EARLY <= replay['tick'] <= base['tick'] + LATE or replay['hit']:
                raise SystemExit(f'{name}: replay stopped at {replay} before tick {base["tick"]}')
            extra = {}
            if scene.get('kind') == 'goback':
                extra = page.evaluate(GOBACK_JS, TRAIL)
                if not extra.get('open'):
                    raise SystemExit(f'{name}: the go-back dialog did not open: {extra}')
            elif scene.get('kind') == 'pause':
                page.keyboard.press('Escape')
                if not page.evaluate('menu.gamePaused'):
                    raise SystemExit(f'{name}: Escape did not pause')
            elif not page.evaluate('grapnel.grappled'):
                raise SystemExit(f'{name}: not grappled: {replay}')
            for vp in vps:
                vw, vh = VIEWPORTS[vp]
                (frames_dir / vp).mkdir(exist_ok=True)
                if page.viewport_size != {'width': vw, 'height': vh}:
                    page.set_viewport_size({'width': vw, 'height': vh})
                    page.wait_for_function('([w, h]) => canvas.width === w && canvas.height === h', arg=[vw * DPR, vh * DPR])
                page.evaluate('() => screen.trackGrappleOver(true)')
                for lang in LANGS:
                    # setLanguage relabels and, under the pause/dialog screens, redraws them (redrawOverlays)
                    page.evaluate('l => { setLanguage(l); if (menu.gamePaused) redrawOverlays(); else draw() }', lang)
                    facts = page.evaluate(FACTS_JS)
                    path = frames_dir / vp / f'{name}-{lang}.png'
                    page.screenshot(path=str(path), type='png')
                    meta['frames'][f'{vp}/{name}-{lang}'] = {
                        'file': f'{vp}/{path.name}', 'viewport': [vw, vh], 'scene': name, 'label': scene['label'],
                        'lang': lang, 'replay': {**source, 'stop_tick': replay['tick'], 'hit': replay['hit'],
                                                 'after': scene.get('after'), 'replayed_at': first_vp},
                        'extra': extra, 'facts': facts}
                    print(f'{vp}/{path.name}: {facts}', flush=True)
            context.close()
    meta['blocked_requests'] = blocked
    meta_path.write_text(json.dumps(meta, indent=1))
    return errors + [f'blocked: {u}' for u in blocked]


def compose(frames_dir, release_dir=RELEASE):
    from PIL import Image, ImageFilter
    meta = json.loads((frames_dir / 'frames.json').read_text())['frames']
    report = []
    for portal, slots in PLAN.items():
        out = release_dir / portal / 'screenshots'
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        for slot, w, h, vp, scenes, langs, formats, cap in slots:
            for i, scene in enumerate(scenes, 1):
                for lang in langs:
                    key = f'{vp}/{scene}-{lang}'
                    frame = Image.open(frames_dir / meta[key]['file']).convert('RGB')
                    fw, fh = frame.size
                    if abs(fw / fh - w / h) > 0.002:
                        raise SystemExit(f'{key}: frame {fw}x{fh} is not the aspect of {w}x{h}')
                    if fw < 2 * w:
                        raise SystemExit(f'{key}: frame {fw}x{fh} under 2x {w}x{h}')
                    image = frame.resize((w, h), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.0, 100, 2))
                    stem = f'{slot}-{i:02d}-{scene}-{lang}'
                    path = out / f'{stem}.png'
                    image.save(path, optimize=True)
                    fmt = 'png'
                    if cap is not None and path.stat().st_size > cap * 0.95:
                        if 'jpg' not in formats:
                            raise SystemExit(f'{path}: over the byte cap and JPEG not allowed')
                        path.unlink()
                        path, fmt = out / f'{stem}.jpg', 'jpg'
                        for quality in (95, 92, 90, 85):
                            image.save(path, quality=quality, subsampling=0)   # optimize=True overflows PIL's JPEG buffer on busy frames
                            if path.stat().st_size <= cap * 0.95:
                                break
                    report.append({'portal': portal, 'slot': slot, 'index': i, 'scene': scene, 'lang': lang,
                                   'label': meta[key]['label'], 'file': str(path.relative_to(ROOT)), 'width': w,
                                   'height': h, 'format': fmt, 'bytes': path.stat().st_size, 'max_bytes': cap,
                                   'source_frame': meta[key]['file'], 'source_size': [fw, fh],
                                   'downscale': round(fw / w, 3)})
                    print(f'{portal}/{path.name}: {w}x{h} from {key} ({fw / w:.2f}x) {path.stat().st_size} B', flush=True)
    (release_dir / 'screenshots.json').write_text(json.dumps(report, indent=1))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--frames', required=True, help='frame dir (capture output, compose input)')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--zip', default=str(BUILD_ZIP))
    parser.add_argument('--scenes', help='comma list of SCENES (default: all)')
    parser.add_argument('--viewports', help='comma list of VIEWPORTS (default: all)')
    parser.add_argument('--explore', help='comma list of ticks: dump replay frames instead of capturing')
    parser.add_argument('--release', default=str(RELEASE))
    parser.add_argument('--errors-dir')
    args = parser.parse_args()
    frames = Path(args.frames)
    if args.capture or args.explore:
        errors = capture(frames, Path(args.zip).resolve(), set(args.scenes.split(',')) if args.scenes else None,
                         set(args.viewports.split(',')) if args.viewports else None,
                         [int(t) for t in args.explore.split(',')] if args.explore else None)
        (Path(args.errors_dir) if args.errors_dir else frames).joinpath('browser-errors.log').write_text(
            ''.join(e + '\n' for e in errors))
        return 1 if errors else 0
    compose(frames, Path(args.release))
    return 0


if __name__ == '__main__':
    sys.exit(main())
