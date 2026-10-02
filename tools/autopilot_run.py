"""Seed search and video capture for the store-asset autopilot (TASK-084).

For every mode the seeds are tried in order with tools/autopilot.js driving
physics by hand (fast, no rendering). A mode stops early once a seed survives
--target seconds. The best seed of each mode is then replayed under
requestAnimationFrame with Playwright video recording; the canvas is sampled
once per game second for the filmstrip.

Usage:
  python3 tools/autopilot_run.py --modes classic,bad --seeds 1-200 \
      --out artifacts/TASK-084

Writes to --out: seed-search.json, best-<mode>.webm, filmstrip-<mode>.png,
frames/<mode>/sNN.png, console-errors.log, page-errors.log.
"""
import argparse
import base64
import contextlib
import io
import json
import shutil
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test

ROOT = Path(__file__).resolve().parent.parent
AUTOPILOT = Path(__file__).with_name('autopilot.js')
VIEWPORT = {'width': 1920, 'height': 1080}
# Smaller encode keeps the 2-CPU capture machine closer to real time
VIDEO_SIZE = {'width': 1280, 'height': 720}
TICKS_PER_SECOND = 60

# Samples the canvas (downscaled) at the first draw after each game second.
FRAME_SAMPLER = r'''(width) => {
    const ap = window.__ap
    ap.frames = []
    const realDraw = window.draw
    const small = document.createElement('canvas')
    window.draw = function() {
        realDraw.apply(this, arguments)
        // first draw at or after the end of game second N
        if (ap.tick >= (ap.frames.length + 1) * 60) {
            small.width = width
            small.height = Math.round(width * canvas.height / canvas.width)
            small.getContext('2d').drawImage(canvas, 0, 0, small.width, small.height)
            ap.frames.push({second: ap.frames.length + 1, tick: ap.tick,
                ninjaX: ninja.x, ninjaY: ninja.y, url: small.toDataURL('image/png')})
        }
    }
}'''


def parse_seeds(text):
    """'1-200' or '1,5,9-12' -> list of ints."""
    seeds = []
    for part in text.split(','):
        if '-' in part:
            lo, hi = part.split('-')
            seeds.extend(range(int(lo), int(hi) + 1))
        else:
            seeds.append(int(part))
    return seeds


