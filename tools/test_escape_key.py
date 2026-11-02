"""TASK-872: the Playgama build does not use the Escape key.

Playgama requirement 1.5.2: the browser reserves Escape for leaving full
screen. In the playgama build (BUILD_CONFIG.platform 'playgama',
buildUsesEscape() false) Escape neither pauses / unpauses nor answers the Go
back dialog, and its keydown is not preventDefault-ed; P still pauses and the
dialog keeps Enter (and arrows / Space / its buttons). Other builds (itch here)
keep Escape: it pauses, and keeps falling in the Go back dialog.

Zips come from ESC_ZIP_DIR (DIR/<portal>/grapple-over-<portal>.zip, as
tools/build_release.py writes them) or are built from HEAD into a temp dir
(the itch build needs GA_GAME_KEY / GA_SECRET_KEY, else skipped). The playgama
zip boots offline with game_harness.LOCAL_BRIDGE as its SDK (no Playgama URL
is ever loaded); the itch GameAnalytics SDK is stubbed. ESC_KEYS_EVIDENCE=FILE
writes one compact JSON row per build.

    ESC_ZIP_DIR=artifacts/TASK-872/build python3 tools/test_escape_key.py -v
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

VIEWPORT = {'width': 1280, 'height': 720}
PORTALS = ('playgama', 'itch')

# Records whether each keydown reached the window already defaultPrevented
KEY_SPY = r'''(() => {
    window.__keys = []
    addEventListener('keydown', e => __keys.push({key: e.key, prevented: e.defaultPrevented}))
})()'''
STATE = '''() => ({paused: menu.gamePaused, dialog: CLIMB_UI.goBackOpen(),
    goingBack: CLIMB_UI.goingBack, prevented: (__keys[__keys.length - 1] || {}).prevented})'''


def log(msg):
    print(msg, file=sys.stderr, flush=True)


class EscapeKeyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import build_release
        cls.build_release = build_release
        zip_dir = os.environ.get('ESC_ZIP_DIR')
        if zip_dir:
            cls.out = Path(zip_dir)
            return
        from test_build_release import y8_env
        env = y8_env()
        if not (env['GA_GAME_KEY'] and env['GA_SECRET_KEY']):
            raise unittest.SkipTest('GA_GAME_KEY / GA_SECRET_KEY unavailable for the itch build')
        cls.out = Path(tempfile.mkdtemp(prefix='esc-zips-'))
        cls.addClassCleanup(shutil.rmtree, cls.out, True)
        tree = build_release.CommittedTree('HEAD')
        for portal in PORTALS:
            build_release.build(portal, cls.out, env=env, tree=tree)

    def press(self, page, key):
        page.keyboard.press(key)
        # Two frames: the key handler and any redraw have run
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        return page.evaluate(STATE)

    def run_build(self, portal):
        from browser_test_support import start_browser_test, wait_for_boot_run
        from game_harness import LOCAL_BRIDGE, SDK_URL, collect_errors
        path = self.out / portal / f'grapple-over-{portal}.zip'
        site = Path(tempfile.mkdtemp(prefix=f'esc-{portal}-'))
        self.addCleanup(shutil.rmtree, site, True)
        with zipfile.ZipFile(path) as z:
            z.extractall(site)
        with ExitStack() as stack:
            url, browser = start_browser_test(site, stack.callback)
            context = browser.new_context(viewport=VIEWPORT, locale='en-US')
            stack.callback(context.close)
            context.route(url + self.build_release.GA_SDK, lambda r: r.fulfill(
                content_type='application/javascript', body='// GameAnalytics stub\n'))
            if portal == 'playgama':
                context.route(SDK_URL, lambda r: r.fulfill(
                    content_type='application/javascript', body=LOCAL_BRIDGE))
            context.add_init_script(KEY_SPY)
            page = context.new_page()
            errors = collect_errors(page)
            page.goto(url + 'index.html')
            wait_for_boot_run(page)
            page.wait_for_function('() => runInProgress && !menu.gamePaused && !isViewRotated()')
            row = {'portal': portal, 'platform': page.evaluate('BUILD_CONFIG.platform'),
                   'usesEscape': page.evaluate('buildUsesEscape()'),
                   'zipSha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            # In play: Escape, then P (each from an unpaused run)
            row['escInPlay'] = self.press(page, 'Escape')
            if row['escInPlay']['paused']:
                row['escAgain'] = self.press(page, 'Escape')  # Escape unpauses where it pauses
                if page.evaluate('menu.gamePaused'):
                    page.evaluate('menu.unPause()')
            row['pInPlay'] = self.press(page, 'p')
            row['pAgain'] = self.press(page, 'p')
            if page.evaluate('menu.gamePaused'):
                page.evaluate('menu.unPause()')
            # Go back dialog: Escape, then Enter (focus on Go back)
            page.evaluate('() => CLIMB_UI.offerGoBack()')
            row['dialogOpened'] = page.evaluate(STATE)
            row['escInDialog'] = self.press(page, 'Escape')
            if row['escInDialog']['dialog']:
                page.keyboard.press('Enter')
                page.wait_for_function('() => !CLIMB_UI.goingBack', timeout=20000)
                row['enterInDialog'] = page.evaluate(STATE)
            else:
                # Escape answered it (other builds): reopen to check Enter too
                page.evaluate('() => CLIMB_UI.offerGoBack()')
                page.keyboard.press('Enter')
                page.wait_for_function('() => !CLIMB_UI.goingBack', timeout=20000)
                row['enterInDialog'] = page.evaluate(STATE)
            row['pageErrors'] = errors['page']
            return row

    def test_escape_by_build(self):
        rows = []
        for portal in PORTALS:
            with self.subTest(portal=portal):
                row = self.run_build(portal)
                pg = portal == 'playgama'
                row['pass'] = (
                    row['platform'] == portal and row['usesEscape'] == (not pg)
                    and row['escInPlay']['paused'] == (not pg)
                    and row['escInPlay']['prevented'] == (not pg)
                    and (pg or row['escAgain']['paused'] is False)
                    and row['pInPlay']['paused'] is True and row['pAgain']['paused'] is False
                    and row['dialogOpened']['dialog'] is True
                    and row['escInDialog']['dialog'] == pg
                    and row['escInDialog']['paused'] == pg
                    and row['enterInDialog']['dialog'] is False
                    and row['enterInDialog']['paused'] is False
                    and row['pageErrors'] == [])
                rows.append(row)
                log(json.dumps(row, separators=(',', ':')))
                self.assertEqual(row['pageErrors'], [])
                self.assertEqual((row['platform'], row['usesEscape']), (portal, not pg))
                # Escape in play: nothing on Playgama (not even preventDefault), pause elsewhere
                self.assertEqual((row['escInPlay']['paused'], row['escInPlay']['prevented']), (not pg, not pg))
                if not pg:
                    self.assertFalse(row['escAgain']['paused'])
                # P pauses and unpauses everywhere
                self.assertEqual((row['pInPlay']['paused'], row['pAgain']['paused']), (True, False))
                self.assertTrue(row['dialogOpened']['dialog'])
                # Escape leaves the dialog open on Playgama, keeps falling elsewhere
                self.assertEqual((row['escInDialog']['dialog'], row['escInDialog']['paused']), (pg, pg))
                # Enter answers the dialog (Go back) everywhere
                self.assertEqual((row['enterInDialog']['dialog'], row['enterInDialog']['paused']), (False, False))
                self.assertTrue(row['pass'])
        evidence = os.environ.get('ESC_KEYS_EVIDENCE')
        if evidence:
            Path(evidence).write_text(json.dumps(rows, separators=(',', ':')) + '\n')
        self.assertEqual(len(rows), 2)


if __name__ == '__main__':
    unittest.main()
