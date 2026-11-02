"""Store cover images from real gameplay (TASK-085, sizes extended in TASK-097, TASK-131).

Two steps:

  python3 tools/make_covers.py --capture --seeds artifacts/TASK-084/seed-search.json \
      --frames artifacts/TASK-085/source-frames
  python3 tools/make_covers.py --out artifacts/TASK-097/assets \
      --frames artifacts/TASK-085/source-frames

--capture replays the best TASK-084 autopilot seed of each mode tick by tick
(physics + draw, no requestAnimationFrame) up to the chosen game time and
saves the canvas: once at 1920x1080 (DPR 1) as the reference landscape frame
and once at 2880x1620 (DPR 1.5). All covers are cut from the 2880x1620
frame inside the playfield band (bad mode draws flat dark bands above and
below it) and downscaled, so the landscape is supersampled too. HUD
and FPS layers are skipped so the only text is the composed title.
Frame metadata (mode, seed, tick, ninja position) goes to source-frames.json.

The compose step (default --frames is <out>/../source-frames) writes one
cover per size in COVER_SIZES: 16:9 (1920x1080, 1280x720), 4:3 (800x600,
1024x768), 1:1 (1024x1024, 800x800, 512x512, 256x256), 2:3 (800x1200) and
9:16 (1080x1920, a portrait store cover), so
a portal's thumbnail slots can be matched without knowing their exact sizes
up front. --sizes WxH,... composes only those sizes (they must be in
COVER_SIZES), e.g. --sizes 256x256,1024x1024,1024x768.
"""
import argparse
import base64
import contextlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
AUTOPILOT = Path(__file__).with_name('autopilot.js')
VIEWPORT = {'width': 1920, 'height': 1080}
TITLE = 'Grapnel Ninja'
# Same colour as STYLE.colors.ui.title (the in-game menu title)
TITLE_RGB = (0x8f, 0xfc, 0xff)

# Inner playfield band (fractions of the canvas height, bad mode) between the
# neon floor lines; crops stay inside it so no cover edge is the flat dark band.
PLAYFIELD = (0.099, 0.901)

# 'crop' (2880x1620) is the frame all covers are cut from; 'landscape' is the
# plain 1920x1080 capture of the same moment, kept as a reference frame.
SHOTS = {
    'landscape': {'mode': 'bad', 'tick': 690},
    'crop': {'mode': 'bad', 'tick': 690},
}

# (width, height) -> horizontal shift of the crop centre past the ninja
COVER_SIZES = {
    (1920, 1080): 0.1,
    (1360, 850): 0.1,
    (1280, 720): 0.1,
    (800, 600): 0.08,
    (800, 1200): 0.05,
    (1080, 1920): 0.05,
    (800, 800): 0.07,
    (512, 512): 0.07,
    (256, 256): 0.07,
    (1024, 1024): 0.07,
    (1024, 768): 0.08,
}

CAPTURE_JS = '''async ([mode, seed, actions, targetTick]) => {
    __ap.install(seed)
    __ap.replay(actions)
    startGame(mode)
    cancelAnimationFrame(game)
    // no HUD/score/pause icon and no FPS counter on a cover
    window.drawUILayer = function() {}
    window.drawFpsCounterLayer = function() {}
    while (__ap.tick < targetTick && __ap.deathTick === null)
    {
        physics()
        draw()
    }
    const s = scale[version]
    return {tick: __ap.tick, deathTick: __ap.deathTick, score: scoreText.count[version],
        canvas: [canvas.width, canvas.height],
        ninja: [(ninja.x + screen.x) * s / width, (ninja.y + screen.y) * s / height],
        url: canvas.toDataURL('image/png')}
}'''


