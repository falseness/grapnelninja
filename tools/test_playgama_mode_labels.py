"""Offline English canvas-button labels and trusted input → runtime mode proof.

MODE_LABELS_EVIDENCE_DIR selects the output directory (default artifacts/TASK-318).
"""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from playgama_render_compare import PROTOCOL, ROOT, SDK, FIXTURE


class ModeLabelTests(unittest.TestCase):
    def test_english_labels_and_handlers(self):
        url, browser = start_browser_test(ROOT, self.addCleanup)
        out = Path(os.environ.get('MODE_LABELS_EVIDENCE_DIR', 'artifacts/TASK-318'))
        out.mkdir(parents=True, exist_ok=True)
        observations = []
        for mode, label in (('classic', 'Chill'), ('bad', 'Main')):
            with self.subTest(mode=mode):
                context = browser.new_context(viewport={'width':844, 'height':390}, locale='en')
                self.addCleanup(context.close)
                context.route(SDK, lambda r: r.fulfill(content_type='application/javascript', body=FIXTURE))
                context.add_init_script("""
                    window.labelInputs = [];
                    document.addEventListener('mousedown', e => labelInputs.push({
                        type:e.type, trusted:e.isTrusted, x:e.clientX, y:e.clientY}), true);
                """)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url + 'index.html')
                wait_for_boot(page)
                page.wait_for_function("menu.visible && I18N.language === 'en' && !unTouch")
                before = page.evaluate("""mode => {
                    const button = menu[mode+'VersionButton'];
                    const b=button.background, r=canvas.getBoundingClientRect();
                    return {label:button.text.text, language:I18N.language,
                        records:scoreText.record,
                        point:{x:r.x+(b.x+b.width/2)*r.width/width,
                               y:r.y+(b.y+b.height/2)*r.height/height}};
                }""", mode)
                self.assertEqual(before['label'], label.lower() + ' version')
                self.assertEqual(before['records'], {'classic':12, 'bad':7})
                page.mouse.click(**before['point'])
                page.wait_for_function('!menu.visible && !!ninja')
                after = page.evaluate('({version, inputs:labelInputs, records:scoreText.record})')
                self.assertEqual(after['version'], mode)
                self.assertEqual(after['records'], before['records'])
                self.assertEqual(len(after['inputs']), 1)
                self.assertTrue(after['inputs'][0]['trusted'])
                self.assertEqual(PROTOCOL['mode_labels'][after['version']], label)
                self.assertEqual(errors, [])
                verdict = f'PASS {mode}={label}'
                observation = dict(verdict=verdict, before=before, after=after,
                    protocol_label=PROTOCOL['mode_labels'][mode], browser=browser.version, errors=errors)
                observations.append(observation)
                (out/'mode-labels.json').write_text(json.dumps(observations, indent=2)+'\n')
                print(verdict + '; ' + json.dumps(observation), flush=True)
                context.close()


if __name__ == '__main__':
    unittest.main()
