"""Shared server/browser lifetime for unittest browser suites."""
from functools import partial
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import sync_playwright


# Any request that is not to the local test server (index.html's only
# external script is the Y8 SDK, served by the stub route below)
EXTERNAL_URL = re.compile(r'^(?!https?://127\.0\.0\.1[:/])(?:https?|wss?)://')
# index.html's Y8 minimal SDK script.  Aborting it logs a console error
# (net::ERR_FAILED) and leaves PLATFORM.init() waiting for its 2900 ms
# fallback timer, which never fires under render_snapshot's frozen clock.
Y8_SDK_URL = re.compile(r'^https?://cdn\.y8\.com/minimal-sdk/.*y8\.min\.js')
# Offline stand-in: sdk().init() rejects, so PLATFORM.init() settles to
# environment "disabled" through its catch path, with no timer and no
# console error; isRewardedSupported() stays false.
Y8_SDK_STUB = ('window.y8 = {sdk: () => ({init: () => Promise.reject(new Error("offline test stub"))}),'
               ' emitReadyEvent() { window.dispatchEvent(new Event("y8sdk.ready")) }};'
               ' window.y8.emitReadyEvent()')
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


def stub_y8_sdk(route):
    """Fulfil the Y8 SDK script with the inline offline stub."""
    route.fulfill(status=200, content_type='text/javascript', body=Y8_SDK_STUB)


def route_offline(context):
    """Abort every external URL except the Y8 SDK script, which gets the stub.

    Playwright consults routes in reverse registration order, so the SDK
    route is registered last to be matched before the generic abort.
    """
    context.route(EXTERNAL_URL, block_external)
    context.route(Y8_SDK_URL, stub_y8_sdk)


class OfflineBrowser:
    """Browser whose pages never reach the network beyond the test server.

    Routes added later take precedence (verify_y8_release.py relies on this
    to replace the SDK stub with its full fake).
    """
    def __init__(self, browser):
        self._browser = browser

    def __getattr__(self, name):
        return getattr(self._browser, name)

    def new_context(self, **kwargs):
        context = self._browser.new_context(**kwargs)
        route_offline(context)
        return context

    def new_page(self, **kwargs):
        page = self._browser.new_page(**kwargs)
        route_offline(page.context)
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
