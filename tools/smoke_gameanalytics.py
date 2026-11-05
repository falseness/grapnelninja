"""TASK-860: real GameAnalytics smoke test of the built itch zip.

Serves the itch zip (default artifacts/release-grapple-over/itch/
grapple-over-itch.zip) on 127.0.0.1, opens it in headless Chromium WITH
network access to *.gameanalytics.com only (every other external request is
aborted), lets the game boot and play a few seconds, and records every
GameAnalytics request/response: method, URL with the game key replaced by
<GA_GAME_KEY> (the secret key never appears in URLs; it is redacted too in
case), HTTP status and, for /events posts, the event categories in the body
and the design event ids (no other body content). Passes when the init request (SDK 5.0.0:
POST remote_configs/v1/init, answered 2xx; GameAnalytics answers it 201
Created) succeeded, an /events post carrying the session-start 'user'
event answered 200, an /events post answered 200 carried the boot
env:* design events (sent before the init answer: they must not be dropped),
and the game booted on the gameanalytics backend without page errors.
Sends one real smoke session to the GameAnalytics game.

TASK-899 --quit: instead of ANALYTICS.sessionEnd() the player really leaves:
the page navigates to about:blank (beforeunload / pagehide / visibility
hidden as on a real quit), then the same browser context comes back
(--revisit-seconds), so the SDK can re-send what it stored. The GameAnalytics
SDK calls made from the leave on (recorded by wrapping
gameanalytics.GameAnalytics.*) and every GA request with its event ids are
recorded. Passes only if every design event id and progression event the
game handed the SDK at pagehide arrives in an /events POST answered 200
after the leave (in the pagehide request or re-sent on the revisit), no
design / progression event is added after endSession, nothing is added
after the SDK stored the session_end, and no quit event arrives twice.
A keepalive fetch sent at unload outlives its document: DevTools (so
Playwright) reports it as failed net::ERR_ABORTED although the browser's
network service still sends it. --quit therefore runs Chromium with a NetLog
(--log-net-log, temp file, deleted after use) and takes the real HTTP status
of such a request from the NetLog entry with the same URL and Authorization
header (row 'status_source': 'netlog'); the header values are never written.

TASK-907 --bfcache: the page is kept in the back/forward cache (full
Chromium, channel='chromium', bfcache enabled): after the boot session the
player leaves to a same-origin page (pagehide persisted, the game ends its
session and sends the quit-time events), comes back with go_back
(pageshow persisted: the game reopens a GameAnalytics session), plays and
opens the pause screen, then leaves again. SDK calls are tagged by phase
(leave1 / restore / leave2) in the page. Passes only if the page really
came back from the bfcache, after the restore startSession and at least one
design event were handed to the SDK and every design / progression event of
the restore phase arrived in an /events POST answered 200 together with the
new session's 'user' event, the first and the second pagehide each pass the
--quit checks, and no event arrived after the restore more often than the
game handed it to the SDK after the restore.

GA_GAME_KEY / GA_SECRET_KEY are read from the environment or
/root/credentials/grapnelninja/credentials.env only to redact them.

    python3 tools/smoke_gameanalytics.py [--zip ZIP] [--quit | --bfcache] --out ga-smoke.json
"""
import argparse
from contextlib import ExitStack
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import gzip
import json
from pathlib import Path
import re
import shutil
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


def env_ok(rows):
    return any(r['url'].endswith('/events') and r['status'] == 200
               and any(str(c).startswith('design:env:') for c in r.get('categories') or []) for r in rows)


# Wraps the SDK's public add*/session calls and the store of the session_end
# event; each call is logged to the console (the page is about to unload)
RECORD_SDK = r'''() => {
    const ga = gameanalytics.GameAnalytics
    for (const fn of ['addDesignEvent', 'addProgressionEvent', 'addErrorEvent', 'addAdEvent',
                      'endSession', 'startSession']) {
        const orig = ga[fn]
        ga[fn] = function(...a) { console.log('GA-CALL ' + JSON.stringify([fn, a])); return orig.apply(this, a) }
    }
    const events = gameanalytics.events.GAEvents, end = events.addSessionEndEvent
    events.addSessionEndEvent = function(...a) {
        console.log('GA-CALL ' + JSON.stringify(['<session_end stored>', []])); return end.apply(this, a) }
}'''


