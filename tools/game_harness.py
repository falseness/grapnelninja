"""Open game pages in a shared test browser and observe PLATFORM storage.

The local build has no SDK: PLATFORM.storage goes to localStorage. An init
script wraps Storage.prototype.getItem/setItem on localStorage and groups the
calls made in one synchronous run (one getMany or setMany) into one record
{name: 'storage.get' | 'storage.set', args: [keys, values], t} in
window.__storageSpy.calls, the call log shape the tests expect.
"""
from browser_test_support import start_browser_test

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


def start_game_test(root, add_cleanup):
    """Return URL/browser from the shared server/browser lifetime."""
    return start_browser_test(root, add_cleanup)


def open_game(browser, url, viewport, **context_options):
    """Return (context, page, errors); errors has 'console' and 'page' lists."""
    context = browser.new_context(viewport=viewport, **context_options)
    context.add_init_script(STORAGE_SPY)
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
    """Return the recorded localStorage get/set batches ([] without the spy)."""
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

