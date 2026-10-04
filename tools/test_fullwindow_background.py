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
import os
import statistics
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser_test_support import wait_for_boot
from playgama_harness import click_canvas, open_game, start_playgama_test

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
        cls.url, cls.browser = start_playgama_test(ROOT, cls.addClassCleanup)
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

    def test_window_background_renders_at_quarter_size(self):
        """TASK-138: a full-resolution bars repaint cost ~30% of the frame at
        2560x1080; the window canvas backing store is a quarter of the window
        (1/16 of the pixels) and CSS stretches it over the whole window."""
        for viewport in [(2560, 1080, False), (390, 844, True)]:
            with self.subTest(viewport=viewport_name(viewport)):
                page = self.boot(viewport)
                size = page.evaluate('''() => {
                    const b = document.getElementById('background')
                    const r = b.getBoundingClientRect()
                    return {scale: WINDOW_BACKGROUND_SCALE, width: b.width, height: b.height,
                            css: {left: r.left, top: r.top, width: r.width, height: r.height},
                            window: {width: innerWidth, height: innerHeight}}
                }''')
                self.assertEqual(size['scale'], 0.25)
                self.assertEqual(size['width'], round(viewport[0] * 0.25))
                self.assertEqual(size['height'], round(viewport[1] * 0.25))
                self.assertEqual(size['css'], {'left': 0, 'top': 0, 'width': viewport[0],
                                               'height': viewport[1]})
                print(f'\n  {viewport_name(viewport)} window background {json.dumps(size)}',
                      file=sys.stderr)

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
