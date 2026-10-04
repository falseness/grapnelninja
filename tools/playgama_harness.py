"""Open pages against the fake Playgama Bridge in a shared test browser."""
import json
from pathlib import Path

from browser_test_support import BRIDGE_URL, start_browser_test

CONFIG_ROUTE = '**/playgama-bridge-config.json'
FAKE_BRIDGE = Path(__file__).with_name('fixtures') / 'fake-playgama-bridge.js'
STUB_CONFIG = {'advertisement': {'interstitial': {'placements': []},
                                 'rewarded': {'placements': []}}}


def start_playgama_test(root, add_cleanup):
    """Return URL/browser from the shared server/browser lifetime."""
    return start_browser_test(root, add_cleanup)


def serve_config(route):
    """Serve the local config, or a stub when the server has none."""
    response = route.fetch()
    if response.status == 404:
        route.fulfill(content_type='application/json',
                      body=json.dumps(STUB_CONFIG))
    else:
        route.fulfill(response=response)


def open_game(browser, url, viewport, fake_options=None, block_bridge=False,
              **context_options):
    """Return (context, page, errors); errors has 'console' and 'page' lists."""
    context = browser.new_context(viewport=viewport, **context_options)
    if block_bridge:
        context.route(BRIDGE_URL, lambda route: route.abort())
    else:
        context.route(BRIDGE_URL, lambda route: route.fulfill(
            path=str(FAKE_BRIDGE), content_type='application/javascript'))
    context.route(CONFIG_ROUTE, serve_config)
    context.add_init_script(
        f'window.__fakeBridge = Object.assign(window.__fakeBridge || {{}}, '
        f'{json.dumps(fake_options or {})})')
    page = context.new_page()
    errors = collect_errors(page, block_bridge)
    page.goto(url)
    return context, page, errors


def collect_errors(page, block_bridge=False):
    """Collect console errors and uncaught page errors.

    The failed load of a deliberately blocked Bridge is kept apart in
    'blocked_bridge' so the remaining lists hold only unexpected errors.
    """
    errors = {'console': [], 'page': [], 'blocked_bridge': []}

    def on_console(msg):
        if msg.type != 'error':
            return
        if block_bridge and 'playgama-bridge.js' in msg.location.get('url', ''):
            errors['blocked_bridge'].append(msg.text)
        else:
            errors['console'].append(msg.text)

    page.on('console', on_console)
    page.on('pageerror', lambda exc: errors['page'].append(str(exc)))
    return errors


def bridge_calls(page):
    """Return the fake Bridge's recorded calls ([] when it is absent)."""
    return page.evaluate(
        '() => (window.__fakeBridge && window.__fakeBridge.calls) || []')


def bridge_errors(page):
    """Return the fake Bridge's recorded misuse errors."""
    return page.evaluate(
        '() => (window.__fakeBridge && window.__fakeBridge.errors) || []')


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
