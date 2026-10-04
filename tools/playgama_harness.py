"""Open pages against the fake Playgama Bridge in a shared test browser."""
import json
from pathlib import Path

from browser_test_support import start_browser_test

BRIDGE_URL = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'
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


def open_game(browser, url, viewport, fake_options=None, block_bridge=False):
    """Return (context, page, errors); errors has 'console' and 'page' lists."""
    context = browser.new_context(viewport=viewport)
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
