"""Static poster check (TASK-892): index.html's #poster (art/poster.webp) is up from the first HTML
paint and gone in every frame after the first gameLoop frame.

For every SCREEN MATRIX size (tools/boot_timing.py, 13 sizes; --sizes to narrow) the game is booted
from a source tree (default the repo root, --root) or a release zip (--zip) on a local server. An
init script records, at DOMContentLoaded, whether the poster is visible (checkVisibility, box
covering the window) and its image decoded (complete, naturalWidth > 0); it wraps
requestAnimationFrame to mark the first gameLoop callback and, after every later callback, whether
the poster is still in the document. The level script (leveldata.js, loaded by the boot after DCL)
is held (its <script> append delayed, shot sizes only) until the "dcl" screenshot is
taken, so the shot shows the page as it stands at DCL.

Pass per size: visible + decoded at DCL, the poster was present when the first gameLoop frame began
and gone when it ended, it is absent in all >= --frames later frames, the window centre hit-tests
through it (pointer-events: none), the run reached ready (bootComplete, runInProgress) and the
platform's game_ready went out, and no page errors.

  python3 tools/test_poster.py --out artifacts/TASK-892/poster.json --shots artifacts/TASK-892 \\
      [--shot-sizes desktop-1366x768@1,pixel7-portrait,iphone13-landscape] [--sizes matrix] [--zip Z]

With no arguments (or -v/-q; tools/run_regression.py) it is a unittest on two sizes.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import boot_timing as bt  # noqa: E402

POSTER_FILE = 'art/poster.webp'
POSTER_MAX_BYTES = 80 * 1024
FRAMES_AFTER = 30
SHOT_SIZES = ['desktop-1366x768@1', 'pixel7-portrait', 'iphone13-landscape']

INIT_SCRIPT = r'''(() => {
    const m = window.__poster = {dcl: null, start: null, end: null, framesAfter: 0, presentAfter: 0,
        visibleAfter: 0, gameReady: false}
    const visible = el => !!el && el.isConnected &&
        (el.checkVisibility ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
                            : el.offsetParent !== null)
    const state = () => {
        const poster = document.getElementById('poster')
        const img = poster && poster.querySelector('img')
        const r = poster ? poster.getBoundingClientRect() : null
        const hit = document.elementFromPoint(innerWidth / 2, innerHeight / 2)
        return {present: !!poster, visible: visible(poster) && visible(img),
                decoded: !!img && img.complete && img.naturalWidth > 0,
                natural: img ? [img.naturalWidth, img.naturalHeight] : null,
                covers: !!r && r.left <= 0.5 && r.top <= 0.5 && r.right >= innerWidth - 0.5 &&
                        r.bottom >= innerHeight - 0.5,
                fit: img ? getComputedStyle(img).objectFit : null,
                background: poster ? getComputedStyle(poster).backgroundColor : null,
                pointerEvents: poster ? getComputedStyle(poster).pointerEvents : null,
                hitsPoster: !!hit && !!poster && poster.contains(hit),
                hit: hit ? (hit.id || hit.tagName.toLowerCase()) : null,
                window: [innerWidth, innerHeight], t: performance.now()}
    }
    window.__posterState = state
    // Hold the boot at its level script (mountain.js appends leveldata.js) until the test releases
    // it for the "dcl" screenshot: the append itself waits, so no request is left pending
    if (window.__posterHold) {
        const append = Node.prototype.appendChild
        Node.prototype.appendChild = function(child) {
            if (child && child.tagName === 'SCRIPT' && /leveldata\.js/.test(child.src || '')) {
                m.held = true
                window.__posterRelease = () => { Node.prototype.appendChild = append; append.call(this, child) }
                return child
            }
            return append.call(this, child)
        }
    }
    addEventListener('DOMContentLoaded', () => {
        m.dcl = state()
        // game_ready must still reach the platform (the wrap is observation only)
        try {
            const orig = PLATFORM.gameReady
            PLATFORM.gameReady = function(...args) { m.gameReady = true; return orig.apply(this, args) }
            m.gameReadyWrapped = PLATFORM.gameReady !== orig
        } catch (e) { m.gameReadyWrapped = false }
    })
    const raw = window.requestAnimationFrame.bind(window)
    window.requestAnimationFrame = cb => raw(t => {
        const isFirst = m.start === null && cb.name === 'gameLoop'
        if (isFirst) m.start = state()
        try { return cb(t) }
        finally {
            if (isFirst) m.end = state()
            else if (m.end !== null) {
                const s = document.getElementById('poster')
                m.framesAfter++
                if (s) m.presentAfter++
                if (s && visible(s)) m.visibleAfter++
            }
        }
    })
})()'''

AFTER_INIT_JS = '''() => {
    try { return {runReady: !!bootComplete && !!runInProgress,
                  loadingHidden: document.getElementById('loading').hidden} }
    catch (e) { return {error: String(e)} }
}'''


def check_size(browsers, name, shots_dir=None, shoot=False, frames=FRAMES_AFTER):
    size = bt.SIZES[name]
    browser, url = browsers.get(size['browser'])
    hold = bool(shoot and shots_dir)
    ctx, page = bt.new_page(browser, url, size, (['window.__posterHold = true'] if hold else []) + [INIT_SCRIPT])
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    row = {'size': name, 'browser': size['browser']}
    try:
        page.goto(url + 'index.html', wait_until='domcontentloaded', timeout=90000)
        page.wait_for_function('() => window.__poster.dcl !== null', timeout=60000)
        if shoot and shots_dir:
            page.wait_for_function('() => window.__poster.held === true', timeout=60000)
            row['boot_held_at_level_script'] = True
            path = Path(shots_dir) / ('poster-%s-dcl.png' % name.replace('@', '_'))
            page.screenshot(path=str(path))
            row['shot_dcl'] = str(path)
            row['at_shot'] = page.evaluate('window.__posterState()')
            page.evaluate('window.__posterRelease()')
        row['dcl'] = page.evaluate('window.__poster.dcl')
        page.wait_for_function('() => window.__poster.end !== null && window.__poster.framesAfter >= %d'
                               % frames, timeout=90000)
        page.wait_for_function('() => typeof bootComplete !== "undefined" && bootComplete && runInProgress',
                               timeout=90000)
        m = page.evaluate('window.__poster')
        row.update({'first_frame_start': m['start'], 'first_frame_end': m['end'],
                    'frames_after': m['framesAfter'], 'present_after': m['presentAfter'],
                    'visible_after': m['visibleAfter']})
        row['ready'] = page.evaluate(AFTER_INIT_JS)
        page.wait_for_function('() => window.__poster.gameReady', timeout=30000)
        row['game_ready'] = page.evaluate('window.__poster.gameReady')
        if shoot and shots_dir:
            path = Path(shots_dir) / ('poster-%s-after.png' % name.replace('@', '_'))
            page.screenshot(path=str(path))
            row['shot_after'] = str(path)
    except Exception as error:  # noqa: BLE001 - reported per size
        row['exception'] = repr(error)[:500]
    finally:
        ctx.close()
    row['errors'] = errors
    d, s, e = row.get('dcl') or {}, row.get('first_frame_start') or {}, row.get('first_frame_end') or {}
    row['checks'] = {
        'visible_at_dcl': bool(d.get('visible') and d.get('covers')),
        'decoded_at_dcl': bool(d.get('decoded')),
        'input_passes_through': d.get('pointerEvents') == 'none' and not d.get('hitsPoster'),
        'present_at_first_frame_start': bool(s.get('present')),
        'removed_by_first_frame_end': e.get('present') is False,
        'absent_in_all_later_frames': row.get('frames_after', 0) >= frames and row.get('present_after') == 0,
        'run_ready': bool((row.get('ready') or {}).get('runReady')),
        'game_ready': row.get('game_ready') is True,
        'no_errors': not errors and 'exception' not in row,
    }
    row['pass'] = all(row['checks'].values())
    return row


def run(sizes, zip_path=None, root=None, shots_dir=None, shot_sizes=(), frames=FRAMES_AFTER, log=print):
    with ExitStack() as stack:
        site = bt.serve_root(zip_path, root, stack.callback)
        poster = site / POSTER_FILE
        result = {'meta': {'source': bt.describe_source(zip_path, root), 'poster': POSTER_FILE,
                           'poster_bytes': poster.stat().st_size if poster.exists() else None,
                           'frames_after': frames}, 'sizes': {}}
        browsers = bt.Browsers(site, stack)
        for name in sizes:
            row = check_size(browsers, name, shots_dir, name in shot_sizes, frames)
            result['sizes'][name] = row
            log('%s %s %s' % ('PASS' if row['pass'] else 'FAIL', name,
                              {k: v for k, v in row['checks'].items() if not v} or ''))
        result['all_pass'] = all(r['pass'] for r in result['sizes'].values()) and \
            (result['meta']['poster_bytes'] or 1e9) <= POSTER_MAX_BYTES
        result['passed'] = sum(r['pass'] for r in result['sizes'].values())
        result['total'] = len(result['sizes'])
        return result


class PosterTest(unittest.TestCase):
    def test_poster_two_sizes(self):
        result = run(['desktop-1366x768@1', 'pixel7-portrait'], log=lambda *a: None)
        for name, row in result['sizes'].items():
            self.assertTrue(row['pass'], (name, row['checks'], row.get('exception'), row['errors']))
        self.assertLessEqual(result['meta']['poster_bytes'], POSTER_MAX_BYTES)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--sizes', default='matrix', help='comma list of size names or "matrix" (all 13)')
    p.add_argument('--zip')
    p.add_argument('--root')
    p.add_argument('--out')
    p.add_argument('--shots', help='directory for the dcl/after screenshot pairs')
    p.add_argument('--shot-sizes', default=','.join(SHOT_SIZES))
    p.add_argument('--frames', type=int, default=FRAMES_AFTER)
    args = p.parse_args(argv)
    sizes = bt.SCREEN_MATRIX if args.sizes == 'matrix' else [s for s in args.sizes.split(',') if s]
    result = run(sizes, args.zip, args.root, args.shots, args.shot_sizes.split(','), args.frames)
    text = json.dumps(result, indent=1)
    if args.out:
        Path(args.out).write_text(text + '\n')
    print('poster: %d/%d sizes pass, %s bytes, all_pass=%s' % (
        result['passed'], result['total'], result['meta']['poster_bytes'], result['all_pass']))
    return 0 if result['all_pass'] else 1


if __name__ == '__main__':
    if all(a in ('-v', '-q') for a in sys.argv[1:]):
        unittest.main()
    else:
        sys.exit(main())
