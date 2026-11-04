"""Boot timing harness (TASK-887): how long a boot takes to show something and to be playable.

Serves a source tree (default the repo root, --root DIR) or a release zip (--zip PATH, extracted to a
temp dir) on a local http server; every non-local request is aborted. For each size in --sizes
(default TIMING_SET) it boots index.html --runs times (default 5), each boot in a fresh context, and
records per boot (all ms on the page's performance.now() clock, navigation start = 0):

  dcl_ms          DOMContentLoaded
  load_ms         window load
  first_paint_ms  first frame where any pixel is on screen: the end of the first animation frame in
                  which something was drawn on a visible, document-attached canvas, or the first frame
                  in which a loaded <img> / CSS background image (a poster) is visible. The loading
                  overlay's text does not count.
  fcp_ms          the browser's first-contentful-paint entry (informational; includes overlay text)
  first_frame_ms  duration of the first gameLoop animation-frame callback (the frame that builds the
                  lazy caches today). gameLoop is found by function name, else (minified bundles) as
                  the first rAF callback that starts with bootComplete && runInProgress.
  run_ready_ms    bootComplete && runInProgress (tools/browser_test_support.py wait_for_boot_run),
                  observed at the end of an animation-frame callback - i.e. the run's first frame
                  has been produced, as wait_for_boot_run's rAF polling sees it.

With --profile, every size gets --runs extra boots under the CDP sampling profiler (100 us, from
navigation to two frames after run ready; separate from the timing boots so the profiler's overhead
does not skew the timings) and reports inclusive CPU ms of the boot's lazy cache builders
(PROFILED_FUNCTIONS, matched by function name and file basename - a release bundle's frames map back to
their source file via window.GAME_BUNDLE_FILES, TASK-895; 0 when never sampled, e.g. once a
cache is baked at build time). Profiling needs Chromium (WebKit sizes skip it). The same functions
are also reported for the first gameLoop frame alone as first_frame.<name> (TASK-889): the samples
from the first one whose stack holds gameLoop up to the next (idle) sample - work deferred to later
frames (render/glowsprites.js BACKGROUND_BAKE_QUEUE, GLYPH_GLOW_QUEUE) lands inside the whole window
but not in the first frame. first_frame.window_ms is that span's sampled CPU ms (0 and no
first_frame.* split when no sample names gameLoop, e.g. a minified bundle).

Output (--out FILE, else stdout): compact JSON {meta, sizes: {name: {runs: [...], median: {...},
profile_runs: [...], profile_median: {...}}}}.

Headless timings are only meaningful as relative A/B on the same host in the same period: compare two
outputs with --compare A.json B.json (relative difference of the medians per size and metric).

Usage:
  python3 tools/boot_timing.py [--zip PATH | --root DIR] [--sizes a,b] [--runs N] [--profile]
                               [--query '?visualsPerf=1'] [--out FILE]
  python3 tools/boot_timing.py --compare A.json B.json [--out FILE]
  python3 tools/boot_timing.py --list-sizes
"""
import argparse
import collections
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from functools import partial  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
from threading import Thread  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

from browser_test_support import OfflineBrowser, QuietHandler, shared_memory_launch_options  # noqa: E402
# The SCREEN MATRIX reuses test_portal_display's desktop, square and phone cells
from test_portal_display import DESKTOPS, SQUARES, PHONES  # noqa: E402

# 13th size: the most common Windows laptop setting (1920x1080 panel at 125 % scaling), a fractional DPR
EXTRA_DESKTOPS = [(1536, 864, 1.25)]


def _dpr_label(dpr):
    return ('%g' % dpr)


