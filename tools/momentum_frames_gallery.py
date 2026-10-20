"""Momentum M-frame gallery and play check (TASK-114).

sheets: packs the concept|game montages that test_momentum_frames_h/_v/_turn
write to <evidence dir>/shots/<id>-<viewport>.png (concept left, the frame
placed in the game right, no annotations on the game half) into contact
sheets, one per group (right / shaft / corner) and viewport:
    python3 momentum_frames_gallery.py sheets <out dir> <shots dir> ...
(an evidence dir with a shots/ subdirectory may be given instead of it).
Writes <out dir>/sheet-<group>-<viewport>.png and prints the ids per sheet.
Fails when one of the 22 ids x 2 viewports has no montage.

play: one seeded 60 s momentum run at 1280x720 (test_momentum_run's SETUP
generator and DRIVE: ninja teleported along the centre line, invulnerable)
with a screenshot every 15 s:
    python3 momentum_frames_gallery.py play <out dir> [seed]
Every spawned group is recorded with its id; at each shot the elements in
view (every floor) are split into walls (MomentumBorder) and obstacle
pieces, each piece with the id of the group it belongs to. Writes
<out dir>/play-<second>s.png and play-check.json (compact {seed, shots:
[{second, segment, walls, pieces, kinds, ids, foreign}], spawned}); foreign
= pieces in view that belong to no M-frame group. Exit status 1 when a shot has a
foreign piece, a bad-frame id spawned or a page error occurred.
Requires PIL (sheets) and Playwright Chromium (play).
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'right': ['M04', 'M23', 'M24', 'M46', 'M47', 'M66'],
    'shaft': ['M11', 'M30', 'M93', 'M110', 'M11-up', 'M30-up', 'M93-up', 'M110-up'],
    'corner': ['M18', 'M60', 'M39', 'M117', 'M134', 'M40', 'M98', 'M136'],
}
VIEWPORTS = ['1280x720', '390x844']
CELL_W = 900
COLUMNS = 2
SHOT_SECONDS = [15, 30, 45, 60]


def sheets(out, dirs):
    from PIL import Image
    # An evidence dir stands for its shots/ (where the frame suites write)
    dirs = [d / 'shots' if (d / 'shots').is_dir() else d for d in dirs]
    out.mkdir(parents=True, exist_ok=True)
    missing = []
    for group, ids in GROUPS.items():
        for vp in VIEWPORTS:
            cells = []
            for id in ids:
                path = next((d / f'{id}-{vp}.png' for d in dirs if (d / f'{id}-{vp}.png').exists()), None)
                if path is None:
                    missing.append(f'{id}-{vp}')
                    continue
                im = Image.open(path).convert('RGB')
                cells.append(im.resize((CELL_W, round(im.height * CELL_W / im.width)), Image.LANCZOS))
            if not cells:
                continue
            rows = [cells[i:i + COLUMNS] for i in range(0, len(cells), COLUMNS)]
            pad = 8
            heights = [max(c.height for c in r) for r in rows]
            sheet = Image.new('RGB', (COLUMNS * (CELL_W + pad) + pad, sum(heights) + pad * (len(rows) + 1)), 'white')
            y = pad
            for r, h in zip(rows, heights):
                for k, c in enumerate(r):
                    sheet.paste(c, (pad + k * (CELL_W + pad), y))
                y += h + pad
            name = out / f'sheet-{group}-{vp}.png'
            sheet.save(name, optimize=True)
            print(name.name, ids)
    if missing:
        print('missing', missing)
        return 1
    return 0


# test_momentum_run's SETUP generator; onSpawn records the id of every group
SETUP = '''(seed) => {
    let a = seed >>> 0
    Math.random = () => {
        a = (a + 0x6D2B79F5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    window.runRngState = (v) => v === undefined ? a : (a = v)
    window.runFrame = 0
    window.runTurns = []
    window.runShaftGroups = {}
    window.playIds = {}
    window.playSpawns = []
    MomentumObstacleFloor.onSpawn = (s) => {
        playIds[s.group.id] = s.id
        playSpawns.push([Math.round(runFrame / 6) / 10, s.id, s.kind, s.dir])
    }
    startGame('momentum')
    cancelAnimationFrame(game)
    TUTORIAL_HINT.visible = false; TUTORIAL_HINT.done = true
    const floor = floors.find(f => f instanceof MomentumObstacleFloor)
    window.runArc = floor.getNinjaArc()
}'''

IN_VIEW = '''(() => {
    const w = width / scale[version], h = height / scale[version], out = []
    for (const f of floors)
        for (const e of f.elements) {
            const b = getElementBounds(e)
            if (b.right > -screen.x && b.left < -screen.x + w && b.bottom > -screen.y && b.top < -screen.y + h)
                out.push([e.constructor.name, playIds[e.generationGroupId] || null])
        }
    return {pieces: out, dir: screen.getSegment().dir}
})()'''


def play(out, seed):
    from browser_test_support import start_browser_test, wait_for_boot_run
    from test_momentum_run import DRAW, DRIVE, DRIVE_SPEED, FPS
    out.mkdir(parents=True, exist_ok=True)
    cleanups, errors, shots = [], [], []
    url, browser = start_browser_test(ROOT, cleanups.append)
    try:
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
        page.goto(url)
        wait_for_boot_run(page)
        page.evaluate(SETUP, seed)
        step = page.evaluate('height') * DRIVE_SPEED
        driven = 0
        for second in SHOT_SECONDS:
            left = second * FPS - driven
            while left:
                left -= page.evaluate(DRIVE, [left, step, {}])['frames']
            driven = second * FPS
            view = page.evaluate(IN_VIEW)
            page.evaluate(DRAW)
            page.screenshot(path=str(out / f'play-{second}s.png'))
            walls = [p for p in view['pieces'] if p[0] == 'MomentumBorder']
            pieces = [p for p in view['pieces'] if p[0] != 'MomentumBorder']
            ids = sorted({i for _, i in pieces if i})
            foreign = [p for p in pieces if not p[1] or not p[1].startswith('M')]
            shots.append({'second': second, 'segment': view['dir'], 'walls': len(walls), 'pieces': len(pieces),
                          'kinds': sorted({k for k, _ in pieces}), 'ids': ids, 'foreign': foreign})
            print(f'{second} s: {view["dir"]} {len(walls)} walls, {len(pieces)} pieces {shots[-1]["kinds"]}, '
                  f'ids {ids}, foreign {foreign}', flush=True)
        spawned = page.evaluate('playSpawns')
        context.close()
    finally:
        for cleanup in reversed(cleanups):
            cleanup()
    bad = [s for s in spawned if not s[1].startswith('M')]
    result = {'seed': seed, 'viewport': '1280x720', 'shots': shots, 'spawned': len(spawned),
              'spawnedIds': sorted({s[1] for s in spawned}), 'nonMSpawns': bad, 'errors': errors[:20]}
    (out / 'play-check.json').write_text(json.dumps(result, separators=(',', ':')))
    print('spawned', len(spawned), 'ids', result['spawnedIds'], 'non-M', bad, 'errors', len(errors))
    return 1 if bad or errors or any(s['foreign'] for s in shots) else 0


if __name__ == '__main__':
    if sys.argv[1] == 'sheets':
        sys.exit(sheets(Path(sys.argv[2]), [Path(d) for d in sys.argv[3:]]))
    sys.exit(play(Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 5))
