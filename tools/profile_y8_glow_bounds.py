"""Offline experiment: clip additive glow to nonblack source bounds.

Never changes the shipping runtime. Pixel comparisons and FPS samples are
separate: fixed simulation captures cannot measure display FPS. Even exact
sample pixels and a faster sample do not satisfy the six-run release gate.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

import numpy as np
from PIL import Image
from browser_test_support import start_browser_test, wait_for_boot
from perf_mobile import SEED_SCRIPT
from render_snapshot import CLOCK_SCRIPT, SETUP_SCRIPT, boot_frozen, input_script, png_bytes
from y8_fps_baseline import INSTRUMENT, SDK
from y8_performance_gate import metrics

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ('control', 'bounded')
DEPENDENCIES = ('browser_test_support.py', 'perf_mobile.py', 'render_snapshot.py',
                'y8_fps_baseline.py', 'y8_performance_gate.py', 'fixtures/fake-y8-sdk.js')
OLD = '            this.ctx.drawImage(this.levels[i].canvas, 0, 0, this.canvas.width, this.canvas.height)'
NEW = '''            const level = this.levels[i]
            const w = level.canvas.width, h = level.canvas.height
            const pixels = level.ctx.getImageData(0, 0, w, h).data
            let left = w, top = h, right = -1, bottom = -1
            for (let y = 0; y < h; ++y)
                for (let x = 0; x < w; ++x)
                {
                    const p = (y * w + x) * 4
                    if (pixels[p] || pixels[p + 1] || pixels[p + 2])
                    {
                        left = Math.min(left, x); right = Math.max(right, x)
                        top = Math.min(top, y); bottom = Math.max(bottom, y)
                    }
                }
            if (right < left) continue
            // Keep original resampling coordinates and one full texel of
            // black support around nonblack pixels for bilinear interpolation.
            const sx = this.canvas.width / w, sy = this.canvas.height / h
            const x0 = Math.max(0, Math.floor((left - 1) * sx))
            const y0 = Math.max(0, Math.floor((top - 1) * sy))
            const x1 = Math.min(this.canvas.width, Math.ceil((right + 2) * sx))
            const y1 = Math.min(this.canvas.height, Math.ceil((bottom + 2) * sy))
            this.ctx.save()
            this.ctx.beginPath(); this.ctx.rect(x0, y0, x1 - x0, y1 - y0); this.ctx.clip()
            this.ctx.drawImage(level.canvas, 0, 0, this.canvas.width, this.canvas.height)
            this.ctx.restore()'''


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, data):
    p.write_text(json.dumps(data, indent=2) + '\n')


def comparisons(out):
    rows = []
    for mode in ('bad', 'classic'):
        for tick in (60, 150):
            arrays = [np.array(Image.open(out / f'{mode}-{v}-{tick}.png').convert('RGBA')).astype(int)
                      for v in VARIANTS]
            assert all(a.shape == (780, 1560, 4) for a in arrays)
            delta = np.abs(arrays[0] - arrays[1])
            rows.append(dict(mode=mode, tick=tick, different_pixels=int(np.any(delta, axis=2).sum()),
                             max_channel_difference=int(delta.max())))
    return rows


def capture(archive, out):
    out.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist()))
        assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist())
        for v in VARIANTS:
            z.extractall(out / v)
    path = out / 'bounded/render/effects.js'
    original = path.read_text()
    assert original.count(OLD) == 1
    changed = original.replace(OLD, NEW)
    path.write_text(changed)
    (out / 'experiment.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), changed.splitlines(True), fromfile='control', tofile='bounded')))
    runtime = {v: {str(p.relative_to(out / v)): sha(p) for p in sorted((out / v).rglob('*')) if p.is_file()}
               for v in VARIANTS}
    runs, states = [], {}
    with ExitStack() as stack:
        url, browser = start_browser_test(out, stack.callback)
        environment = dict(os=platform.platform(), python=sys.version, browser=browser.version,
                           gpu=browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu'])
        for frozen in (True, False):
            for variant in VARIANTS:
                for mode in (('bad', 'classic') if frozen else ('bad',)):
                    name = f'{variant}-{mode}-frozen-{frozen}'
                    c = browser.new_context(viewport={'width': 780, 'height': 390}, device_scale_factor=2,
                                            service_workers='block')
                    network, errors = [], []
                    def route(r):
                        u = r.request.url
                        if u == SDK:
                            network.append('FAKE_SDK ' + u)
                            r.fulfill(content_type='text/javascript', body=(ROOT / 'tools/fixtures/fake-y8-sdk.js').read_text())
                        elif u.startswith(url):
                            network.append('LOCAL ' + u); r.continue_()
                        else:
                            network.append('BLOCKED ' + u); r.abort()
                    c.route('**/*', route)
                    c.add_init_script(SEED_SCRIPT % 1 + (';\n' + CLOCK_SCRIPT if frozen else ''))
                    p = c.new_page()
                    p.on('pageerror', lambda e: errors.append(str(e)))
                    p.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
                    c.new_cdp_session(p).send('Emulation.setCPUThrottlingRate', {'rate': 1})
                    p.goto(url + variant + '/index.html', wait_until='load')
                    if frozen:
                        boot_frozen(p)
                        p.evaluate(SETUP_SCRIPT, [input_script(ticks=150, width=780, height=390), False])
                        p.evaluate('RENDER_BUDGET.densityLimit=2; RENDER_BUDGET.observe=()=>false')
                    else:
                        wait_for_boot(p); p.evaluate(INSTRUMENT)
                    p.evaluate('(mode)=>startGame(mode)', mode)
                    if frozen:
                        for tick in (60, 150):
                            p.evaluate('t=>{while(__snap.tick<t)__snap.step()}', tick)
                            states[f'{mode}-{variant}-{tick}'] = p.evaluate('[ninja.x,ninja.y,screen.x,screen.y,floors.length,ninja.track.length]')
                            (out / f'{mode}-{variant}-{tick}.png').write_bytes(png_bytes(p.evaluate('()=>__snap.capture()')))
                    else:
                        p.wait_for_function('measure.done', timeout=180000)
                        raw = p.evaluate('measure')
                        assert all(f['canvas'] == [1560, 780] for f in raw['frames'])
                        save(out / f'{variant}-fps.json', raw)
                        runs.append(dict(variant=variant, metrics=metrics(raw['frames'])))
                    save(out / f'{name}-network.json', network)
                    save(out / f'{name}-errors.json', errors)
                    assert not errors, errors
                    assert any(n.startswith('FAKE_SDK ') for n in network)
                    print('PASS capture', name, runs[-1:] if not frozen else '', flush=True)
                    c.close()
    report = dict(started_utc=started, ended_utc=datetime.now(timezone.utc).isoformat(),
                  command=sys.argv, source_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  archive=str(archive), archive_sha256=sha(archive), runtime=runtime,
                  environment=environment, settings=dict(viewport=[780,390], DPR=2, canvas=[1560,780],
                  seed=1, cpu_throttle=1, effects='unchanged', density='pinned; adaptive disabled'),
                  runs=runs, states=states, comparisons=comparisons(out), tool_sha256=sha(Path(__file__)),
                  dependencies={n: sha(ROOT / 'tools' / n) for n in DEPENDENCIES},
                  limitations='One FPS sample per variant on shared software host; fixed-tick pixel checks sample only two modes/ticks. No gate PASS, native-device proof or shipping change.')
    report['evidence_sha256'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    save(out / 'manifest.json', report)


def audit(archive, out):
    m = json.loads((out / 'manifest.json').read_text())
    assert sha(archive) == m['archive_sha256']
    assert sha(Path(__file__)) == m['tool_sha256']
    assert m['dependencies'] == {n: sha(ROOT / 'tools' / n) for n in DEPENDENCIES}
    for path in out.glob('*-errors.json'):
        assert json.loads(path.read_text()) == [], path
    for path in out.glob('*-network.json'):
        network = json.loads(path.read_text())
        assert any(n.startswith('FAKE_SDK ') for n in network)
        assert all(n.startswith(('LOCAL ', 'FAKE_SDK ', 'BLOCKED ')) for n in network)
    for path, digest in m['evidence_sha256'].items():
        assert sha(out / path) == digest, path
    with zipfile.ZipFile(archive) as z:
        assert {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()} == m['runtime']['control']
    assert comparisons(out) == m['comparisons']
    for row in m['comparisons']:
        mode, tick = row['mode'], row['tick']
        assert m['states'][f'{mode}-control-{tick}'] == m['states'][f'{mode}-bounded-{tick}']
        print('PASS recomputed matched-state pixels', json.dumps(row))
    for row in m['runs']:
        raw = json.loads((out / (row['variant'] + '-fps.json')).read_text())
        assert all(f['canvas'] == [1560,780] for f in raw['frames'])
        assert metrics(raw['frames']) == row['metrics']
        print('PASS recomputed 30-second matched-density diagnostic', json.dumps(row))
    print('PASS archive, tool and', len(m['evidence_sha256']), 'evidence hashes; no shipping or performance gate PASS')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('capture','audit'))
    ap.add_argument('--archive', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    (capture if args.action == 'capture' else audit)(args.archive.resolve(), args.out.resolve())