# --bfcache, init script (before the game's scripts, so these listeners run
# before the game's own pagehide / pageshow handlers): the phase is
# leave<n> from the n-th pagehide, restore<n> from the n-th persisted pageshow
BFCACHE_LIFECYCLE = r'''
    window.__gaPhase = 'before'; window.__gaLog = []; window.__gaMarks = []
    let leaves = 0, restores = 0
    addEventListener('pagehide', e => { window.__gaPhase = 'leave' + (++leaves); window.__gaMarks.push(['pagehide', e.persisted]) })
    addEventListener('pageshow', e => { if (e.persisted) window.__gaPhase = 'restore' + (++restores);
        window.__gaMarks.push(['pageshow', e.persisted]) })
'''

# --bfcache: the RECORD_SDK calls kept in the page (console messages of a page
# entering the bfcache are not delivered reliably); read after the last return
RECORD_PHASES = r'''() => {
    const ga = gameanalytics.GameAnalytics
    for (const fn of ['addDesignEvent', 'addProgressionEvent', 'addErrorEvent', 'addAdEvent',
                      'endSession', 'startSession']) {
        const orig = ga[fn]
        ga[fn] = function(...a) { window.__gaLog.push([window.__gaPhase, fn, JSON.parse(JSON.stringify(a))]); return orig.apply(this, a) }
    }
    const events = gameanalytics.events.GAEvents, end = events.addSessionEndEvent
    events.addSessionEndEvent = function(...a) { window.__gaLog.push([window.__gaPhase, '<session_end stored>', []]); return end.apply(this, a) }
    // The backend's unload batch: fetch(keepalive) /events. DevTools never
    // reports it for a page going into the bfcache, so its body is read here
    // and its status from the NetLog (same Authorization header)
    window.__gaFetch = []
    const fetchOrig = window.fetch
    window.fetch = function(url, init) {
        try {
            if (/gameanalytics\.com\/.*\/events$/.test(String(url))) {
                const rows = JSON.parse(init.body)
                window.__gaFetch.push({phase: window.__gaPhase, url: String(url), auth: init.headers.Authorization,
                    keepalive: !!init.keepalive, categories: rows.map(e => e.category + ((e.category === 'design' ||
                        e.category === 'progression') && typeof e.event_id === 'string' ? ':' + e.event_id : ''))})
            }
        } catch (e) {}
        return fetchOrig.apply(this, arguments)
    }
}'''


def delivered_200(rows):
    return [c for r in rows if r['url'].endswith('/events') and r['status'] == 200 for c in r.get('categories') or []]


def bfcache_verdict(calls, rows, marks, restored):
    """calls: [[phase, fn, args]] from the leave on; rows: GA rows from leave1 on (with markers)."""
    at = {r['marker']: i for i, r in enumerate(rows) if r.get('marker')}
    phase = {name: [[fn, a] for ph, fn, a in calls if ph == name]
             for name in ('leave1', 'restore1', 'leave2', 'restore2')}
    restore_rows = rows[at['restore']:]
    expected_restore = [event_id(fn, a) for fn, a in phase['restore1'] if event_id(fn, a)]
    pool = delivered_200(restore_rows)
    missing = []
    for e in expected_restore:
        if e in pool:
            pool.remove(e)
        else:
            missing.append(e)
    handed_after = expected_restore + [event_id(fn, a) for name in ('leave2', 'restore2')
                                       for fn, a in phase[name] if event_id(fn, a)]
    delivered_after = [c for c in delivered_200(restore_rows) if c.split(':')[0] in ('design', 'progression')]
    twice = sorted({c for c in delivered_after if delivered_after.count(c) > handed_after.count(c)})
    leave1 = quit_verdict(phase['leave1'], rows[:at['restore']])
    leave2 = quit_verdict(phase['leave2'], rows[at['leave2']:])
    names = [fn for fn, _ in phase['restore1']]
    result = {
        'restored_from_bfcache': restored,
        'marks': marks,
        'restore_calls': [fn + (':' + (event_id(fn, a) or '')) for fn, a in phase['restore1']],
        'restore_start_session': 'startSession' in names,
        'restore_design_events': [e for e in expected_restore if e.startswith('design:')],
        'restore_expected': expected_restore,
        'restore_missing': missing,
        'restore_session_user_event_200': any(r['url'].endswith('/events') and r['status'] == 200
                                              and 'user' in (r.get('categories') or []) for r in restore_rows),
        'delivered_twice_after_restore': twice,
        'leave1_quit': leave1,
        'leave2_quit': leave2,
    }
    persisted = [m for m in marks if m != ['pageshow', False]]
    result['pass'] = bool(restored and persisted[:2] == [['pagehide', True], ['pageshow', True]]
                          and result['restore_start_session'] and result['restore_design_events']
                          and not missing and result['restore_session_user_event_200'] and not twice
                          and leave1['pass'] and leave2['pass'])
    return result


