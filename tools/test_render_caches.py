"""Render caches preserve text metrics and trail pixels across invalidation."""
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot


class RenderCacheTests(unittest.TestCase):
    def test_empty_lightmap_skips_composite_without_changing_pixels(self):
        url, browser = start_browser_test(Path(__file__).resolve().parents[1], self.addCleanup)
        page = browser.new_page()
        self.addCleanup(page.close)
        page.goto(url + 'index.html')
        wait_for_boot(page)
        result = page.evaluate("""() => {
            startGame('classic')
            const canvas = document.createElement('canvas')
            canvas.width = 400; canvas.height = 200
            const context = canvas.getContext('2d')
            const lights = new LightmapRenderer(context, canvas)
            let composites = 0
            const original = context.drawImage.bind(context)
            context.drawImage = (...args) => { ++composites; original(...args) }
            const paint = () => {
                context.fillStyle = '#102040'
                context.fillRect(0, 0, 400, 200)
            }
            const pixels = () => context.getImageData(0, 0, 400, 200).data
            paint()
            const before = pixels()
            lights.clear()
            lights.composite()
            const emptyCalls = composites
            const offscreen = lights.drawRadialLight(-1e6, -1e6, 140, '#00ffff', .5)
            lights.composite()
            const offscreenCalls = composites
            lights.lightCtx.save()
            const light = lights.drawRadialLight(100, 100, 140, '#00ffff', .5)
            lights.lightCtx.restore()
            lights.composite()
            const litCalls = composites
            const litPixels = pixels().some((v, i) => v !== before[i])
            lights.clear()
            paint()
            lights.composite()
            const clearedCalls = composites
            const optimized = pixels()
            // Force the original full-canvas composite of the cleared bitmap.
            lights.hasLights = true
            lights.composite()
            const reference = pixels()
            return {emptyCalls, offscreen, offscreenCalls, light, litCalls,
                litPixels, clearedCalls,
                same: optimized.every((v, i) => v === reference[i] && v === before[i])}
        }""")
        self.assertEqual(result, dict(emptyCalls=0, offscreen=False, offscreenCalls=0,
                                     light=True, litCalls=1, litPixels=True,
                                     clearedCalls=1, same=True))
        print('PASS empty lightmap composite:', result, flush=True)

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

    def test_ribbon_paths_match_immediate_drawing_and_expire_each_frame(self):
        url, browser = start_browser_test(Path(__file__).resolve().parents[1], self.addCleanup)
        page = browser.new_page()
        self.addCleanup(page.close)
        page.goto(url + 'index.html')
        wait_for_boot(page)
        result = page.evaluate('''() => {
            const main = ctx
            const canvasA = document.createElement('canvas')
            const canvasB = document.createElement('canvas')
            canvasA.width = canvasB.width = 300
            canvasA.height = canvasB.height = 150
            const a = canvasA.getContext('2d'), b = canvasB.getContext('2d')
            const cached = new PlayerTrailRenderer(), immediate = new PlayerTrailRenderer()
            immediate.fillRibbon = function(positions, start, width, color, alpha) {
                if (positions.length - start < 2) return
                const outline = this.getRibbonOutline(positions, start, width)
                if (!outline.length) return
                ctx.globalAlpha = this.clampAlpha(alpha)
                ctx.fillStyle = color
                this.drawRibbonOutline(outline)
                ctx.fill()
            }
            const track = {lineWidth: 3, pos: Array.from({length: 25}, (_, i) =>
                ({x: 30 + i * 8, y: 70 + Math.sin(i * .3) * 20}))}
            const mismatches = []
            let reused = true, expired = true, previous
            try {
                startGame('bad')
                screen.x = screen.y = 0
                for (let frame = 0; frame < 3; ++frame) {
                    ++drawFrameId
                    track.pos[24].y += 4
                    for (const zoom of [1, .2]) {
                        for (const target of [a, b]) {
                            target.resetTransform()
                            target.clearRect(0, 0, 300, 150)
                            target.scale(zoom, zoom)
                        }
                        ctx = a; cached.drawSmoothPlayerTrail(track)
                        ctx = b; immediate.drawSmoothPlayerTrail(track)
                        const ap = a.getImageData(0, 0, 300, 150).data
                        const bp = b.getImageData(0, 0, 300, 150).data
                        if (!ap.some(v => v)) mismatches.push('empty rendering')
                        if (ap.some((v, i) => v !== bp[i])) mismatches.push([frame, zoom])
                        if (zoom === 1) {
                            expired &&= previous !== cached.ribbonPaths[0]
                            previous = cached.ribbonPaths[0]
                        } else reused &&= previous === cached.ribbonPaths[0]
                    }
                }
            } finally { ctx = main }
            return {mismatches, reused, expired}
        }''')
        self.assertEqual(result['mismatches'], [])
        self.assertTrue(result['reused'])
        self.assertTrue(result['expired'])


if __name__ == '__main__':
    unittest.main()
