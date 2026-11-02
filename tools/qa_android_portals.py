#!/usr/bin/env python3
"""TASK-864: the itch and Y8 release zips in real Android Chrome on the emulator.

Needs the emulator up (tools/android_emulator.md on commit 11540c7: AVD
y8pixel7, Android 14, Play image Chrome). Each zip is extracted into
<out>/site/game/<portal>/ and served by a host http server; the emulator
opens the portal-like host page of tools/test_portal_display.py (phone
variant: itch's 'launch in fullscreen' iframe with itch's sandbox flags, Y8's
full-window iframe) at http://10.0.2.2:PORT/host/<portal>-phone.html, and
the game iframe is cross-origin on http://localhost:PORT/ (adb reverse), as
on the portals.

Input is real Android input (`adb shell input tap` / `input swipe` holds,
rotation via settings user_rotation). Playwright attaches to Chrome's
DevTools socket (adb forward) only to read state and errors, to answer the
Y8 SDK URL with the fake SDK of tools/test_y8_backend.py, and to abort any
other non-local request. The itch zip's vendored GameAnalytics SDK is
answered with a stub by the local server, so no event reaches GameAnalytics.

The emulator touchscreen advertises a stylus (Chrome reports pointer: fine,
recorded as 'pointerAsIs'); as in TASK-432 the coarse pointer of a
stylus-less phone is restored with Emulation.setTouchEmulationEnabled and a
reload. Chrome's flag file gets --disable-accelerated-2d-canvas, else the
swiftshader display shows the canvas blank (tools/android_emulator.md).

Per portal: portrait launch (rotate prompt, stage rotated, run paused) ->
screencap android-<portal>-portrait.png; rotate to landscape (canvas refits
to the viewport, no prompt), real tap on Resume, then real hold swipes at
grapplable world points in view until the grapnel catches (first grapple)
-> android-<portal>-landscape.png. Writes <out>/android.json; exit 1 on a
failed check.

    python3 tools/qa_android_portals.py --out artifacts/TASK-864
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_portal_display import (GA_SDK, GA_STUB, INIT, RELEASE, ROOT, SDKS, STATE,  # noqa: E402
                                 RESUME_BUTTON, host_page)

SDK_HOME = Path.home() / 'android-sdk'
ADB = str(SDK_HOME / 'platform-tools' / 'adb')
CHROME = 'com.android.chrome'
CHROME_MAIN = CHROME + '/com.google.android.apps.chrome.Main'
CDP_PORT = 9222
CHROME_FLAGS = ('--disable-fre --no-default-browser-check --no-first-run'
                ' --disable-accelerated-2d-canvas')
PORTALS = ('itch', 'y8')
HOLD_MS = 2500
MAX_HOLDS = 16

BOOTED = ('() => typeof PLATFORM !== "undefined" && PLATFORM.environment !== "pending"'
          ' && typeof bootComplete !== "undefined" && bootComplete'
          ' && document.getElementById("loading").hidden')
POINTER = '''() => ({coarse: matchMedia('(pointer: coarse)').matches,
    fine: matchMedia('(pointer: fine)').matches, maxTouchPoints: navigator.maxTouchPoints,
    touchFirst: isTouchFirstDevice(), inner: [innerWidth, innerHeight], dpr: devicePixelRatio})'''
# A touch at a known screen pixel -> this frame's client point (the probe
# swallows its own events so the calibration tap reaches no game control)
PROBE = '''() => { window.__probe = null
    const types = ['touchstart', 'touchend', 'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click']
    const swallow = e => { e.stopImmediatePropagation(); if (e.cancelable) e.preventDefault()
        if (e.type === 'touchstart' && !window.__probe) { const t = e.changedTouches[0]
            window.__probe = {x: t.clientX, y: t.clientY, dpr: devicePixelRatio} }
        if (e.type === 'click' || e.type === 'touchend')
            setTimeout(() => types.forEach(k => window.removeEventListener(k, swallow, true)), 400) }
    types.forEach(k => window.addEventListener(k, swallow, true)) }'''
# Grapple Over catches only within grappleOverAcquisitionRadius() of the
# ninja: the nearest boundary point of each grapplable, shot-able element in
# that radius (elements above the ninja first), as game-canvas points
# (world -> canvas: (p + screen) * scale[version])
TARGETS = '''() => {
    const k = scale[version], r = grappleOverAcquisitionRadius() * 0.9, out = []
    const near = (a, b) => { const dx = b.x - a.x, dy = b.y - a.y, l = dx * dx + dy * dy
        const t = l ? Math.max(0, Math.min(1, ((ninja.x - a.x) * dx + (ninja.y - a.y) * dy) / l)) : 0
        return {x: a.x + t * dx, y: a.y + t * dy} }
    for (const e of floors[0].elements) {
        if (e.grapplable === false || (grapnel.blocksShot && grapnel.blocksShot(e))) continue
        const pts = e.getPoints()
        let best = null
        for (let i = 0; i < pts.length; i++) {
            const q = near(pts[i], pts[(i + 1) % pts.length]), d = Math.hypot(q.x - ninja.x, q.y - ninja.y)
            if (!best || d < best.d) best = {x: q.x, y: q.y, d}
        }
        if (!best || best.d > r || best.d < 1) continue
        // aim a little past the edge point, along the ninja -> point line
        const ux = (best.x - ninja.x) / best.d, uy = (best.y - ninja.y) / best.d
        const ax = best.x + ux * 15, ay = best.y + uy * 15
        out.push({x: (ax + screen.x) * k, y: (ay + screen.y) * k, id: e.id, d: best.d, above: best.y < ninja.y})
    }
    out.sort((a, b) => (b.above - a.above) || (a.d - b.d))
    return out.slice(0, 8)
}'''
LANDSCAPE_STATE = '''() => { const r = canvas.getBoundingClientRect()
    return {inner: [innerWidth, innerHeight], canvasRect: [r.left, r.top, r.width, r.height].map(v => Math.round(v * 10) / 10),
        rotated: isViewRotated(), paused: menu.gamePaused, inRun: runInProgress, version,
        env: PLATFORM.environment, ticks: window.__ticks || 0} }'''
TICKS = '''() => { if (window.__tickHook) return; window.__tickHook = true; window.__ticks = 0
    const step = () => { if (!menu.gamePaused && runInProgress) window.__ticks++; requestAnimationFrame(step) }
    requestAnimationFrame(step) }'''


class Check(Exception):
    pass


def adb(*args, check=True, timeout=60):
    r = subprocess.run([ADB, *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError('adb %s: %s %s' % (' '.join(args), r.returncode, r.stderr))
    return r.stdout


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        # The itch zip ships the real GameAnalytics SDK (and keys): stub it
        if self.path.split('?')[0].endswith('/' + GA_SDK):
            body = GA_STUB.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.server.stubbed.append(self.path)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def devtools(path):
    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (CDP_PORT, path), timeout=10) as r:
        return json.load(r)


def wait_devtools(timeout=120):
    deadline = time.time() + timeout
    started = False
    while time.time() < deadline:
        try:
            return devtools('/json/version')
        except Exception:
            if not started:
                adb('shell', 'am', 'start', '-n', CHROME_MAIN)
                started = True
            time.sleep(2)
    raise RuntimeError('Chrome DevTools socket not reachable')


class Device:
    def __init__(self, out):
        self.out = out
        self.offset = None

    def rotate(self, landscape):
        adb('shell', 'settings', 'put', 'system', 'accelerometer_rotation', '0')
        adb('shell', 'settings', 'put', 'system', 'user_rotation', '1' if landscape else '0')

    def screencap(self, name):
        path = self.out / name
        with path.open('wb') as f:
            subprocess.run([ADB, 'exec-out', 'screencap', '-p'], stdout=f, check=True, timeout=30)
        return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)

    def size(self):
        # 'Physical size: 1080x2400' (+ 'Override size')
        return adb('shell', 'wm', 'size').strip().splitlines()[-1].split(':')[1].strip()

    def to_screen(self, x, y):
        (dx, dy), dpr = self.offset
        return round(dx + x * dpr), round(dy + y * dpr)

    def tap(self, x, y):
        adb('shell', 'input', 'tap', str(x), str(y))

    def hold(self, x, y, ms):
        return subprocess.Popen([ADB, 'shell', 'input', 'swipe', str(x), str(y), str(x), str(y), str(ms)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class PortalRun:
    def __init__(self, pw, dev, portal, host_url, log):
        self.pw, self.dev, self.portal, self.url, self.log = pw, dev, portal, host_url, log
        self.errors, self.blocked = [], []
        self.browser = None

    def route(self, route):
        url = route.request.url
        if url in SDKS:
            return route.fulfill(content_type='application/javascript', body=SDKS[url])
        if url.startswith(('http://10.0.2.2:', 'http://localhost:')):
            return route.continue_()
        self.blocked.append(url)
        return route.abort()

    def connect(self):
        if self.browser:
            self.context.unroute_all(behavior='ignoreErrors')
            self.browser.close()
        self.browser = self.pw.chromium.connect_over_cdp('http://127.0.0.1:%d' % CDP_PORT)
        self.context = self.browser.contexts[0]
        self.context.route('**/*', self.route)
        self.context.add_init_script(INIT)

    def attach(self, page):
        page.on('pageerror', lambda e: self.errors.append('page: %s' % e))
        page.on('console', lambda m: m.type == 'error' and self.errors.append(
            'console: %s @ %s' % (m.text, m.location.get('url', ''))))
        self.page = page

    def frame(self):
        return self.page.wait_for_selector('#game_drop', state='attached', timeout=30000).content_frame()

    def open(self):
        for t in devtools('/json'):
            if t.get('type') == 'page' and '/host/' in t.get('url', ''):
                urllib.request.urlopen('http://127.0.0.1:%d/json/close/%s' % (CDP_PORT, t['id'])).read()
        self.connect()
        # A first-time player on both origins
        cdp0 = self.context.new_cdp_session(self.context.pages[0])
        for origin in (self.url.split('/host/')[0], 'http://localhost:' + self.url.split(':')[2].split('/')[0]):
            cdp0.send('Storage.clearDataForOrigin',
                      {'origin': origin, 'storageTypes': 'local_storage,indexeddb,cookies,cache_storage'})
        adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', self.url, CHROME)
        deadline = time.time() + 40
        while not any(t.get('url') == self.url for t in devtools('/json')):
            if time.time() > deadline:
                raise Check('no tab with %s' % self.url)
            time.sleep(0.5)
        page = next((p for p in self.context.pages if p.url == self.url), None)
        if page is None:
            self.connect()
            page = next(p for p in self.context.pages if p.url == self.url)
        self.attach(page)
        page.wait_for_load_state()
        f = self.frame()
        f.wait_for_function(BOOTED, timeout=90000)
        self.pointer_as_is = f.evaluate(POINTER)
        # Stylus-less phone: coarse pointer, then reload (TASK-432)
        cdp = self.context.new_cdp_session(page)
        cdp.send('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
        self.cdp = cdp
        page.reload()
        f = self.frame()
        f.wait_for_function(BOOTED, timeout=90000)
        f.evaluate(TICKS)
        return f

    def calibrate(self, f, sx, sy):
        f.evaluate(PROBE)
        self.dev.tap(sx, sy)
        p = f.wait_for_function('window.__probe', timeout=8000).json_value()
        time.sleep(0.6)
        dpr = p['dpr']
        self.dev.offset = ((sx - p['x'] * dpr, sy - p['y'] * dpr), dpr)
        return {'screen': [sx, sy], 'client': [p['x'], p['y']], 'dpr': dpr,
                'offset': [round(v, 1) for v in self.dev.offset[0]]}

    def game_to_screen(self, f, x, y):
        p = f.evaluate('([x, y]) => canvasCoordsToViewportCoords({x, y})', [x, y])
        return self.dev.to_screen(p['x'], p['y'])

    def run(self):
        res = {'portal': self.portal, 'url': self.url, 'checks': {}}
        c = res['checks']
        self.dev.rotate(False)
        time.sleep(1.5)
        f = self.open()
        time.sleep(1.5)
        s = f.evaluate(STATE)
        pointer = f.evaluate(POINTER)
        res['pointerAsIs'] = self.pointer_as_is
        res['userAgent'] = f.evaluate('navigator.userAgent')
        res['pointer'] = pointer
        res['portraitShot'] = self.dev.screencap('android-%s-portrait.png' % self.portal)
        res['portraitState'] = {k: s[k] for k in ('inner', 'dpr', 'rotated', 'transform', 'promptVisible',
                                                  'stageHidden', 'paused', 'canvasCss', 'backing', 'logical')}
        c['boot'] = {'ok': True, 'environment': f.evaluate('PLATFORM.environment'),
                     'version': f.evaluate('version')}
        c['boot']['ok'] = c['boot']['environment'] == self.portal and c['boot']['version'] == 'grapple_over'
        c['portrait'] = {'ok': pointer['coarse'] and s['rotated'] and s['transform'] == 'rotate(90deg)'
                         and s['promptVisible'] and s['paused'] and s['inner'][1] > s['inner'][0]}
        # Landscape
        self.dev.rotate(True)
        f.wait_for_function('() => !isViewRotated() && innerWidth > innerHeight', timeout=15000)
        time.sleep(2)
        land = f.evaluate(STATE)
        ls = f.evaluate(LANDSCAPE_STATE)
        w, h = ls['inner']
        cx, cy, cw, ch = ls['canvasRect']
        # Fills the screen: touch devices use the full aspect (gameoptions.js),
        # so the canvas covers the viewport (within a 2 CSS px rounding)
        fills = abs(cw - w) <= 2 and abs(ch - h) <= 2 and abs(cx) <= 1 and abs(cy) <= 1
        c['landscape'] = {'ok': fills and not land['promptVisible'] and land['transform'] == ''
                          and not land['rotated'], 'viewport': [w, h], 'canvasRect': ls['canvasRect'],
                          'fillsViewport': fills, 'promptVisible': land['promptVisible'],
                          'backing': land['backing'], 'dpr': land['dpr']}
        # Calibrate on the empty lower-left of the paused screen (screen px, landscape 2400x1080)
        res['calibration'] = self.calibrate(f, 260, 1000)
        paused = f.evaluate('menu.gamePaused')
        if paused:
            b = f.evaluate(RESUME_BUTTON)
            xy = self.game_to_screen(f, b['x'], b['y'])
            time.sleep((f.evaluate('STYLE.timing.inputUntouchMs') + 150) / 1000)
            self.dev.tap(*xy)
            f.wait_for_function('() => !menu.gamePaused', timeout=8000)
            res['resumeTap'] = list(xy)
        t0 = f.evaluate('window.__ticks')
        time.sleep(1)
        live = f.evaluate('window.__ticks') - t0
        # First grapple: real holds at grapplable points in view
        holds = []
        grappled = False
        while not grappled and len(holds) < MAX_HOLDS:
            if f.evaluate('menu.gamePaused || !runInProgress || continueOffer.visible'):
                raise Check('run interrupted before the first grapple: %s' % f.evaluate(LANDSCAPE_STATE))
            targets = f.evaluate(TARGETS)
            t = targets[len(holds) % len(targets)] if targets else dict(
                f.evaluate('() => ({x: (ninja.x + screen.x) * scale[version] + 60,'
                           ' y: (ninja.y + screen.y) * scale[version] - 300})'), id=None)
            xy = self.game_to_screen(f, t['x'], t['y'])
            proc = self.dev.hold(*xy, HOLD_MS)
            thrown = False
            while proc.poll() is None:
                st = f.evaluate('({t: !!grapnel.throwed, g: !!grapnel.isGrappled()})')
                thrown |= st['t']
                grappled |= st['g']
                time.sleep(0.03)
            time.sleep(0.15)
            holds.append({'target': t.get('id'), 'inRange': len(targets), 'screen': list(xy), 'thrown': thrown, 'grappled': grappled,
                          'releasedAfter': not f.evaluate('!!grapnel.throwed')})
        res['landscapeShot'] = self.dev.screencap('android-%s-landscape.png' % self.portal)
        res['landscapeState'] = f.evaluate(LANDSCAPE_STATE)
        c['resume'] = {'ok': live > 0,
                       'wasPaused': paused, 'ticksIn1s': live}
        c['first_grapple'] = {'ok': grappled and holds[-1]['releasedAfter'], 'holds': holds,
                              'tutorialDone': f.evaluate('TUTORIAL_HINT.pressed')}
        time.sleep(0.5)
        frame_errors = f.evaluate('() => window.__errors || ["no INIT error hook"]')
        c['console_errors'] = {'ok': not self.errors and not frame_errors and not self.blocked,
                               'count': len(self.errors) + len(frame_errors), 'errors': self.errors + frame_errors,
                               'blocked': self.blocked}
        self.cdp.send('Emulation.setTouchEmulationEnabled', {'enabled': False})
        self.context.unroute_all(behavior='ignoreErrors')
        self.browser.close()
        self.browser = None
        return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=Path, default=ROOT / 'artifacts' / 'TASK-864')
    ap.add_argument('--port', type=int, default=8864)
    ap.add_argument('--portals', default=','.join(PORTALS))
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    site = out / 'site'
    if site.exists():
        shutil.rmtree(site)
    (site / 'host').mkdir(parents=True)
    portals = args.portals.split(',')
    zips = {}
    for p in portals:
        z = RELEASE / p / ('grapple-over-%s.zip' % p)
        zips[p] = z
        with zipfile.ZipFile(z) as zf:
            zf.extractall(site / 'game' / p)
        game = 'http://localhost:%d/game/%s/index.html' % (args.port, p)
        (site / 'host' / ('%s-phone.html' % p)).write_text(host_page(p, True, game))
    log_f = (out / 'android.log').open('w')

    def log(m):
        print(m, flush=True)
        log_f.write(m + '\n')
        log_f.flush()

    if 'emulator-' not in adb('devices'):
        log('no emulator')
        return 2
    chrome = [l.strip() for l in adb('shell', 'dumpsys', 'package', CHROME).splitlines() if 'versionName' in l][0]
    adb('shell', 'echo "_ %s" > /data/local/tmp/chrome-command-line' % CHROME_FLAGS)
    adb('shell', 'am', 'force-stop', CHROME)
    adb('reverse', 'tcp:%d' % args.port, 'tcp:%d' % args.port)
    adb('forward', 'tcp:%d' % CDP_PORT, 'localabstract:chrome_devtools_remote')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(site)))
    server.stubbed = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    dev = Device(out)
    info = {'chrome': chrome, 'android': adb('shell', 'getprop', 'ro.build.version.release').strip(),
            'sdk': adb('shell', 'getprop', 'ro.build.version.sdk').strip(),
            'device': adb('shell', 'getprop', 'ro.product.model').strip(), 'screen': dev.size(),
            'chromeFlags': adb('shell', 'cat', '/data/local/tmp/chrome-command-line').strip(),
            'realAndroidChrome': True}
    log('device %s' % json.dumps(info))
    results = []
    started = time.time()
    try:
        with sync_playwright() as pw:
            wait_devtools()
            info['devtoolsBrowser'] = devtools('/json/version').get('Browser')
            for p in portals:
                runner = PortalRun(pw, dev, p, 'http://10.0.2.2:%d/host/%s-phone.html' % (args.port, p), log)
                try:
                    r = runner.run()
                except Exception as e:
                    r = {'portal': p, 'checks': {'exception': {'ok': False, 'error': repr(e)[:1500],
                                                               'trace': traceback.format_exc(limit=5)}}}
                    try:
                        r['failShot'] = dev.screencap('fail-%s.png' % p)
                    except Exception:
                        pass
                r['zip'] = str(zips[p].relative_to(ROOT))
                r['ok'] = all(v['ok'] for v in r['checks'].values())
                r['failed'] = [k for k, v in r['checks'].items() if not v['ok']]
                log('%s %s %s' % (p, 'OK' if r['ok'] else 'FAIL', r['failed']))
                results.append(r)
    finally:
        server.shutdown()
        try:
            dev.rotate(False)
        except Exception:
            pass
    info['gaSdkStubbed'] = sorted(set(server.stubbed))
    summary = {'portals': len(results), 'ok': sum(r['ok'] for r in results),
               'fail': sum(not r['ok'] for r in results), 'seconds': round(time.time() - started, 1)}
    (out / 'android.json').write_text(json.dumps({'summary': summary, 'device': info, 'results': results},
                                                 indent=1, sort_keys=True) + '\n')
    log('SUMMARY %s' % json.dumps(summary))
    log_f.close()
    return 0 if summary['fail'] == 0 and results else 1


if __name__ == '__main__':
    sys.exit(main())
