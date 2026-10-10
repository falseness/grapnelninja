"""Verify production-only paused repaint on DPR changes; no manual post-change draw."""
import argparse
import base64
import json
from contextlib import ExitStack
from pathlib import Path
from browser_test_support import start_browser_test, wait_for_boot
from verify_y8_release import point


def run(root, out):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        for mode in ['bad', 'classic']:
            context = browser.new_context(viewport={'width': 960, 'height': 540}, device_scale_factor=1)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url)
            wait_for_boot(page)
            page.mouse.click(**point(page, 'menu.' + mode + 'VersionButton.background'))
            page.wait_for_function('!menu.visible && !unTouch')
            page.evaluate('''() => {
                RENDER_BUDGET.densityLimit = Infinity;
                menu.startPause();
                window.repaintProbe = {scene: 0, overlay: 0, resize: 0};
                const scene = draw, overlay = menu.drawPauseScreen;
                draw = function() { repaintProbe.scene++; return scene.apply(this, arguments) };
                menu.drawPauseScreen = function() { repaintProbe.overlay++; return overlay.apply(this, arguments) };
                window.addEventListener('resize', () => repaintProbe.resize++);
            }''')
            cd = context.new_cdp_session(page)
            css = page.evaluate('JSON.stringify(getCanvasCssRect())')
            for dpr in [2, 1, 3, 1]:
                before = page.evaluate('({...repaintProbe})')
                cd.send('Emulation.setDeviceMetricsOverride', dict(width=960, height=540, deviceScaleFactor=dpr, mobile=False))
                page.wait_for_timeout(250)
                state = page.evaluate('''() => {
                    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                    let opaque = 0;
                    for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) opaque++;
                    return {dpr: devicePixelRatio, paused: menu.gamePaused, css: JSON.stringify(getCanvasCssRect()),
                        backing: [canvas.width, canvas.height], opaque, counts: {...repaintProbe}};
                }''')
                assert state['dpr'] == dpr and state['paused'] and state['css'] == css, state
                assert state['counts']['resize'] == 0, state
                assert state['backing'] == [960 * min(dpr, 2), 540 * min(dpr, 2)], state
                assert state['counts']['scene'] == before['scene'] + 1, state
                assert state['counts']['overlay'] == before['overlay'] + 1, state
                assert state['opaque'] > 0.9 * state['backing'][0] * state['backing'][1], state
                name = f'paused-dpr-{mode}-{dpr}-{len(rows)}.png'
                capture = base64.b64decode(cd.send('Page.captureScreenshot', {'format': 'png'})['data'])
                (out / name).write_bytes(capture)
                if mode == 'bad' and dpr == 2:
                    (out / 'paused-dpr.png').write_bytes(capture)
                rows.append(dict(mode=mode, capture=name, **state))
                print(f'PASS paused DPR-only {mode} DPR={dpr}: unchanged CSS; zero resize events; production scene + pause overlay repaint; opaque={state["opaque"]}; capture={name}', flush=True)
            assert not errors, errors
            context.close()
    (out / 'paused-dpr-profile.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('PASS paused-dpr.png: production repaint captured without manual draw after DPR change', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.out)