def capture(seed_report, frames_dir, shots):
    from browser_test_support import start_browser_test, wait_for_boot_run
    report = json.loads(Path(seed_report).read_text())
    frames_dir.mkdir(parents=True, exist_ok=True)
    meta = {'seed_report': str(seed_report), 'frames': {}}
    errors = {'console': [], 'page': []}
    with contextlib.ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        for name, shot in shots.items():
            entry = report['modes'][shot['mode']]
            dpr = 1 if name == 'landscape' else 1.5
            label = f'{name}:{shot["mode"]}:{entry["best_seed"]}@{shot["tick"]}'
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=dpr)
            context.add_init_script(path=str(AUTOPILOT))
            page = context.new_page()
            page.set_default_timeout(0)
            page.on('console', lambda m, label=label: m.type == 'error' and
                    errors['console'].append(f'[{label}] {m.text}'))
            page.on('pageerror', lambda e, label=label: errors['page'].append(f'[{label}] {e}'))
            page.goto(url + 'index.html')
            wait_for_boot_run(page)
            facts = page.evaluate(CAPTURE_JS, [shot['mode'], entry['best_seed'],
                                               entry['best_actions'], shot['tick']])
            context.close()
            if facts['deathTick'] is not None:
                raise SystemExit(f'{label}: ninja died at tick {facts["deathTick"]}')
            path = frames_dir / f'{name}-{shot["mode"]}-seed{entry["best_seed"]}-t{shot["tick"]}.png'
            path.write_bytes(base64.b64decode(facts.pop('url').split(',', 1)[1]))
            meta['frames'][name] = {'file': path.name, 'mode': shot['mode'], 'seed': entry['best_seed'],
                                    'tick': facts['tick'], 'time_s': facts['tick'] / 60,
                                    'dpr': dpr, **facts}
            print(f'{label}: {path.name} {facts["canvas"]} ninja {facts["ninja"]}', flush=True)
    (frames_dir / 'source-frames.json').write_text(json.dumps(meta, indent=1))
    return errors


def find_font(size):
    from PIL import ImageFont
    for name in ('DejaVuSansMono-Bold.ttf', 'LiberationMono-Bold.ttf', 'DejaVuSans-Bold.ttf'):
        for base in ('/usr/share/fonts/truetype/dejavu', '/usr/share/fonts/truetype/liberation', ''):
            with contextlib.suppress(OSError):
                return ImageFont.truetype(str(Path(base) / name) if base else name, size)
    return ImageFont.load_default(size)


