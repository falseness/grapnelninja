"""Open pages against the fake CrazyGames SDK in a shared test browser."""
import json
from pathlib import Path

from browser_test_support import SDK_ROUTE, start_browser_test

FAKE_SDK = Path(__file__).with_name('fixtures') / 'fake-crazygames-sdk.js'


def start_crazygames_test(root, add_cleanup):
    """Return URL/browser from the shared server/browser lifetime."""
    return start_browser_test(root, add_cleanup)


def open_game(browser, url, viewport, fake_options=None, block_sdk=False):
    """Return (context, page, errors); errors has 'console' and 'page' lists."""
    context = browser.new_context(viewport=viewport)
    if block_sdk:
        context.route(SDK_ROUTE, lambda route: route.abort())
    else:
        context.route(SDK_ROUTE, lambda route: route.fulfill(
            path=str(FAKE_SDK), content_type='application/javascript'))
    context.add_init_script(
        f'window.__cgFake = Object.assign(window.__cgFake || {{}}, '
        f'{json.dumps(fake_options or {})})')
    page = context.new_page()
    errors = collect_errors(page, block_sdk)
    page.goto(url)
    return context, page, errors


def collect_errors(page, block_sdk=False):
    """Collect console errors and uncaught page errors.

    The failed load of a deliberately blocked SDK is kept apart in
    'blocked_sdk' so the remaining lists hold only unexpected errors.
    """
    errors = {'console': [], 'page': [], 'blocked_sdk': []}

    def on_console(msg):
        if msg.type != 'error':
            return
        if block_sdk and 'crazygames-sdk-v3.js' in msg.location.get('url', ''):
            errors['blocked_sdk'].append(msg.text)
        else:
            errors['console'].append(msg.text)

    page.on('console', on_console)
    page.on('pageerror', lambda exc: errors['page'].append(str(exc)))
    return errors


def sdk_calls(page):
    """Return the fake SDK's recorded calls ([] when the SDK is absent)."""
    return page.evaluate('() => (window.__cgFake && window.__cgFake.calls) || []')


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
