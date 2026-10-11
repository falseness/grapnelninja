"""Shared server/browser lifetime for unittest browser suites.

Also the node binary and ticket-revision helpers the tool suites share.
"""
from datetime import datetime, timezone
from functools import partial
import os
from pathlib import Path
import re
import shutil
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


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


def node_binary(fallback=True):
    """Playwright's bundled node (v24) when installed, else the system `node`.

    The system node here is v12 and cannot parse the optional chaining in
    render/effects.js, so every subprocess that evaluates game sources must
    use this instead of a bare 'node'.  fallback=False returns None instead
    of the system node (suites that only make sense on the bundled one skip).
    """
    try:
        import playwright
    except ImportError:
        playwright = None
    if playwright is not None:
        node = Path(playwright.__file__).resolve().parent / 'driver' / 'node'
        if node.exists():
            return str(node)
    return (shutil.which('node') or 'node') if fallback else None


def node_label(node=None):
    """'v24.15.0 (bundled)' / 'v12.22.9 (system)' for logs and manifests."""
    node = node or node_binary()
    version = subprocess.check_output([node, '--version'], text=True).strip()
    origin = 'bundled' if 'playwright' in Path(node).parts else 'system'
    return f'{version} ({origin})'


def ticket_base_rev(var, *recorded):
    """Pre-ticket revision: $var, else the hash recorded in the first existing file.

    Ticket-bound suites save the base before editing (artifacts/<ticket>/base-rev.txt);
    with neither the env nor a recorded file the suite skips instead of raising KeyError.
    """
    if os.environ.get(var):
        return os.environ[var]
    for path in recorded:
        path = ROOT / path
        if path.exists() and path.read_text().split():
            return path.read_text().split()[0]
    raise unittest.SkipTest(f'set {var} (no recorded base revision: {", ".join(map(str, recorded))})')


def ticket_head(var, ticket):
    """Measured tree: $var, else the commit whose subject starts with '<ticket>:', else the worktree."""
    if os.environ.get(var):
        return os.environ[var]
    try:
        found = subprocess.check_output(['git', 'log', '--all', '-1', '--format=%H', f'--grep=^{ticket}:'],
                                        cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        found = ''
    return found or 'worktree'


def ticket_evidence_dir(var, ticket, relative_to=None):
    """Evidence directory: $var, else a fresh artifacts/<ticket>/rerun-<utc> dir.

    The default never overwrites the ticket's historical evidence.  `relative_to`
    anchors a relative $var (default: the current directory, as the suites did).
    """
    if os.environ.get(var):
        return ((relative_to or Path.cwd()) / os.environ[var]).resolve()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return ROOT / 'artifacts' / ticket / f'rerun-{stamp}'


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