def screen_matrix():
    """[{name, browser, context kwargs or device}] - the 13 sizes of TASK-887."""
    out = []
    for w, h, dpr in list(DESKTOPS) + EXTRA_DESKTOPS:
        out.append({'name': 'desktop-%dx%d@%s' % (w, h, _dpr_label(dpr)), 'browser': 'chromium',
                    'context': {'viewport': {'width': w, 'height': h}, 'device_scale_factor': dpr}})
    for w, h, dpr in SQUARES:
        out.append({'name': 'square-%dx%d@%s' % (w, h, _dpr_label(dpr)), 'browser': 'chromium',
                    'context': {'viewport': {'width': w, 'height': h}, 'device_scale_factor': dpr}})
    for short, device, browser in PHONES:
        for orient in ('landscape', 'portrait'):
            out.append({'name': '%s-%s' % (short, orient), 'browser': browser,
                        'device': device + (' landscape' if orient == 'landscape' else '')})
    return out


SIZES = {s['name']: s for s in screen_matrix()}
SCREEN_MATRIX = [s['name'] for s in screen_matrix()]
TIMING_SET = ['desktop-1920x1080@1', 'desktop-1366x768@1', 'desktop-1280x720@2', 'pixel7-landscape']
assert len(SCREEN_MATRIX) == 13 and all(n in SIZES for n in TIMING_SET), SCREEN_MATRIX

METRICS = ['dcl_ms', 'load_ms', 'first_paint_ms', 'fcp_ms', 'first_frame_ms', 'run_ready_ms']

# key -> (function name, file basename) of the lazy cache builders measured in TASK-887's context
PROFILED_FUNCTIONS = {
    'drawGlowGlyphs': ('drawGlowGlyphs', 'glowsprites.js'),
    'paint8': ('paint8', 'glowsprites.js'),
    'effects_paint': ('paint', 'effects.js'),
    'buildGrappleOverParallaxTiles': ('buildGrappleOverParallaxTiles', 'parallax.js'),
    'routeArrowsFor': ('routeArrowsFor', 'routearrows.js'),
    # TASK-890: one arrow (routeArrowsFor, the run-start warm and the per-frame queue call it)
    'computeRouteArrow': ('computeRouteArrow', 'routearrows.js'),
    'tutorial_hint_build': ('build', 'tutorialhint.js'),
    'palette_strips': ('buildGrappleOverPaletteStrips', 'draw.js'),
}

# Runs before any page script. Uses the real clock; only observes.
INIT_SCRIPT = r'''(() => {
    const m = window.__bootTiming = {dcl: null, load: null, firstPaint: null, firstFrame: null,
        firstFrameStart: null, runReady: null, drew: false, frames: 0, afterReady: 0}
    const now = () => performance.now()
    addEventListener('DOMContentLoaded', () => { m.dcl = now() })
    addEventListener('load', () => { m.load = now() })
    const runReady = () => {
        try { return typeof bootComplete !== 'undefined' && !!bootComplete && !!runInProgress }
        catch (e) { return false }
    }
    // Something drawn onto a canvas a player could see
    const visible = el => el && el.isConnected &&
        (el.checkVisibility ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
                            : el.offsetParent !== null) &&
        el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0
    const proto = CanvasRenderingContext2D.prototype
    for (const name of ['fillRect', 'strokeRect', 'fill', 'stroke', 'fillText', 'strokeText',
                        'drawImage', 'putImageData']) {
        const orig = proto[name]
        if (typeof orig !== 'function') continue
        proto[name] = function(...args) {
            if (!m.drew && this.canvas && this.canvas.isConnected && visible(this.canvas))
                m.drew = true
            return orig.apply(this, args)
        }
    }
    const posterVisible = () => {
        for (const img of document.images)
            if (img.complete && img.naturalWidth > 0 && visible(img)) return true
        for (const el of document.querySelectorAll('[style*="background"], .poster, #poster')) {
            const bg = getComputedStyle(el).backgroundImage
            if (bg && bg !== 'none' && visible(el)) return true
        }
        return false
    }
    const rawRaf = window.requestAnimationFrame.bind(window)
    // Observer frame (not counted as a game callback): paints that happened outside rAF, posters
    const observe = () => {
        if (m.firstPaint === null && (m.drew || posterVisible())) m.firstPaint = now()
        if (m.runReady === null || m.afterReady < 3) rawRaf(observe)
    }
    rawRaf(observe)
    window.requestAnimationFrame = cb => rawRaf(t => {
        const start = now()
        const isGameLoop = m.firstFrame === null &&
            (cb.name === 'gameLoop' || (typeof window.gameLoop === 'function' ? cb === window.gameLoop
                                                                              : runReady()))
        try { return cb(t) }
        finally {
            const end = now()
            m.frames++
            if (isGameLoop) { m.firstFrame = end - start; m.firstFrameStart = start }
            if (m.firstPaint === null && m.drew) m.firstPaint = end
            if (m.runReady === null && runReady() && m.firstFrame !== null) m.runReady = end
            else if (m.runReady !== null) m.afterReady++
        }
    })
})()'''

