"""TASK-860: real GameAnalytics smoke test of the built itch zip.

Serves the itch zip (default artifacts/release-grapple-over/itch/
grapple-over-itch.zip) on 127.0.0.1, opens it in headless Chromium WITH
network access to *.gameanalytics.com only (every other external request is
aborted), lets the game boot and play a few seconds, and records every
GameAnalytics request/response: method, URL with the game key replaced by
<GA_GAME_KEY> (the secret key never appears in URLs; it is redacted too in
case), HTTP status and, for /events posts, the event categories in the body
(no other body content). Passes when the init request (SDK 5.0.0:
POST remote_configs/v1/init, answered 2xx; GameAnalytics answers it 201
Created) succeeded, an /events post carrying the session-start 'user'
event answered 200, and the game booted on the gameanalytics backend
without page errors.
Sends one real smoke session to the GameAnalytics game.

GA_GAME_KEY / GA_SECRET_KEY are read from the environment or
/root/credentials/grapnelninja/credentials.env only to redact them.

    python3 tools/smoke_gameanalytics.py [--zip ZIP] --out ga-smoke.json
"""
import argparse
from contextlib import ExitStack
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import gzip
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import time
from urllib.parse import urlparse
import zipfile

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gameanalytics_backend import credentials  # noqa: E402
from browser_test_support import wait_for_boot_run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZIP = ROOT / 'artifacts' / 'release-grapple-over' / 'itch' / 'grapple-over-itch.zip'


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def is_ga(url):
    host = urlparse(url).hostname or ''
    return host == 'gameanalytics.com' or host.endswith('.gameanalytics.com')


def init_ok(rows):
    return any('/init' in r['url'] and r['status'] and 200 <= r['status'] < 300 for r in rows)


def session_ok(rows):
    return init_ok(rows) and any(r['url'].endswith('/events') and r['status'] == 200
                                 and 'user' in (r.get('categories') or []) for r in rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--zip', type=Path, default=DEFAULT_ZIP)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=20.0)
    args = parser.parse_args(argv)
    env = credentials()
    secrets = {name: env[name] for name in ('GA_GAME_KEY', 'GA_SECRET_KEY') if env.get(name)}

    def redact(text):
        for name, value in secrets.items():
            text = text.replace(value, f'<{name}>')
        return text

    rows, blocked, page_errors = [], [], []
    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='ga-smoke-') as site:
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(site)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=site))
        Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.server_close)
        stack.callback(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}/'
        playwright = sync_playwright().start()
        stack.callback(playwright.stop)
        browser = playwright.chromium.launch(args=['--no-sandbox'])
        stack.callback(browser.close)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})

        def route(r):
            url = r.request.url
            if url.startswith(base) or is_ga(url):
                return r.continue_()
            blocked.append(redact(url))
            return r.abort()
        context.route('**/*', route)
        started = time.time()

        def categories(request):
            try:
                body = request.post_data_buffer
                if body and body[:2] == b'\x1f\x8b':
                    body = gzip.decompress(body)
                events = json.loads(body) if body else None
                if isinstance(events, list):
                    return [e.get('category') for e in events if isinstance(e, dict)]
            except Exception as e:  # noqa: BLE001 - evidence only
                return [f'<unreadable: {type(e).__name__}>']
            return None

        def on_response(response):
            if is_ga(response.url):
                row = {'t': round(time.time() - started, 2), 'method': response.request.method,
                       'url': redact(response.url), 'status': response.status}
                if response.url.endswith('/events'):
                    row['categories'] = categories(response.request)
                rows.append(row)

        def on_failed(request):
            if is_ga(request.url):
                rows.append({'t': round(time.time() - started, 2), 'method': request.method,
                             'url': redact(request.url), 'status': None,
                             'failure': request.failure})
        context.on('response', on_response)
        context.on('requestfailed', on_failed)
        page = context.new_page()
        page.on('pageerror', lambda e: page_errors.append(redact(str(e))))
        page.goto(base + 'index.html')
        wait_for_boot_run(page)
        state = page.evaluate('() => ({version, runInProgress, backend: ANALYTICS_BACKEND.backendId, '
                              'build: BUILD_CONFIG.build, platform: BUILD_CONFIG.platform})')
        box = page.locator('#canvas').bounding_box()
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            page.mouse.click(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.3)
            page.wait_for_timeout(1000)
            if session_ok(rows):
                break
        page.evaluate('() => ANALYTICS.sessionEnd()')
        page.wait_for_timeout(2000)
        context.close()

    init = [r for r in rows if '/init' in r['url']]
    events = [r for r in rows if r['url'].endswith('/events')]
    report = {
        'zip': str(args.zip.relative_to(ROOT) if args.zip.is_relative_to(ROOT) else args.zip),
        'state': state,
        'ga_requests': rows,
        'init_statuses': [r['status'] for r in init],
        'events_statuses': [r['status'] for r in events],
        'blocked_non_ga': blocked,
        'page_errors': page_errors,
        'keys_redacted': sorted(f'<{n}>' for n in secrets),
    }
    report['init_ok_2xx'] = init_ok(rows)
    report['session_start_events_200'] = session_ok(rows)
    report['pass'] = (report['session_start_events_200'] and not page_errors
                      and state['backend'] == 'gameanalytics' and state['runInProgress'])
    text = redact(json.dumps(report, indent=1))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + '\n')
    print(('PASS' if report['pass'] else 'FAIL') + f': init statuses {report["init_statuses"]}, '
          f'events statuses {report["events_statuses"]}, page errors {len(page_errors)}')
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
