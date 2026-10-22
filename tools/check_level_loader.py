#!/usr/bin/env python3
"""Run level JSON files through the production loader in the booted game.

Serves the repo with tools/browser_test_support.py, boots index.html in
Chromium and calls the page's own validateFixedLevel() and loadFixedLevel()
(fixedlevel.js) on each file. Prints one ACCEPT/REJECT line per file and
exits 0 only when every file is accepted.

    python3 tools/check_level_loader.py LEVEL.json [LEVEL.json ...]
"""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys

from browser_test_support import start_browser_test, wait_for_boot

ROOT = Path(__file__).resolve().parent.parent

LOAD = '''data => {
    const result = {}
    try { validateFixedLevel(data); result.validate = 'accept' }
    catch (e) { result.validate = 'reject'; result.error = e.message; return result }
    const world = loadFixedLevel(data)
    result.world = world.constructor.name
    result.elements = world.elements.length
    result.dragZones = world.dragZones.length
    result.ids = world.elements.map(e => e.id).concat(world.dragZones.map(e => e.id))
    result.grapplable = world.elements.filter(e => e.grapplable).length
    result.roles = world.elements.reduce((n, e) => (n[e.surfaceRole] = (n[e.surfaceRole] || 0) + 1, n), {})
    return result
}'''


def check_levels(levels):
    """Return [(path, result)] from the production loader in one booted page."""
    with ExitStack() as stack:
        url, browser = start_browser_test(ROOT, stack.callback)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        wait_for_boot(page)
        out = [(path, page.evaluate(LOAD, json.loads(Path(path).read_text()))) for path in levels]
        return browser.version, out, errors


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    source = (ROOT / 'fixedlevel.js').read_bytes()
    print('LOADER fixedlevel.js sha256=%s' % hashlib.sha256(source).hexdigest())
    version, results, errors = check_levels(argv)
    print('BROWSER chromium %s' % version)
    ok = not errors
    for path, r in results:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if r['validate'] == 'accept':
            ids = r['ids']
            print('ACCEPT %s sha256=%s validateFixedLevel=accept loadFixedLevel=%s elements=%d dragZones=%d grapplable=%d roles=%s unique_ids=%s' % (
                path, digest, r['world'], r['elements'], r['dragZones'], r['grapplable'],
                json.dumps(r['roles'], sort_keys=True), len(set(ids)) == len(ids)))
        else:
            ok = False
            print('REJECT %s sha256=%s validateFixedLevel=reject error=%s' % (path, digest, r['error']))
    for e in errors:
        print('PAGE_ERROR %s' % e)
    print('LOADER_RESULT %s files=%d page_errors=%d' % ('PASS' if ok else 'FAIL', len(results), len(errors)))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