RESULT_JS = '''() => {
    const m = window.__bootTiming, fcp = performance.getEntriesByName('first-contentful-paint')[0]
    return {dcl_ms: m.dcl, load_ms: m.load, first_paint_ms: m.firstPaint, fcp_ms: fcp ? fcp.startTime : null,
            first_frame_ms: m.firstFrame, run_ready_ms: m.runReady}
}'''


def serve_root(zip_path, root, add_cleanup):
    if zip_path:
        scratch = tempfile.TemporaryDirectory(prefix='boot-timing-')
        add_cleanup(scratch.cleanup)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(scratch.name)
        return Path(scratch.name)
    return Path(root or ROOT)


def describe_source(zip_path, root):
    if zip_path:
        import hashlib
        data = Path(zip_path).read_bytes()
        return {'zip': str(Path(zip_path).resolve()), 'zip_sha256': hashlib.sha256(data).hexdigest(),
                'zip_bytes': len(data)}
    r = Path(root or ROOT).resolve()
    info = {'root': str(r)}
    try:
        info['head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=r, text=True).strip()
        info['dirty'] = bool(subprocess.check_output(
            ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=r, text=True).strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return info


class Browsers:
    """One local server and one Playwright instance; a browser per engine, launched on first use
    (Playwright's sync API allows one instance per thread)."""
    def __init__(self, site, stack):
        self.stack, self.by_name = stack, {}
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(site)))
        stack.callback(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(thread.join)
        stack.callback(server.shutdown)
        self.url = 'http://127.0.0.1:%d/' % server.server_port
        self.playwright = sync_playwright().start()
        stack.callback(self.playwright.stop)
        global DEVICES
        DEVICES = dict(self.playwright.devices)

    def get(self, name):
        if name not in self.by_name:
            options = (dict(args=['--no-sandbox'], **shared_memory_launch_options())
                       if name == 'chromium' else {})
            browser = getattr(self.playwright, name).launch(**options)
            self.stack.callback(browser.close)
            self.by_name[name] = OfflineBrowser(browser)
        return self.by_name[name], self.url


def context_options(size, playwright_devices):
    if 'device' in size:
        return {k: v for k, v in playwright_devices[size['device']].items() if k != 'default_browser_type'}
    return dict(size['context'])


def new_page(browser, url, size, init_scripts=()):
    ctx = browser.new_context(locale='en-US', **context_options(size, DEVICES))
    ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())
    for s in init_scripts:
        ctx.add_init_script(s)
    return ctx, ctx.new_page()


DEVICES = None  # Playwright device descriptors, set by Browsers


def wait_ready(page, timeout=90000):
    page.wait_for_function('() => window.__bootTiming && window.__bootTiming.runReady !== null'
                           ' && window.__bootTiming.afterReady >= 2', timeout=timeout)


def timing_boot(browser, url, size, query, errors):
    ctx, page = new_page(browser, url, size, [INIT_SCRIPT])
    try:
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html' + query)
        wait_ready(page)
        return {k: (round(v, 1) if isinstance(v, (int, float)) else v)
                for k, v in page.evaluate(RESULT_JS).items()}
    finally:
        ctx.close()