def netlog_requests(path):
    """[{method, url, auth, status}] of the URL requests in a Chromium NetLog file."""
    data = json.loads(Path(path).read_text())
    types = {v: k for k, v in data['constants']['logEventTypes'].items()}
    found = {}
    for e in data['events']:
        name, params = types.get(e['type']), e.get('params') or {}
        row = found.setdefault(e['source']['id'], {})
        if name == 'URL_REQUEST_START_JOB':  # BEGIN carries the params, END none
            if params.get('url'):
                row.update(method=params.get('method'), url=params.get('url'))
        elif name in ('HTTP_TRANSACTION_SEND_REQUEST_HEADERS', 'HTTP_TRANSACTION_HTTP2_SEND_REQUEST_HEADERS',
                      'HTTP_TRANSACTION_QUIC_SEND_REQUEST_HEADERS'):
            for h in params.get('headers') or []:
                if str(h).lower().startswith('authorization:'):
                    row['auth'] = str(h).split(':', 1)[1].strip()
        elif name == 'HTTP_TRANSACTION_READ_RESPONSE_HEADERS':
            heads = params.get('headers') or []
            m = re.match(r'HTTP/\S+ (\d{3})', str(heads[0])) if heads else None
            if m:
                row['status'] = int(m.group(1))
    return [r for r in found.values() if r.get('url')]


def event_id(fn, args):
    """GA event id of an add*Event call: design 'design:<id>', progression 'progression:Fail:a:b'."""
    if fn == 'addDesignEvent':
        return 'design:' + str(args[0])
    if fn == 'addProgressionEvent':
        status = {1: 'Start', 2: 'Complete', 3: 'Fail'}.get(args[0], str(args[0]))
        return 'progression:' + ':'.join([status] + [str(a) for a in args[1:4] if isinstance(a, str) and a])
    return None


