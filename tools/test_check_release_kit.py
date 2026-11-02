#!/usr/bin/env python3
"""Unit tests for tools/check_release_kit.py on a synthetic kit in a temp dir
(no dependency on artifacts/)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_release_kit as kit  # noqa: E402

STORY = ('This started as an endless swing game and the climb slowly took over. '
         'Building the mountain took more tries than the hook. How far did your worst fall take you?')
LONG = 'Grapple Over is a one-button climbing game with a grappling hook and a long neon mountain to climb. ' * 2


def single_texts(lang):
    head = '## Title\nGrapple Over\n' if lang == 'en' else '## Название\nGrapple Over\n'
    return '# Grapple Over\n\n' + head + '\n## Description\nClimb to the summit.\n'


PLAYGAMA_EN = ('# Grapple Over\n\n## title\nGrapple Over\n\n## description\n' + LONG +
               ' Two bonus modes are on the pause screen: the main version and the chill version.\n\n'
               '## howToPlayText\n' + LONG + '\n\n## story\n' + STORY + '\n')
PLAYGAMA_RU = ('# Grapple Over\n\n## description\n' + LONG +
               ' Бонус: основной режим и спокойный режим.\n\n## howToPlayText\n' + LONG + '\n')


class CheckReleaseKitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, 'kit')
        for portal in kit.PORTALS:
            os.makedirs(os.path.join(self.root, portal, 'images'))
            for name in ['cover-01.png', 'cover-02.png']:
                with open(os.path.join(self.root, portal, 'images', name), 'wb') as f:
                    f.write(b'x')
            if portal == 'playgama':
                self.write('playgama/texts.en.md', PLAYGAMA_EN)
                self.write('playgama/texts.ru.md', PLAYGAMA_RU)
            else:
                self.write(portal + '/texts.en.md', single_texts('en'))
                self.write(portal + '/texts.ru.md', single_texts('ru'))
            self.write(portal + '/CHECKLIST.md',
                       '1. [ ] Upload `images/cover-01.png` and `cover-0N.png` and `texts.en.md`.\n')
        self.write('README.md', 'Index: `itch/CHECKLIST.md`\n')
        self.creds = os.path.join(self.tmp, 'credentials.env')
        with open(self.creds, 'w') as f:
            f.write('# test\nSECRET_KEY=abcdef123456\n')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), 'w', encoding='utf-8') as f:
            f.write(text)

    def run_check(self):
        return kit.check(self.root, self.creds)

    def test_good_kit_passes(self):
        r = self.run_check()
        self.assertTrue(r['all_ok'], r['summary'])
        self.assertEqual(r['summary']['files'], 13)
        pattern = [e for e in r['paths'] if e['pattern']]
        self.assertTrue(pattern and all(e['matches'] == 2 for e in pattern))

    def test_missing_referenced_file_fails(self):
        self.write('y8/CHECKLIST.md', 'Upload `images/promo-missing.png`.\n')
        r = self.run_check()
        self.assertFalse(r['all_ok'])
        self.assertIn('images/promo-missing.png', r['summary']['paths_missing'])

    def test_other_mode_in_single_mode_texts_fails(self):
        self.write('gamepix/texts.ru.md', single_texts('ru') + 'Есть спокойный режим.\n')
        r = self.run_check()
        self.assertFalse(r['summary']['texts_ok'])
        bad = [t for t in r['texts'] if not t['ok']]
        self.assertEqual([t['file'].endswith('gamepix/texts.ru.md') for t in bad], [True])

    def test_playgama_without_extras_fails(self):
        self.write('playgama/texts.en.md', PLAYGAMA_EN.replace('Two bonus modes are', 'Modes are'))
        self.write('playgama/texts.ru.md', PLAYGAMA_RU.replace('Бонус:', 'Режимы:'))
        self.assertFalse(self.run_check()['summary']['texts_ok'])

    def test_credential_value_fails_without_printing_it(self):
        self.write('itch/CHECKLIST.md', 'key abcdef123456 `texts.en.md`\n')
        r = self.run_check()
        self.assertFalse(r['summary']['credentials_ok'])
        self.assertEqual(r['credentials']['hits'], [{'file': os.path.relpath(
            os.path.join(self.root, 'itch', 'CHECKLIST.md'), kit.REPO), 'variable': 'SECRET_KEY'}])
        self.assertNotIn('abcdef123456', repr(r))


if __name__ == '__main__':
    unittest.main()