BUNDLE_NAME = re.compile(r'^game-[0-9a-f]+\.js$')


def frame_file(f, bundle_table=None):
    """File basename of a CPU profile callFrame. A release zip runs one bundle (TASK-893): a frame inside
    game-<sha>.js maps to the basename of its source part via window.GAME_BUNDLE_FILES
    ([[first line (1-based), source path, sha], ...]), like render/visualsperf.js sourceLine."""
    name = f['url'].split('?')[0].split('/')[-1]
    if bundle_table and BUNDLE_NAME.match(name):
        line, part = f.get('lineNumber', -1) + 1, None
        for row in bundle_table:
            if row[0] <= line:
                part = row
        if part:
            return part[1].split('#')[0].split('/')[-1]
    return name


def aggregate_profile(prof, bundle_table=None):
    nodes = {n['id']: n for n in prof['nodes']}
    parent = {}
    for n in prof['nodes']:
        for c in n.get('children', []):
            parent[c] = n['id']
    wanted = {v: k for k, v in PROFILED_FUNCTIONS.items()}
    incl = collections.Counter()
    deltas = prof['timeDeltas']
    for s, d in zip(prof['samples'], deltas[1:] + [0]):
        seen, i = set(), s
        while i in nodes:
            f = nodes[i]['callFrame']
            key = wanted.get((f['functionName'], frame_file(f, bundle_table)))
            if key and key not in seen:
                incl[key] += d
                seen.add(key)
            i = parent.get(i)
    out = {k: round(incl.get(k, 0) / 1000, 1) for k in PROFILED_FUNCTIONS}
    out['profiled_total_ms'] = round(sum(deltas) / 1000, 1)
    # The first gameLoop frame: first sample under gameLoop up to the next (idle) sample
    first, window, started = collections.Counter(), 0, False
    for s, d in zip(prof['samples'], deltas[1:] + [0]):
        names, i = [], s
        while i in nodes:
            f = nodes[i]['callFrame']
            names.append((f['functionName'], frame_file(f, bundle_table)))
            i = parent.get(i)
        if not started:
            if not any(n == 'gameLoop' for n, _ in names):
                continue
            started = True
        if names and names[0][0] == '(idle)':
            break
        window += d
        for key in {wanted[n] for n in names if n in wanted}:
            first[key] += d
    for k in PROFILED_FUNCTIONS:
        out['first_frame.' + k] = round(first.get(k, 0) / 1000, 1)
    out['first_frame.window_ms'] = round(window / 1000, 1)
    return out


def profile_boot(browser, url, size, query, errors):
    ctx, page = new_page(browser, url, size, [INIT_SCRIPT])
    try:
        page.on('pageerror', lambda e: errors.append(str(e)))
        cdp = ctx.new_cdp_session(page)
        cdp.send('Profiler.enable')
        cdp.send('Profiler.setSamplingInterval', {'interval': 100})
        cdp.send('Profiler.start')
        page.goto(url + 'index.html' + query)
        wait_ready(page)
        prof = cdp.send('Profiler.stop')['profile']
        table = page.evaluate('() => Array.isArray(window.GAME_BUNDLE_FILES) ? window.GAME_BUNDLE_FILES : null')
        result = aggregate_profile(prof, table)
        result['run_ready_ms'] = round(page.evaluate('() => __bootTiming.runReady'), 1)
        return result
    finally:
        ctx.close()


def medians(rows, keys):
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        out[k] = round(statistics.median(vals), 1) if vals else None
    return out