def neon_title(image, text, center_x, center_y, max_width):
    """Draws the neon title: wide soft glow, tight glow, dark outline, bright core."""
    from PIL import Image, ImageDraw, ImageFilter
    size = int(image.height * 0.2)
    while True:
        font = find_font(size)
        left, top, right, bottom = font.getbbox(text)
        if right - left <= max_width or size <= 10:
            break
        size -= 2
    w, h = right - left, bottom - top
    x, y = center_x - w / 2 - left, center_y - h / 2 - top
    stroke = max(2, size // 18)

    def layer(fill, width=0):
        im = Image.new('RGBA', image.size, (0, 0, 0, 0))
        ImageDraw.Draw(im).text((x, y), text, font=font, fill=fill,
                                stroke_width=width, stroke_fill=fill)
        return im

    # darken behind the title so it reads on bright frames
    shade = layer((0, 0, 0, 170), stroke * 3).filter(ImageFilter.GaussianBlur(size / 4))
    out = Image.alpha_composite(image.convert('RGBA'), shade)
    for radius, alpha in ((size / 3, 200), (size / 9, 255)):
        glow = layer(TITLE_RGB + (alpha,), stroke * 2).filter(ImageFilter.GaussianBlur(radius))
        out = Image.alpha_composite(out, glow)
    out = Image.alpha_composite(out, layer((8, 20, 40, 255), stroke))
    out = Image.alpha_composite(out, layer((235, 255, 255, 255)))
    return out.convert('RGB')


def crop_around(image, center_x, aspect):
    """Largest crop of the given aspect (w/h) inside the playfield band,
    centred horizontally on center_x (fraction of the width)."""
    iw, ih = image.size
    top, bottom = round(PLAYFIELD[0] * ih), round(PLAYFIELD[1] * ih)
    ch = bottom - top
    cw = round(ch * aspect)
    cx = min(max(center_x * iw, cw / 2), iw - cw / 2)
    left = round(cx - cw / 2)
    return image.crop((left, top, left + cw, bottom))


def compose(frames_dir, out, sizes=None):
    from PIL import Image
    meta = json.loads((frames_dir / 'source-frames.json').read_text())['frames']
    out.mkdir(parents=True, exist_ok=True)
    source = Image.open(frames_dir / meta['crop']['file']).convert('RGB')
    ninja_x = meta['crop']['ninja'][0]
    results = {}
    # All come from the same 2880x1620 frame so the style matches;
    # the shift keeps the ninja left of centre with the obstacles ahead of it.
    for (w, h), shift in COVER_SIZES.items():
        if sizes is not None and (w, h) not in sizes:
            continue
        cover = crop_around(source, ninja_x + shift, w / h).resize((w, h), Image.LANCZOS)
        title_y = 0.13 if h > w else 0.15
        cover = neon_title(cover, TITLE, w / 2, h * title_y, w * (0.62 if w > h else 0.88))
        results[f'cover-{w}x{h}.png'] = cover

    for name, image in results.items():
        image.save(out / name, optimize=True)
        print(f'{name}: {image.size} {(out / name).stat().st_size} bytes', flush=True)


# ---------------------------------------------------------------- Grapple Over

GO_TITLE = ('Grapple', 'Over')
GO_FILL = (0xea, 0xfe, 0xff)   # STYLE.colors.ui.title
GO_GLOW = (0x30, 0xd5, 0xc8)   # STYLE.colors.ui.titleGlow
GO_POLICY_KEYS = ('pumps', 'fraction', 'lastAimOffset', 'targetWhenInRange', 'targetFraction', 'drop', 'budget')
GO_MEASUREMENTS = ROOT / 'artifacts/levels/extended-mountain-measurements.json'

# Recorded climb transfer, physics tick to stop after, camera centre offset
# from the rope midpoint (world units) and camera world width.
GO_SHOTS = {
    # swing on a rope out of the Z2 no-grapple (purple) zone of the gauntlet
    'swing': {'fixture': 'gauntlet', 'transfer': 5, 'tick': 577, 'offset': (-600, 260), 'world': 3000, 'dpr': 2},
    'swing-tall': {'fixture': 'gauntlet', 'transfer': 5, 'tick': 577, 'offset': (-150, 420), 'world': 4200, 'dpr': 4},
    # Sky Spire: tall purple zones Y2 and the T1 safe space, player hooked to SP-T1-G2
    'spire': {'fixture': 'spire', 'transfer': 4, 'tick': 1056, 'offset': (-3300, -400), 'world': 12000, 'dpr': 2},
    # high view of the mountain: the gauntlet zig-zag of purple zones
    'mountain': {'fixture': 'gauntlet', 'transfer': 10, 'tick': 548, 'offset': (-4000, -2500), 'world': 26000, 'dpr': 2},
}

GO_CAPTURE_JS = '''([o, stop]) => {
    const real = physics
    let n = 0
    window.physics = function() {
        real()
        n++
        if (n > stop - 90) draw()
        if (n === stop) throw new Error('COVER_STOP')
    }
    try { ROUTE_PROBE.run(o) } catch (e) { if (e.message !== 'COVER_STOP') throw e } finally { window.physics = real }
    return {tick: n, ninja: [ninja.x, ninja.y], speed: [ninja.speedX, ninja.speedY], grappled: grapnel.grappled,
            rope: grapnel.pos.map(q => [q[0], q[1], q[2].id || null]), layoutId: floors[0].level.layoutId}
}'''

GO_DRAW_JS = '''([cx, cy, ww]) => {
    drawUILayer = () => {}
    drawTutorialHintLayer = () => {}
    drawFpsCounterLayer = () => {}
    const k = canvas.width / ww
    scale[version] = k * width / canvas.width
    screen.x = -(cx - ww / 2)
    screen.y = -(cy - ww * height / width / 2)
    ctx.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
    draw()
    return {canvas: [canvas.width, canvas.height], k, left: cx - ww / 2, top: cy - ww * height / width / 2,
            url: canvas.toDataURL('image/png')}
}'''


def go_capture(frames_dir, shots=None):
    from browser_test_support import start_browser_test, wait_for_boot_run
    measurements = json.loads(GO_MEASUREMENTS.read_text())
    ids = {f['semanticId']: f['id'] for f in measurements['fragments'] if f.get('semanticId')}
    frames_dir.mkdir(parents=True, exist_ok=True)
    meta = {'method': 'real index.html (Grapple Over boot); tools/probe_level_routes.js ROUTE_PROBE replay of a '
                      'recorded climb transfer (document mouse events + production physics()), stopped after tick; '
                      'HUD/hint/FPS layers skipped; one draw() with the shot camera',
            'measurements': str(GO_MEASUREMENTS.relative_to(ROOT)), 'frames': {}}
    previous = frames_dir / 'source-frames.json'
    if shots and previous.exists():
        # a partial recapture keeps the other frames
        meta['frames'] = json.loads(previous.read_text())['frames']
    errors = []
    with contextlib.ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        for name, shot in GO_SHOTS.items():
            if shots and name not in shots:
                continue
            transfer = json.loads((ROOT / f'tools/fixtures/{shot["fixture"]}-climb-inputs.json').read_text())
            t = transfer['transfers'][shot['transfer']]
            options = {k: t[k] for k in GO_POLICY_KEYS if k in t}
            options.update(source=ids[t['source']], target=ids[t['target']])
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=shot['dpr'])
            page = context.new_page()
            page.set_default_timeout(0)
            page.on('console', lambda m, n=name: m.type == 'error' and errors.append(f'[{n}] console: {m.text}'))
            page.on('pageerror', lambda e, n=name: errors.append(f'[{n}] page: {e}'))
            page.goto(url + 'index.html')
            wait_for_boot_run(page)
            if page.evaluate('version') != 'grapple_over':
                raise SystemExit(f'{name}: boot mode is not grapple_over')
            # ROUTE_PROBE drops visual effects and contact marks for speed; keep them for a cover
            page.evaluate('window.__coverFx = visualEffects; window.__coverMark = ROLE_DETAIL.markContact')
            page.add_script_tag(path=str(ROOT / 'tools/probe_level_routes.js'))
            page.evaluate('visualEffects = window.__coverFx; ROLE_DETAIL.markContact = window.__coverMark')
            facts = page.evaluate(GO_CAPTURE_JS, [options, shot['tick']])
            if facts['tick'] != shot['tick'] or not facts['grappled']:
                raise SystemExit(f'{name}: replay did not reach a grappled tick {shot["tick"]}: {facts}')
            anchor = facts['rope'][-1]
            cx = (anchor[0] + facts['ninja'][0]) / 2 + shot['offset'][0]
            cy = (anchor[1] + facts['ninja'][1]) / 2 + shot['offset'][1]
            view = page.evaluate(GO_DRAW_JS, [cx, cy, shot['world']])
            context.close()
            path = frames_dir / f'{name}.png'
            path.write_bytes(base64.b64decode(view.pop('url').split(',', 1)[1]))
            px = lambda p: [(p[0] - view['left']) * view['k'], (p[1] - view['top']) * view['k']]
            meta['frames'][name] = {
                'file': path.name, 'size': view['canvas'], 'dpr': shot['dpr'], 'fixture': shot['fixture'] + '-climb-inputs.json',
                'transfer': shot['transfer'], 'source': t['source'], 'target': t['target'], 'tick': facts['tick'],
                'layoutId': facts['layoutId'], 'camera': {'center': [cx, cy], 'worldWidth': shot['world'], 'pxPerUnit': view['k']},
                'ninja': facts['ninja'], 'speed': facts['speed'], 'rope': facts['rope'],
                'ninjaPx': px(facts['ninja']), 'anchorPx': px(anchor)}
            print(f'{name}: {path.name} {view["canvas"]} tick {facts["tick"]} ninja px {meta["frames"][name]["ninjaPx"]}', flush=True)
    (frames_dir / 'source-frames.json').write_text(json.dumps(meta, indent=1))
    return errors


