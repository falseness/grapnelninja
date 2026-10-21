"""Open game pages in a shared test browser and observe PLATFORM storage.

Offline, the SDK fixture defines no window.bridge, so PLATFORM is 'disabled'
and nothing persists. open_game(..., fake_bridge=True) serves LOCAL_BRIDGE
instead: a Playgama Bridge whose platform.language is navigator.language
(the context locale) and whose storage persists in the page's localStorage,
so storage and language survive page.reload() like on a real host.

An init script wraps Storage.prototype.getItem/setItem on localStorage and groups
the calls made in one synchronous run into one record
{name: 'storage.get' | 'storage.set', args: [keys, values], t} in
window.__storageSpy.calls, the call log shape the tests expect. LOCAL_BRIDGE
logs one such record per bridge.storage.get/set and uses the raw methods.
"""
from browser_test_support import SDK_URL, start_browser_test

STORAGE_SPY = r'''(() => {
    if (window.__storageSpy) return
    const proto = Storage.prototype
    const raw = {getItem: proto.getItem, setItem: proto.setItem}
    const spy = window.__storageSpy = {calls: [], raw: raw}
    let batch = null
    function record(name, key, value) {
        if (batch && batch.name !== name) flush()
        if (!batch) {
            batch = {name: name, args: [[], []], t: performance.now()}
            queueMicrotask(flush)
        }
        batch.args[0].push(key)
        batch.args[1].push(value)
    }
    function flush() {
        if (!batch) return
        if (batch.name === 'storage.get') batch.args = [batch.args[0]]
        spy.calls.push(batch)
        batch = null
    }
    proto.getItem = function (key) {
        const value = raw.getItem.call(this, key)
        if (this === window.localStorage) record('storage.get', String(key), value)
        return value
    }
    proto.setItem = function (key, value) {
        if (this === window.localStorage) record('storage.set', String(key), String(value))
        return raw.setItem.call(this, key, value)
    }
})()'''


# Removed local adapter (7fd7a46/83e53de) rebuilt behind the Bridge boundary
LOCAL_BRIDGE = r'''(() => {
    const spy = window.__storageSpy
    const raw = spy ? spy.raw : {getItem: Storage.prototype.getItem, setItem: Storage.prototype.setItem}
    const log = (name, args) => spy && spy.calls.push({name: name, args: args, t: performance.now()})
    const noop = () => {}
    window.bridge = {
        async initialize() {},
        EVENT_NAME: {PAUSE_STATE_CHANGED: 'pause', AUDIO_STATE_CHANGED: 'audio',
            INTERSTITIAL_STATE_CHANGED: 'interstitial', REWARDED_STATE_CHANGED: 'rewarded'},
        platform: {id: 'local-fake', language: navigator.language, isAudioEnabled: true,
            on: noop, sendMessage: () => Promise.resolve()},
        advertisement: {on: noop, off: noop, isInterstitialSupported: false, isRewardedSupported: false},
        storage: {
            async get(keys) {
                log('storage.get', [keys.slice()])
                return keys.map(key => raw.getItem.call(localStorage, key))
            },
            async set(keys, values) {
                log('storage.set', [keys.slice(), values.slice()])
                keys.forEach((key, i) => raw.setItem.call(localStorage, key, values[i]))
            }
        }
    }
})()
'''


def start_game_test(root, add_cleanup):
    """Return URL/browser from the shared server/browser lifetime."""
    return start_browser_test(root, add_cleanup)


def open_game(browser, url, viewport, fake_bridge=False, **context_options):
    """Return (context, page, errors); errors has 'console' and 'page' lists.

    fake_bridge serves LOCAL_BRIDGE as the SDK (see the module docstring).
    """
    context = browser.new_context(viewport=viewport, **context_options)
    context.add_init_script(STORAGE_SPY)
    if fake_bridge:
        context.route(SDK_URL, lambda route: route.fulfill(
            content_type='application/javascript', body=LOCAL_BRIDGE))
    page = context.new_page()
    errors = collect_errors(page)
    page.goto(url)
    return context, page, errors


