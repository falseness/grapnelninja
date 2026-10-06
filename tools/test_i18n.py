"""English + Russian localization (TASK-126).

The browser locale is navigator.language, which the local PLATFORM reports
as its language. Boot language: the saved 'grapnelninja.lang' storage value,
else 'ru' for a platform language starting with 'ru', else 'en'. The menu's
LANGUAGE_BUTTON switches language at once and saves it through the single
storage write (localStorage, observed by game_harness's storage spy).

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
from game_harness import open_game, start_game_test, storage_calls
from test_audio_wiring import READY, canvas_to_viewport
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

    def open(self, language, viewport=VIEWPORT):
        context, page, errors = open_game(self.browser, self.url + 'index.html',
                                          viewport, locale=language)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function(READY, timeout=15000)
        return page

    def ui(self, page):
        return page.evaluate('''() => ({lang: I18N.language, title: document.title,
            htmlLang: document.documentElement.lang,
            chill: menu.classicVersionButton.text.text, button: I18N.t('language.name')})''')

    def click_language(self, page):
        r = page.evaluate('LANGUAGE_BUTTON.rect()')
        p = canvas_to_viewport(page, r['x'] + r['width'] / 2, r['y'] + r['height'] / 2)
        page.mouse.click(p['x'], p['y'])

    def saved_langs(self, page):
        out = []
        for c in storage_calls(page):
            if c['name'] == 'storage.set' and LANG_KEY in c['args'][0]:
                out.append(c['args'][1][c['args'][0].index(LANG_KEY)])
        return out

    def test_ru_locale_boots_russian(self):
        ui = self.ui(self.open('ru-RU'))
        self.assertEqual(ui, {'lang': 'ru', 'title': 'Grapnel Ninja', 'htmlLang': 'ru',
                              'chill': 'спокойный режим', 'button': 'Русский'})
        log('ru-RU -> ru: pass')

    def test_en_locale_boots_english(self):
        ui = self.ui(self.open('en-US'))
        self.assertEqual(ui, {'lang': 'en', 'title': 'Grapnel Ninja', 'htmlLang': 'en',
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
        page.wait_for_function(f'''() => window.__storageSpy.calls.some(c =>
            c.name == 'storage.set' && c.args[0].includes({json.dumps(LANG_KEY)}))''')
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
        page.wait_for_function(f'''() => window.__storageSpy.calls.some(c =>
            c.name == 'storage.set' && c.args[0].includes({json.dumps(LANG_KEY)}))''')
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
        # Every ru string except the title and the shared labels is translated
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
        self.assertEqual(same, ['game.title', 'hud.fps'])

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
        page.screenshot(path=str(out / 'menu.png'))
        page.evaluate('''() => { const b = menu.classicVersionButton.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2}) }''')
        page.evaluate('() => { scoreText.count[version] = 7 }')
        page.wait_for_timeout(600)
        page.screenshot(path=str(out / 'hud.png'))
        page.evaluate('menu.startPause()')
        page.wait_for_timeout(100)
        page.screenshot(path=str(out / 'pause.png'))
        page.evaluate('menu.unPause()')
        log(f'{lang} {viewport["width"]}x{viewport["height"]}: menu/hud/pause saved')


if __name__ == '__main__':
    unittest.main()
