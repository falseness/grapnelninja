"""CrazyGames preview videos from real gameplay (TASK-086).

  python3 tools/make_preview_video.py --out artifacts/TASK-086/videos

Replays the best TASK-084 autopilot seed (classic mode, seed 1) tick by tick
with no requestAnimationFrame: two physics() ticks per video frame, then
draw() and a canvas PNG, so the clip plays at exactly 30 fps on any machine.
The canvas is rendered once at 2880x1620 (1920x1080 viewport, DPR 1.5, the
viewport the seeds were recorded at, so the replay stays deterministic).
Classic keeps the ninja at a fixed screen x for the whole window, so it never
falls behind the camera (bad seed 4 does, for seconds at a time). Both videos
are cut from those frames inside the mode's crop band (bad mode draws flat
near-black bands above and below its playfield), following the ninja with a
smoothed crop:

  preview-1920x1080.mp4  16:9 crop (the whole classic canvas), downscaled
  preview-1080x1620.mp4  2:3 crop, 1:1 pixels in classic

The tool fails if the ninja is ever outside a crop box (or the canvas) or the
score resets, and logs the off-crop frame count (must be 0).

Each video opens with the matching TASK-085 cover for 0.5 s, then cuts
straight into gameplay. H.264 (yuv420p) via imageio-ffmpeg, no audio stream.
Raw frames and the per-frame capture log (tick, score, ninja position) go to
<out>/../frames and <out>/../capture-log.json.
"""
import argparse
import base64
import contextlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_covers import AUTOPILOT, PLAYFIELD, ROOT, VIEWPORT

FPS = 30
TICKS_PER_FRAME = 60 // FPS
DPR = 1.5  # 2880x1620 canvas (the 1920x1080 viewport the seeds were recorded at)
# Classic seed 1 settles at its fixed screen x by tick 60; 1020 ticks = 17 s.
MODE = 'classic'
START_TICK = 180
END_TICK = 1200
# Vertical band (fractions of the canvas height) the crops stay inside
CROP_BAND = {'classic': (0.0, 1.0), 'bad': PLAYFIELD}
# The ninja point must stay this far (fraction of the crop size) inside every crop
NINJA_MARGIN = 0.03
COVER_SECONDS = 0.5
# Crop centre = ninja x + LEAD * crop width, so the obstacles ahead stay in view
LEAD = {'landscape': 0.1, 'portrait': 0.15}
VIDEOS = {
    'landscape': {'size': (1920, 1080), 'cover': 'cover-1920x1080.png'},
    'portrait': {'size': (1080, 1620), 'cover': 'cover-800x1200.png'},
}

SETUP_JS = '''([mode, seed, actions, startTick]) => {
    __ap.install(seed)
    __ap.replay(actions)
    startGame(mode)
    cancelAnimationFrame(game)
    // no HUD/score/pause icon and no FPS counter in a store video
    window.drawUILayer = function() {}
    window.drawFpsCounterLayer = function() {}
    while (__ap.tick < startTick && __ap.deathTick === null)
        physics()
    return __ap.tick
}'''

FRAME_JS = '''(ticks) => {
    for (let i = 0; i < ticks && __ap.deathTick === null; ++i)
        physics()
    draw()
    const s = scale[version]
    return {tick: __ap.tick, deathTick: __ap.deathTick, score: scoreText.count[version],
        canvas: [canvas.width, canvas.height],
        ninja: [(ninja.x + screen.x) * s / width, (ninja.y + screen.y) * s / height],
        url: canvas.toDataURL('image/png')}
}'''


def capture(seed_report, frames_dir, mode, start_tick, end_tick):
    from browser_test_support import start_browser_test
    entry = json.loads(Path(seed_report).read_text())['modes'][mode]
    frames_dir.mkdir(parents=True, exist_ok=True)
    errors = {'console': [], 'page': []}
    log = []
    with contextlib.ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=DPR)
        stack.callback(context.close)
        context.add_init_script(path=str(AUTOPILOT))
        page = context.new_page()
        page.set_default_timeout(0)
        page.on('console', lambda m: m.type == 'error' and errors['console'].append(m.text))
        page.on('pageerror', lambda e: errors['page'].append(str(e)))
        page.goto(url + 'index.html')
        page.wait_for_function('typeof menu != "undefined" && menu.visible')
        tick = page.evaluate(SETUP_JS, [mode, entry['best_seed'], entry['best_actions'], start_tick])
        ticks = 0  # the first frame shows start_tick itself
        while tick < end_tick:
            facts = page.evaluate(FRAME_JS, ticks)
            ticks = TICKS_PER_FRAME
            if facts['deathTick'] is not None:
                raise SystemExit(f'ninja died at tick {facts["deathTick"]}')
            if log and facts['score'] < log[-1]['score']:
                raise SystemExit(f'score reset at tick {facts["tick"]}')
            tick = facts['tick']
            path = frames_dir / f'f{len(log):04d}.png'
            path.write_bytes(base64.b64decode(facts.pop('url').split(',', 1)[1]))
            log.append({'frame': len(log), 'file': path.name, **facts})
            if len(log) % 30 == 0:
                print(f'frame {len(log)} tick {tick} score {facts["score"]} ninja {facts["ninja"]}',
                      flush=True)
    meta = {'mode': mode, 'seed': entry['best_seed'], 'dpr': DPR, 'fps': FPS,
            'ticks_per_frame': TICKS_PER_FRAME, 'start_tick': start_tick, 'frames': log}
    return meta, errors