def build_filmstrip(frames, out_path, columns=6):
    """Grid of frames (PIL images) with their second labelled."""
    from PIL import Image, ImageDraw
    w, h = frames[0].size
    rows = (len(frames) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * w, rows * h), 'black')
    draw = ImageDraw.Draw(sheet)
    for i, frame in enumerate(frames):
        x, y = (i % columns) * w, (i // columns) * h
        sheet.paste(frame.convert('RGB'), (x, y))
        draw.text((x + 6, y + 4), f't={i + 1}s', fill='yellow')
    sheet.save(out_path)
    return sheet.size


class Runner:
    def __init__(self, url, browser, out):
        self.url = url
        self.browser = browser
        self.out = out
        self.errors = {'console': [], 'page': []}

    def open(self, label, **context_options):
        context = self.browser.new_context(viewport=VIEWPORT, **context_options)
        context.add_init_script(path=str(AUTOPILOT))
        page = context.new_page()
        page.on('console', lambda m: m.type == 'error' and
                self.errors['console'].append(f'[{label}] {m.text}'))
        page.on('pageerror', lambda e: self.errors['page'].append(f'[{label}] {e}'))
        page.goto(self.url + 'index.html')
        page.wait_for_function('typeof menu != "undefined" && menu.visible')
        return context, page

    def search(self, mode, seed, max_ticks):
        context, page = self.open(f'{mode}:{seed}')
        try:
            page.set_default_timeout(0)
            return page.evaluate('''([mode, seed, maxTicks]) => {
                __ap.install(seed)
                startGame(mode)
                cancelAnimationFrame(game)
                return __ap.run(maxTicks)
            }''', [mode, seed, max_ticks])
        finally:
            context.close()

    def replay(self, mode, result):
        """Replays the recorded actions with video; returns replay facts."""
        video_dir = self.out / 'video-tmp' / mode
        context, page = self.open(f'{mode}:replay', record_video_dir=str(video_dir),
                                  record_video_size=VIDEO_SIZE)
        end_tick = result['deathTick'] if result['deathTick'] is not None else result['ticks']
        stop_tick = end_tick + TICKS_PER_SECOND // 2
        page.evaluate(FRAME_SAMPLER, 480)
        page.evaluate('''([mode, seed, actions]) => {
            __ap.install(seed)
            __ap.replay(actions)
            startGame(mode)
        }''', [mode, result['seed'], result['actions']])
        # After a death the continue offer may freeze physics: stop on either.
        page.wait_for_function(f'__ap.tick >= {stop_tick} || __ap.deathTick !== null',
                               timeout=(stop_tick / TICKS_PER_SECOND) * 20 * 1000)
        page.wait_for_timeout(1000)
        facts = page.evaluate('''() => ({tick: __ap.tick, deathTick: __ap.deathTick,
            score: scoreText.count[version], frames: __ap.frames, trace: __ap.trace})''')
        video = page.video
        context.close()
        target = self.out / f'best-{mode}.webm'
        video.save_as(str(target))
        video.delete()
        return facts, target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--modes', default='classic,bad')
    parser.add_argument('--seeds', default='1-200')
    parser.add_argument('--out', required=True)
    parser.add_argument('--target', type=float, default=20.0)
    parser.add_argument('--max-seconds', type=float, default=22.0)
    parser.add_argument('--no-early-stop', action='store_true')
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    max_ticks = int(args.max_seconds * TICKS_PER_SECOND)
    report = {'viewport': VIEWPORT, 'video_size': VIDEO_SIZE, 'target_s': args.target, 'max_s': args.max_seconds,
              'seeds_requested': args.seeds, 'modes': {}}
    report_path = out / 'seed-search.json'

    with contextlib.ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        runner = Runner(url, browser, out)
        for mode in args.modes.split(','):
            entry = report['modes'][mode] = {'tried': [], 'best': None}
            for seed in parse_seeds(args.seeds):
                result = runner.search(mode, seed, max_ticks)
                entry['tried'].append({k: result[k] for k in
                                       ('seed', 'survivalS', 'deathTick', 'ticks', 'score', 'wallMs')}
                                      | {'actions': len(result['actions'])})
                print(f'{time.strftime("%H:%M:%S")} {mode} seed {seed}: '
                      f'survival {result["survivalS"]:.2f} s score {result["score"]} '
                      f'died {result["deathTick"] is not None} wall {result["wallMs"] / 1000:.0f} s',
                      flush=True)
                if not entry['best'] or result['survivalS'] > entry['best']['survivalS']:
                    entry['best'] = result
                report_path.write_text(json.dumps(report, indent=1, default=str))
                if result['survivalS'] >= args.target and not args.no_early_stop:
                    entry['stopped_early'] = (f'seed {seed} reached the {args.target} s target; '
                                              f'remaining seeds not tried')
                    break

            best = entry['best']
            entry['best_seed'] = best['seed']
            entry['best_survival_s'] = best['survivalS']
            entry['best_actions'] = best['actions']
            entry['best_trace'] = best['trace']
            del entry['best']
            facts, video = runner.replay(mode, best)
            frames_dir = out / 'frames' / mode
            frames_dir.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            images = []
            for frame in facts['frames']:
                data = base64.b64decode(frame['url'].split(',', 1)[1])
                (frames_dir / f's{frame["second"]:02d}.png').write_bytes(data)
                images.append(Image.open(io.BytesIO(data)))
            size = build_filmstrip(images, out / f'filmstrip-{mode}.png')
            entry['replay'] = {
                'video': video.name, 'ticks': facts['tick'], 'deathTick': facts['deathTick'],
                'score': facts['score'], 'frames': len(images), 'filmstrip_size': size,
                'matches_search': facts['deathTick'] == best['deathTick'] and
                    facts['trace'][:len(best['trace'])] == best['trace'],
                'frame_positions': [{k: f[k] for k in ('second', 'tick', 'ninjaX', 'ninjaY')}
                                    for f in facts['frames']]}
            print(f'{mode}: best seed {best["seed"]} {best["survivalS"]:.2f} s; replay '
                  f'deathTick {facts["deathTick"]} (search {best["deathTick"]}), '
                  f'{len(images)} frames', flush=True)
            report_path.write_text(json.dumps(report, indent=1, default=str))

        shutil.rmtree(out / 'video-tmp', ignore_errors=True)
        (out / 'console-errors.log').write_text(''.join(e + '\n' for e in runner.errors['console']))
        (out / 'page-errors.log').write_text(''.join(e + '\n' for e in runner.errors['page']))
    return 1 if runner.errors['console'] or runner.errors['page'] else 0


if __name__ == '__main__':
    sys.exit(main())
