"""Open game pages in a shared test browser and observe PLATFORM storage.

The Y8 adapter (platform.js) boots with environment "pending" and settles to
"y8" when the SDK initialises or "disabled" when it is absent, stubbed or
rejects; platformId is always "y8". OfflineBrowser serves index.html's SDK
script with a rejecting stub, so suites boot "disabled" unless they ask for
the fake SDK (tools/fixtures/fake-y8-sdk.js, served the way
tools/verify_y8_release.py does) to reach the rewarded path.

Storage is observed where the game writes it: platform.js is served with a
wrapper appended that records every PLATFORM.storage.getMany/setMany call as
{name: 'storage.get' | 'storage.set', args: [keys] | [keys, values], t} in
window.__storageSpy.calls, the call log shape the tests expect.
"""
import json
from pathlib import Path
import re

from browser_test_support import start_browser_test

FAKE_SDK_URL = 'https://cdn.y8.com/minimal-sdk/2-0/y8.min.js'
FAKE_SDK = Path(__file__).with_name('fixtures') / 'fake-y8-sdk.js'
PLATFORM_JS = re.compile(r'^https?://127\.0\.0\.1[:/].*/platform\.js$')

# Appended to platform.js: PLATFORM is the script's top-level const, so the
# wrapper runs before index.html's boot() makes the first getMany.
STORAGE_SPY = r'''
;(() => {
    if (window.__storageSpy) return
    const storage = PLATFORM.storage
    const raw = {getMany: storage.getMany, setMany: storage.setMany}
    const spy = window.__storageSpy = {calls: [], raw: raw}
    storage.getMany = function (keys) {
        spy.calls.push({name: 'storage.get', args: [Array.from(keys)], t: performance.now()})
        return raw.getMany.call(this, keys)
    }
    storage.setMany = function (obj) {
        spy.calls.push({name: 'storage.set',
            args: [Object.keys(obj), Object.keys(obj).map(k => String(obj[k]))],
            t: performance.now()})
        return raw.setMany.call(this, obj)
    }
})()
'''


# A real lethal death through ninja.move(): the ninja is placed on the top
# side floor's block under its own x (Side edges are lethal spikes:
# Element.prototype.collision). Classic: centred on the block's bottom edge
# midway along it, so exactly one lethal line is hit and onLethalDeath runs
# once (each hit line reports; a corner would restart the run per edge). Bad:
# the bottom edge is the bouncy ceiling, so the ninja is centred on the seam
# between two blocks and hits their two vertical edges (the second report is
# dropped by the visible continue offer). Since TASK-225 the camera-fixed left
# wall bounces anything placed behind the deletion border, so the old
# behind-the-border death is unreachable. Install as window.__placeOnTopSide.
PLACE_ON_TOP_SIDE = r'''() => {
    const x = ninja.x
    const sides = floors.flatMap(f => f.elements)
        .filter(e => e instanceof Side && e.y < height / 2)
        .sort((a, b) => a.getLeftPointX() - b.getLeftPointX())
    let i = sides.findIndex(e => e.getLeftPointX() <= x && x <= e.getRightPointX())
    if (i < 0) i = 0
    const side = sides[i]
    const ys = side.getPoints().map(p => p.y)
    const top = Math.min(...ys), bottom = Math.max(...ys)
    if (version == 'bad') {
        ninja.x = side.getRightPointX()
        ninja.y = (top + bottom) / 2
    } else {
        ninja.x = (side.getLeftPointX() + side.getRightPointX()) / 2
        ninja.y = bottom
    }
    ninja.speedX = 0
    ninja.speedY = 0
    return {element: side.constructor.name, x: ninja.x, y: ninja.y, version: version}
}'''


def install_kill(page):
    """Install window.__placeOnTopSide (see PLACE_ON_TOP_SIDE)."""
    # Wrapped so Playwright installs the function instead of calling it
    page.evaluate('() => { window.__placeOnTopSide = ' + PLACE_ON_TOP_SIDE + ' }')


