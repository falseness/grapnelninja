"""Shared server/browser lifetime for unittest browser suites."""
from functools import partial
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright


# Any request that is not to the local test server (the game loads no
# external scripts; older baseline trees may still reference an SDK URL)
EXTERNAL_URL = re.compile(r'^(?!https?://127\.0\.0\.1[:/])(?:https?|wss?)://')
LOGICAL_HEIGHT = 1080


def logical_size(viewport_width, viewport_height):
    """Logical canvas size for a browser viewport (gameoptions.js)."""
    aspect = min(2, max(4 / 3, viewport_width / viewport_height))
    return round(LOGICAL_HEIGHT * aspect), LOGICAL_HEIGHT


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def block_external(route):
    """Abort the request so pages run offline."""
    route.abort()


class OfflineBrowser:
    """Browser whose pages never reach the network beyond the test server.

    Routes added later take precedence.
    """
    def __init__(self, browser):
        self._browser = browser

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)
        context.route(EXTERNAL_URL, block_external)
        return context

    def new_page(self, **kwargs):
        page = self._browser.new_page(**kwargs)
        page.context.route(EXTERNAL_URL, block_external)
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
    return url, OfflineBrowser(browser)
