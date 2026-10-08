"""Visual gallery: deterministic captures, GIFs and a contact sheet of one revision.

Reuses render_snapshot's frozen clock, seeded Math.random and seeded input, so
two runs of one revision give byte-identical PNGs and identical game states.

Usage: python3 tools/visual_gallery.py --rev worktree|<git rev> --out DIR
       python3 tools/visual_gallery.py --compare-state A.json B.json
--rev writes into DIR: <viewport>-menu.png and <viewport>-<mode>-tick<NNNN>.png
for desktop 1920x1080@1 and phone 844x390@3; <viewport>-<mode>-pause.png (the
pause screen opened after the last tick, listed under 'screens': no state
check, it runs after every state capture); gif-bad.gif and gif-classic.gif (camera
parallax followed by labelled factory danger inspection); ember-gif-{mode}.gif (8 s fixed ember scene at 15 fps,
native phone scale plus labelled 3x crops); phone-{mode}-embers.png; sheet.png (the reference AI cover top-left, then every capture,
labelled); hanging-still-{mode}.gif (5 s full-scene frozen physics, live render clock); gif-menu.gif (3 s of idle menu animation); manifest.json (rev,
viewport, mode, tick and the game state per capture).
--compare-state prints one line per capture and 'differences: N' (exit 1 if N > 0).
"""
import argparse
import hashlib
import io
import json
import math
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys

import ember_gallery
import danger_gallery

from PIL import Image, ImageDraw, ImageFont

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
from render_snapshot import (ADVANCE_SCRIPT, CLOCK_SCRIPT, SEED, SETUP_SCRIPT, boot_frozen,
                             input_script, png_bytes)

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / 'artifacts/TASK-172/upload/ai-covers/cover-ai-1-original.png'
VIEWPORTS = [
    {'name': 'desktop', 'width': 1920, 'height': 1080, 'dpr': 1, 'touch': False},
    {'name': 'phone', 'width': 844, 'height': 390, 'dpr': 3, 'touch': True},
]
MODES = ['bad', 'classic']
TICKS = [300, 900]
# Seed 1's desktop bad run hangs at a fixed camera. The phone run scrolls
# after tick 900; retain the desktop classic swing and its scrolling segment.
GIF_CAPTURE = {'bad': ('phone', 900), 'classic': ('desktop', 300), 'menu': ('desktop', 0)}
GIF_SIZE = (960, 540)
GIF_FPS = 15
GIF_STEP = 60 // GIF_FPS          # game ticks per GIF frame
GIF_FRAMES = 45                   # 3 s at 15 fps
STATE_KEYS = ['ninja.x', 'ninja.y', 'scoreText.count', 'screen.x', 'screen.y', 'version']
TOLERANCE = 1e-9
THUMB = (480, 270)
LABEL_H = 22

STATE_SCRIPT = '''() => {
    const g = name => { try { return (0, eval)(name) } catch (e) { return null } }
    const ninja = g('ninja'), scoreText = g('scoreText'), screen = g('screen'), version = g('version')
    const num = v => typeof v == 'number' ? v : null
    return {
        'ninja.x': ninja ? num(ninja.x) : null,
        'ninja.y': ninja ? num(ninja.y) : null,
        'scoreText.count': scoreText && version ? num(scoreText.count[version]) : null,
        'screen.x': screen ? num(screen.x) : null,
        'screen.y': screen ? num(screen.y) : null,
        'version': version || null,
    }
}'''


def git_head():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def capture_name(vp, mode, tick=None):
    return f'{vp}-menu' if mode == 'menu' else f'{vp}-{mode}-tick{tick:04d}'


def gif_ticks(mode):
    return [GIF_CAPTURE[mode][1] + i * GIF_STEP for i in range(GIF_FRAMES)]


def to_gif_frame(data):
    img = Image.open(io.BytesIO(data)).convert('RGB').resize(GIF_SIZE, Image.LANCZOS)
    # Preserve small, saturated neon edges instead of merging them into the
    # much larger cave/background colour populations (pink could become orange).
    return img.quantize(colors=256, method=Image.FASTOCTREE, dither=Image.NONE)


def write_gif(frames, path):
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=1000 // GIF_FPS,
                   loop=0, optimize=False, disposal=1)


