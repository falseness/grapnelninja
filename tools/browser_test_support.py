"""Shared server/browser lifetime for unittest browser suites."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright


BRIDGE_URL = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'
LOGICAL_HEIGHT = 1080


def logical_size(viewport_width, viewport_height):
    """Logical canvas size for a browser viewport (gameoptions.js)."""
    aspect = min(2, max(4 / 3, viewport_width / viewport_height))
    return round(LOGICAL_HEIGHT * aspect), LOGICAL_HEIGHT


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def stub_bridge(route):
    """Serve an empty Bridge so pages boot offline with PLATFORM disabled."""
    route.fulfill(content_type='application/javascript', body='')


class OfflineBridgeBrowser:
    """Browser whose pages never fetch the real Playgama Bridge.

    Routes added later (e.g. by playgama_harness) take precedence.
    """
    def __init__(self, browser):
        self._browser = browser

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)
        context.route(BRIDGE_URL, stub_bridge)
        return context

    def new_page(self, **kwargs):
        page = self._browser.new_page(**kwargs)
        page.context.route(BRIDGE_URL, stub_bridge)
        return page


def wait_for_boot(page):
    """Wait until index.html's async boot() has run start().

    Older trees (verification baselines) boot synchronously, without #loading.
    """
    page.wait_for_function(
        "() => { const el = document.getElementById('loading'); return !el || el.hidden }")


def start_browser_test(root, add_cleanup):
    """Return URL/browser; register acquired resources with a LIFO cleanup stack."""
    server = ThreadingHTTPServer(('127.0.0.1', 0),
                                 partial(QuietHandler, directory=str(root)))
    add_cleanup(server.server_close)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    add_cleanup(thread.join)
    add_cleanup(server.shutdown)
    url = f'http://127.0.0.1:{server.server_port}/'
    playwright = sync_playwright().start()
    add_cleanup(playwright.stop)
    browser = playwright.chromium.launch(args=['--no-sandbox'])
    add_cleanup(browser.close)
    return url, OfflineBridgeBrowser(browser)
