"""Frozen-clock extrusion call counts and flag-on parent pixel equivalence.

Writes TASK-203 evidence by default; EXTRUSION_OUT and EXTRUSION_PARENT
can override the evidence directory and reference revision for later use.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest

import numpy as np
from PIL import Image, ImageDraw
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get('EXTRUSION_OUT', ROOT / 'artifacts/TASK-203'))
FORCE_ON = '''(() => {
    const freeze = Object.freeze
    Object.freeze = function(value) {
        if (value && Object.hasOwn(value, 'extrusion') && Object.hasOwn(value, 'background'))
            value.extrusion = true
        return freeze(value)
    }
})()'''
COUNT = '''() => {
    window.__extrusion = {drawExtrusions: 0, drawExtrusion: 0, drawPolygonExtrusion: 0}
    for (const proto of [Floor.prototype, Element.prototype, Rect.prototype,
                          Side.prototype, Ground.prototype, Trampoline.prototype]) {
        for (const name of Object.keys(__extrusion)) {
            if (!Object.hasOwn(proto, name)) continue
            const original = proto[name]
            proto[name] = function(...args) {
                __extrusion[name]++
                return original.apply(this, args)
            }
        }
    }
}'''


def capture(rev, label, force=False):
    result = {'captures': {}, 'page_errors': []}
    folder = OUT / label
    folder.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        root, result['rev'] = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        for vp in snap.VIEWPORTS:
            for mode in snap.MODES:
                context = browser.new_context(viewport={k: vp[k] for k in ('width', 'height')},
                    device_scale_factor=vp['dpr'], is_mobile=vp['touch'], has_touch=vp['touch'])
                try:
                    context.add_init_script(SEED_SCRIPT % snap.SEED)
                    context.add_init_script(snap.CLOCK_SCRIPT)
                    if force:
                        context.add_init_script(FORCE_ON)
                    page = context.new_page()
                    page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
                    page.goto(url + 'index.html', wait_until='load')
                    snap.boot_frozen(page)
                    page.evaluate(COUNT)
                    page.evaluate(snap.SETUP_SCRIPT, [snap.input_script(ticks=900,
                        width=vp['width'], height=vp['height']), vp['touch']])
                    page.evaluate('mode => startGame(mode)', mode)
                    for tick in (300, 900):
                        page.evaluate(snap.ADVANCE_SCRIPT, tick)
                        name = f'{vp["name"]}-{mode}-tick{tick:04d}'
                        (folder / f'{name}.png').write_bytes(snap.png_bytes(page.evaluate('() => __snap.capture()')))
                        result['captures'][name] = page.evaluate('''() => ({
                            counts: {...__extrusion}, flag: STYLE.features.extrusion ?? true,
                            padding: getCullPadding(),
                            extrusionPadding: STYLE.extrusion.depth / scale[version] + STYLE.extrusion.edgeWidth
                        })''')
                    print(f'{label}: {vp["name"]} {mode} 900 frames', flush=True)
                finally:
                    context.close()
    return result


def probe():
    subject = subprocess.check_output(['git', 'log', '-1', '--format=%s'], cwd=ROOT, text=True)
    parent = os.environ.get('EXTRUSION_PARENT', 'HEAD^' if subject.startswith('TASK-203:') else 'HEAD')
    report = {'parent': capture(parent, 'parent'), 'off': capture('worktree', 'off'),
              'on': capture('worktree', 'on', True),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name, entry in report['on']['captures'].items():
        a = np.asarray(Image.open(OUT / 'parent' / f'{name}.png').convert('RGB'), dtype=np.int16)
        b = np.asarray(Image.open(OUT / 'on' / f'{name}.png').convert('RGB'), dtype=np.int16)
        entry['max_channel_delta'] = int(np.abs(a-b).max())
    (OUT / 'switch.json').write_text(json.dumps(report, indent=2) + '\n')
    sheet = Image.new('RGB', (1920, 1120))
    draw = ImageDraw.Draw(sheet)
    for row, mode in enumerate(snap.MODES):
        for col, label in enumerate(('parent', 'off')):
            draw.text((col*960+10, row*560+3), f'{mode}: {label}', fill='white')
            with Image.open(OUT / label / f'desktop-{mode}-tick0300.png') as im:
                sheet.paste(im.resize((960, 540)), (col*960, row*560+20))
    sheet.save(OUT / 'before-after.png')
    return report


class ExtrusionSwitchTests(unittest.TestCase):
    def test_switch_and_parent_pixels(self):
        report = probe()
        for label in ('parent', 'off', 'on'):
            self.assertEqual(report[label]['page_errors'], [])
        for name, on in report['on']['captures'].items():
            off = report['off']['captures'][name]
            self.assertFalse(off['flag'])
            self.assertTrue(on['flag'])
            for method, count in off['counts'].items():
                self.assertEqual(count, 0, (name, method))
                self.assertGreater(on['counts'][method], 0, (name, method))
            self.assertAlmostEqual(on['padding']-off['padding'], on['extrusionPadding'])
            self.assertLessEqual(on['max_channel_delta'], 2, name)
            print(f'PASS {name}: off={off["counts"]} on={on["counts"]} '
                  f'max_channel_delta={on["max_channel_delta"]} <= 2', flush=True)


if __name__ == '__main__':
    unittest.main()
