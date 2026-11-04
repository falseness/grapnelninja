"""Build-time bake of the size-independent boot caches (TASK-891), for tools/build_release.py.

    python3 tools/release_bake.py SITE_DIR

SITE_DIR holds the source runtime files of one commit (index.html with its local references and
the files its scripts load, as tools/build_release.py collects them, no bake). This serves it on
127.0.0.1, boots the game once in headless Chromium (1366x768, en-US, every external request
aborted) and prints one JSON object on stdout:

  {"route_arrows": {"layoutId": ..., "arrows": [{id, from, to, guide, gap, length, target, t}]}}

route_arrows: render/routearrows.js computeRouteArrow's level-only values for every guided transfer
of the Grapple Over level, from the same file the zip ships (routeArrowsFor in that boot). An
entry with a non-finite value is null (the runtime then computes that arrow). Route arrows depend
on the level alone (world units): not on viewport size, DPR, pixel scale or language.

The caches that do depend on those (glyph and glow sprites, background gradient, parallax tiles,
palette strips, tutorial hint) and the seeded noise table (cheaper to compute than to load) are not
baked: artifacts/TASK-891/caches.json.

Runs in its own process so a caller that already drives Playwright can still build.
"""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
import math
import sys
from threading import Thread

from playwright.sync_api import sync_playwright

VIEWPORT = {'width': 1366, 'height': 768}

DUMP = '''() => {
    const level = floors[0].level
    const arrows = routeArrowsFor(level)
    const transfers = routeArrowState(level).transfers
    return {layoutId: level.layoutId, arrows: arrows.map((a, i) => ({id: a.id, from: transfers[i].from,
        to: transfers[i].to, guide: transfers[i].guide, gap: a.gap, length: a.length, target: a.target, t: a.t}))}
}'''


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def finite(entry):
    return all(isinstance(entry[k], (int, float)) and math.isfinite(entry[k])
               for k in ('gap', 'length', 'target', 't'))


def bake(site):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(site)))
    Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % server.server_port
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--no-sandbox'])
            try:
                context = browser.new_context(locale='en-US', viewport=VIEWPORT)
                context.route('**/*', lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url + 'index.html')
                page.wait_for_function('() => typeof bootComplete !== "undefined" && bootComplete && runInProgress',
                                       timeout=180000)
                table = page.evaluate(DUMP)
                # The page's own numbers, unrounded: Playwright hands doubles over as doubles
                table['arrows'] = [a if finite(a) else None for a in table['arrows']]
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    if errors:
        raise SystemExit('page errors while baking: %s' % errors[:3])
    if not table['arrows'] or all(a is None for a in table['arrows']):
        raise SystemExit('no route arrows baked')
    return {'route_arrows': table}


if __name__ == '__main__':
    json.dump(bake(sys.argv[1]), sys.stdout, separators=(',', ':'))
