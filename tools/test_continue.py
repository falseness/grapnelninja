"""Lethal death without the continue offer (itch.io build, no rewarded ad).

The ad SDK build showed a Continue/Restart offer after an eligible death
(TASK-080/093/125). The itch.io PLATFORM reports rewarded ads unsupported
(TASK-163), so every lethal death, at any score, restarts the run at once
and the offer never shows.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_harness import open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent

# Count reStart calls and pin the ninja at its start state after every physics
# tick so it never dies on its own. window.__kill moves it behind the deletion
# border before the next tick: a real lethal death through ninja.move().
INSTRUMENT_RUN = '''() => {
    window.__reStarts = 0
    const original = window.reStart
    window.reStart = function() {
        window.__reStarts++
        window.__pin = null
        return original.apply(this, arguments)
    }
    const physicsStep = window.physics
    window.physics = function() {
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        if (window.__kill) {
            window.__kill = false
            ninja.x = screen.getDeletionBorder() - screen.x - 10 * ninja.radius
            ninja.speedX = 0
            ninja.speedY = 0
        }
        const result = physicsStep.apply(this, arguments)
        if (continueOffer.visible)
            return result
        if (!window.__pin) window.__pin = {x: ninja.x, y: ninja.y}
        ninja.x = window.__pin.x
        ninja.y = window.__pin.y
        ninja.speedX = 0
        ninja.speedY = 0
        return result
    }
}'''


def state(page):
    return page.evaluate('''() => ({offer: continueOffer.visible, score: scoreText.count[version],
        reStarts: window.__reStarts, continueUsed: continueUsed,
        gamePaused: menu.gamePaused, menuVisible: menu.visible})''')


class NoContinueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)

    def boot(self, viewport, **context_options):
        context, page, errors = open_game(self.browser, self.url + 'index.html', viewport,
                                          **context_options)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        page.wait_for_function('PLATFORM.environment === "itch" && menu.visible'
                               ' && document.getElementById("loading").hidden', timeout=15000)
        self.assertEqual(page.evaluate('PLATFORM.isRewardedSupported()'), False)
        page.evaluate(INSTRUMENT_RUN)
        page.evaluate('''() => {
            const b = menu.classicVersionButton.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2})
        }''')
        page.wait_for_timeout(300)
        return page

    def kill(self, page, score):
        page.evaluate('s => { scoreText.count[version] = s; window.__kill = true }', score)
        page.wait_for_function('!window.__kill')
        page.wait_for_timeout(100)

    def check_instant_restarts(self, page, scores):
        for i, score in enumerate(scores, 1):
            self.kill(page, score)
            s = state(page)
            self.assertEqual((s['offer'], s['reStarts'], s['score'], s['continueUsed']),
                             (False, i, 0, False), f'score {score}')
            self.assertFalse(s['gamePaused'] or s['menuVisible'], f'score {score}')
            print(f'  ASSERT score {score} death -> instant reStart, no offer: pass',
                  file=sys.stderr)

    def test_death_restarts_instantly_mouse(self):
        page = self.boot({'width': 1280, 'height': 720})
        self.assertEqual(page.evaluate('CONTINUE_MIN_SCORE'), 5)
        self.check_instant_restarts(page, [4, 5, 7])

    def test_death_restarts_instantly_touch_844x390(self):
        page = self.boot({'width': 844, 'height': 390}, has_touch=True, is_mobile=True)
        self.check_instant_restarts(page, [5, 6])


if __name__ == '__main__':
    unittest.main()
