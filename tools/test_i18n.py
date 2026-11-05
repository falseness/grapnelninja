"""English + Russian localization (TASK-126).

The browser locale is navigator.language. The 'local' PLATFORM that reported
it was removed in 7fd7a46 (TASK-236); each page now gets game_harness.LOCAL_BRIDGE,
a fake Bridge whose platform.language is navigator.language. Boot language: the saved 'grapnelninja.lang' storage value,
else 'ru' for a platform language starting with 'ru', else 'en'. The menu's
LANGUAGE_BUTTON switches language at once and saves it through the single
storage write (fake Bridge storage in localStorage, observed by
game_harness's storage spy).

Env: I18N_EVIDENCE_DIR receives key-parity.txt, ru-strings.md and
screens/{en,ru}/{menu,pause,hud}.png (1280x720) plus the same under
screens/{en,ru}/390x844/.
"""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import READY, canvas_to_viewport, open_game, start_game_test, storage_calls, switch_mode
import test_continue as continue_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
LANG_KEY = 'grapnelninja.lang'

# Pixels of single glyphs drawn in the game font. Missing glyphs render as
# identical tofu boxes, so distinct Cyrillic letters must give distinct images.
GLYPHS = '''(chars) => {
    const c = document.createElement('canvas')
    c.width = 64; c.height = 64
    const g = c.getContext('2d')
    g.font = '48px ' + STYLE.ui.fontFamily
    g.textBaseline = 'middle'
    return chars.map(ch => {
        g.clearRect(0, 0, 64, 64)
        g.fillStyle = 'black'
        g.fillText(ch, 4, 32)
        const data = g.getImageData(0, 0, 64, 64).data
        let ink = 0, hash = 0
        for (let i = 3; i < data.length; i += 4) {
            if (data[i]) ink++
            hash = (hash * 31 + data[i]) | 0
        }
        return {ch: ch, ink: ink, hash: hash}
    })
}'''


def log(msg):
    print('  ' + msg, file=sys.stderr)


