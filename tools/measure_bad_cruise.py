"""Bad-mode cruise speed (TASK-007): the source of GAMEPLAY.momentumMaxSpeed.

The seeded store-asset autopilot (tools/autopilot.js) plays bad mode with the
rAF loop stopped, throwing the grapnel at trampolines and ceiling points
through the game's own input handlers. Seeds are tried in order until one
survives --seconds; per real physics frame (__ap.step) the ninja's |v| = hypot(speedX, speedY)
after physics() is recorded (world units per physics cycle, the unit of
ninja.speedX/speedY).

Usage: python3 measure_bad_cruise.py --out ../artifacts/TASK-007
Writes bad-cruise.json: {seed, frames, median, p95, max, medianHeightRatio}
(compact; the per-frame series is not kept).
"""
import argparse
import contextlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test, wait_for_boot_run

ROOT = Path(__file__).resolve().parent.parent
AUTOPILOT = Path(__file__).with_name('autopilot.js')

RUN = '''([seed, ticks]) => {
    __ap.install(seed)
    startGame('bad')
    cancelAnimationFrame(game)
    const speeds = []
    // __ap.step is one real physics tick; the autopilot's look-ahead calls
    // physics() on clones too, so physics itself is not wrapped
    const realStep = __ap.step
    __ap.step = function() {
        realStep()
        speeds.push(Math.hypot(ninja.speedX, ninja.speedY))
    }
    const result = __ap.run(ticks)
    __ap.step = realStep
    const alive = result.deathTick === null ? speeds : speeds.slice(0, result.deathTick)
    return {seed: seed, deathTick: result.deathTick, speeds: alive, height: height}
}'''


def percentile(sorted_values, p):
    """Linear interpolation between closest ranks."""
    k = (len(sorted_values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--seconds', type=float, default=20.0)
    parser.add_argument('--seeds', type=int, default=40)
    args = parser.parse_args()
    ticks = int(args.seconds * 60)
    with contextlib.ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        for seed in range(1, args.seeds + 1):
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            context.add_init_script(path=str(AUTOPILOT))
            page = context.new_page()
            page.goto(url + 'index.html')
            wait_for_boot_run(page)
            page.set_default_timeout(0)
            run = page.evaluate(RUN, [seed, ticks])
            context.close()
            print(f'seed {seed}: deathTick {run["deathTick"]}, frames {len(run["speeds"])}', flush=True)
            if run['deathTick'] is None and len(run['speeds']) >= ticks:
                break
        else:
            sys.exit(f'no seed survived {args.seconds} s')
    speeds = sorted(run['speeds'])
    median = percentile(speeds, 0.5)
    result = {'seed': run['seed'], 'frames': len(speeds), 'seconds': len(speeds) / 60,
              'median': median, 'p95': percentile(speeds, 0.95), 'max': speeds[-1],
              'medianHeightRatio': median / run['height'], 'unit': 'world units per physics cycle'}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'bad-cruise.json').write_text(json.dumps(result, separators=(',', ':')))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
