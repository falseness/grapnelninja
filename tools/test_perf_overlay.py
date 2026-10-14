"""On-canvas ?perf=1 profiler panel (render/perfprofile.js PERF_OVERLAY, TASK-415).

test_layout: in bad and classic at 1280x720 (desktop) and 844x390 (touch,
dpr 2), with ?perf=1 and the FPS counter on, one draw() under LAYOUT_PROBE
gives the panel rect and the HUD boxes (score, record, menu button, FPS
counter) in CSS px. The panel must lie inside the canvas, intersect no HUD
box, use a font >= 11 CSS px and show real numbers ('FPS n.nn  frames n'
and 'name mean / p95' lines with 2 decimals). Its text refreshes at most
every 500 ms.
test_no_flag: without ?perf=1 a draw() makes no panel fillText/fillRect
call and probes no panel box; PERF_OVERLAY and PERF_PROFILE are undefined.

Env: PERF_OVERLAY_EVIDENCE_DIR (absolute) receives overlay-<mode>-<WxH>.png.
"""
import os
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import start_browser_test
from game_harness import READY, open_game, switch_mode

ROOT = Path(__file__).resolve().parent.parent
CASES = [(mode, w, h, touch) for mode in ('bad', 'classic')
         for w, h, touch in ((1280, 720, False), (844, 390, True))]
MIN_FONT_PX = 11
REFRESH_MS = 500
HEAD_LINE = re.compile(r'^FPS \d+\.\d\d  frames \d+$')
ENTRY_LINE = re.compile(r'^\w+ \d+\.\d\d / \d+\.\d\d$')
EPS = 0.5

# Boxes and fillText/fillRect calls of one draw(); the canvas rect in CSS px
PROBE = '''() => {
    const proto = CanvasRenderingContext2D.prototype
    const fillText = proto.fillText, fillRect = proto.fillRect
    const calls = {texts: [], rects: 0}
    proto.fillText = function(text) { calls.texts.push(String(text)); return fillText.apply(this, arguments) }
    proto.fillRect = function() { calls.rects++; return fillRect.apply(this, arguments) }
    LAYOUT_PROBE.boxes = []
    try { draw() } finally { proto.fillText = fillText; proto.fillRect = fillRect }
    const boxes = LAYOUT_PROBE.boxes
    LAYOUT_PROBE.boxes = null
    const r = getCanvasCssRect()
    const overlay = window.PERF_OVERLAY && {lines: PERF_OVERLAY.lines, fontPx: PERF_OVERLAY.rect.fontPx}
    return {boxes, calls, overlay, canvas: {x: 0, y: 0, width: r.width, height: r.height},
            hud: [scoreText.text + scoreText.count[version], scoreText.rtext + scoreText.record[version],
                  I18N.t('hud.fps', {value: fpsCounter.value})]}
}'''


def inside(a, b):
    return (a['x'] >= b['x'] - EPS and a['y'] >= b['y'] - EPS and
            a['x'] + a['width'] <= b['x'] + b['width'] + EPS and
            a['y'] + a['height'] <= b['y'] + b['height'] + EPS)


def intersect(a, b):
    return (a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] and
            a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height'])


def fmt(r):
    return f"x={r['x']:.1f} y={r['y']:.1f} w={r['width']:.1f} h={r['height']:.1f}"


def panel_lines(texts):
    return [t for t in texts if HEAD_LINE.match(t) or ENTRY_LINE.match(t)]


class PerfOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_browser_test(ROOT, cls.addClassCleanup)
        out = os.environ.get('PERF_OVERLAY_EVIDENCE_DIR')
        cls.out = Path(out) if out else None
        if cls.out:
            cls.out.mkdir(parents=True, exist_ok=True)

    def open(self, query, size, touch):
        kwargs = {'has_touch': True, 'is_mobile': True, 'device_scale_factor': 2} if touch else {}
        context, page, errors = open_game(self.browser, self.url + 'index.html' + query,
                                          {'width': size[0], 'height': size[1]}, fake_bridge=True,
                                          locale='en-US', **kwargs)
        self.addCleanup(context.close)
        page.wait_for_function(READY, timeout=30000)
        return page, errors

    def test_layout(self):
        for mode, w, h, touch in CASES:
            key = f'{mode}-{w}x{h}'
            with self.subTest(case=key):
                page, errors = self.open('?perf=1', (w, h), touch)
                switch_mode(page, mode)
                page.evaluate('() => { scoreText.count[version] = 7; if (!fpsCounter.enabled) fpsCounter.toggle() }')
                # Two refreshes: the panel shows numbers from live frames
                page.wait_for_function('PERF_OVERLAY.refreshes >= 3 && fpsCounter.value > 0',
                                       timeout=60000, polling=100)
                if self.out:
                    page.screenshot(path=str(self.out / f'overlay-{key}.png'))
                start = page.evaluate('[performance.now(), PERF_OVERLAY.refreshes]')
                page.wait_for_timeout(1600)
                end = page.evaluate('[performance.now(), PERF_OVERLAY.refreshes]')
                shot = page.evaluate(PROBE)
                self.assertEqual((errors['console'], errors['page']), ([], []))

                boxes = shot['boxes']
                panels = [b for b in boxes if b['kind'] == 'perf']
                self.assertEqual(len(panels), 1, boxes)
                panel = panels[0]
                hud = [b for b in boxes if b['kind'] != 'perf']
                names = [b['name'] for b in hud]
                canvas = shot['canvas']
                font = shot['overlay']['fontPx']
                lines = shot['overlay']['lines']
                print(f'CASE {key}: canvas {fmt(canvas)}', file=sys.stderr)
                print(f'  panel {fmt(panel)} font={font}px', file=sys.stderr)
                for b in hud:
                    print(f"  hud {b['kind']} '{b['name']}' {fmt(b)} "
                          f"intersects_panel={intersect(panel, b)}", file=sys.stderr)
                print(f'  lines {lines}', file=sys.stderr)
                elapsed = end[0] - start[0]
                refreshes = end[1] - start[1]
                print(f'  refreshes {refreshes} in {elapsed:.0f} ms (max {elapsed / REFRESH_MS + 1:.1f})',
                      file=sys.stderr)

                # Score, record, FPS counter and the menu (icon) button
                for name in shot['hud']:
                    self.assertIn(name, names)
                self.assertEqual([b['kind'] for b in hud].count('button'), 1, names)
                self.assertEqual(len(hud), 4, names)
                self.assertTrue(inside(panel, canvas), key)
                self.assertEqual([b['name'] for b in hud if intersect(panel, b)], [], key)
                self.assertGreaterEqual(font, MIN_FONT_PX)
                self.assertRegex(lines[0], HEAD_LINE)
                self.assertGreater(float(lines[0].split()[1]), 0)
                self.assertEqual(len(lines), 7)
                for line in lines[1:]:
                    self.assertRegex(line, ENTRY_LINE)
                self.assertEqual(panel_lines(shot['calls']['texts']), lines)
                self.assertLessEqual(refreshes, elapsed / REFRESH_MS + 1)
                self.assertGreaterEqual(refreshes, 1)
                print(f'  PASS {key}: inside canvas, no HUD intersection, font {font}px', file=sys.stderr)

    def test_no_flag(self):
        for w, h, touch in ((1280, 720, False), (844, 390, True)):
            key = f'{w}x{h}'
            with self.subTest(case=key):
                page, errors = self.open('', (w, h), touch)
                switch_mode(page, 'bad')
                page.evaluate('() => { if (!fpsCounter.enabled) fpsCounter.toggle() }')
                page.wait_for_timeout(700)
                state = page.evaluate('[typeof window.PERF_OVERLAY, typeof window.PERF_PROFILE]')
                shot = page.evaluate(PROBE)
                texts = shot['calls']['texts']
                perf_boxes = [b for b in shot['boxes'] if b['kind'] == 'perf']
                print(f'NOFLAG {key}: PERF_OVERLAY={state[0]} PERF_PROFILE={state[1]} '
                      f'fillText calls={len(texts)} {texts} fillRect calls={shot["calls"]["rects"]} '
                      f'panel lines={panel_lines(texts)} perf boxes={perf_boxes}', file=sys.stderr)
                self.assertEqual(state, ['undefined', 'undefined'])
                self.assertEqual(panel_lines(texts), [])
                self.assertEqual(perf_boxes, [])
                self.assertEqual((errors['console'], errors['page']), ([], []))
                print(f'  PASS {key}: no panel draw calls', file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