def quit_verdict(calls, rows):
    """calls: [[fn, args]] made from the leave on; rows after the leave."""
    names = [c[0] for c in calls]
    end = names.index('endSession') if 'endSession' in names else len(calls)
    stored = names.index('<session_end stored>') if '<session_end stored>' in names else len(calls)
    expected = [event_id(fn, a) for fn, a in calls[:end] if event_id(fn, a)]
    after_end = [event_id(fn, a) for fn, a in calls[end + 1:] if event_id(fn, a)]
    after_stored = [event_id(fn, a) for fn, a in calls[stored + 1:] if event_id(fn, a)]
    delivered = [c for r in rows if r['url'].endswith('/events') and r['status'] == 200
                 for c in r.get('categories') or []]
    pool = list(delivered)
    missing = []
    for e in expected:
        if e in pool:
            pool.remove(e)
        else:
            missing.append(e)
    # a quit event the pagehide request delivered and the revisit sent again
    duplicates = sorted({e for e in expected if delivered.count(e) > expected.count(e)})
    return {
        'end_session_called': 'endSession' in names,
        'session_end_stored': '<session_end stored>' in names,
        'expected_at_pagehide': expected,
        'delivered_after_leave_200': delivered,
        'missing': missing,
        'added_after_endSession': after_end,
        'added_after_session_end_stored': after_stored,
        'delivered_twice': duplicates,
        'pass': bool(expected) and 'endSession' in names and not missing and not after_end
        and not after_stored and not duplicates,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--zip', type=Path, default=DEFAULT_ZIP)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=20.0)
    parser.add_argument('--quit', action='store_true', help='real pagehide by navigation, then a revisit')
    parser.add_argument('--leave-seconds', type=float, default=10.0)
    parser.add_argument('--revisit-seconds', type=float, default=12.0)
    parser.add_argument('--bfcache', action='store_true',
                        help='leave to a same-origin page, come back from the back/forward cache, leave again')
    parser.add_argument('--restore-seconds', type=float, default=30.0,
                        help='--bfcache: longest wait for the restored session\'s events')
    args = parser.parse_args(argv)
    if args.quit and args.bfcache:
        parser.error('--quit and --bfcache are separate runs')
    env = credentials()
    secrets = {name: env[name] for name in ('GA_GAME_KEY', 'GA_SECRET_KEY') if env.get(name)}

    def redact(text):
        for name, value in secrets.items():
            text = text.replace(value, f'<{name}>')
        return text

    rows, blocked, page_errors = [], [], []
    # Authorization headers of the /events requests DevTools answered (never written)
    seen_auth = set()
    # row index -> (raw url, Authorization) of GA requests DevTools saw fail
    failed_raw = {}
    netlog_dir = Path(tempfile.mkdtemp(prefix='ga-netlog-'))
    netlog = netlog_dir / 'net.json'
    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='ga-smoke-') as site:
        with zipfile.ZipFile(args.zip) as z:
            z.extractall(site)
        if args.bfcache:
            Path(site, 'away.html').write_text('<!doctype html><title>away</title><p>away</p>')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=site))
        Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.server_close)
        stack.callback(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}/'
        playwright = sync_playwright().start()
        stack.callback(playwright.stop)
        launch_args = ['--no-sandbox']
        if args.quit or args.bfcache:
            launch_args += [f'--log-net-log={netlog}', '--net-log-capture-mode=IncludeSensitive']
        if args.bfcache:
            # The default headless shell never restores from the bfcache
            browser = playwright.chromium.launch(channel='chromium', args=launch_args,
                                                 ignore_default_args=['--disable-back-forward-cache'])
        else:
            browser = playwright.chromium.launch(args=launch_args)
        stack.callback(browser.close)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        if args.bfcache:
            context.add_init_script(BFCACHE_LIFECYCLE)

        def route(r):
            url = r.request.url
            if url.startswith(base):
                return r.continue_()
            blocked.append(redact(url))
            return r.abort()
        # TASK-899: GA requests are not intercepted at all (an intercepted
        # request dies with its document, a real keepalive one does not)
        context.route(lambda url: not is_ga(url), route)
        started = time.time()

        def categories(request):
            try:
                body = request.post_data_buffer
                if body and body[:2] == b'\x1f\x8b':
                    body = gzip.decompress(body)
                events = json.loads(body) if body else None
                if isinstance(events, list):
                    return [e.get('category') + (':' + e['event_id'] if e.get('category') in ('design', 'progression')
                                                 and isinstance(e.get('event_id'), str) else '')
                            for e in events if isinstance(e, dict) and isinstance(e.get('category'), str)]
            except Exception as e:  # noqa: BLE001 - evidence only
                return [f'<unreadable: {type(e).__name__}>']
            return None

        def on_response(response):
            if is_ga(response.url):
                row = {'t': round(time.time() - started, 2), 'method': response.request.method,
                       'url': redact(response.url), 'status': response.status,
                       'type': response.request.resource_type}
                if response.url.endswith('/events'):
                    row['categories'] = categories(response.request)
                    seen_auth.add((response.request.headers or {}).get('authorization'))
                rows.append(row)

        def on_failed(request):
            if is_ga(request.url):
                failed_raw[len(rows)] = (request.url, (request.headers or {}).get('authorization'))
                rows.append({'t': round(time.time() - started, 2), 'method': request.method,
                             'url': redact(request.url), 'status': None, 'type': request.resource_type,
                             'failure': request.failure,
                             'categories': categories(request) if request.url.endswith('/events') else None})
        # --bfcache: GA requests DevTools never answered (a page in the bfcache)
        unanswered = {}
        page_fetches = []

        def on_request(request):
            if is_ga(request.url):
                unanswered[id(request)] = (round(time.time() - started, 2), request)
        if args.bfcache:
            context.on('request', on_request)
            context.on('response', lambda r: unanswered.pop(id(r.request), None))
            context.on('requestfailed', lambda r: unanswered.pop(id(r), None))
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
            if session_ok(rows) and env_ok(rows):
                break
        quit_calls, leave_at = [], None
        marks, restored = [], False
        if args.bfcache:
            page.evaluate(RECORD_PHASES)
            page.wait_for_timeout(500)
            leave_at = len(rows)
            rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'leave1'})
            page.goto(base + 'away.html')
            page.wait_for_timeout(args.leave_seconds * 1000)
            rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'restore'})
            page.go_back(wait_until='commit')
            page.wait_for_timeout(1500)
            # (away.html runs the init script too: the game's globals tell the pages apart)
            restored = page.evaluate("() => typeof ANALYTICS === 'object' && "
                                     "window.__gaMarks.some(m => m[0] === 'pageshow' && m[1])")
            if restored:
                def restore_calls(fn):
                    return [c for c in page.evaluate('() => window.__gaLog') if c[0] == 'restore1' and c[1] == fn]
                # The restored page is auto-paused: toggle until the player opened the pause screen
                for _ in range(4):
                    page.mouse.click(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.3)
                    page.wait_for_timeout(500)
                    page.keyboard.press('p')
                    page.wait_for_timeout(700)
                    if any(c[2][:1] == ['ui:pause:open:user'] for c in restore_calls('addDesignEvent')):
                        break
                deadline = time.time() + args.restore_seconds
                while time.time() < deadline:
                    page.wait_for_timeout(1000)
                    expected = [event_id(fn, a) for ph, fn, a in page.evaluate('() => window.__gaLog')
                                if ph == 'restore1' and event_id(fn, a)]
                    pool = delivered_200(rows[[i for i, r in enumerate(rows) if r.get('marker') == 'restore'][0]:])
                    if expected and all(pool.count(e) >= expected.count(e) for e in expected) and 'user' in pool:
                        break
                page.wait_for_timeout(500)
                rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'leave2'})
                page.goto(base + 'away.html')
                page.wait_for_timeout(args.leave_seconds * 1000)
                # Come back once more only to read the page's call log
                rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'back to read the log'})
                page.go_back(wait_until='commit')
                page.wait_for_timeout(1500)
            if page.evaluate("() => typeof ANALYTICS === 'object'"):
                quit_calls[:] = page.evaluate('() => window.__gaLog')
                marks[:] = page.evaluate('() => window.__gaMarks')
                page_fetches[:] = page.evaluate('() => window.__gaFetch || []')
            rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'end'})
        elif args.quit:
            page.on('console', lambda m: quit_calls.append(json.loads(m.text[len('GA-CALL '):]))
                    if m.text.startswith('GA-CALL ') else None)
            page.evaluate(RECORD_SDK)
            page.wait_for_timeout(500)
            quit_calls.clear()
            leave_at = len(rows)
            rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'leave (goto about:blank)'})
            page.goto('about:blank')
            page.wait_for_timeout(args.leave_seconds * 1000)
            rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'revisit'})
            page.goto(base + 'index.html')
            wait_for_boot_run(page)
            page.wait_for_timeout(args.revisit_seconds * 1000)
            rows.append({'url': '', 't': round(time.time() - started, 2), 'marker': 'end'})
        else:
            page.evaluate('() => ANALYTICS.sessionEnd()')
            page.wait_for_timeout(2000)
        context.close()
        browser.close()
        for t, request in unanswered.values():
            if request.method == 'POST' and request.url.endswith('/events'):
                failed_raw[len(rows)] = (request.url, (request.headers or {}).get('authorization'))
                rows.append({'t': t, 'method': request.method, 'url': redact(request.url), 'status': None,
                             'type': request.resource_type, 'failure': 'no response in DevTools (page in bfcache)',
                             'categories': categories(request)})

    netlog_summary = []
    if args.quit or args.bfcache:
        logged = netlog_requests(netlog) if netlog.exists() else []
        auths = {auth for _, auth in failed_raw.values() if auth}
        netlog_summary = [{'method': r.get('method'), 'events': r['url'].endswith('/events'),
                           'status': r.get('status'), 'has_auth': bool(r.get('auth')),
                           'auth_matches_failed_request': r.get('auth') in auths}
                          for r in logged if is_ga(r['url']) and r.get('method') != 'OPTIONS']
        for i, (url, auth) in failed_raw.items():
            hits = [r for r in logged if r.get('method') == 'POST' and r['url'] == url and auth
                    and r.get('auth') == auth and r.get('status')]
            if hits:
                rows[i]['devtools_failure'] = rows[i].pop('failure', None)
                rows[i]['status'] = hits[-1]['status']
                rows[i]['status_source'] = 'netlog'
        if args.bfcache:
            # In-page keepalive /events fetches DevTools never reported: the
            # status of the NetLog request with the same Authorization header,
            # placed right after the marker of the phase that sent them
            marker_t = {r['marker']: r['t'] for r in rows if r.get('marker')}
            names = {'leave1': 'leave1', 'restore1': 'restore', 'leave2': 'leave2'}
            for f in page_fetches:
                if f['auth'] in seen_auth:
                    continue
                hits = [r for r in logged if r.get('method') == 'POST' and r['url'] == f['url']
                        and r.get('auth') == f['auth'] and r.get('status')]
                rows.append({'t': marker_t.get(names.get(f['phase']), 0) + 0.01, 'method': 'POST',
                             'url': redact(f['url']), 'status': hits[-1]['status'] if hits else None,
                             'type': 'fetch', 'keepalive': f['keepalive'], 'phase': f['phase'],
                             'status_source': 'netlog' if hits else 'none',
                             'body_source': 'in-page fetch', 'categories': f['categories']})
    shutil.rmtree(netlog_dir, ignore_errors=True)
    if args.bfcache:
        rows.sort(key=lambda r: r['t'])
        leave_at = next(i for i, r in enumerate(rows) if r.get('marker') == 'leave1')

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
    report['env_events_200'] = env_ok(rows)
    report['pass'] = (report['session_start_events_200'] and report['env_events_200'] and not page_errors
                      and state['backend'] == 'gameanalytics' and state['runInProgress'])
    if args.quit:
        report['mode'] = 'quit'
        report['netlog_ga_requests'] = netlog_summary
        report['sdk_calls_from_leave'] = quit_calls
        report['quit'] = quit_verdict(quit_calls, rows[leave_at:])
        report['pass'] = report['pass'] and report['quit']['pass']
    if args.bfcache:
        report['mode'] = 'bfcache'
        report['netlog_ga_requests'] = netlog_summary
        report['sdk_calls_from_leave'] = quit_calls
        report['bfcache'] = bfcache_verdict(quit_calls, rows[leave_at:], marks, restored)
        report['pass'] = report['pass'] and report['bfcache']['pass']
    text = redact(json.dumps(report, separators=(',', ':')))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + '\n')
    print(('PASS' if report['pass'] else 'FAIL') + f': init statuses {report["init_statuses"]}, '
          f'events statuses {report["events_statuses"]}, page errors {len(page_errors)}')
    if args.quit:
        q = report['quit']
        print(f'quit: expected {len(q["expected_at_pagehide"])}, missing {q["missing"]}, '
              f'after endSession {q["added_after_endSession"]}, after session_end {q["added_after_session_end_stored"]}')
    if args.bfcache:
        b = report['bfcache']
        print(f'bfcache: restored {b["restored_from_bfcache"]}, marks {b["marks"]}, restore calls {b["restore_calls"]}, '
              f'missing {b["restore_missing"]}, user 200 {b["restore_session_user_event_200"]}, '
              f'twice {b["delivered_twice_after_restore"]}, leave1 pass {b["leave1_quit"]["pass"]} '
              f'(missing {b["leave1_quit"]["missing"]}), leave2 pass {b["leave2_quit"]["pass"]} '
              f'(missing {b["leave2_quit"]["missing"]})')
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