class I18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('I18N_EVIDENCE_DIR')
        cls.marks = {}

    def open(self, language, viewport=VIEWPORT):
        context, page, errors = open_game(self.browser, self.url + 'index.html',
                                          viewport, locale=language, fake_bridge=True)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function(READY, timeout=15000)
        self.marks[id(page)] = len(storage_calls(page))
        return page

    def ui(self, page):
        # Grapple Over's pause screen (CLIMB_UI) is rebuilt on each draw; [3] is the chill (classic) switch
        page.evaluate('() => { if (!menu.gamePaused) menu.startPause() }')
        return page.evaluate('''() => ({lang: I18N.language, title: document.title,
            htmlLang: document.documentElement.lang,
            chill: (redrawOverlays(), CLIMB_UI.buttons[3].text.text), button: I18N.t('language.name')})''')

    def click_language(self, page):
        # The language button lives on the pause and death screens (TASK-363)
        page.evaluate('() => { if (!menu.gamePaused) menu.startPause() }')
        page.wait_for_function('LANGUAGE_BUTTON.active() && !unTouch')
        r = page.evaluate('LANGUAGE_BUTTON.rect()')
        p = canvas_to_viewport(page, r['x'] + r['width'] / 2, r['y'] + r['height'] / 2)
        # Pausing saves progress (language unchanged); count only later saves
        self.marks[id(page)] = len(storage_calls(page))
        page.mouse.click(p['x'], p['y'])

    def wait_lang_saved(self, page):
        page.wait_for_function(f'''mark => window.__storageSpy.calls.slice(mark).some(c =>
            c.name == 'storage.set' && c.args[0].includes({json.dumps(LANG_KEY)}))''',
                               arg=self.marks.get(id(page), 0))

    def saved_langs(self, page):
        out = []
        for c in storage_calls(page)[self.marks.get(id(page), 0):]:
            if c['name'] == 'storage.set' and LANG_KEY in c['args'][0]:
                out.append(c['args'][1][c['args'][0].index(LANG_KEY)])
        return out

    def test_ru_locale_boots_russian(self):
        ui = self.ui(self.open('ru-RU'))
        self.assertEqual(ui, {'lang': 'ru', 'title': 'Grapple Over', 'htmlLang': 'ru',
                              'chill': 'спокойный режим', 'button': 'Русский'})
        log('ru-RU -> ru: pass')

    def test_en_locale_boots_english(self):
        ui = self.ui(self.open('en-US'))
        self.assertEqual(ui, {'lang': 'en', 'title': 'Grapple Over', 'htmlLang': 'en',
                              'chill': 'chill version', 'button': 'English'})
        log('en-US -> en: pass')

    def test_other_locale_boots_english(self):
        self.assertEqual(self.ui(self.open('de-DE'))['lang'], 'en')
        log('de-DE -> en: pass')

    def test_toggle_switches_and_persists_across_reload(self):
        page = self.open('en-US')
        self.click_language(page)
        ui = self.ui(page)
        self.assertEqual((ui['lang'], ui['chill'], ui['button'], ui['htmlLang']),
                         ('ru', 'спокойный режим', 'Русский', 'ru'))
        self.wait_lang_saved(page)
        self.assertEqual(self.saved_langs(page), ['ru'])
        page.reload()
        page.wait_for_function(READY, timeout=15000)
        self.assertEqual(self.ui(page)['lang'], 'ru')
        log('en-US, toggle -> ru, saved, reload -> ru: pass')

        # The saved choice beats a Russian platform language too
        page = self.open('ru-RU')
        self.assertEqual(self.ui(page)['lang'], 'ru')
        self.click_language(page)
        self.assertEqual(self.ui(page)['lang'], 'en')
        self.wait_lang_saved(page)
        self.assertEqual(self.saved_langs(page), ['en'])
        page.reload()
        page.wait_for_function(READY, timeout=15000)
        self.assertEqual(self.ui(page)['lang'], 'en')
        log('ru-RU, toggle -> en, saved, reload -> en: pass')

    def test_every_key_in_both_dictionaries(self):
        page = self.open('en-US')
        d = page.evaluate('I18N.dictionaries')
        self.assertEqual(sorted(d), ['en', 'ru'])
        missing_ru = sorted(set(d['en']) - set(d['ru']))
        missing_en = sorted(set(d['ru']) - set(d['en']))
        empty = sorted(k for lang in d for k, v in d[lang].items() if not v.strip())
        report = (f'keys en: {len(d["en"])}\nkeys ru: {len(d["ru"])}\n'
                  f'missing in ru: {missing_ru}\nmissing in en: {missing_en}\n'
                  f'empty values: {empty}\n')
        # Placeholders must match so t() fills the same params
        placeholders = {}
        for k in d['en']:
            en = sorted(p for p in d['en'][k].split('{')[1:])
            ru = sorted(p for p in d['ru'].get(k, '').split('{')[1:])
            en = sorted(p.split('}')[0] for p in en)
            ru = sorted(p.split('}')[0] for p in ru)
            if en != ru:
                placeholders[k] = (en, ru)
        report += f'placeholder mismatches: {placeholders}\n'
        # Every ru string except the titles (game.title, mode.grapple_over: the Latin
        # publication title, Playgama 3.5.1) and the shared labels is translated
        same = sorted(k for k in d['en'] if d['en'][k] == d['ru'].get(k))
        report += f'identical en/ru: {same}\n'
        if self.evidence:
            out = Path(self.evidence)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'key-parity.txt').write_text(report)
            rows = ['# ru strings for review (TASK-126)', '',
                    '| key | en | ru |', '|---|---|---|']
            rows += [f'| `{k}` | {d["en"][k]} | {d["ru"].get(k, "MISSING")} |' for k in d['en']]
            (out / 'ru-strings.md').write_text('\n'.join(rows) + '\n')
        print(report, file=sys.stderr)
        self.assertEqual((missing_ru, missing_en, empty, placeholders), ([], [], [], {}))
        self.assertEqual(same, ['game.title', 'hud.fps', 'mode.grapple_over'])

    def test_every_level_section_has_a_label(self):
        # The HUD draws I18N.t(section.labelKey || 'climb.section.' + id) (menu.js), and t()
        # returns the key itself when it is missing (TASK-906): every section of the
        # shipped level (leveldata.js) needs a label in both dictionaries.
        src = (ROOT / 'leveldata.js').read_text(encoding='utf-8')
        start = src.index('window.GRAPPLE_OVER_BUNDLED_LEVEL')
        level, _ = json.JSONDecoder().raw_decode(src, src.index('{', start))
        sections = [{'id': s['id'], 'key': s.get('labelKey') or 'climb.section.' + s['id']}
                    for s in level['sections']]
        self.assertTrue(sections)
        page = self.open('en-US')
        got = page.evaluate('''sections => Object.fromEntries(['en', 'ru'].map(lang => {
            I18N.language = lang
            return [lang, sections.map(s => ({id: s.id, key: s.key, label: I18N.t(s.key),
                own: s.key in I18N.dictionaries[lang]}))]
        }))''', sections)
        page.evaluate("I18N.language = 'en'")
        raw = {lang: [r['id'] for r in rows if r['label'] == r['key'] or not r['own']]
               for lang, rows in got.items()}
        print(f'  {level.get("layoutId")}: {len(sections)} sections, unlabeled {raw}', file=sys.stderr)
        self.assertEqual(raw, {'en': [], 'ru': []},
                         f'level sections without a climb.section label: {raw}')

    def test_cyrillic_glyphs_render(self):
        page = self.open('ru-RU')
        letters = 'ЖЛФЩЯбдж'
        glyphs = page.evaluate(GLYPHS, list(letters) + ['\U000FFFFD'])
        cyr, tofu = glyphs[:-1], glyphs[-1]
        for g in cyr:
            self.assertGreater(g['ink'], 50, g)
            self.assertNotEqual(g['hash'], tofu['hash'], g)
        self.assertEqual(len({g['hash'] for g in cyr}), len(letters), cyr)
        log(f'{letters}: {len(letters)} distinct glyphs, none equal to tofu: pass')

    def test_screens(self):
        if not self.evidence:
            self.skipTest('I18N_EVIDENCE_DIR not set')
        for lang, locale in [('en', 'en-US'), ('ru', 'ru-RU')]:
            for viewport, sub in [(VIEWPORT, ''), ({'width': 390, 'height': 844}, '390x844')]:
                with self.subTest(lang=lang, viewport=viewport):
                    self.shoot(lang, locale, viewport, sub)

    def shoot(self, lang, locale, viewport, sub):
        out = Path(self.evidence) / 'screens' / lang / sub
        out.mkdir(parents=True, exist_ok=True)
        page = self.open(locale, viewport)
        self.assertEqual(page.evaluate('I18N.language'), lang)
        page.evaluate(continue_test.INSTRUMENT_RUN)
        page.screenshot(path=str(out / 'boot.png'))
        switch_mode(page, 'classic')
        page.evaluate('() => { scoreText.count[version] = 7 }')
        page.wait_for_timeout(600)
        page.screenshot(path=str(out / 'hud.png'))
        page.evaluate('menu.startPause()')
        page.wait_for_timeout(100)
        page.screenshot(path=str(out / 'pause.png'))
        page.evaluate('menu.unPause()')
        log(f'{lang} {viewport["width"]}x{viewport["height"]}: boot/hud/pause saved')


