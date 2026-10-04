"""audio.js: synthesized SFX, ambient music, mute sources, no-AudioContext no-op."""
import itertools
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playgama_harness import bridge_errors, open_game, start_playgama_test

ROOT = Path(__file__).resolve().parent.parent
VIEWPORT = {'width': 1280, 'height': 720}
READY = ('PLATFORM.environment !== "pending" && menu.visible'
         ' && document.getElementById("loading").hidden')
SFX = ['throw', 'hook', 'bounce', 'trampoline', 'death', 'score', 'record',
       'click']
SOURCES = ['user', 'host', 'ad', 'hidden']
NO_AUDIO_CONTEXT = 'delete window.AudioContext; delete window.webkitAudioContext'


def log(message):
    print('  ' + message, file=sys.stderr)


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('AUDIO_EVIDENCE_DIR')

    def write_evidence(self, name, data):
        if not self.evidence:
            return
        out = Path(self.evidence)
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(json.dumps(data, indent=2) + '\n')

    def boot(self, init_script=None):
        context, page, errors = open_game(self.browser, 'about:blank', VIEWPORT)
        if init_script:
            context.add_init_script(init_script)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        self.addCleanup(lambda: self.assertEqual(bridge_errors(page), []))
        page.goto(self.url + 'index.html')
        page.wait_for_function(READY)
        # Keep the game idle: only the test touches AUDIO
        page.evaluate('runFixedPhysics = function () {}')
        return page

    def unlock(self, page):
        page.keyboard.press('Shift')
        page.wait_for_function('AUDIO.getState().state === "running"')

    def state(self, page):
        return page.evaluate('AUDIO.getState()')

    def test_sound_table_limits(self):
        page = self.boot()
        table = page.evaluate('AUDIO.sounds')
        self.assertEqual(sorted(table), sorted(SFX))
        sounds = {name: {'duration_ms': round(table[name]['duration'] * 1000),
                         'peak_gain': table[name]['gain'],
                         'source': table[name]['source']}
                  for name in SFX}
        for name, sound in sounds.items():
            self.assertLess(sound['duration_ms'], 400, name)
            self.assertLessEqual(sound['peak_gain'], 0.5, name)
        music = page.evaluate('AUDIO.musicVolume')
        self.assertLessEqual(music, 0.12)
        self.write_evidence('sounds.json', {'sounds': sounds,
                                            'music_gain': music})
        log(f'sounds ok, music gain {music}')

    def test_context_created_on_first_input(self):
        page = self.boot()
        before = self.state(page)
        self.assertEqual((before['available'], before['started'],
                          before['gain'], before['state']),
                         (True, False, None, None))
        page.evaluate('AUDIO.play("click")')
        self.unlock(page)
        after = self.state(page)
        self.assertEqual((after['started'], after['gain'], after['state']),
                         (True, 1, 'running'))
        self.assertEqual(page.evaluate('__audioLog.length'), 1)
        log(f'before {before}, after {after}')

    def test_play_counts(self):
        page = self.boot()
        self.unlock(page)
        page.evaluate('''(names) => names.forEach((name, i) => {
            for (let k = 0; k <= i; ++k) AUDIO.play(name)
        })''', SFX)
        page.evaluate('AUDIO.play("no-such-sound")')
        entries = page.evaluate('__audioLog')
        counts = {name: sum(e['name'] == name for e in entries) for name in SFX}
        self.assertEqual(counts, {name: i + 1 for i, name in enumerate(SFX)})
        self.assertEqual(len(entries), sum(range(1, len(SFX) + 1)))
        self.assertTrue(all(e['muted'] is False and e['t'] > 0 for e in entries))
        self.write_evidence('play-counts.json', counts)
        log(f'counts {counts}')

    def test_mute_matrix(self):
        page = self.boot()
        self.unlock(page)
        matrix = []
        for combo in itertools.product([False, True], repeat=len(SOURCES)):
            flags = dict(zip(SOURCES, combo))
            measured = page.evaluate('''async (flags) => {
                for (const [source, value] of Object.entries(flags))
                    await AUDIO.setMute(source, value)
                AUDIO.play('click')
                const s = AUDIO.getState()
                return {gain: s.gain, state: s.state, muted: AUDIO.isMuted(),
                        logged: __audioLog[__audioLog.length - 1].muted}
            }''', flags)
            any_muted = any(combo)
            expected = (0, 'suspended') if any_muted else (1, 'running')
            self.assertEqual((measured['gain'], measured['state']), expected,
                             flags)
            self.assertEqual((measured['muted'], measured['logged']),
                             (any_muted, any_muted), flags)
            matrix.append({'sources': flags, 'any_muted': any_muted,
                           'gain': measured['gain'],
                           'context_state': measured['state']})
        self.assertEqual(len(matrix), 16)
        self.write_evidence('mute-matrix.json', matrix)
        log(f'{len(matrix)} combinations ok')

    def test_unmute_restores(self):
        page = self.boot()
        self.unlock(page)
        steps = page.evaluate('''async () => {
            const out = []
            const snap = (label) => {
                const s = AUDIO.getState()
                out.push({label, gain: s.gain, state: s.state})
            }
            await AUDIO.setMute('hidden', true);  snap('hidden')
            await AUDIO.setMute('ad', true);      snap('hidden+ad')
            await AUDIO.setMute('hidden', false); snap('ad')
            await AUDIO.setMute('ad', false);     snap('none')
            AUDIO.setMute('user', true)
            AUDIO.setMute('user', false)
            await AUDIO.setMute('bogus', true);   snap('bogus ignored')
            return out
        }''')
        self.assertEqual([(s['gain'], s['state']) for s in steps],
                         [(0, 'suspended'), (0, 'suspended'), (0, 'suspended'),
                          (1, 'running'), (1, 'running')])
        log(f'steps {steps}')

    def test_mute_before_first_input(self):
        page = self.boot()
        page.evaluate('AUDIO.setMute("hidden", true)')
        page.keyboard.press('Shift')
        page.wait_for_function('AUDIO.getState().state === "suspended"')
        self.assertEqual(self.state(page)['gain'], 0)
        page.evaluate('AUDIO.setMute("hidden", false)')
        page.wait_for_function('AUDIO.getState().state === "running"')
        self.assertEqual(self.state(page)['gain'], 1)

    def test_music_start_stop(self):
        page = self.boot()
        page.evaluate('AUDIO.startMusic()')
        self.assertFalse(self.state(page)['music'])
        self.unlock(page)
        self.assertTrue(self.state(page)['music'])
        page.wait_for_timeout(200)
        page.evaluate('AUDIO.stopMusic()')
        self.assertFalse(self.state(page)['music'])
        page.evaluate('AUDIO.startMusic(); AUDIO.startMusic()')
        self.assertTrue(self.state(page)['music'])
        page.evaluate('AUDIO.stopMusic(); AUDIO.stopMusic()')
        self.assertFalse(self.state(page)['music'])

    def test_no_audio_context_is_noop(self):
        page = self.boot(NO_AUDIO_CONTEXT)
        self.assertFalse(page.evaluate('"AudioContext" in window'))
        page.keyboard.press('Shift')
        # Bottom-left corner: the top-left one holds the language button
        page.mouse.click(10, VIEWPORT['height'] - 10)
        result = page.evaluate('''async () => {
            AUDIO.startMusic()
            for (const name of AUDIO.sources) await AUDIO.setMute(name, true)
            AUDIO.play('death')
            for (const name of AUDIO.sources) await AUDIO.setMute(name, false)
            AUDIO.play('score')
            AUDIO.stopMusic()
            return {state: AUDIO.getState(), log: __audioLog}
        }''')
        state = result['state']
        self.assertEqual((state['available'], state['started'], state['gain'],
                          state['state'], state['music']),
                         (False, False, None, None, False))
        self.assertEqual([(e['name'], e['muted']) for e in result['log']],
                         [('death', True), ('score', False)])
        self.write_evidence('no-audio-context.json', result)
        log(f'no-AudioContext state {state}')


if __name__ == '__main__':
    unittest.main()
