"""TASK-863: scaling and orientation matrix of the four release zips.

Each zip (artifacts/release-grapple-over/<portal>/grapple-over-<portal>.zip,
or <PORTAL>_ZIP) is extracted into a temp dir and served over real http by a
local ThreadingHTTPServer. The game is loaded from http://localhost:PORT/
game/<portal>/ inside a host page on another origin (http://127.0.0.1:PORT/
host/...) that imitates the portal's embed:

- itch     desktop: the iframe itch.io emits (sandbox flags, allow list,
           allowfullscreen) at the 'Embed in page' size 960x540 inside an
           itch-like game page, plus itch's fullscreen button (the cell is
           measured again in fullscreen); phones: itch's 'Mobile friendly /
           launch in fullscreen' overlay, a fixed 100vw x 100vh iframe.
- gamepix  full-window iframe (desktop and phones).
- y8       desktop: the game page frame at 800x600 (Y8 shows HTML5 games
           at the size set in its upload form; 800x600 is the old Y8 frame,
           4:3, the narrowest box the game supports); phones: full-window
           iframe (old tools/qa_y8_mobile.py on the y8 branch).
- playgama full-window iframe, with the FAKE bridge of
           tools/test_playgama_backend.py (LOCAL_BRIDGE). Nothing Playgama
           hosts is ever requested.

Portal SDK URLs are answered in-process with the fake SDKs of the backend
suites (tools/test_{gamepix,y8,playgama}_backend.py); the itch zip's
vendored GameAnalytics SDK is stubbed; every other non-local request is
aborted and recorded.

Viewports: desktop 1920x1080, 1366x768, 1280x720 at DPR 1 and 2
(Chromium); phones from Playwright's device list, iPhone 13 (WebKit) and
Pixel 7 (Chromium), landscape and portrait. Square windows (Playgama 1.6.8): 800x800 at
DPR 1 and 1080x1080 at DPR 2 (Chromium). 4 portals x 12 cells.

Checks per cell (all must hold):
- frame: the game iframe box is the portal's intended size, and the game
  document's window is exactly that box (no border, no inner scroll).
- canvas: the canvas CSS rect equals the rect computed here from the frame
  size (gameoptions.js rules re-derived in Python: logical aspect clamped to
  [1:1, 2:1] on desktop, uncapped on touch; centred letterbox), and on
  screen (getBoundingClientRect, in the host page) it sits inside the frame.
- no_scroll: no scrollbars in the game document; also none in the host page
  for the full-window embeds.
- hud: HUD and pause screen text/buttons (menu.js LAYOUT_PROBE) inside the
  canvas (tools/layout_matrix.py evaluate, 'clipped' empty), text >= 12 CSS
  px and, on touch, buttons >= 44 CSS px (the layout_matrix.py rules).
- dpr: canvas backing store == round(CSS size * DPR * BACKDROP.resolution),
  DPR capped at 2 on touch (configureCanvasViewport), resolution 1.
- orientation: phones in portrait: isViewRotated(), the stage turned
  rotate(90deg), the rotate prompt visible and the run paused; landscape
  and desktop: not rotated, no prompt.
- tap: a real click/tap (page.mouse / page.touchscreen in the HOST page,
  through the iframe) aimed via canvasCoordsToViewportCoords at a game
  point (rounded to the nearest whole host px, as event client coordinates
  are whole px) lands there: the window listener sees exactly the aimed
  client point, and viewportCoordsToCanvasCoords maps it back within 1 CSS px. Desktop and
  landscape: tapping the HUD menu button opens the pause screen.
  Portrait: the tap reaches nothing (stage inert, run stays paused); then the
  phone turns to landscape (the device's landscape viewport): the prompt
  goes away, the stage is not rotated, the canvas refits, and tapping the
  Resume button (CLIMB_UI.buttons[0]) resumes the run.
- itch desktop also: after itch's fullscreen button the canvas checks hold
  for the full viewport.
- square (square cells; itch also in fullscreen): the canvas covers the
  whole game iframe box (no letterbox bars) and every HUD, pause and
  'Go back?' dialog element box (LAYOUT_PROBE) lies inside the canvas with
  no overlaps.
- errors: no uncaught errors, unhandled rejections, console errors, blocked
  or missing requests.

PORTAL_DISPLAY_EVIDENCE_DIR=DIR writes DIR/matrix.json (per-cell checks),
DIR/cells/<portal>-<cell>.png (+ -landscape / -fullscreen) and
DIR/grid-<portal>.png. PORTAL_DISPLAY_PORTALS=itch,y8 limits the portals,
PORTAL_DISPLAY_CELLS=desktop-1280x720@1,pixel7-portrait the cells (debugging).

    python3 tools/test_portal_display.py -v
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Thread
import time
import unittest
import zipfile

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_matrix as lm
from test_gamepix_backend import FAKE_SDK as GAMEPIX_SDK
from test_y8_backend import FAKE_SDK as Y8_SDK
from test_playgama_backend import FAKE_BRIDGE as PLAYGAMA_BRIDGE

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / 'artifacts' / 'release-grapple-over'
PORTALS = ('itch', 'gamepix', 'y8', 'playgama')
SDKS = {
    'https://integration.gamepix.com/sdk/v3/gamepix.sdk.js': GAMEPIX_SDK,
    'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js': Y8_SDK,
    'https://bridge.playgama.com/v2/stable/playgama-bridge.js': PLAYGAMA_BRIDGE,
}
GA_SDK = 'analytics/vendor/GameAnalytics.min.js'
GA_STUB = '// GameAnalytics stub (test_portal_display): no network\n'
# Desktop embed boxes; None = the whole window
DESKTOP_FRAME = {'itch': (960, 540), 'gamepix': None, 'y8': (800, 600), 'playgama': None}
ITCH_SANDBOX = ('allow-scripts allow-same-origin allow-pointer-lock allow-forms '
                'allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals')
ITCH_ALLOW = ('autoplay; fullscreen *; geolocation; microphone; camera; midi; monetization; '
              'xr-spatial-tracking; gamepad; gyroscope; accelerometer; xr; cross-origin-isolated; web-share')
LOGICAL_HEIGHT = 1080
TOL = 1.01   # CSS px

DESKTOPS = [(w, h, dpr) for (w, h) in [(1920, 1080), (1366, 768), (1280, 720)] for dpr in (1, 2)]
# Square (1:1) desktop windows (Playgama requirement 1.6.8): the game fills
# the area, no letterbox bars, no clipped or overlapping elements
SQUARES = [(800, 800, 1), (1080, 1080, 2)]
PHONES = [('iphone13', 'iPhone 13', 'webkit'), ('pixel7', 'Pixel 7', 'chromium')]

READY = ('typeof PLATFORM !== "undefined" && PLATFORM.environment !== "pending" && bootComplete'
         ' && runInProgress && document.getElementById("loading").hidden')

INIT = r'''(() => {
    window.__errors = []
    addEventListener('error', e => __errors.push('error: ' + (e.message || e.type)))
    addEventListener('unhandledrejection', e => __errors.push('unhandledrejection: ' +
        (e.reason && e.reason.message || String(e.reason))))
    // Where the last real pointer/touch landed, in this document's client px
    window.__taps = []
    const rec = (x, y, type) => window.__taps.push({x, y, type})
    addEventListener('mousedown', e => rec(e.clientX, e.clientY, 'mousedown'), true)
    addEventListener('touchstart', e => { const t = e.changedTouches[0]; rec(t.clientX, t.clientY, 'touchstart') }, true)
})()'''

STATE = '''() => {
    const css = (el) => { const s = el.style; return {left: parseFloat(s.left), top: parseFloat(s.top),
        width: parseFloat(s.width), height: parseFloat(s.height)} }
    const stage = document.getElementById('stage')
    const prompt = document.getElementById('rotate-prompt')
    const pr = prompt.getBoundingClientRect()
    const d = document.documentElement
    return {inner: [innerWidth, innerHeight], dpr: devicePixelRatio, touch: isTouchFirstDevice(),
        rotated: isViewRotated(), logical: [width, height], transform: stage.style.transform,
        canvasCss: css(canvas), backing: [canvas.width, canvas.height],
        resolution: typeof BACKDROP != 'undefined' ? BACKDROP.resolution : 1,
        expectedRect: getCanvasCssRect(),
        promptVisible: getComputedStyle(prompt).display !== 'none' && getComputedStyle(prompt).visibility !== 'hidden'
            && pr.width >= innerWidth - 1 && pr.height >= innerHeight - 1,
        stageHidden: getComputedStyle(stage).visibility === 'hidden', stageInert: !!stage.inert,
        paused: menu.gamePaused,
        scroll: {sw: d.scrollWidth, sh: d.scrollHeight, cw: d.clientWidth, ch: d.clientHeight,
                 bsw: document.body.scrollWidth, bsh: document.body.scrollHeight},
        errors: window.__errors}
}'''

HOST_SCROLL = '''() => { const d = document.documentElement
    return {sw: d.scrollWidth, sh: d.scrollHeight, cw: d.clientWidth, ch: d.clientHeight} }'''

# A game point -> this document's client point, and the button centres used
TO_VIEWPORT = '([x, y]) => canvasCoordsToViewportCoords({x, y})'
TO_CANVAS = '([x, y]) => viewportCoordsToCanvasCoords({x, y})'
# menu.button is laid out in HUD units (layoutHud divides by scale[version])
MENU_BUTTON = '''() => { const b = menu.button.background, k = scale[version]
    return {x: (b.x + b.width / 2) * k, y: (b.y + b.height / 2) * k} }'''
# CLIMB_UI (menu.js) lays out its buttons when the pause screen is drawn
# The 'Go back?' dialog (CLIMB_UI.offerGoBack) drawn once, without its
# analytics or pause side effects
GO_BACK_DRAW = ('const c = CLIMB_UI, g = c.goingBack, w = c.goBackWorld; c.goingBack = true; '
                'c.goBackWorld = floors[0]; try { menu.drawPauseScreen() } '
                'finally { c.goingBack = g; c.goBackWorld = w }')
RESUME_BUTTON = '''() => { menu.drawPauseScreen(); const b = CLIMB_UI.buttons[0].background
    return {x: b.x + b.width / 2, y: b.y + b.height / 2} }'''


def expected_layout(w, h, touch, dpr, resolution=1):
    """gameoptions.js getCanvasCssRect / configureCanvasViewport for a w x h window."""
    rotated = touch and w < h
    vw, vh = (h, w) if rotated else (w, h)
    aspect = min(math.inf if touch else 2, max(1, vw / vh))
    lw = (math.floor if touch else round)(LOGICAL_HEIGHT * aspect)
    fit = min(vw / lw, vh / LOGICAL_HEIGHT)
    cw, ch = lw * fit, LOGICAL_HEIGHT * fit
    rect = {'left': (vw - cw) / 2, 'top': (vh - ch) / 2, 'width': cw, 'height': ch}
    eff = (min(dpr, 2) if touch else dpr) * resolution
    return {'rotated': rotated, 'logical': [lw, LOGICAL_HEIGHT], 'rect': rect,
            'backing': [max(1, round(cw * eff)), max(1, round(ch * eff))]}


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def rect_close(a, b, tol=TOL):
    return all(close(a[k], b[k], tol) for k in ('left', 'top', 'width', 'height'))


def host_page(portal, phone, game_url):
    """The portal-like page holding the game iframe (id game_drop)."""
    head = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Grapple Over - %s host</title><style>%s</style></head><body>')
    full = ('html,body{margin:0;height:100%;overflow:hidden;background:#000}'
            '#game_drop{position:fixed;left:0;top:0;width:100%;height:100%;border:0;display:block}')
    if portal == 'itch' and not phone:
        css = ('body{margin:0;background:#2e2e2e;color:#ddd;font:16px sans-serif}'
               'header{height:120px;padding:20px;box-sizing:border-box}'
               '.game_frame{position:relative;margin:0 auto;width:960px;height:540px;background:#000}'
               '.game_frame iframe{display:block;width:100%;height:100%;border:0}'
               '.controls{width:960px;margin:8px auto;text-align:right}'
               '.description{width:960px;margin:0 auto;height:1500px}')
        body = ('<header><h1>Grapple Over</h1></header>'
                '<div class="game_frame" id="game_frame">'
                '<iframe id="game_drop" frameborder="0" allowfullscreen="true" scrolling="no" '
                'allowtransparency="true" webkitallowfullscreen="true" mozallowfullscreen="true" '
                'msallowfullscreen="true" allow="%s" sandbox="%s" src="%s"></iframe></div>'
                '<div class="controls"><button id="fullscreen_btn" '
                'onclick="document.getElementById(\'game_drop\').requestFullscreen()">Fullscreen</button></div>'
                '<div class="description">Throw the grapnel and climb.</div>'
                % (ITCH_ALLOW, ITCH_SANDBOX, game_url))
        return head % (portal, css) + body + '</body></html>'
    if portal == 'y8' and not phone:
        css = ('body{margin:0;background:#1d1d1d;color:#ddd;font:14px sans-serif}'
               'header{height:90px}'
               '#frame_box{width:800px;height:600px;margin:0 auto;background:#000}'
               '#game_drop{display:block;width:800px;height:600px;border:0}'
               'footer{height:900px}')
        body = ('<header>Y8 header</header><div id="frame_box">'
                '<iframe id="game_drop" src="%s" allow="autoplay; fullscreen" allowfullscreen '
                'scrolling="no" frameborder="0"></iframe></div><footer>comments</footer>' % game_url)
        return head % (portal, css) + body + '</body></html>'
    # Full window: GamePix, Playgama, Y8 phones, itch's mobile fullscreen launch
    extra = ' sandbox="%s"' % ITCH_SANDBOX if portal == 'itch' else ''
    body = ('<iframe id="game_drop" src="%s" allow="autoplay; fullscreen; gamepad" allowfullscreen '
            'scrolling="no" frameborder="0"%s></iframe>' % (game_url, extra))
    return head % (portal, full) + body + '</body></html>'


def cells():
    out = []
    for w, h, dpr in DESKTOPS:
        out.append({'cell': 'desktop-%dx%d@%d' % (w, h, dpr), 'kind': 'desktop', 'browser': 'chromium',
                    'context': {'viewport': {'width': w, 'height': h}, 'device_scale_factor': dpr}})
    for w, h, dpr in SQUARES:
        out.append({'cell': 'square-%dx%d@%d' % (w, h, dpr), 'kind': 'square', 'browser': 'chromium',
                    'context': {'viewport': {'width': w, 'height': h}, 'device_scale_factor': dpr}})
    for short, device, browser in PHONES:
        for orient in ('landscape', 'portrait'):
            out.append({'cell': '%s-%s' % (short, orient), 'kind': orient, 'browser': browser,
                        'device': device})
    return out


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


class PortalDisplayTests(unittest.TestCase):
    rows = []

    @classmethod
    def setUpClass(cls):
        cls.out = os.environ.get('PORTAL_DISPLAY_EVIDENCE_DIR')
        cls.out = Path(cls.out).resolve() if cls.out else None
        cls.tmp = Path(tempfile.mkdtemp(prefix='portal-display-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.zips = {}
        for portal in PORTALS:
            z = Path(os.environ.get(portal.upper() + '_ZIP') or
                     RELEASE / portal / ('grapple-over-%s.zip' % portal))
            if not z.is_file():
                raise unittest.SkipTest('no %s zip: run tools/build_release.py --portal all' % z)
            cls.zips[portal] = z
            with zipfile.ZipFile(z) as f:
                f.extractall(cls.tmp / 'game' / portal)
            (cls.tmp / 'host').mkdir(exist_ok=True)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(cls.tmp)))
        cls.addClassCleanup(server.server_close)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        cls.port = server.server_port
        for portal in PORTALS:
            game = 'http://localhost:%d/game/%s/index.html' % (cls.port, portal)
            for phone in (False, True):
                name = '%s%s.html' % (portal, '-phone' if phone else '')
                (cls.tmp / 'host' / name).write_text(host_page(portal, phone, game))
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        cls.browsers = {
            'chromium': cls.pw.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage']),
            'webkit': cls.pw.webkit.launch(),
        }
        for b in cls.browsers.values():
            cls.addClassCleanup(b.close)
        cls.addClassCleanup(cls.save)

    @classmethod
    def save(cls):
        if not cls.out:
            return
        cls.out.mkdir(parents=True, exist_ok=True)
        (cls.out / 'matrix.json').write_text(json.dumps(cls.rows, separators=(',', ':')) + '\n')
        for portal in PORTALS:
            rows = [r for r in cls.rows if r['portal'] == portal]
            if rows:
                make_grid(cls.out, portal, rows)

    # -- serving ------------------------------------------------------------

    def route(self, route):
        url = route.request.url
        local = ('http://127.0.0.1:%d/' % self.port, 'http://localhost:%d/' % self.port)
        if url in SDKS:
            return route.fulfill(content_type='application/javascript', body=SDKS[url])
        if url.startswith(local):
            path = url.split('/', 3)[3].split('?')[0].split('#')[0]
            if path.endswith('/' + GA_SDK):
                return route.fulfill(content_type='application/javascript', body=GA_STUB)
            if not (self.tmp / path).is_file():
                self.missing.append(path)
            return route.continue_()
        self.blocked.append(url)
        return route.abort()

    def open(self, portal, cell):
        browser = self.browsers[cell['browser']]
        if 'device' in cell:
            device = self.pw.devices[cell['device'] + (' landscape' if cell['kind'] == 'landscape' else '')]
            options = {k: v for k, v in device.items() if k != 'default_browser_type'}
        else:
            options = dict(cell['context'])
        context = browser.new_context(locale='en-US', **options)
        self.addCleanup(context.close)
        context.add_init_script(INIT)
        context.route('**/*', self.route)
        page = context.new_page()
        page.on('pageerror', lambda e: self.errors.append('page: %s' % e))
        page.on('console', lambda m: m.type == 'error' and self.errors.append('console: %s' % m.text))
        phone = 'device' in cell
        page.goto('http://127.0.0.1:%d/host/%s%s.html' % (self.port, portal, '-phone' if phone else ''))
        frame = page.wait_for_selector('#game_drop').content_frame()
        frame.wait_for_function(READY, timeout=60000)
        page.wait_for_timeout(400)
        return context, page, frame, phone

    # -- measuring ------------------------------------------------------------

    def measure(self, page, frame, intended, touch, dpr, full_window, square=False):
        """Geometry, HUD and scroll checks for the current state."""
        s = frame.evaluate(STATE)
        box = page.locator('#game_drop').bounding_box()
        canvas_box = frame.locator('#canvas').bounding_box()
        w, h = s['inner']
        exp = expected_layout(w, h, touch, dpr, s['resolution'])
        checks = {}
        frame_ok = close(box['width'], intended[0]) and close(box['height'], intended[1]) \
            and close(w, box['width']) and close(h, box['height'])
        checks['frame'] = {'ok': frame_ok, 'iframe': [box['width'], box['height']],
                           'inner': [w, h], 'intended': list(intended)}
        on_screen = canvas_box is not None and \
            canvas_box['x'] >= box['x'] - TOL and canvas_box['y'] >= box['y'] - TOL and \
            canvas_box['x'] + canvas_box['width'] <= box['x'] + box['width'] + TOL and \
            canvas_box['y'] + canvas_box['height'] <= box['y'] + box['height'] + TOL
        # Rotated: the on-screen box is the turned rect (width <-> height)
        if canvas_box is not None:
            seen = (canvas_box['height'], canvas_box['width']) if exp['rotated'] else \
                (canvas_box['width'], canvas_box['height'])
            size_ok = close(seen[0], exp['rect']['width']) and close(seen[1], exp['rect']['height'])
        else:
            size_ok = False
        checks['canvas'] = {'ok': rect_close(s['canvasCss'], exp['rect']) and
                            rect_close(s['expectedRect'], exp['rect']) and
                            s['logical'] == exp['logical'] and on_screen and size_ok,
                            'css': s['canvasCss'], 'expected': exp['rect'], 'logical': s['logical'],
                            'expectedLogical': exp['logical'], 'onScreen': canvas_box,
                            'letterbox': [round(w - (exp['rect']['height'] if exp['rotated'] else exp['rect']['width']), 2),
                                          round(h - (exp['rect']['width'] if exp['rotated'] else exp['rect']['height']), 2)]}
        sc = s['scroll']
        game_scroll = sc['sw'] > sc['cw'] or sc['sh'] > sc['ch'] or sc['bsw'] > w or sc['bsh'] > h
        hs = page.evaluate(HOST_SCROLL)
        host_scroll = hs['sw'] > hs['cw'] or hs['sh'] > hs['ch']
        checks['no_scroll'] = {'ok': not game_scroll and not (full_window and host_scroll),
                               'game': sc, 'host': hs, 'hostChecked': full_window}
        hud = {}
        for screen in ('hud', 'pause'):
            row, _ = lm.evaluate(frame.evaluate(lm.PROBE, lm.DRAW[screen]), touch)
            hud[screen] = {'clipped': row['clipped'], 'boxes': row['boxes'],
                           'min_font_px': row['min_font_px'], 'min_button_px': row['min_button_px'],
                           'overlaps': row['overlaps']}
        frame.evaluate('() => draw()')
        checks['hud'] = {'ok': all(not v['clipped'] and v['boxes'] > 0 and
                                   v['min_font_px'] is not None and v['min_font_px'] >= lm.MIN_FONT_PX - 0.01 and
                                   (not touch or (v['min_button_px'] or 0) >= lm.MIN_BUTTON_PX - 0.01)
                                   for v in hud.values()), **hud}
        checks['dpr'] = {'ok': s['backing'] == exp['backing'] and s['resolution'] == 1,
                         'backing': s['backing'], 'expected': exp['backing'], 'dpr': s['dpr'],
                         'resolution': s['resolution']}
        if square:
            checks['square'] = self.square_check(frame, box, canvas_box, touch)
        return s, exp, checks

    def square_check(self, frame, box, canvas_box, touch):
        """1:1 window: the canvas covers the whole iframe box (no letterbox
        bars) and every HUD / pause / Go back element box lies inside the
        canvas without overlapping another."""
        covers = canvas_box is not None and all(
            close(canvas_box[k], box[k]) for k in ('x', 'y', 'width', 'height'))
        screens = {}
        for screen, code in (('hud', lm.DRAW['hud']), ('pause', lm.DRAW['pause']), ('goback', GO_BACK_DRAW)):
            row, boxes = lm.evaluate(frame.evaluate(lm.PROBE, code), touch)
            screens[screen] = {'clipped': row['clipped'], 'overlaps': row['overlaps'],
                               'boxes': [[b['name'], round(b['x'], 1), round(b['y'], 1),
                                          round(b['width'], 1), round(b['height'], 1)] for b in boxes]}
        frame.evaluate('() => draw()')
        ok = covers and all(v['boxes'] and not v['clipped'] and not v['overlaps'] for v in screens.values())
        r = lambda b: b and [round(b[k], 1) for k in ('x', 'y', 'width', 'height')]
        return {'ok': ok, 'covers': covers, 'iframeBox': r(box), 'canvasBox': r(canvas_box), **screens}

    def tap(self, page, frame, phone, point):
        """Real click/tap at a game point; returns where it landed in game units."""
        target = frame.evaluate(TO_VIEWPORT, [point['x'], point['y']])
        box = page.locator('#game_drop').bounding_box()
        # A fixed embed wider than the window (itch's 960 px frame in an
        # 800 px square window): scroll the host page, as a player would,
        # until the aimed point is on screen
        vp = page.viewport_size
        dx = box['x'] + target['x'] - (vp['width'] - 1)
        if dx > 0 or box['x'] + target['x'] < 0:
            page.evaluate('(dx) => scrollBy(dx, 0)', dx + 40 if dx > 0 else box['x'] + target['x'] - 40)
            page.wait_for_timeout(100)
            box = page.locator('#game_drop').bounding_box()
        frame.evaluate('() => { window.__taps = [] }')
        # Mouse/touch client coordinates are whole CSS px: aim at the nearest
        # whole host pixel, so the landed point is the aimed one exactly
        x, y = round(box['x'] + target['x']), round(box['y'] + target['y'])
        aimed = {'x': x - box['x'], 'y': y - box['y']}
        if phone:
            page.touchscreen.tap(x, y)
        else:
            page.mouse.click(x, y)
        try:
            frame.wait_for_function('() => window.__taps.length > 0', timeout=5000)
        except Exception:
            return {'game': point, 'client': target, 'landed': None, 'ok': False}
        hit = frame.evaluate('() => window.__taps[0]')
        back = frame.evaluate(TO_CANVAS, [hit['x'], hit['y']])
        # Error in CSS px: game units * CSS px per game unit
        scale = frame.evaluate('() => getCanvasCssRect().height / height')
        err = math.hypot(back['x'] - point['x'], back['y'] - point['y']) * scale
        inside = 0 <= target['x'] <= box['width'] and 0 <= target['y'] <= box['height']
        exact = close(hit['x'], aimed['x'], 0.01) and close(hit['y'], aimed['y'], 0.01)
        return {'game': point, 'client': target, 'aimed': aimed, 'landed': hit, 'mappedBack': back,
                'errorCssPx': round(err, 3), 'insideFrame': inside, 'landedExact': exact,
                'ok': err <= TOL and inside and exact}

    def shot(self, page, name):
        if not self.out:
            return None
        path = self.out / 'cells' / (name + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path))
        return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)

    # -- one cell -------------------------------------------------------------

    def run_cell(self, portal, cell):
        self.errors, self.blocked, self.missing = [], [], []
        t0 = time.time()
        context, page, frame, phone = self.open(portal, cell)
        vp = page.viewport_size
        dpr = cell['context']['device_scale_factor'] if 'context' in cell else \
            self.pw.devices[cell['device']]['device_scale_factor']
        full_window = phone or DESKTOP_FRAME[portal] is None
        intended = (vp['width'], vp['height']) if full_window else DESKTOP_FRAME[portal]
        row = {'portal': portal, 'cell': cell['cell'], 'browser': cell['browser'],
               'viewport': [vp['width'], vp['height']], 'dpr': dpr, 'touch': phone,
               'embed': 'full-window' if full_window else '%dx%d iframe' % intended,
               'zip': str(self.zips[portal].relative_to(ROOT))}
        square = cell['kind'] == 'square'
        s, exp, checks = self.measure(page, frame, intended, phone, dpr, full_window, square)
        portrait = cell['kind'] == 'portrait'
        checks['orientation'] = {
            'ok': (s['rotated'] and s['transform'] == 'rotate(90deg)' and s['promptVisible'] and
                   s['stageHidden'] and s['stageInert'] and s['paused']) if portrait else
                  (not s['rotated'] and s['transform'] == '' and not s['promptVisible'] and not s['stageHidden']),
            'rotated': s['rotated'], 'transform': s['transform'], 'prompt': s['promptVisible'],
            'stageHidden': s['stageHidden'], 'inert': s['stageInert'], 'paused': s['paused']}
        row['screenshot'] = self.shot(page, '%s-%s' % (portal, cell['cell']))
        if portrait:
            # The stage is inert: the tap maps right but reaches no game control
            tap = self.tap(page, frame, phone, frame.evaluate(RESUME_BUTTON))
            page.wait_for_timeout(300)
            tap['stillPaused'] = frame.evaluate('menu.gamePaused')
            tap['ok'] = tap['ok'] and tap['stillPaused']
            # Turn the phone
            land = self.pw.devices[cell['device'] + ' landscape']['viewport']
            page.set_viewport_size(land)
            frame.wait_for_function('() => !isViewRotated()', timeout=10000)
            page.wait_for_timeout(500)
            s2, exp2, checks2 = self.measure(page, frame, (land['width'], land['height']), phone, dpr, True)
            turned = self.tap(page, frame, phone, frame.evaluate(RESUME_BUTTON))
            wait_quietly(frame, '() => !menu.gamePaused')
            turned['resumed'] = not frame.evaluate('menu.gamePaused')
            checks['turn_to_landscape'] = {
                'ok': all(c['ok'] for c in checks2.values()) and turned['ok'] and turned['resumed'] and
                      not s2['promptVisible'] and s2['transform'] == '' and not s2['rotated'],
                'viewport': [land['width'], land['height']], 'checks': checks2, 'tap': turned}
            row['screenshot_landscape'] = self.shot(page, '%s-%s-landscape' % (portal, cell['cell']))
        else:
            tap = self.tap(page, frame, phone, frame.evaluate(MENU_BUTTON))
            wait_quietly(frame, '() => menu.gamePaused')
            tap['opensPause'] = frame.evaluate('menu.gamePaused')
            tap['ok'] = tap['ok'] and tap['opensPause']
        checks['tap'] = tap
        if portal == 'itch' and not phone:
            frame.evaluate('() => { if (menu.gamePaused) menu.unPause() }')
            page.click('#fullscreen_btn')
            page.wait_for_function('() => !!document.fullscreenElement', timeout=5000)
            frame.wait_for_function('([w, h]) => innerWidth === w && innerHeight === h',
                                    arg=[vp['width'], vp['height']], timeout=5000)
            page.wait_for_timeout(500)
            # The itch page itself keeps scrolling under the fullscreen element
            s3, _, checks3 = self.measure(page, frame, (vp['width'], vp['height']), phone, dpr, False, square)
            ftap = self.tap(page, frame, phone, frame.evaluate(MENU_BUTTON))
            checks['fullscreen'] = {'ok': all(c['ok'] for c in checks3.values()) and ftap['ok'],
                                    'checks': checks3, 'tap': ftap}
            row['screenshot_fullscreen'] = self.shot(page, '%s-%s-fullscreen' % (portal, cell['cell']))
        frame_errors = []
        for f in page.frames:
            try:
                frame_errors += f.evaluate('() => window.__errors || []')
            except Exception as e:
                frame_errors.append('evaluate failed: %s' % e)
        checks['errors'] = {'ok': not (self.errors or frame_errors or self.blocked or self.missing),
                            'page': self.errors, 'frames': frame_errors, 'blocked': self.blocked,
                            'missing': self.missing}
        row['checks'] = checks
        row['failed'] = [k for k, c in checks.items() if not c['ok']]
        row['ok'] = not row['failed']
        row['seconds'] = round(time.time() - t0, 1)
        context.close()
        return row

    def check_portal(self, portal):
        if portal not in os.environ.get('PORTAL_DISPLAY_PORTALS', ','.join(PORTALS)).split(','):
            self.skipTest('PORTAL_DISPLAY_PORTALS')
        only = os.environ.get('PORTAL_DISPLAY_CELLS')
        for cell in cells():
            if only and cell['cell'] not in only.split(','):
                continue
            with self.subTest(portal=portal, cell=cell['cell']):
                try:
                    row = self.run_cell(portal, cell)
                except Exception as e:
                    row = {'portal': portal, 'cell': cell['cell'], 'ok': False,
                           'failed': ['exception'], 'exception': repr(e)[:2000]}
                type(self).rows.append(row)
                print('  %-9s %-22s %s %s' % (portal, cell['cell'], 'ok' if row['ok'] else 'FAIL',
                                              row['failed']), file=sys.stderr, flush=True)
                self.assertTrue(row['ok'], {k: row.get('checks', {}).get(k, row.get('exception'))
                                            for k in row['failed']})

    def test_itch(self):
        self.check_portal('itch')

    def test_gamepix(self):
        self.check_portal('gamepix')

    def test_y8(self):
        self.check_portal('y8')

    def test_playgama(self):
        self.check_portal('playgama')


def wait_quietly(frame, predicate, timeout=5000):
    """Wait for predicate; a timeout is left to the caller's own check."""
    try:
        frame.wait_for_function(predicate, timeout=timeout)
    except Exception:
        pass


