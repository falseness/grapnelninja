"""Cached HUD metrics must agree with the browser across text/layout changes."""
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot


class RenderCacheTests(unittest.TestCase):
    def test_text_metrics_and_font_invalidation(self):
        url, browser = start_browser_test(Path(__file__).resolve().parents[1], self.addCleanup)
        page = browser.new_page()
        self.addCleanup(page.close)
        page.goto(url + 'index.html')
        wait_for_boot(page)
        result = page.evaluate('''() => {
            const mismatches = []
            const fields = ['width', 'actualBoundingBoxLeft', 'actualBoundingBoxRight',
                'actualBoundingBoxAscent', 'actualBoundingBoxDescent']
            ctx.save()
            for (const font of ['16px sans-serif', 'bold 31px serif'])
            for (const text of ['SCORE: 0', 'SCORE: 999', 'РЕКОРД: 125', 'مرحبا'])
            for (const align of ['start', 'center', 'end'])
            for (const baseline of ['middle', 'alphabetic'])
            for (const direction of ['ltr', 'rtl']) {
                Object.assign(ctx, {font, textAlign: align, textBaseline: baseline, direction})
                const fresh = ctx.measureText(text)
                const first = measureGlowText(text), second = measureGlowText(text)
                if (first !== second) mismatches.push('cache miss on repeated text')
                for (const field of fields)
                    if (fresh[field] !== second[field]) mismatches.push([font, text, align, baseline, direction, field])
            }
            ctx.restore()
            const bounded = GLOW_TEXT_METRICS.size <= 128
            document.fonts.dispatchEvent(new Event('loadingdone'))
            return {mismatches, bounded, invalidated: GLOW_TEXT_METRICS.size === 0}
        }''')
        self.assertEqual(result['mismatches'], [])
        self.assertTrue(result['bounded'])
        self.assertTrue(result['invalidated'])


if __name__ == '__main__':
    unittest.main()
