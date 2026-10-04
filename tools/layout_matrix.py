"""Layout checks per screen, size and language (Playgama UX rules).

For each (language, size) one page is opened against the fake Bridge and
walked through menu -> hud -> pause -> continue offer -> ad unavailable.
Every screen is drawn once with LAYOUT_PROBE.boxes on (menu.js), which
returns the text and button boxes in CSS px relative to the canvas.

Checks per shot:
- aspect: canvas CSS box width / height, <= 2.0 on desktop sizes
- scrollbar: document scrollWidth/Height > clientWidth/Height
- clipped: boxes not inside the canvas box
- overlaps: pairs of boxes that intersect (a text inside the button it
  labels, or a label inside a checkbox hit area, is not an overlap)
- min_font_px: smallest text, >= 12
- min_button_px: smallest button side, >= 44 on touch sizes
"""
import json
from pathlib import Path

from playgama_harness import BRIDGE_URL, CONFIG_ROUTE, FAKE_BRIDGE, collect_errors, serve_config
from test_audio_wiring import READY
from test_continue import INSTRUMENT_RUN

SIZES = [(360, 640, True), (390, 844, True), (915, 412, True), (844, 390, True),
         (1280, 720, False), (1920, 1080, False), (2560, 1440, False),
         (2560, 1080, False), (1280, 500, False), (925, 925, False), (1024, 768, False),
         (1280, 1024, False)]
LANGS = {'en': 'en-US', 'ru': 'ru-RU'}
SCREENS = ['menu', 'hud', 'pause', 'offer', 'ad_unavailable']
MAX_ASPECT = 2.0
MIN_FONT_PX = 12
MIN_BUTTON_PX = 44
EPS = 0.5

# Boxes drawn by one synchronous call with the probe on
PROBE = '''(code) => {
    LAYOUT_PROBE.boxes = []
    try { (new Function(code))() } finally {}
    const boxes = LAYOUT_PROBE.boxes
    LAYOUT_PROBE.boxes = null
    const r = canvas.getBoundingClientRect()
    const d = document.documentElement
    return {boxes: boxes, canvas: {left: r.left, top: r.top, width: r.width, height: r.height},
            scroll: {sw: d.scrollWidth, sh: d.scrollHeight, cw: d.clientWidth, ch: d.clientHeight,
                     bsw: document.body.scrollWidth, bsh: document.body.scrollHeight}}
}'''
DRAW = {
    'menu': 'menu.draw()',
    'hud': 'draw()',
    'pause': 'menu.drawPauseScreen()',
    'offer': 'continueOffer.draw()',
    'ad_unavailable': 'continueOffer.draw()',
}


def inside(a, b):
    return (a['x'] >= b['x'] - EPS and a['y'] >= b['y'] - EPS and
            a['x'] + a['width'] <= b['x'] + b['width'] + EPS and
            a['y'] + a['height'] <= b['y'] + b['height'] + EPS)


def intersect(a, b):
    return (a['x'] < b['x'] + b['width'] - EPS and b['x'] < a['x'] + a['width'] - EPS and
            a['y'] < b['y'] + b['height'] - EPS and b['y'] < a['y'] + a['height'] - EPS)


def dedupe(boxes):
    seen, out = set(), []
    for b in boxes:
        key = (b['kind'], b['name'], round(b['x'], 1), round(b['y'], 1),
               round(b['width'], 1), round(b['height'], 1))
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


def evaluate(shot, touch):
    """Row of check results for one probe result."""
    boxes = dedupe(shot['boxes'])
    c = shot['canvas']
    s = shot['scroll']
    field = {'x': 0, 'y': 0, 'width': c['width'], 'height': c['height']}
    aspect = c['width'] / c['height']
    scrollbar = s['sw'] > s['cw'] or s['sh'] > s['ch']
    clipped = [b['name'] for b in boxes if not inside(b, field)]
    overlaps = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if not intersect(a, b):
                continue
            # A label inside the button (or checkbox hit area) it belongs to
            if 'button' in (a['kind'], b['kind']) and a['kind'] != b['kind'] and \
                    (inside(a, b) if a['kind'] == 'text' else inside(b, a)):
                continue
            overlaps.append([a['name'], b['name']])
    fonts = [b['fontPx'] for b in boxes if b['kind'] == 'text']
    buttons = [min(b['width'], b['height']) for b in boxes if b['kind'] == 'button']
    min_font = round(min(fonts), 2) if fonts else None
    min_button = round(min(buttons), 2) if buttons else None
    row = {
        'aspect': round(aspect, 4),
        'scrollbar': scrollbar,
        'overlaps': overlaps,
        'clipped': clipped,
        'min_font_px': min_font,
        'min_button_px': min_button,
        'boxes': len(boxes),
    }
    failures = []
    if not touch and aspect > MAX_ASPECT + 1e-3:
        failures.append('aspect')
    if scrollbar:
        failures.append('scrollbar')
    if overlaps:
        failures.append('overlaps')
    if clipped:
        failures.append('clipped')
    if min_font is None or min_font < MIN_FONT_PX - 1e-6:
        failures.append('min_font_px')
    if touch and (min_button is None or min_button < MIN_BUTTON_PX - 1e-6):
        failures.append('min_button_px')
    row['failures'] = failures
    row['pass'] = not failures
    return row, boxes


def open_page(browser, url, size, touch, locale):
    w, h = size
    kwargs = {'viewport': {'width': w, 'height': h}}
    if touch:
        kwargs.update(has_touch=True, is_mobile=True, device_scale_factor=2)
    context = browser.new_context(**kwargs)
    context.route(BRIDGE_URL, lambda route: route.fulfill(
        path=str(FAKE_BRIDGE), content_type='application/javascript'))
    context.route(CONFIG_ROUTE, serve_config)
    context.add_init_script(
        f'window.__fakeBridge = Object.assign(window.__fakeBridge || {{}}, '
        f'{json.dumps({"language": locale})})')
    page = context.new_page()
    errors = collect_errors(page)
    page.goto(url + 'index.html')
    page.wait_for_function(READY, timeout=15000)
    return context, page, errors


def walk(browser, url, lang, size, touch, shots_dir=None):
    """Rows for every screen of one language at one size."""
    context, page, errors = open_page(browser, url, size, touch, LANGS[lang])
    rows = []
    try:
        assert page.evaluate('I18N.language') == lang
        page.evaluate(INSTRUMENT_RUN)

        def shot(screen):
            page.wait_for_timeout(150)
            if shots_dir:
                out = Path(shots_dir) / lang / f'{size[0]}x{size[1]}'
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / f'{screen}.png'))
            result = page.evaluate(PROBE, DRAW[screen])
            row, boxes = evaluate(result, touch)
            row.update(lang=lang, size=f'{size[0]}x{size[1]}', touch=touch, screen=screen,
                       canvas=result['canvas'], box_list=boxes)
            rows.append(row)

        shot('menu')
        page.evaluate('''() => { const b = menu.classicVersionButton.background
            menu.click({x: b.x + b.width / 2, y: b.y + b.height / 2}) }''')
        page.evaluate('() => { scoreText.count[version] = 7 }')
        page.wait_for_timeout(450)
        shot('hud')
        page.evaluate('menu.startPause()')
        shot('pause')
        page.evaluate('menu.unPause()')
        page.evaluate('() => { scoreText.count[version] = 7; window.__kill = true }')
        page.wait_for_function('continueOffer.visible')
        shot('offer')
        page.evaluate('continueOffer.showAdError()')
        shot('ad_unavailable')
        assert (errors['console'], errors['page']) == ([], []), errors
    finally:
        context.close()
    return rows
