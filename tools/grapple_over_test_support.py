"""Offline, seeded fixtures and task-local proof for focused Grapple Over suites.

Only the browser test loads these helpers. Production physics functions are
never replaced: the fixture cancels rAF and explicitly steps physics().
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from browser_test_support import wait_for_boot
from perf_mobile import SEED_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
VIEWPORT = {'width': 1280, 'height': 720}


def source_hashes():
    names = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    names = [n for n in names if (n.endswith('.js') and not n.startswith('tools/'))
             or n == 'index.html']
    names += ['tools/browser_test_support.py', 'tools/perf_mobile.py',
              'tools/grapple_over_test_support.py', 'tools/test_grapple_over_baseline.py']
    return {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in sorted(names)}


class EvidenceWriter:
    def __init__(self, task='TASK-444'):
        self.root = Path(os.environ.get('GRAPPLE_OVER_EVIDENCE_DIR', ROOT / 'artifacts' / task))
        if not self.root.is_absolute():
            self.root = ROOT / self.root
        self.root = self.root.resolve()
        if not self.root.is_relative_to((ROOT / 'artifacts').resolve()):
            raise ValueError('Evidence must stay inside artifacts/')
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name):
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Evidence path escapes task directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, name, value):
        self.path(name).write_text(json.dumps(value, indent=2) + '\n')

    def log(self, line):
        with self.path('commands.log').open('a') as stream:
            stream.write(line + '\n')


STATE = '''() => ({mode: version, x: ninja.x, y: ninja.y,
    speedX: ninja.speedX, speedY: ninja.speedY, radius: ninja.radius,
    paused: menu.gamePaused, throwed: grapnel.throwed,
    grappled: grapnel.isGrappled(), rope: grapnel.pos.map(p => p.slice(0, 2))})'''


def open_fixture(browser, url, mode, cleanup):
    if mode not in ('classic', 'bad'):
        raise ValueError('Explicit existing mode required')
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    cleanup(context.close)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script(SEED_SCRIPT % 1)
    page.goto(url)
    wait_for_boot(page)
    page.evaluate(SEED_SCRIPT % 1)
    page.evaluate('mode => {startGame(mode); cancelAnimationFrame(game)}', mode)
    page.wait_for_function('!unTouch')
    return page, errors


def step(page, count):
    return page.evaluate('''count => {
        const rows = [];
        for (let i = 0; i < count; i++) {physics(); rows.push((STATE)())}
        return rows;
    }'''.replace('STATE', STATE), count)


def screenshot(page, evidence, name):
    page.evaluate('draw()')
    page.screenshot(path=str(evidence.path('screenshots/' + name + '.png')))
