#!/usr/bin/env python3
"""Unit tests for tools/check_release_kit.py on a synthetic kit in a temp dir
(no dependency on artifacts/). The kit zips are tools/build_release.py builds
of committed revisions with fake credentials."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_release  # noqa: E402
import check_release_kit as kit  # noqa: E402

FAKE_ENV = {'GA_GAME_KEY': 'a' * 32, 'GA_SECRET_KEY': 'b' * 40,
            'Y8_APP_ID': 'fakeappid123', 'Y8_GAME_ID': 'gid999'}
# Built before TASK-871..876 (title, Escape on Playgama, telemetry storage)
STALE_REV = '5a72fa9'

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
    @classmethod
    def setUpClass(cls):
        cls.builds = tempfile.mkdtemp()
        cls.head_tree = build_release.CommittedTree('HEAD')
        for portal in kit.PORTALS:
            build_release.build(portal, cls.builds, env=FAKE_ENV, tree=cls.head_tree)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.builds)

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
            for name in ['manifest.json', 'grapple-over-%s.zip' % portal]:
                shutil.copy(os.path.join(self.builds, portal, name),
                            os.path.join(self.root, portal, name))
            self.write(portal + '/CHECKLIST.md',
                       '1. [ ] Upload `images/cover-01.png` and `cover-0N.png` and `texts.en.md`.\n')
        self.write('README.md', 'Index: `itch/CHECKLIST.md`\n')
        self.creds = os.path.join(self.tmp, 'credentials.env')
        with open(self.creds, 'w') as f:
            f.write('# test\nSECRET_KEY=abcdef123456\n' +
                    ''.join('%s=%s\n' % kv for kv in FAKE_ENV.items()))

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

    def test_good_kit_zips_match_head(self):
        r = self.run_check()
        self.assertTrue(r['summary']['zips_ok'], r['summary'])
        self.assertEqual([z['revision'] for z in r['zips']], [self.head_tree.revision] * 4)
        self.assertTrue(all(z['rev_is_head'] and not z['stale_files'] for z in r['zips']))

    def test_stale_zip_fails_with_differing_files(self):
        out = tempfile.mkdtemp(dir=self.tmp)
        build_release.build('playgama', out, rev=STALE_REV, env=FAKE_ENV)
        for name in ['manifest.json', 'grapple-over-playgama.zip']:
            shutil.copy(os.path.join(out, 'playgama', name), os.path.join(self.root, 'playgama', name))
        r = self.run_check()
        self.assertFalse(r['all_ok'])
        self.assertFalse(r['summary']['zips_ok'])
        z = {e['portal']: e for e in r['zips']}['playgama']
        self.assertEqual(z['zip_vs_rev_build'], [])  # a true build of its revision...
        for name in ['events.js', 'index.html', 'menu.js', 'telemetry.js']:
            self.assertIn(name, z['stale_files'])  # ...but that revision is not HEAD
        self.assertEqual(r['summary']['stale_zips']['playgama'], z['stale_files'])
        self.assertEqual([e['portal'] for e in r['zips'] if not e['ok']], ['playgama'])

    def test_zip_not_built_from_its_revision_fails(self):
        path = os.path.join(self.root, 'gamepix', 'grapple-over-gamepix.zip')
        files = kit.zip_files(path)
        bundle = build_release.bundle_path(files)
        menu = build_release.bundle_part(files, 'menu.js').decode() + '// edited after the build'
        files[bundle] = build_release.replace_part(files, 'menu.js', menu)
        with open(path, 'wb') as f:
            f.write(build_release.archive(files))
        r = self.run_check()
        z = {e['portal']: e for e in r['zips']}['gamepix']
        self.assertFalse(z['ok'])
        # the scripts are one bundle (TASK-893): the edited menu.js shows as it
        self.assertEqual(z['zip_vs_rev_build'], [bundle])
        self.assertEqual(z['stale_files'], [])
        self.assertFalse(r['all_ok'])

    def test_missing_y8_ids_fail_without_crash(self):
        with open(self.creds, 'w') as f:
            f.write('SECRET_KEY=abcdef123456\nGA_GAME_KEY=%s\nGA_SECRET_KEY=%s\n'
                    % (FAKE_ENV['GA_GAME_KEY'], FAKE_ENV['GA_SECRET_KEY']))
        r = self.run_check()
        z = {e['portal']: e for e in r['zips']}
        self.assertIn('build failed', z['y8']['error'])
        self.assertTrue(z['itch']['ok'])
        self.assertNotIn(FAKE_ENV['GA_SECRET_KEY'], json.dumps(r))

    def test_playgama_esc_text_fails(self):
        self.assertTrue(self.run_check()['summary']['playgama_esc_ok'])
        self.write('playgama/texts.en.md', PLAYGAMA_EN + 'Esc or P pauses on desktop.\n')
        self.write('playgama/texts.ru.md', PLAYGAMA_RU + 'Клавиша Escape ставит паузу.\n')
        r = self.run_check()
        self.assertFalse(r['summary']['playgama_esc_ok'])
        self.assertFalse(r['all_ok'])
        self.assertEqual(sorted((os.path.basename(h['file']), h['match'])
                                for h in r['playgama_esc']['hits']),
                         [('texts.en.md', 'Esc'), ('texts.ru.md', 'Escape')])

    def test_esc_in_other_portal_texts_is_allowed(self):
        self.write('itch/texts.en.md', single_texts('en') + 'Esc or P pauses.\n')
        r = self.run_check()
        self.assertTrue(r['summary']['playgama_esc_ok'])
        self.assertTrue(r['all_ok'], r['summary'])


if __name__ == '__main__':
    unittest.main()