def collect_errors(page):
    """Collect console errors and uncaught page errors."""
    errors = {'console': [], 'page': []}

    def on_console(msg):
        if msg.type == 'error':
            errors['console'].append(msg.text)

    page.on('console', on_console)
    page.on('pageerror', lambda exc: errors['page'].append(str(exc)))
    return errors


def storage_calls(page):
    """Return the recorded storage get/set batches ([] without the spy)."""
    return page.evaluate(
        '() => (window.__storageSpy && window.__storageSpy.calls) || []')


def local_store(page):
    """Return localStorage as a dict, read without touching the spy log."""
    return page.evaluate('''() => {
        const get = (window.__storageSpy ? window.__storageSpy.raw.getItem
                                         : Storage.prototype.getItem)
        return Object.fromEntries(Object.keys(localStorage).sort()
            .map(k => [k, get.call(localStorage, k)]))
    }''')


def seed_store(page, store):
    """Replace localStorage with store (dict of strings), not logged."""
    page.evaluate('''(store) => {
        const set = (window.__storageSpy ? window.__storageSpy.raw.setItem
                                         : Storage.prototype.setItem)
        localStorage.clear()
        for (const [k, v] of Object.entries(store)) set.call(localStorage, k, v)
    }''', store)


def canvas_to_viewport(page, x, y):
    """Invert the page's affine viewportCoordsToCanvasCoords at (x, y)."""
    return page.evaluate('''([x, y]) => {
        const o = viewportCoordsToCanvasCoords({x: 0, y: 0})
        const ex = viewportCoordsToCanvasCoords({x: 1, y: 0})
        const ey = viewportCoordsToCanvasCoords({x: 0, y: 1})
        const a = ex.x - o.x, b = ey.x - o.x, c = ex.y - o.y, d = ey.y - o.y
        const det = a * d - b * c
        const dx = x - o.x, dy = y - o.y
        return {x: (d * dx - b * dy) / det, y: (a * dy - c * dx) / det}
    }''', [x, y])


def click_canvas(page, x, y):
    """Click at logical canvas coordinates (x, y)."""
    point = canvas_to_viewport(page, x, y)
    page.mouse.click(point['x'], point['y'])
    return point


# The game booted: platform ready, loading overlay hidden, and the boot-time
# main-version ('bad') run started (there is no title menu)
READY = ('PLATFORM.environment !== "pending" && bootComplete && runInProgress'
         ' && document.getElementById("loading").hidden')


def switch_mode(page, mode):
    """Make mode ('classic'/'bad'/'momentum') the running mode via the pause
    screen's mode selector.

    The title menu is gone: any mode is entered by pausing and clicking its
    button in menu.modeSelector. The click is a real mouse click at the
    button's centre; a rotated (portrait touch) view ignores page input, so
    there the same canvas point goes through the menu's hit test instead.
    No-op when mode is already running.
    """
    target = page.evaluate('''mode => {
        if (version === mode && runInProgress) return null
        if (!menu.gamePaused) menu.startPause()
        const b = menu.modeSelector.button(mode).background
        return {x: b.x + b.width / 2, y: b.y + b.height / 2, rotated: isViewRotated()}
    }''', mode)
    if target is not None:
        if target['rotated']:
            page.evaluate('p => menu.click(p)', target)
        else:
            # A real press within STYLE.timing.inputUntouchMs of the last
            # menu click (e.g. a pause checkbox) is dropped by events.js
            page.wait_for_function('!unTouch')
            click_canvas(page, target['x'], target['y'])
    # A rotated (portrait touch) view starts the new run paused (TASK-403);
    # resume it as the switch did before, so callers get a live run
    page.wait_for_function('mode => version === mode && runInProgress', arg=mode)
    page.evaluate('() => { if (menu.gamePaused && isViewRotated()) menu.unPause() }')
    page.wait_for_function(
        'mode => version === mode && runInProgress && !menu.gamePaused', arg=mode)