def run(zip_path=None, root=None, sizes=TIMING_SET, runs=5, profile=False, query='', log=print):
    meta = {'tool': 'tools/boot_timing.py', 'source': describe_source(zip_path, root), 'runs': runs,
            'profile': profile, 'query': query, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'host_load_before': list(os.getloadavg()), 'metrics': METRICS,
            'profiled_functions': {k: list(v) for k, v in PROFILED_FUNCTIONS.items()}}
    result = {'meta': meta, 'sizes': {}}
    errors = []
    with ExitStack() as stack:
        site = serve_root(zip_path, root, stack.callback)
        browsers = Browsers(site, stack)
        for name in sizes:
            size = SIZES[name]
            browser, url = browsers.get(size['browser'])
            rows = []
            for i in range(runs):
                rows.append(timing_boot(browser, url, size, query, errors))
                log('%s timing %d/%d %s' % (name, i + 1, runs, json.dumps(rows[-1])))
            entry = {'runs': rows, 'median': medians(rows, METRICS)}
            if profile and size['browser'] == 'chromium':
                prows = []
                for i in range(runs):
                    prows.append(profile_boot(browser, url, size, query, errors))
                    log('%s profile %d/%d %s' % (name, i + 1, runs, json.dumps(prows[-1])))
                entry['profile_runs'] = prows
                entry['profile_median'] = medians(prows, list(prows[0]))
            result['sizes'][name] = entry
    meta['host_load_after'] = list(os.getloadavg())
    meta['page_errors'] = errors[:20]
    meta['page_error_count'] = len(errors)
    return result


def rel(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    if a == 0:
        return 0.0 if b == 0 else None
    return round((b - a) / a, 4)


def compare(a, b):
    """Relative difference (B - A) / A of the medians, per size and metric, plus the largest |diff|
    per metric over all sizes."""
    out = {'a': a['meta']['source'], 'b': b['meta']['source'], 'sizes': {}, 'max_abs_rel_by_metric': {}}
    for name in a['sizes']:
        if name not in b['sizes']:
            continue
        sa, sb = a['sizes'][name], b['sizes'][name]
        row = {k: rel(sa['median'].get(k), sb['median'].get(k)) for k in sa['median']}
        if 'profile_median' in sa and 'profile_median' in sb:
            row.update({'profile.' + k: rel(sa['profile_median'].get(k), sb['profile_median'].get(k))
                        for k in sa['profile_median']})
        out['sizes'][name] = row
        for k, v in row.items():
            if v is not None:
                out['max_abs_rel_by_metric'][k] = max(out['max_abs_rel_by_metric'].get(k, 0.0), abs(v))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group()
    src.add_argument('--zip')
    src.add_argument('--root')
    p.add_argument('--sizes', default=','.join(TIMING_SET),
                   help='comma list of size names (see --list-sizes); "matrix" = all 13')
    p.add_argument('--runs', type=int, default=5)
    p.add_argument('--profile', action='store_true')
    p.add_argument('--query', default='', help="extra URL query, e.g. '?visualsPerf=1'")
    p.add_argument('--out')
    p.add_argument('--compare', nargs=2, metavar=('A', 'B'))
    p.add_argument('--list-sizes', action='store_true')
    args = p.parse_args(argv)
    if args.list_sizes:
        print('\n'.join(n + ('  (timing set)' if n in TIMING_SET else '') for n in SCREEN_MATRIX))
        return 0
    if args.compare:
        result = compare(*(json.loads(Path(f).read_text()) for f in args.compare))
    else:
        sizes = SCREEN_MATRIX if args.sizes == 'matrix' else [s for s in args.sizes.split(',') if s]
        unknown = [s for s in sizes if s not in SIZES]
        if unknown:
            p.error('unknown sizes %s (see --list-sizes)' % unknown)
        log = lambda s: print(s, file=sys.stderr, flush=True)
        result = run(args.zip, args.root, sizes, args.runs, args.profile, args.query, log=log)
    text = json.dumps(result, separators=(',', ':'))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + '\n')
        if not args.compare:
            for name, e in result['sizes'].items():
                print(name, json.dumps(e['median']), json.dumps(e.get('profile_median', {})))
        else:
            print(json.dumps(result['max_abs_rel_by_metric']))
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
