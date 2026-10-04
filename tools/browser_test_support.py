"""Shared server/browser lifetime for unittest browser suites."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright


SDK_ROUTE = '**/y8.min.js'
LOGICAL_HEIGHT = 1080


def logical_size(viewport_width, viewport_height):
    """Logical canvas size for a browser viewport (gameoptions.js)."""
    aspect = min(2, max(4 / 3, viewport_width / viewport_height))
    return round(LOGICAL_HEIGHT * aspect), LOGICAL_HEIGHT


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def stub_sdk(route):
    """Serve an empty SDK so pages boot offline with PLATFORM disabled."""
    route.fulfill(content_type='application/javascript', body='')


class OfflineSdkBrowser:
    """Browser whose pages never fetch the real Y8 SDK.

    Routes added later (e.g. by y8_harness) take precedence.
    """
    def __init__(self, browser):
        self._browser = browser

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)
        context.route(SDK_ROUTE, stub_sdk)
        return context

    def new_page(self, **kwargs):
        page = self._browser.new_page(**kwargs)
        page.context.route(SDK_ROUTE, stub_sdk)
        return page


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
    return url, OfflineSdkBrowser(browser)