def smooth(values, radius):
    """Centred moving average (window 2 * radius + 1, clamped at the ends)."""
    out = []
    for i in range(len(values)):
        window = values[max(0, i - radius):i + radius + 1]
        out.append(sum(window) / len(window))
    return out


def crop_box(image_size, center_x, aspect, band):
    """Largest crop of aspect w/h inside the vertical band, centred on center_x px."""
    iw, ih = image_size
    top, bottom = round(band[0] * ih), round(band[1] * ih)
    cw = round((bottom - top) * aspect)
    cx = min(max(center_x, cw / 2), iw - cw / 2)
    left = round(cx - cw / 2)
    return left, top, left + cw, bottom


def inside(box, point, margin):
    left, top, right, bottom = box
    mx, my = margin * (right - left), margin * (bottom - top)
    return left + mx <= point[0] <= right - mx and top + my <= point[1] <= bottom - my


def encode(meta, frames_dir, covers_dir, out):
    import imageio_ffmpeg
    import numpy as np
    from PIL import Image
    out.mkdir(parents=True, exist_ok=True)
    frames = meta['frames']
    first = Image.open(frames_dir / frames[0]['file'])
    iw, ih = first.size
    band = CROP_BAND[meta['mode']]
    xs = smooth([f['ninja'][0] * iw for f in frames], FPS)
    # Plan every crop first, so a ninja that leaves the frame fails before encoding
    boxes = {}
    for name, video in VIDEOS.items():
        w, h = video['size']
        boxes[name] = [crop_box((iw, ih), x + LEAD[name] * (band[1] - band[0]) * ih * w / h, w / h, band)
                       for x in xs]
        off = [f['frame'] for f, box in zip(frames, boxes[name])
               if not inside(box, (f['ninja'][0] * iw, f['ninja'][1] * ih), NINJA_MARGIN)]
        print(f'{name}: ninja outside the crop (margin {NINJA_MARGIN}) in {len(off)} of {len(frames)} frames'
              + (f': {off[:10]}' if off else ''), flush=True)
        if off:
            raise SystemExit(f'{name}: ninja leaves the crop in {len(off)} frames, first {off[0]}')
    crops = {}
    for name, video in VIDEOS.items():
        w, h = video['size']
        path = out / f'preview-{w}x{h}.mp4'
        writer = imageio_ffmpeg.write_frames(
            str(path), (w, h), fps=FPS, codec='libx264', pix_fmt_out='yuv420p',
            quality=None, bitrate=None, macro_block_size=1,
            output_params=['-crf', '18', '-preset', 'medium', '-an', '-movflags', '+faststart'])
        writer.send(None)
        cover = Image.open(covers_dir / video['cover']).convert('RGB').resize((w, h), Image.LANCZOS)
        cover_bytes = np.asarray(cover).tobytes()
        for _ in range(round(COVER_SECONDS * FPS)):
            writer.send(cover_bytes)
        for frame, box in zip(frames, boxes[name]):
            image = Image.open(frames_dir / frame['file']).convert('RGB').crop(box)
            if image.size != (w, h):
                image = image.resize((w, h), Image.LANCZOS)
            writer.send(np.asarray(image).tobytes())
        writer.close()
        box = boxes[name][0]
        crops[name] = {'file': path.name, 'size': [w, h], 'cover_frames': round(COVER_SECONDS * FPS),
                       'gameplay_frames': len(frames), 'crop_size': [box[2] - box[0], box[3] - box[1]],
                       'crop_band': list(band), 'ninja_margin': NINJA_MARGIN, 'ninja_off_crop_frames': 0,
                       'crop_left_range': [min(b[0] for b in boxes[name]), max(b[0] for b in boxes[name])]}
        print(f'{path.name}: {(path.stat().st_size)} bytes, {crops[name]}', flush=True)
    return crops


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--seeds', default=str(ROOT / 'artifacts/TASK-084/seed-search.json'))
    parser.add_argument('--covers', default=str(ROOT / 'artifacts/TASK-085/covers'))
    parser.add_argument('--mode', default=MODE)
    parser.add_argument('--start-tick', type=int, default=START_TICK)
    parser.add_argument('--end-tick', type=int, default=END_TICK)
    parser.add_argument('--skip-capture', action='store_true',
                        help='re-encode from existing frames and capture-log.json')
    args = parser.parse_args()

    out = Path(args.out)
    frames_dir = out.parent / 'frames'
    log_path = out.parent / 'capture-log.json'
    if args.skip_capture:
        meta = json.loads(log_path.read_text())
    else:
        meta, errors = capture(args.seeds, frames_dir, args.mode, args.start_tick, args.end_tick)
        log_path.write_text(json.dumps(meta, indent=1))
        for kind in ('console', 'page'):
            (out.parent / f'{kind}-errors.log').write_text(''.join(e + '\n' for e in errors[kind]))
        if errors['console'] or errors['page']:
            return 1
    meta['videos'] = encode(meta, frames_dir, Path(args.covers), out)
    log_path.write_text(json.dumps(meta, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
