"""TASK-873 probe: the built playgama zip never touches localStorage.

Boots the zip offline with game_harness.LOCAL_BRIDGE as its SDK (no Playgama
URL is requested). An init script wraps Storage.prototype.getItem/setItem/
removeItem before any game script runs and counts calls on localStorage; the
fake bridge reads and writes through the raw methods (window.__storageSpy.raw)
so only the game's own direct access is counted. Counts persist across the
reload in sessionStorage (raw methods, not counted).

Sequence: boot, 20 s of play, pagehide, reload, 5 s of play, pagehide.
Writes compact JSON: localStorage call count, bridge storage get/set calls
with the play time key, totals before/after the reload.

    python3 tools/probe_storage_calls.py ZIP OUT.json
"""
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import SDK_URL, start_browser_test, wait_for_boot_run  # noqa: E402
from game_harness import LOCAL_BRIDGE  # noqa: E402

KEY = 'grapnelninja_playtime_v1'
SPY = r'''(() => {
    const proto = Storage.prototype
    const raw = {getItem: proto.getItem, setItem: proto.setItem, removeItem: proto.removeItem}
    window.__storageSpy = {calls: [], raw: raw}
    const bump = (name, key) => {
        const s = window.sessionStorage
        const counts = JSON.parse(raw.getItem.call(s, '__lsCalls') || '{}')
        counts[name] = (counts[name] || 0) + 1
        counts.keys = Array.from(new Set([...(counts.keys || []), String(key)]))
        raw.setItem.call(s, '__lsCalls', JSON.stringify(counts))
    }
    for (const name of ['getItem', 'setItem', 'removeItem'])
        proto[name] = function (key, ...rest) {
            if (this === window.localStorage) bump(name, key)
            return raw[name].call(this, key, ...rest)
        }
})()'''
PAGEHIDE = "() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))"
COUNTS = "() => JSON.parse(window.__storageSpy.raw.getItem.call(sessionStorage, '__lsCalls') || '{}')"
BRIDGE = '() => window.__storageSpy.calls'


def play(page, seconds):
    page.wait_for_function('() => runInProgress && !isViewRotated()')
    if page.evaluate('menu.gamePaused'):
        page.evaluate('menu.unPause()')
    page.wait_for_timeout(seconds * 1000)


def bridge_rows(calls):
    """Only the fields the assertions need: op, has play time key, its value."""
    rows = []
    for c in calls:
        keys = c['args'][0]
        row = {'op': c['name'], 'n': len(keys), 'playtime': KEY in keys}
        if c['name'] == 'storage.set' and KEY in keys:
            row['value'] = json.loads(c['args'][1][keys.index(KEY)])
        rows.append(row)
    return rows


def main(zip_path, out):
    zip_path = Path(zip_path)
    site = Path(tempfile.mkdtemp(prefix='probe873-'))
    result = {'zip': str(zip_path), 'zipSha256': hashlib.sha256(zip_path.read_bytes()).hexdigest()}
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(site)
        with ExitStack() as stack:
            url, browser = start_browser_test(site, stack.callback)
            context = browser.new_context(viewport={'width': 1280, 'height': 720}, locale='en-US')
            stack.callback(context.close)
            requests = []
            context.on('request', lambda r: requests.append(r.url))
            context.route(SDK_URL, lambda r: r.fulfill(content_type='application/javascript', body=LOCAL_BRIDGE))
            context.add_init_script(SPY)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + 'index.html')
            wait_for_boot_run(page)
            result['platform'] = page.evaluate('[BUILD_CONFIG.platform, PLATFORM.environment]')
            result['progressKeys'] = page.evaluate('PROGRESS.keys')
            play(page, 20)
            before = page.evaluate('TELEMETRY.playTime()')
            page.evaluate(PAGEHIDE)
            page.wait_for_timeout(500)
            page1 = bridge_rows(page.evaluate(BRIDGE))
            page.reload()
            wait_for_boot_run(page)
            restored = page.evaluate('TELEMETRY.playTime()')
            play(page, 5)
            after = page.evaluate('TELEMETRY.playTime()')
            page.evaluate(PAGEHIDE)
            page.wait_for_timeout(500)
            page2 = bridge_rows(page.evaluate(BRIDGE))
            counts = page.evaluate(COUNTS)
            ls_calls = sum(v for k, v in counts.items() if k != 'keys')
            result.update({
                'localStorageCalls': ls_calls, 'localStorageCounts': counts,
                'bridge': {'page1': page1, 'page2': page2},
                'bridgeGets': sum(r['op'] == 'storage.get' for r in page1 + page2),
                'bridgePlaytimeSets': sum(r['op'] == 'storage.set' and r['playtime'] for r in page1 + page2),
                'totalsBefore': before['total'], 'totalsRestored': restored['total'], 'totalsAfter': after['total'],
                'sessionPage1': before['session'], 'sessionPage2': after['session'],
                # SDK_URL is fulfilled by the route above (never reaches the network)
                'sdkRequestsFulfilledLocally': requests.count(SDK_URL),
                'playgamaRequests': [u for u in requests
                                     if 'playgama' in u.lower() and not u.startswith(url) and u != SDK_URL],
                'pageErrors': errors})
    finally:
        shutil.rmtree(site, True)
    modes = ('single', 'double')
    checks = {
        'localStorageCallsZero': result['localStorageCalls'] == 0,
        'oneGetPerBoot': [r['op'] for r in result['bridge']['page1']].count('storage.get') == 1
        and [r['op'] for r in result['bridge']['page2']].count('storage.get') == 1,
        'getsCarryPlaytimeKey': all(r['playtime'] for r in result['bridge']['page1'] + result['bridge']['page2']
                                    if r['op'] == 'storage.get'),
        'bridgePlaytimeSetsAtLeast1': result['bridgePlaytimeSets'] >= 1,
        'playedPage1': sum(result['sessionPage1'].values()) >= 15000,
        # Stored totals are rounded to whole ms
        'restoredGeBefore': all(result['totalsRestored'][m] >= result['totalsBefore'][m] - 1 for m in modes),
        'totalsAfterGeBefore': all(result['totalsAfter'][m] >= result['totalsBefore'][m] for m in modes)
        and sum(result['totalsAfter'].values()) > sum(result['totalsBefore'].values()),
        'noPlaygamaRequests': not result['playgamaRequests'],
        'noPageErrors': not result['pageErrors']}
    result['checks'] = checks
    result['pass'] = all(checks.values())
    Path(out).write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(json.dumps({'pass': result['pass'], 'checks': checks}))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