def start_game_test(root, add_cleanup):
    """Return URL/browser from the shared server/browser lifetime."""
    return start_browser_test(root, add_cleanup)


def serve_platform_with_spy(route):
    """Fulfil platform.js from the test server with the storage spy appended."""
    response = route.fetch()
    route.fulfill(response=response, body=response.text() + STORAGE_SPY)


def serve_fake_sdk(context, options=None):
    """Serve the fake Y8 SDK in place of the CDN script (environment "y8").

    options go to window.__y8Fake before the script loads (rewardOutcome,
    adDurationMs, initReject, readyNever, ...). Registered after
    OfflineBrowser's routes, so it wins over the rejecting stub.
    """
    context.route(FAKE_SDK_URL, lambda route: route.fulfill(
        status=200, content_type='text/javascript', body=FAKE_SDK.read_text()))
    context.add_init_script(
        f'window.__y8Fake = Object.assign(window.__y8Fake || {{}}, '
        f'{json.dumps(options or {})})')


def open_game(browser, url, viewport, fake_sdk=None, **context_options):
    """Return (context, page, errors); errors has 'console' and 'page' lists.

    fake_sdk: None boots against the offline stub (environment "disabled");
    a dict (possibly empty) serves the fake SDK with those options ("y8").
    """
    context = browser.new_context(viewport=viewport, **context_options)
    context.route(PLATFORM_JS, serve_platform_with_spy)
    if fake_sdk is not None:
        serve_fake_sdk(context, fake_sdk)
    page = context.new_page()
    errors = collect_errors(page)
    page.goto(url)
    return context, page, errors


def collect_errors(page):
    """Collect console errors and uncaught page errors."""
    errors = {'console': [], 'page': []}

    def on_console(msg):
        if msg.type == 'error':
            errors['console'].append(msg.text)

    page.on('console', on_console)
    page.on('pageerror', lambda exc: errors['page'].append(str(exc)))
    return errors


def storage_calls(page):
    """Return the recorded PLATFORM.storage get/set calls ([] without the spy)."""
    return page.evaluate(
        '() => (window.__storageSpy && window.__storageSpy.calls) || []')


def sdk_calls(page):
    """Return the fake SDK's recorded calls ([] when the fake is not served)."""
    return page.evaluate('() => (window.__y8Fake && window.__y8Fake.calls) || []')


def local_store(page):
    """Return localStorage as a dict (the adapter's backing store)."""
    return page.evaluate('''() => Object.fromEntries(Object.keys(localStorage).sort()
        .map(k => [k, localStorage.getItem(k)]))''')


def seed_store(page, store):
    """Replace localStorage with store (dict of strings), not logged."""
    page.evaluate('''(store) => {
        localStorage.clear()
        for (const [k, v] of Object.entries(store)) localStorage.setItem(k, v)
    }''', store)


def canvas_to_viewport(page, x, y):
    """Invert the page's affine viewportCoordsToCanvasCoords at (x, y)."""
    return page.evaluate('''([x, y]) => {
        const o = viewportCoordsToCanvasCoords({x: 0, y: 0})
        const ex = viewportCoordsToCanvasCoords({x: 1, y: 0})
        const ey = viewportCoordsToCanvasCoords({x: 0, y: 1})
        const a = ex.x - o.x, b = ey.x - o.x, c = ex.y - o.y, d = ey.y - o.y
        const det = a * d - b * c
        const dx = x - o.x, dy = y - o.y
        return {x: (d * dx - b * dy) / det, y: (a * dy - c * dx) / det}
    }''', [x, y])


def click_canvas(page, x, y):
    """Click at logical canvas coordinates (x, y)."""
    point = canvas_to_viewport(page, x, y)
    page.mouse.click(point['x'], point['y'])
    return point


# The game booted: platform settled ("y8" or "disabled"), menu drawn,
# loading overlay hidden (input is attached right after)
READY = ('PLATFORM.environment !== "pending" && menu.visible'
         ' && document.getElementById("loading").hidden')