def capture_hanging_still(browser, url, mode, out, rev, log):
    """Freeze a real seeded grapple, then render the entire scene over five seconds.

    Physics/input/timers stop only in this probe; draw(), including motes, stays
    unmodified. Separate contexts leave baseline gameplay captures untouched.
    """
    vp = next(v for v in VIEWPORTS if v['name'] == 'phone')
    context = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                  device_scale_factor=vp['dpr'], is_mobile=True, has_touch=True)
    try:
        context.add_init_script(SEED_SCRIPT % SEED)
        context.add_init_script(CLOCK_SCRIPT)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html', wait_until='load')
        boot_frozen(page)
        page.evaluate(SETUP_SCRIPT, [input_script(SEED, 900, vp['width'], vp['height']), True])
        page.evaluate('mode => startGame(mode)', mode)
        for tick in range(1, 901):
            page.evaluate(ADVANCE_SCRIPT, tick)
            if page.evaluate("""() => {
                const z = scale[version], margin = 30;
                const visible = (x,y) => (x+screen.x)*z > margin &&
                    (x+screen.x)*z < LOGICAL_VIEWPORT.width-margin &&
                    (y+screen.y)*z > margin && (y+screen.y)*z < LOGICAL_VIEWPORT.height-margin;
                return grapnel.throwed && grapnel.grappled && grapnel.pos.length &&
                    visible(ninja.x,ninja.y) && visible(grapnel.pos[0][0],grapnel.pos[0][1]) &&
                    (ninja.y-grapnel.pos[0][1])*z > 60;
            }"""):
                break
        else:
            raise AssertionError(f'{mode}: no visible seeded hanging grapple')
        # At-rest visual probe: stop velocity-driven foreground emission too.
        page.evaluate('() => { ninja.speedX = ninja.speedY = 0 }')
        start = page.evaluate('() => __snap.now')
        frames, records = [], []
        for i in range(11):
            timestamp = start + i * 500
            page.evaluate('time => { __snap.now = time; draw() }', timestamp)
            frames.append(to_gif_frame(png_bytes(page.evaluate('() => __snap.capture()'))))
            records.append({'timestamp_ms': timestamp, 'physics_tick': tick,
                            'state': page.evaluate(STATE_SCRIPT),
                            'grapnel': page.evaluate("""() => ({throwed:grapnel.throwed,
                                grappled:grapnel.grappled, points:grapnel.pos.map(p => p.slice(0,2))})""")})
        assert not errors, errors
        assert all(r['state'] == records[0]['state'] and r['grapnel'] == records[0]['grapnel']
                   for r in records), f'{mode}: frozen world changed'
        name = f'hanging-still-{mode}.gif'
        frames[0].save(out / name, save_all=True, append_images=frames[1:], duration=500,
                       loop=0, optimize=False, disposal=1)
        with Image.open(out / name) as gif:
            assert gif.n_frames == 11, f'{mode}: missing temporal frames'
        log(f'PASS hanging-still {mode}: 11 full-scene frames over 5000 ms; '
            f'ninja/camera/grapnel identical; grapple attached; rev={rev}')
        return {'file': name, 'rev': rev, 'viewport': 'phone', 'size': list(GIF_SIZE),
                'fps': 2, 'frames': 11, 'duration_ms': 5000,
                'scene': 'real seeded grapple at rest (velocity zero); frozen physics/input/timers; unmodified full draw()',
                'sha256': hashlib.sha256((out / name).read_bytes()).hexdigest(),
                'states': records, 'page_errors': errors}
    finally:
        context.close()


