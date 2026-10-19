"""First momentum shaft centred (TASK-094): probe of a tree.

For seeds 1..SEEDS (the test_momentum_run mulberry32 Math.random seeding)
at 4 viewports, momentum starts and the probe records the first vertical
segment's centre line x (shaft.x0) minus the start view centre (camera x
-screen.x + viewW / 2). For the seeds named in DRIVE_SEEDS (or every seed
whose offset is < 0 when DRIVE_SEEDS is 'negative') the ninja is then put
on the course centre line STEP view heights further every frame (speed
along the segment, physics() once a frame) until it is HOLD_AT view
heights into the shaft (at most 0.8 of the shaft), then held there with
zero speed for HOLD frames. Recorded: the camera x on the last frame, its
closest approach to the centred x (shaft.x0 - viewW / 2, bc954d5's
getShaftCapX in a shaft), how many frames it was within 1 unit of it
(framesCentred) and where the ninja and the view centre were on the first.

Usage: python3 momentum_first_shaft_probe.py ROOT OUT.json [DRIVE_SEEDS]
ROOT is the tree to serve (a worktree for older commits). DRIVE_SEEDS:
'negative' (default), 'none' or comma separated viewport:seed pairs.
"""
import json
import subprocess
import sys
from pathlib import Path

from browser_test_support import start_browser_test, wait_for_boot_run

SEEDS = 40
STEP = 0.01
HOLD_AT = 0.6
HOLD = 120
VIEWPORTS = [
    ('1280x720', {'viewport': {'width': 1280, 'height': 720}}),
    ('1920x1080', {'viewport': {'width': 1920, 'height': 1080}}),
    ('844x390@3', {'viewport': {'width': 844, 'height': 390}, 'device_scale_factor': 3,
                   'has_touch': True, 'is_mobile': True}),
    ('390x844', {'viewport': {'width': 390, 'height': 844}}),
]

START = '''(seed) => {
    let a = seed >>> 0
    Math.random = () => {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    startGame('momentum')
    cancelAnimationFrame(game)
    if (typeof TUTORIAL_HINT != 'undefined') { TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true }
    let i = 0
    while (momentumCourse.segment(i).dir == 'right')
        ++i
    const shaft = momentumCourse.segment(i), viewW = width / scale[version]
    return {shaftIndex: i, dir: shaft.dir, shaftX0: shaft.x0, camX: -screen.x, viewW,
            offset: shaft.x0 - (-screen.x + viewW / 2), seg0Length: momentumCourse.segment(0).length}
}'''

DRIVE = '''([step, holdAt, hold]) => {
    const view = height / scale[version], viewW = width / scale[version]
    let i = 0, q0 = 0
    while (momentumCourse.segment(i).dir == 'right')
        q0 += momentumCourse.segment(i++).length
    const shaftIndex = i, shaft = momentumCourse.segment(i)
    const centred = shaft.x0 - viewW / 2
    const end = q0 + Math.min(holdAt * view, 0.8 * shaft.length)
    const dirOf = s => s.dir == 'right' ? {x: 1, y: 0} : s.dir == 'up' ? {x: 0, y: -1} : {x: 0, y: 1}
    let q = 0, frames = 0, closest = Infinity, maxCamX = -Infinity, framesCentred = 0, firstCentred = null
    const place = (v) => {
        let k = 0, start = 0
        while (k < shaftIndex && start + momentumCourse.segment(k).length <= q)
            start += momentumCourse.segment(k++).length
        const s = momentumCourse.segment(k), d = dirOf(s)
        grapnel.setGrappled(false); grapnel.throwed = false; grapnel.pos = []
        ninja.invulnerableMs = 1e9
        ninja.x = s.x0 + d.x * (q - start); ninja.y = s.y0 + d.y * (q - start)
        ninja.speedX = d.x * v; ninja.speedY = d.y * v
        physics()
        ++frames
        const camX = -screen.x
        maxCamX = Math.max(maxCamX, camX)
        closest = Math.min(closest, Math.abs(camX - centred))
        if (Math.abs(camX - centred) <= 1) {
            ++framesCentred
            if (firstCentred === null)
                firstCentred = {frame: frames, ninjaAlong: q - q0, viewCentreY: -screen.y + view / 2 - shaft.y0}
        }
    }
    const v = step * view / cyclesPerTick
    while (q < end) {
        q = Math.min(end, q + step * view)
        place(v)
    }
    for (let k = 0; k < hold; ++k)
        place(0)
    const camX = -screen.x
    return {frames, centredX: centred, camX, finalDiff: camX - centred, closest, maxOver: maxCamX - centred,
            framesCentred, firstCentred,
            segmentIndex: screen.segmentIndex, shaftIndex}
}'''


def main():
    root, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    drive_arg = sys.argv[3] if len(sys.argv) > 3 else 'negative'
    pairs = set()
    if drive_arg not in ('negative', 'none'):
        pairs = {tuple(p.split(':')) for p in drive_arg.split(',')}
    cleanups = []
    url, browser = start_browser_test(root, cleanups.append)
    sha = subprocess.run(['git', '-C', str(root), 'rev-parse', '--short', 'HEAD'],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--', '*.js', '*.html'],
                           capture_output=True, text=True).stdout.strip() != ''
    result = {'tree': str(root), 'sha': sha, 'dirtyGameCode': dirty, 'seeds': SEEDS,
              'step': STEP, 'holdAt': HOLD_AT, 'hold': HOLD, 'viewports': {}}
    try:
        for name, options in VIEWPORTS:
            context = browser.new_context(locale='en-US', **options)
            page = context.new_page()
            page.set_default_timeout(30000)
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + 'index.html')
            wait_for_boot_run(page)
            rows, drives = [], {}
            for seed in range(1, SEEDS + 1):
                r = page.evaluate(START, seed)
                rows.append([seed, round(r['offset'], 3), r['dir'], r['shaftIndex']])
                if (drive_arg == 'negative' and r['offset'] < 0) or (name, str(seed)) in pairs:
                    d = page.evaluate(DRIVE, [STEP, HOLD_AT, HOLD])
                    drives[seed] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}
            offsets = [r[1] for r in rows]
            result['viewports'][name] = {
                'viewW': r['viewW'], 'fields': ['seed', 'offset', 'dir', 'shaftIndex'], 'rows': rows,
                'negative': sum(o < 0 for o in offsets), 'minOffset': min(offsets),
                'drives': drives, 'pageErrors': errors}
            print(name, 'negative', result['viewports'][name]['negative'], 'min', min(offsets),
                  'drives', len(drives), 'errors', len(errors), flush=True)
            context.close()
    finally:
        for cleanup in reversed(cleanups):
            cleanup()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
