"""The background fills the whole window around the letterboxed play rect.

At every aspect the main menu screenshot has no pure body-black pixel at the
window corners, the edge midpoints or 8 px outside each play-rect edge that
borders a bar; along each bar edge the pixel row/column is not a darker
seam line than its 1 px neighbours (median over the edge, so UI glows near
the edge do not count); the game canvas keeps getCanvasCssRect(); a click on the
'chill version' button still starts a classic run.

FULLWINDOW_EVIDENCE_DIR writes edge-pixels.json, click.log and one main menu
PNG per viewport under screens/.
"""
import io
import json
import math
import os
import statistics
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import wait_for_boot
from game_harness import click_canvas, open_game, start_game_test

ROOT = Path(__file__).resolve().parent.parent
# (width, height, touch)
VIEWPORTS = [(925, 925, False), (1024, 768, False), (1280, 1024, False),
             (390, 844, True), (2560, 1080, False), (1920, 1080, False)]
CLICK_VIEWPORTS = [(925, 925, False), (390, 844, True)]
BLACK_MAX_CHANNEL = 8
BAR_OFFSET_PX = 8
SEAM_STEP_PX = 4
# Edge pixel / darker 1 px neighbour, median along the edge; the fractional
# edges of the 0d9ed39 clip gave 0.69..0.92, a seamless edge gives >= 0.96
SEAM_MIN_RATIO = 0.93


def viewport_name(viewport):
    return f'{viewport[0]}x{viewport[1]}'


def boot_menu(browser, url, viewport):
    """Open the game at viewport and wait for the main menu."""
    width, height, touch = viewport
    options = {'has_touch': True, 'is_mobile': True} if touch else {}
    context, page, errors = open_game(
        browser, url + 'index.html', {'width': width, 'height': height}, **options)
    wait_for_boot(page)
    page.wait_for_function('() => menu.visible')
    page.wait_for_timeout(200)
    return context, page, errors