# Grapple Over's pause screen is CLIMB_UI.drawMenu (menu.drawPauseScreen); its
# title is the first CLIMB_UI.text drawn. Other modes draw menu.getPauseTitle.
# Records every Text drawn while window.__textDraws is an array.
TITLE_HOOKS = '''() => {
    if (window.__titleHook) return
    window.__titleHook = true
    const draw = Text.prototype.draw
    Text.prototype.draw = function(...args) {
        if (window.__textDraws) window.__textDraws.push(this)
        return draw.apply(this, args)
    }
    // Only CLIMB_UI.text calls inside drawMenu (the HUD uses CLIMB_UI.text too)
    let inMenu = false
    const drawMenu = CLIMB_UI.drawMenu
    CLIMB_UI.drawMenu = function(...args) {
        inMenu = true
        try { return drawMenu.apply(this, args) } finally { inMenu = false }
    }
    const text = CLIMB_UI.text
    CLIMB_UI.text = function(...args) {
        if (window.__textDraws && inMenu) window.__pauseTitles.push(args[0])
        return text.apply(this, args)
    }
    const getPauseTitle = menu.getPauseTitle
    menu.getPauseTitle = function(...args) {
        const title = getPauseTitle.apply(this, args)
        if (window.__textDraws) window.__pauseTitles.push(title.text)
        return title
    }
}'''

# The pause panel title as drawn: the first title string handed to the draw that
# also reached Text.prototype.draw
PAUSE_TITLE = '''() => {
    if (!menu.gamePaused) menu.startPause()
    window.__textDraws = []
    window.__pauseTitles = []
    redrawOverlays()
    const drawn = window.__textDraws.map(t => t.text), titles = window.__pauseTitles
    window.__textDraws = null
    const title = titles.length && drawn.includes(titles[0]) ? titles[0] : null
    return {paused: menu.gamePaused, version, pauseTitle: title}
}'''