def go_font(size):
    from PIL import ImageFont
    return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', size)


def go_title(image, lines, center, max_w, max_h):
    """The game's title neon (Text.strokeNeonTube: wide/inner halo, tube, bright fill)
    with an extra soft bloom and speed streaks, lines centred on center."""
    from PIL import Image, ImageDraw, ImageFilter
    size = max(8, int(max_h / len(lines) / 1.05))
    while True:
        font = go_font(size)
        boxes = [font.getbbox(line) for line in lines]
        lw = max(b[2] - b[0] for b in boxes)
        line_h = size * 1.02
        if (lw <= max_w and line_h * len(lines) <= max_h) or size <= 8:
            break
        size -= 1
    total_h = line_h * len(lines)
    x0, y0 = center
    # each line is centred; the second line is shifted right a little like the reference's stagger
    positions = []
    for i, (line, box) in enumerate(zip(lines, boxes)):
        w = box[2] - box[0]
        stagger = (i - (len(lines) - 1) / 2) * size * 0.2
        positions.append((x0 - w / 2 - box[0] + stagger, y0 - total_h / 2 + i * line_h + (line_h - size) / 2 - box[1] * 0.35))

    def layer(fill, stroke=0, alpha_scale=1.0):
        im = Image.new('RGBA', image.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for line, pos in zip(lines, positions):
            d.text(pos, line, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
        return im

    out = image.convert('RGBA')
    # darken behind the title so it reads on any frame
    out = Image.alpha_composite(out, layer((4, 6, 24, 150), int(size * 0.28)).filter(ImageFilter.GaussianBlur(size * 0.3)))
    # speed streaks above and below the block
    streaks = Image.new('RGBA', image.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(streaks)
    span = max(max_w, lw) * 0.55
    for sx, sy, ln, wd in ((-0.15, -0.62, 0.55, 0.05), (0.2, -0.56, 0.35, 0.035), (0.05, 0.6, 0.6, 0.05), (-0.3, 0.55, 0.3, 0.035)):
        cx, cy = x0 + sx * span, y0 + sy * total_h
        half = ln * span / 2
        t = max(1.5, wd * size)
        d.polygon([(cx - half, cy + t * 0.2), (cx + half, cy - t * 0.6), (cx + half * 0.9, cy + t * 0.4)], fill=GO_GLOW + (230,))
    out = Image.alpha_composite(out, streaks.filter(ImageFilter.GaussianBlur(max(1, size * 0.06))))
    out = Image.alpha_composite(out, streaks.filter(ImageFilter.GaussianBlur(max(0.6, size * 0.012))))
    # bloom, then the game's halos (0.16 / 0.07 / 0.03 of the font size), then the fill
    out = Image.alpha_composite(out, layer(GO_GLOW + (200,), int(size * 0.1)).filter(ImageFilter.GaussianBlur(size * 0.22)))
    out = Image.alpha_composite(out, layer(GO_GLOW + (110,), int(size * 0.08)).filter(ImageFilter.GaussianBlur(size * 0.04)))
    out = Image.alpha_composite(out, layer(GO_GLOW + (170,), int(size * 0.035)).filter(ImageFilter.GaussianBlur(size * 0.012)))
    out = Image.alpha_composite(out, layer(GO_GLOW + (255,), max(1, int(size * 0.015))))
    out = Image.alpha_composite(out, layer(GO_FILL + (255,)))
    return out.convert('RGB'), size


# Which frame each image is cut from, where its crop centre lies (fractions of
# the frame) and where the title goes (centre and box as fractions of the image).
def go_plan(portal, entry, index):
    w, h = entry['width'], entry['height']
    name = entry['name']
    aspect = w / h
    shot_kind = 'screenshot' if 'screenshot' in name else ('icon' if name.startswith('icon') else 'cover')
    if shot_kind == 'screenshot':
        frame = ('swing', 'spire', 'mountain')[index % 3]
        return {'frame': frame, 'title': None}
    # The swing frames keep the rope, panel and player in the upper part; the title sits in the lower part
    if aspect < 0.8:
        return {'frame': 'swing-tall', 'title': {'center': (0.5, 0.74), 'box': (0.9, 0.26)}}
    if aspect < 1.1:
        return {'frame': 'swing', 'title': {'center': (0.45, 0.74) if shot_kind == 'icon' else (0.41, 0.75),
                                            'box': (0.76, 0.44) if shot_kind == 'icon' else (0.72, 0.38)}}
    if aspect < 1.5:
        return {'frame': 'swing', 'title': {'center': (0.42, 0.74), 'box': (0.7, 0.4)}}
    return {'frame': 'swing', 'title': {'center': (0.42, 0.71), 'box': (0.6, 0.4)}}


def go_crop(frame, meta, aspect):
    """Largest crop of the aspect inside the frame, placed by the player and rope anchor (pixel positions)."""
    fw, fh = frame.size
    nx, ny = meta['ninjaPx']
    ax, ay = meta['anchorPx']
    cx = (nx + ax) / 2
    if aspect >= fw / fh:
        cw, ch = fw, round(fw / aspect)
    else:
        cw, ch = round(fh * aspect), fh
    # full-width crops stay centred; portrait crops centre on the rope; other narrower crops put the
    # player at 78% of the width so the title fits on its left
    if cw >= fw * 0.95:
        centre = fw / 2
    elif aspect < 0.8:
        centre = cx
    else:
        centre = nx - 0.28 * cw
    left = round(min(max(centre - cw / 2, 0), fw - cw))
    top = round((fh - ch) / 2)
    return (left, top, left + cw, top + ch)


def go_count(entry):
    count = str(entry.get('count', '1'))
    if entry['name'] == 'screenshot' or entry['name'].startswith(('screenshot-', 'standard-screenshot', 'widescreen-screenshot')):
        return 3 if count.startswith('3') else 2
    return 1


def go_compose(frames_dir, spec_path, release_dir, portals=None):
    from PIL import Image, ImageFilter
    meta = json.loads((frames_dir / 'source-frames.json').read_text())['frames']
    spec = json.loads(Path(spec_path).read_text())
    frames = {}
    report = []
    for portal, data in spec['portals'].items():
        if portals and portal not in portals:
            continue
        out = release_dir / portal / 'images'
        out.mkdir(parents=True, exist_ok=True)
        for entry in data['images']:
            for index in range(go_count(entry)):
                w, h = entry['width'], entry['height']
                plan = go_plan(portal, entry, index)
                fname = plan['frame']
                if fname not in frames:
                    frames[fname] = Image.open(frames_dir / meta[fname]['file']).convert('RGB')
                frame = frames[fname]
                box = go_crop(frame, meta[fname], w / h)
                cw, ch = box[2] - box[0], box[3] - box[1]
                if cw < w or ch < h:
                    raise SystemExit(f'{portal}/{entry["name"]}: crop {cw}x{ch} smaller than {w}x{h} (would upscale)')
                # LANCZOS from a 2-8x larger crop, then a mild unsharp mask (radius 1 px) so thumbnails
                # keep crisp neon edges at their final size
                image = frame.crop(box).resize((w, h), Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.0, 100, 2))
                title_px = None
                if plan['title']:
                    t = plan['title']
                    image, title_px = go_title(image, GO_TITLE, (w * t['center'][0], h * t['center'][1]),
                                               w * t['box'][0], h * t['box'][1])
                stem = entry['name'] + (f'-{index + 1}' if go_count(entry) > 1 else '')
                fmt = 'png'
                path = out / f'{stem}.png'
                image.save(path, optimize=True)
                limit = entry.get('max_bytes')
                safe = None if limit is None else min(limit, 5_000_000 if limit > 2_100_000 else 2_000_000)
                if safe is not None and path.stat().st_size > safe:
                    allowed = [f.lower() for f in entry['format']]
                    if 'jpg' not in allowed and 'jpeg' not in allowed:
                        raise SystemExit(f'{path}: {path.stat().st_size} bytes over {safe} and JPEG not allowed')
                    path.unlink()
                    fmt = 'jpg'
                    path = out / f'{stem}.jpg'
                    for quality in (95, 92, 90, 85):
                        image.save(path, quality=quality, subsampling=0, optimize=True)
                        if path.stat().st_size <= safe:
                            break
                report.append({'portal': portal, 'name': entry['name'], 'index': index + 1, 'file': str(path.relative_to(ROOT)),
                               'width': w, 'height': h, 'format': fmt, 'bytes': path.stat().st_size,
                               'source_frame': meta[fname]['file'], 'source_frame_size': meta[fname]['size'],
                               'crop': list(box), 'crop_size': [cw, ch], 'downscale': round(cw / w, 3),
                               'title': bool(plan['title']), 'title_font_px': title_px})
                print(f'{portal}/{path.name}: {w}x{h} from {fname} crop {cw}x{ch} ({cw / w:.2f}x) {path.stat().st_size} B', flush=True)
    (release_dir / 'images.json').write_text(json.dumps(report, indent=1))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--grapple-over', action='store_true', help='Grapple Over covers (GO_SHOTS, image spec)')
    parser.add_argument('--spec', default=str(ROOT / 'artifacts/TASK-865/image-spec.json'))
    parser.add_argument('--release', default=str(ROOT / 'artifacts/release-grapple-over'))
    parser.add_argument('--shots', help='comma list of GO_SHOTS to capture (default: all)')
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--seeds', default=str(ROOT / 'artifacts/TASK-084/seed-search.json'))
    parser.add_argument('--frames')
    parser.add_argument('--out')
    parser.add_argument('--landscape', help='mode:tick for the landscape frame')
    parser.add_argument('--crop', help='mode:tick for the portrait/square frame')
    parser.add_argument('--sizes', help='WxH,... subset of COVER_SIZES to compose (default: all)')
    parser.add_argument('--errors-dir', help='where to write console-errors.log/page-errors.log')
    args = parser.parse_args()

    if args.grapple_over:
        frames = Path(args.frames) if args.frames else Path(args.release) / 'source-frames'
        if args.capture:
            errors = go_capture(frames, set(args.shots.split(',')) if args.shots else None)
            errors_dir = Path(args.errors_dir) if args.errors_dir else frames
            (errors_dir / 'browser-errors.log').write_text(''.join(e + '\n' for e in errors))
            if errors:
                return 1
        else:
            go_compose(frames, args.spec, Path(args.release))
        return 0

    shots = dict(SHOTS)
    for name in ('landscape', 'crop'):
        value = getattr(args, name)
        if value:
            mode, tick = value.split(':')
            shots[name] = {'mode': mode, 'tick': int(tick)}

    if args.capture:
        frames = Path(args.frames)
        errors = capture(args.seeds, frames, shots)
        errors_dir = Path(args.errors_dir) if args.errors_dir else frames.parent
        for kind in ('console', 'page'):
            (errors_dir / f'{kind}-errors.log').write_text(''.join(e + '\n' for e in errors[kind]))
        if errors['console'] or errors['page']:
            return 1
    sizes = None
    if args.sizes:
        sizes = {tuple(int(v) for v in size.split('x')) for size in args.sizes.split(',')}
        unknown = sizes - COVER_SIZES.keys()
        if unknown:
            raise SystemExit(f'sizes not in COVER_SIZES: {sorted(unknown)}')
    if args.out:
        out = Path(args.out)
        compose(Path(args.frames) if args.frames else out.parent / 'source-frames', out, sizes)
    return 0


if __name__ == '__main__':
    sys.exit(main())
