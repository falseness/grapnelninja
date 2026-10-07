"""The colour grade (ColorGradeRenderer, TASK-187) is switched off by
STYLE.features.colorGrade, and that switch is the only change.

On render_snapshot's frozen clock (844x390@3, touch):
(a) the menu and bad/classic games at COLORGRADE_REV (default worktree): every
    CanvasRenderingContext2D call and property set made while
    ColorGradeRenderer.draw runs is counted; it must be 0 on every frame;
(b) the same rev with the switch forced on by an init script must match
    COLORGRADE_PARENT (default 66d2713, the commit before the switch went off)
    within MAX_DELTA per channel.
Writes probe.json into COLORGRADE_EVIDENCE_DIR when it is set.
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot

REV = os.environ.get('COLORGRADE_REV', 'worktree')
PARENT = os.environ.get('COLORGRADE_PARENT', '66d2713')
VIEWPORT = render_snapshot.VIEWPORTS[0]
MODES = ['bad', 'classic']
TICKS = [60, 300]
MAX_DELTA = 2

# Counts the canvas calls and property sets made inside ColorGradeRenderer.draw,
# and how often draw is entered, per stepped frame (and for the menu frame).
COUNT_SCRIPT = '''(() => {
    const grade = window.__grade = {depth: 0, ops: 0, calls: 0}
    const proto = CanvasRenderingContext2D.prototype
    for (const name of Object.getOwnPropertyNames(proto)) {
        const d = Object.getOwnPropertyDescriptor(proto, name)
        if (typeof d.value == 'function' && name != 'constructor')
            proto[name] = function(...args) {
                if (grade.depth) grade.ops++
                return d.value.apply(this, args)
            }
        else if (d.set)
            Object.defineProperty(proto, name, {...d, set(v) {
                if (grade.depth) grade.ops++
                d.set.call(this, v)
            }})
    }
    addEventListener('load', () => {
        grade.frames = []
        const step = __snap.step
        __snap.step = () => {
            const ops = grade.ops, calls = grade.calls
            step()
            grade.frames.push({ops: grade.ops - ops, calls: grade.calls - calls})
        }
        const draw = ColorGradeRenderer.prototype.draw
        ColorGradeRenderer.prototype.draw = function(...args) {
            grade.calls++
            grade.depth++
            try { return draw.apply(this, args) } finally { grade.depth-- }
        }
    })
})()'''

# Forces the switch on without touching the frozen STYLE
FORCE_ON_SCRIPT = '''addEventListener('load', () => {
    ColorGradeRenderer.prototype.shouldDraw = () => true
})'''


def run(rev, extra_init=None, count=False):
    """Menu capture plus captures of each mode at TICKS; with count, grade ops
    and draw calls of the menu frame and of every game frame."""
    result = {'captures': {}, 'frames': {}, 'page_errors': []}
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        result['rev'] = rev_id
        url, browser = start_browser_test(root, stack.callback)
        script = render_snapshot.input_script(render_snapshot.SEED, TICKS[-1],
                                              VIEWPORT['width'], VIEWPORT['height'])
        for mode in [None] + MODES:
            context = browser.new_context(viewport={'width': VIEWPORT['width'], 'height': VIEWPORT['height']},
                                          device_scale_factor=VIEWPORT['dpr'], is_mobile=True, has_touch=True)
            context.add_init_script(SEED_SCRIPT % render_snapshot.SEED)
            context.add_init_script(render_snapshot.CLOCK_SCRIPT)
            if count:
                context.add_init_script(COUNT_SCRIPT)
            if extra_init:
                context.add_init_script(extra_init)
            page = context.new_page()
            page.on('pageerror', lambda e, m=mode: result['page_errors'].append(f'{m or "menu"}: {e}'))
            page.goto(url + 'index.html', wait_until='load')
            render_snapshot.boot_frozen(page)
            page.evaluate(render_snapshot.SETUP_SCRIPT, [script, True])
            name = mode or 'menu'
            if mode is None:
                if count:
                    # One more menu frame on top of the boot frame
                    page.evaluate('() => menu.draw()')
                    result['frames']['menu'] = [page.evaluate('() => ({ops: __grade.ops, calls: __grade.calls})')]
                result['captures']['menu'] = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
            else:
                page.evaluate('mode => startGame(mode)', mode)
                for tick in TICKS:
                    page.evaluate(render_snapshot.ADVANCE_SCRIPT, tick)
                    result['captures'][f'{name}-tick{tick:04d}'] = render_snapshot.png_bytes(
                        page.evaluate('() => __snap.capture()'))
                if count:
                    result['frames'][name] = page.evaluate('() => __grade.frames')
            context.close()
    return result


def pixels(data):
    return np.asarray(Image.open(io.BytesIO(data)).convert('RGB'), dtype=np.int16)


class ColorGradeOffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = {'rev': None, 'parent': PARENT, 'max_delta_allowed': MAX_DELTA}

    @classmethod
    def tearDownClass(cls):
        out = os.environ.get('COLORGRADE_EVIDENCE_DIR')
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / 'probe.json').write_text(json.dumps(cls.probe, indent=1) + '\n')

    def test_a_grade_issues_no_canvas_ops(self):
        off = run(REV, count=True)
        on = run(REV, extra_init=FORCE_ON_SCRIPT, count=True)
        self.probe['rev'] = off['rev']
        summary = {}
        for label, result in (('switch_off', off), ('forced_on', on)):
            self.assertEqual(result['page_errors'], [], label)
            summary[label] = {name: {'frames': len(frames),
                                     'grade_ops_per_frame_max': max(f['ops'] for f in frames),
                                     'grade_ops_total': sum(f['ops'] for f in frames),
                                     'grade_draw_calls_total': sum(f['calls'] for f in frames)}
                              for name, frames in result['frames'].items()}
        self.probe['grade_ops'] = summary
        for name in ['menu'] + MODES:
            # The grade is still asked to draw every frame, so the counter is live...
            self.assertGreater(summary['switch_off'][name]['grade_draw_calls_total'], 0, name)
            # ...and with the switch on it does draw: the counter sees its fills
            self.assertGreater(summary['forced_on'][name]['grade_ops_per_frame_max'], 0, name)
            self.assertEqual(summary['switch_off'][name]['grade_ops_total'], 0, name)

    def test_b_forced_on_matches_parent(self):
        parent = run(PARENT)
        forced = run(REV, extra_init=FORCE_ON_SCRIPT)
        self.probe['parent_rev'] = parent['rev']
        self.probe['forced_on_rev'] = forced['rev']
        self.assertEqual(parent['page_errors'], [])
        self.assertEqual(forced['page_errors'], [])
        deltas = {}
        for name, data in parent['captures'].items():
            a, b = pixels(data), pixels(forced['captures'][name])
            self.assertEqual(a.shape, b.shape, name)
            delta = np.abs(a - b)
            deltas[name] = {'max_channel_delta': int(delta.max()),
                            'differing_pixels': int((delta.max(axis=2) > 0).sum())}
        self.probe['forced_on_vs_parent'] = deltas
        self.probe['forced_on_vs_parent_max_delta'] = max(d['max_channel_delta'] for d in deltas.values())
        for name, d in deltas.items():
            self.assertLessEqual(d['max_channel_delta'], MAX_DELTA, name)


if __name__ == '__main__':
    unittest.main()