class BuiltZipTitleTests(unittest.TestCase):
    """TASK-871: every Grapple Over release zip shows the title 'Grapple Over'.

    Zips come from I18N_ZIP_DIR (DIR/<portal>/grapple-over-<portal>.zip, as
    tools/build_release.py writes them) or are built from HEAD into a temp dir
    (needs the Y8/GA build env, else skipped). Each zip boots offline in en-US
    and ru-RU (the Playgama SDK is game_harness.LOCAL_BRIDGE; other portal SDKs
    are aborted) and must show 'Grapple Over' as document.title, #loading-title
    and the pause panel title (Grapple Over's pause screen draws
    'mode.grapple_over', the other modes' panel 'game.title'). I18N_ZIP_EVIDENCE=FILE writes the rows as
    compact JSON.
    """
    PORTALS = ('itch', 'gamepix', 'y8', 'playgama')
    LANGUAGES = (('en-US', 'en'), ('ru-RU', 'ru'))
    TITLE = 'Grapple Over'

    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        import build_release
        from test_build_release import y8_env
        cls.build_release = build_release
        zip_dir = os.environ.get('I18N_ZIP_DIR')
        if zip_dir:
            cls.out = Path(zip_dir)
        else:
            env = y8_env()
            if not all(env.values()):
                raise unittest.SkipTest('Y8_APP_ID / Y8_GAME_ID / GA_GAME_KEY / GA_SECRET_KEY unavailable')
            cls.out = Path(tempfile.mkdtemp(prefix='i18n-zips-'))
            cls.addClassCleanup(shutil.rmtree, cls.out, True)
            tree = build_release.CommittedTree('HEAD')
            for portal in cls.PORTALS:
                build_release.build(portal, cls.out, env=env, tree=tree)

    def boot(self, site, locale, portal):
        from contextlib import ExitStack
        from browser_test_support import start_browser_test, wait_for_boot_run
        from game_harness import LOCAL_BRIDGE, SDK_URL, collect_errors
        with ExitStack() as stack:
            url, browser = start_browser_test(site, stack.callback)
            context = browser.new_context(viewport=VIEWPORT, locale=locale)
            stack.callback(context.close)
            context.route(url + self.build_release.GA_SDK, lambda r: r.fulfill(
                content_type='application/javascript', body='// GameAnalytics stub\n'))
            if portal == 'playgama':
                context.route(SDK_URL, lambda r: r.fulfill(
                    content_type='application/javascript', body=LOCAL_BRIDGE))
            page = context.new_page()
            errors = collect_errors(page)
            page.goto(url + 'index.html')
            wait_for_boot_run(page)
            page.evaluate(TITLE_HOOKS)
            state = page.evaluate('''() => ({lang: I18N.language, documentTitle: document.title,
                loadingTitle: document.getElementById('loading-title').textContent,
                platform: BUILD_CONFIG.platform, build: BUILD_CONFIG.build})''')
            state.update(page.evaluate(PAUSE_TITLE))
            state['pageErrors'] = errors['page']
            return state

    def test_built_zips_show_grapple_over(self):
        import hashlib
        import shutil
        import tempfile
        import zipfile
        rows = []
        for portal in self.PORTALS:
            path = self.out / portal / f'grapple-over-{portal}.zip'
            data = path.read_bytes()
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if 'i18n.js' in names:
                    i18n_count = z.read('i18n.js').decode('utf-8').count('Grapnel Ninja')
                else:  # TASK-893: i18n.js is a part of the one game bundle
                    import build_release
                    i18n_count = build_release.bundle_part({n: z.read(n) for n in names}, 'i18n.js').decode('utf-8').count('Grapnel Ninja')
            site = Path(tempfile.mkdtemp(prefix=f'i18n-{portal}-'))
            self.addCleanup(shutil.rmtree, site, True)
            with zipfile.ZipFile(path) as z:
                z.extractall(site)
            for locale, lang in self.LANGUAGES:
                with self.subTest(portal=portal, locale=locale):
                    s = self.boot(site, locale, portal)
                    row = {'portal': portal, 'language': lang, 'documentTitle': s['documentTitle'],
                           'loadingTitle': s['loadingTitle'],
                           'pauseTitle': s['pauseTitle'], 'version': s['version'],
                           'bootLanguage': s['lang'], 'platform': s['platform'], 'build': s['build'],
                           'zipSha256': hashlib.sha256(data).hexdigest(), 'i18nGrapnelNinja': i18n_count}
                    row['pass'] = (s['lang'] == lang and s['platform'] == portal and s['paused']
                                   and i18n_count == 0 and s['pageErrors'] == []
                                   and row['documentTitle'] == row['loadingTitle'] == row['pauseTitle'] == self.TITLE)
                    rows.append(row)
                    log(f'{portal} {lang}: ' + json.dumps(row, ensure_ascii=False, separators=(',', ':')))
                    self.assertEqual(s['pageErrors'], [])
                    self.assertEqual((s['lang'], s['platform'], s['paused']), (lang, portal, True))
                    self.assertEqual(i18n_count, 0)
                    self.assertEqual((row['documentTitle'], row['loadingTitle'], row['pauseTitle']),
                                     (self.TITLE,) * 3)
        evidence = os.environ.get('I18N_ZIP_EVIDENCE')
        if evidence:
            Path(evidence).write_text(json.dumps(rows, ensure_ascii=False, separators=(',', ':')) + '\n')
        self.assertEqual(len(rows), 8)


if __name__ == '__main__':
    unittest.main()
