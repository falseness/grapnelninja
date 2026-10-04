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
9:16 (1080x1920, the Playgama portrait cover), so
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
    from browser_test_support import start_browser_test
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
            page.wait_for_function('typeof menu != "undefined" && menu.visible')
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--seeds', default=str(ROOT / 'artifacts/TASK-084/seed-search.json'))
    parser.add_argument('--frames')
    parser.add_argument('--out')
    parser.add_argument('--landscape', help='mode:tick for the landscape frame')
    parser.add_argument('--crop', help='mode:tick for the portrait/square frame')
    parser.add_argument('--sizes', help='WxH,... subset of COVER_SIZES to compose (default: all)')
    parser.add_argument('--errors-dir', help='where to write console-errors.log/page-errors.log')
    args = parser.parse_args()

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