def make_grid(out, portal, rows):
    """grid-<portal>.png: every cell screenshot (and its extra states), labelled."""
    from PIL import Image, ImageDraw
    tiles = []
    for r in rows:
        for key, label in (('screenshot', ''), ('screenshot_landscape', ' turned'),
                           ('screenshot_fullscreen', ' fullscreen')):
            p = r.get(key)
            if p:
                path = Path(p) if Path(p).is_absolute() else ROOT / p
                if path.is_file():
                    tiles.append((path, '%s%s %s' % (r['cell'], label, 'ok' if r['ok'] else 'FAIL ' + ','.join(r['failed']))))
    if not tiles:
        return
    tw, th, lab = 480, 300, 22
    cols = 4
    rows_n = (len(tiles) + cols - 1) // cols
    grid = Image.new('RGB', (cols * tw, rows_n * (th + lab)), (24, 24, 24))
    draw = ImageDraw.Draw(grid)
    for i, (path, label) in enumerate(tiles):
        im = Image.open(path).convert('RGB')
        im.thumbnail((tw - 8, th - 8))
        x, y = (i % cols) * tw, (i // cols) * (th + lab)
        grid.paste(im, (x + (tw - im.width) // 2, y + lab + (th - im.height) // 2))
        draw.text((x + 6, y + 4), label, fill=(120, 255, 120) if label.endswith('ok') else (255, 90, 90))
    grid.save(out / ('grid-%s.png' % portal))


if __name__ == '__main__':
    unittest.main()