def label_font():
    for name in ('DejaVuSans-Bold.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, 15)
        except OSError:
            pass
    return ImageFont.load_default()


def fit(img, box):
    img = img.convert('RGB')
    scale = min(box[0] / img.width, box[1] / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    cell = Image.new('RGB', box, (24, 24, 24))
    cell.paste(img, ((box[0] - img.width) // 2, (box[1] - img.height) // 2))
    return cell


def write_sheet(out, items, path, cols=4):
    """items: [(label, PIL image)]; the reference cover comes first (top-left)."""
    font = label_font()
    rows = math.ceil(len(items) / cols)
    sheet = Image.new('RGB', (cols * THUMB[0], rows * (THUMB[1] + LABEL_H)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(items):
        x, y = (i % cols) * THUMB[0], (i // cols) * (THUMB[1] + LABEL_H)
        draw.text((x + 6, y + 3), label, fill=(255, 255, 255), font=font)
        sheet.paste(fit(img, THUMB), (x, y + LABEL_H))
    sheet.save(path, optimize=False)


def image_to_png(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def run(rev, out, log=print):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    shots, states, gifs, screens, errors = {}, {}, {}, {}, []
    gif_states = {}
    ember_gifs, ember_info = {}, {}
    hanging_info = {}
    danger_info, danger_clips = {}, {}
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for vp in VIEWPORTS:
            last_tick = max(TICKS + [tick for mode in MODES for tick in gif_ticks(mode)])
            # Preserve the baseline input prefix, including throws omitted
            # because their release would fall after the last state capture.
            script = input_script(SEED, max(TICKS), vp['width'], vp['height'])
            script += [event for event in input_script(SEED, last_tick, vp['width'], vp['height'])
                       if event['tick'] > max(TICKS)]
            for mode in ['menu'] + MODES:
                context = browser.new_context(viewport={'width': vp['width'], 'height': vp['height']},
                                              device_scale_factor=vp['dpr'],
                                              is_mobile=vp['touch'], has_touch=vp['touch'])
                context.add_init_script(SEED_SCRIPT % SEED)
                context.add_init_script(CLOCK_SCRIPT)
                page = context.new_page()
                page.on('pageerror', lambda e, n=vp['name']: errors.append(f'{n}: {e}'))
                page.goto(url + 'index.html', wait_until='load')
                boot_frozen(page)
                if not page.evaluate('() => typeof menu != "undefined" && menu.visible'):
                    raise RuntimeError('menu not visible after load')
                page.evaluate(SETUP_SCRIPT, [script, vp['touch']])

                def shoot(name, tick):
                    shots[name] = png_bytes(page.evaluate('() => __snap.capture()'))
                    states[name] = {'viewport': vp['name'], 'mode': mode, 'tick': tick,
                                    'state': page.evaluate(STATE_SCRIPT)}

                if mode == 'menu':
                    shoot(capture_name(vp['name'], mode), 0)
                    if vp['name'] == GIF_CAPTURE['menu'][0]:
                        frames, frame_states = [], []
                        for tick in gif_ticks('menu'):
                            page.evaluate('tick => { __snap.now = tick * 1000 / 60; menu.draw() }', tick)
                            frames.append(to_gif_frame(png_bytes(page.evaluate('() => __snap.capture()'))))
                            frame_states.append(page.evaluate(STATE_SCRIPT))
                        gifs['menu'], gif_states['menu'] = frames, frame_states
                else:
                    page.evaluate('mode => startGame(mode)', mode)
                    frames = []
                    frame_states = []
                    for tick in sorted(set(TICKS + (gif_ticks(mode) if vp['name'] == GIF_CAPTURE[mode][0] else []))):
                        page.evaluate(ADVANCE_SCRIPT, tick)
                        if tick in TICKS:
                            shoot(capture_name(vp['name'], mode, tick), tick)
                        if vp['name'] == GIF_CAPTURE[mode][0] and tick in gif_ticks(mode):
                            frames.append(to_gif_frame(png_bytes(page.evaluate('() => __snap.capture()'))))
                            frame_states.append(page.evaluate(STATE_SCRIPT))
                    if frames:
                        gifs[mode] = frames
                        gif_states[mode] = frame_states
                    page.evaluate('() => menu.startPause()')
                    screens[f'{vp["name"]}-{mode}-pause'] = png_bytes(page.evaluate('() => __snap.capture()'))
                if vp['name'] == 'phone' and mode in MODES:
                    ember_gifs[mode], ember_info[mode] = ember_gallery.capture(page, mode, out)
                    log(f'ember scene {mode}: 120 frames, native phone + 3x details, shared alpha={ember_info[mode]["peak_shared_alpha"]}')
                if mode in MODES:
                    inspection, info = danger_gallery.capture(page, mode, out, vp['name'])
                    danger_info[f'{vp["name"]}-{mode}'] = info
                    if vp['name'] == GIF_CAPTURE[mode][0]:
                        danger_clips[mode] = [to_gif_frame(image_to_png(im)) for im in inspection]
                context.close()
                log(f'rev={rev_id} viewport={vp["name"]} {vp["width"]}x{vp["height"]}@{vp["dpr"]} '
                    f'mode={mode} done')
        for mode in MODES:
            hanging_info[mode] = capture_hanging_still(browser, url, mode, out, rev_id, log)
    rev_sha = rev_id.split('@', 1)[1].split('+', 1)[0] if rev_id.startswith('worktree@') else rev_id
    captures = {}
    for name in sorted(shots, key=list(shots).index):
        (out / f'{name}.png').write_bytes(shots[name])
        size = Image.open(io.BytesIO(shots[name])).size
        captures[name] = dict(states[name], file=f'{name}.png', width=size[0], height=size[1],
                              sha256=hashlib.sha256(shots[name]).hexdigest())
    screen_files = {}
    for name, data in screens.items():
        (out / f'{name}.png').write_bytes(data)
        size = Image.open(io.BytesIO(data)).size
        screen_files[name] = {'file': f'{name}.png', 'width': size[0], 'height': size[1],
                              'sha256': hashlib.sha256(data).hexdigest()}
    for mode, frames in gifs.items():
        write_gif(frames + danger_clips.get(mode, []), out / f'gif-{mode}.gif')
    for mode, frames in ember_gifs.items():
        write_gif(frames, out / f'ember-gif-{mode}.gif')
        ember_info[mode]['file'] = f'ember-gif-{mode}.gif'
    items = [('reference: cover-ai-1-original.png', Image.open(REFERENCE))] if REFERENCE.exists() else []
    items += [(f'{name}  ({c["width"]}x{c["height"]})', Image.open(out / c['file']))
              for name, c in list(captures.items()) + list(screen_files.items())]
    items += [(f'phone-{mode}: fixed ember scene', Image.open(out / info['phone_file']))
              for mode, info in ember_info.items()]
    items += [(name + ': danger inspection', Image.open(out / info['file']))
              for name, info in danger_info.items()]
    write_sheet(out, items, out / 'sheet.png')
    manifest = {
        'rev': rev_sha, 'source': rev_id, 'seed': SEED, 'ticks': TICKS,
        'viewports': VIEWPORTS, 'reference': str(REFERENCE.relative_to(ROOT)) if REFERENCE.exists() else None,
        'ember_gifs': ember_info,
        'hanging_still_gifs': hanging_info,
        'danger_inspection': danger_info,
        'gifs': {mode: {'file': f'gif-{mode}.gif', 'viewport': GIF_CAPTURE[mode][0], 'size': list(GIF_SIZE),
                        'fps': GIF_FPS, 'frames': len(frames) + len(danger_clips.get(mode, [])),
                        'gameplay_frames': len(frames),
                        'inspection_frames': len(danger_clips.get(mode, [])), 'ticks': gif_ticks(mode),
                        'states': gif_states[mode]}
                 for mode, frames in gifs.items()},
        'page_errors': errors, 'captures': captures, 'screens': screen_files,
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    return manifest


def same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= TOLERANCE
    return a == b


def compare_state(path_a, path_b, log=print):
    """Logs one line per capture; returns the number of differing state values."""
    a = json.loads(Path(path_a).read_text())['captures']
    b = json.loads(Path(path_b).read_text())['captures']
    total = 0
    for name in list(a) + [n for n in b if n not in a]:
        if name not in a or name not in b:
            total += 1
            log(f'{name}: missing in {"A" if name not in a else "B"}')
            continue
        sa, sb = a[name]['state'], b[name]['state']
        diffs = [f'{k} {sa.get(k)!r} != {sb.get(k)!r}' for k in STATE_KEYS if not same(sa.get(k), sb.get(k))]
        total += len(diffs)
        log(f'{name}: ' + ('same' if not diffs else 'DIFF ' + '; '.join(diffs)))
    log(f'differences: {total}')
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--rev')
    group.add_argument('--compare-state', nargs=2, metavar=('A', 'B'))
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    log = lambda s: print(s, flush=True)
    if args.compare_state:
        return 1 if compare_state(*args.compare_state, log=log) else 0
    if not args.out:
        parser.error('--rev needs --out')
    manifest = run(args.rev, args.out, log=log)
    for name, c in manifest['captures'].items():
        log(f'{c["sha256"]}  {name}.png  state={json.dumps(c["state"])}')
    for name, c in manifest['screens'].items():
        log(f'{c["sha256"]}  {name}.png  (screen)')
    log(f'rev={manifest["rev"]} source={manifest["source"]} captures={len(manifest["captures"])} '
        f'screens={len(manifest["screens"])} '
        f'gifs={len(manifest["gifs"])} page_errors={len(manifest["page_errors"])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