def sample_points(viewport, rect):
    """Window corners, edge midpoints, and 8 px outside every bar edge."""
    w, h = viewport[0], viewport[1]
    points = {
        'corner_top_left': (0, 0), 'corner_top_right': (w - 1, 0),
        'corner_bottom_left': (0, h - 1), 'corner_bottom_right': (w - 1, h - 1),
        'mid_top': (w // 2, 0), 'mid_bottom': (w // 2, h - 1),
        'mid_left': (0, h // 2), 'mid_right': (w - 1, h // 2),
    }
    if rect['top'] >= 1:
        points['bar_above_play_rect'] = (w // 2, int(rect['top']) - BAR_OFFSET_PX)
        points['bar_below_play_rect'] = (w // 2, int(rect['top'] + rect['height']) + BAR_OFFSET_PX)
    if rect['left'] >= 1:
        points['bar_left_of_play_rect'] = (int(rect['left']) - BAR_OFFSET_PX, h // 2)
        points['bar_right_of_play_rect'] = (int(rect['left'] + rect['width']) + BAR_OFFSET_PX, h // 2)
    return points


def seam_lines(viewport, rect):
    """name -> [(edge pixel, neighbour, neighbour)] along every bar edge."""
    w, h = viewport[0], viewport[1]
    lines = {}
    if rect['top'] >= 1:
        for name, edge in (('top', rect['top']), ('bottom', rect['top'] + rect['height'])):
            y = int(edge)
            lines[name] = [((x, y), (x, y - 1), (x, y + 1)) for x in range(0, w, SEAM_STEP_PX)]
    if rect['left'] >= 1:
        for name, edge in (('left', rect['left']), ('right', rect['left'] + rect['width'])):
            x = int(edge)
            lines[name] = [((x, y), (x - 1, y), (x + 1, y)) for y in range(0, h, SEAM_STEP_PX)]
    return lines


def sample_menu(page, viewport):
    """Return (record, png bytes) for the main menu at viewport."""
    rects = page.evaluate('''() => {
        const r = canvas.getBoundingClientRect()
        return {css: getCanvasCssRect(),
                canvas: {left: r.left, top: r.top, width: r.width, height: r.height}}
    }''')
    png = page.screenshot()
    image = Image.open(io.BytesIO(png)).convert('RGB')
    samples = {}
    for name, (x, y) in sample_points(viewport, rects['css']).items():
        rgb = image.getpixel((x, y))
        samples[name] = {'x': x, 'y': y, 'rgb': list(rgb), 'max_channel': max(rgb)}
    seams = {}
    for name, triples in seam_lines(viewport, rects['css']).items():
        brightness = lambda p: sum(image.getpixel(p))
        ratios = [brightness(edge) / max(1, min(brightness(a), brightness(b)))
                  for edge, a, b in triples]
        seams[name] = {'line': triples[0][0][1] if name in ('top', 'bottom') else triples[0][0][0],
                       'samples': len(ratios), 'ratio': round(statistics.median(ratios), 3)}
    return {'viewport': viewport_name(viewport), 'play_rect': rects['css'],
            'canvas_rect': rects['canvas'], 'samples': samples, 'seams': seams}, png


class FullWindowBackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url, cls.browser = start_game_test(ROOT, cls.addClassCleanup)
        cls.evidence = os.environ.get('FULLWINDOW_EVIDENCE_DIR')

    def out(self):
        out = Path(self.evidence)
        (out / 'screens').mkdir(parents=True, exist_ok=True)
        return out

    def boot(self, viewport):
        context, page, errors = boot_menu(self.browser, self.url, viewport)
        self.addCleanup(context.close)
        self.addCleanup(lambda: self.assertEqual(
            (errors['console'], errors['page']), ([], [])))
        return page

    def test_menu_background_fills_window(self):
        records = []
        for viewport in VIEWPORTS:
            with self.subTest(viewport=viewport_name(viewport)):
                page = self.boot(viewport)
                record, png = sample_menu(page, viewport)
                records.append(record)
                if self.evidence:
                    (self.out() / 'screens' / f'{record["viewport"]}.png').write_bytes(png)
                css, box = record['play_rect'], record['canvas_rect']
                for key in ('left', 'top', 'width', 'height'):
                    self.assertAlmostEqual(box[key], css[key], delta=0.5, msg=key)
                black = {name: s['rgb'] for name, s in record['samples'].items()
                         if s['max_channel'] <= BLACK_MAX_CHANNEL}
                self.assertEqual(black, {})
                seams = {name: s for name, s in record['seams'].items()
                         if s['ratio'] < SEAM_MIN_RATIO}
                self.assertEqual(seams, {})
                print(f'\n  {record["viewport"]} play rect {css} min max-channel '
                      f'{min(s["max_channel"] for s in record["samples"].values())} min seam ratio '
                      f'{min([s["ratio"] for s in record["seams"].values()] or [1.0])}',
                      file=sys.stderr)
        if self.evidence:
            path = self.out() / 'edge-pixels.json'
            data = json.loads(path.read_text()) if path.exists() else {}
            data['after'] = records
            path.write_text(json.dumps(data, indent=2))

    def test_bar_canvases_cover_only_the_bars_at_quarter_size(self):
        """TASK-138: a full-window, full-resolution background layer cost
        ~20-30% of the frame at 2560x1080. Two bar canvases cover only the
        letterbox bars (plus WINDOW_BAR_OVERLAP_PX under the play rect) at a
        quarter of their CSS size; without bars both are hidden."""
        for viewport in [(2560, 1080, False), (390, 844, True), (1920, 1080, False)]:
            with self.subTest(viewport=viewport_name(viewport)):
                page = self.boot(viewport)
                bars = page.evaluate('''() => ({
                    scale: WINDOW_BACKGROUND_SCALE, overlap: WINDOW_BAR_OVERLAP_PX,
                    rect: getCanvasCssRect(),
                    canvases: Array.from(document.getElementsByClassName('window-bar')).map(c => {
                        const r = c.getBoundingClientRect()
                        return {hidden: c.hidden, width: c.width, height: c.height,
                                css: {left: r.left, top: r.top, width: r.width, height: r.height}}
                    })
                })''')
                self.assertEqual((bars['scale'], bars['overlap']), (0.25, 10))
                self.assertEqual(len(bars['canvases']), 2)
                rect, w, h = bars['rect'], viewport[0], viewport[1]
                if viewport[:2] == (1920, 1080):
                    self.assertEqual([c['hidden'] for c in bars['canvases']], [True, True])
                    continue
                for c in bars['canvases']:
                    self.assertFalse(c['hidden'])
                    self.assertEqual(c['width'], math.ceil(c['css']['width'] * 0.25 - 1e-9))
                    self.assertEqual(c['height'], math.ceil(c['css']['height'] * 0.25 - 1e-9))
                first, second = (c['css'] for c in bars['canvases'])
                if rect['left'] >= 0.5:
                    want = [(0, 0, rect['left'] + 10, h),
                            (rect['left'] + rect['width'] - 10, 0, w - rect['left'] - rect['width'] + 10, h)]
                else:
                    want = [(0, 0, w, rect['top'] + 10),
                            (0, rect['top'] + rect['height'] - 10, w, h - rect['top'] - rect['height'] + 10)]
                for got, box in zip((first, second), want):
                    for key, value in zip(('left', 'top', 'width', 'height'), box):
                        self.assertAlmostEqual(got[key], value, delta=0.01, msg=key)
                # The bars layer covers the bars and the two overlap strips, not the play rect
                area = sum(c['css']['width'] * c['css']['height'] for c in bars['canvases'])
                strips = 2 * 10 * (h if rect['left'] >= 0.5 else w)
                self.assertLessEqual(area, w * h - rect['width'] * rect['height'] + strips + 1)
                print(f'\n  {viewport_name(viewport)} bar canvases {json.dumps(bars)} '
                      f'area {area / (w * h):.3f} of the window', file=sys.stderr)

    def test_window_bars_repaint_every_4th_frame(self):
        """TASK-138: in a run the bars repaint every WINDOW_BARS_EVERY_FRAMES
        frames, and on the first frame after a resize (the backing stores
        were cleared)."""
        page = self.boot((2560, 1080, False))
        page.evaluate("startGame('classic')")
        page.wait_for_timeout(300)
        page.evaluate('''() => {
            // paint() starts with one clearRect on the bar canvas
            const bars = document.getElementsByClassName('window-bar')[0].getContext('2d')
            const clear = bars.clearRect
            window.__barsPaints = 0
            bars.clearRect = function() { window.__barsPaints++; return clear.apply(this, arguments) }
            window.__frames = 0
            const loop = () => { window.__frames++; requestAnimationFrame(loop) }
            requestAnimationFrame(loop)
        }''')
        page.wait_for_function('() => window.__frames >= 24', timeout=120000)
        run = page.evaluate('''() => ({frames: __frames, paints: __barsPaints,
            every: WINDOW_BARS_EVERY_FRAMES, menu: menu.visible})''')
        self.assertEqual(run['every'], 4)
        self.assertFalse(run['menu'])
        # rAF callbacks and game frames are counted apart: allow one frame each way
        self.assertGreaterEqual(run['paints'], (run['frames'] - 1) // 4)
        self.assertLessEqual(run['paints'], (run['frames'] + 1) // 4 + 1)
        page.set_viewport_size({'width': 925, 'height': 925})
        page.wait_for_function('''() => { const b = document.getElementsByClassName('window-bar')[0]
            return b.box && b.box.width == 925 && b.barsKey }''', timeout=60000)
        after = page.evaluate('''() => { const b = document.getElementsByClassName('window-bar')[0]
            return {paints: __barsPaints, key: b.barsKey, width: b.width, height: b.height, box: b.box} }''')
        self.assertGreater(after['paints'], run['paints'])
        print(f'\n  2560x1080 run {json.dumps(run)}; after resize to 925x925 {json.dumps(after)}',
              file=sys.stderr)
        if self.evidence:
            (self.out() / 'bars-cadence.json').write_text(json.dumps({'run': run, 'after_resize': after}))

    def test_chill_button_click_starts_classic(self):
        lines = []
        for viewport in CLICK_VIEWPORTS:
            with self.subTest(viewport=viewport_name(viewport)):
                page = self.boot(viewport)
                button = page.evaluate('''() => {
                    const b = menu.classicVersionButton.background
                    return {x: b.x + b.width / 2, y: b.y + b.height / 2,
                            label: menu.classicVersionButton.text.text}
                }''')
                point = click_canvas(page, button['x'], button['y'])
                page.wait_for_function('() => !menu.visible')
                state = page.evaluate('''() => ({version, menuVisible: menu.visible,
                    gamePaused: menu.gamePaused, score: scoreText.count[version]})''')
                lines.append(f'{viewport_name(viewport)} label={button["label"]!r} '
                             f'logical=({button["x"]:.1f},{button["y"]:.1f}) '
                             f'css=({point["x"]:.1f},{point["y"]:.1f}) state={json.dumps(state)}')
                self.assertEqual(state['version'], 'classic')
                self.assertFalse(state['menuVisible'])
        print('\n  ' + '\n  '.join(lines), file=sys.stderr)
        if self.evidence:
            (self.out() / 'click.log').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    unittest.main()
