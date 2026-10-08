"""Seeded 5-second, 60 Hz emitter comparison and actual canvas/bloom probes.

The parent has a dormant world emitter: invoke it at its configured 160 ms
cadence, explicitly, rather than claim its live game emits these particles.
HEAD is driven through ParticleSystem.update. Evidence defaults to TASK-204.
"""
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import unittest

from PIL import Image
from browser_test_support import start_browser_test
from perf_mobile import export_rev, SEED_SCRIPT
import render_snapshot as snap

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get('EMBERS_OUT', ROOT / 'artifacts/TASK-204'))
SETUP = r'''mode => {
    startGame(mode); version = mode; scale[mode] = 1; screen.x = screen.y = 0;
    const s = window.__emberTest = {spawns: {}, records: [], bloomOps: 0, offscreen: 0};
    const elements = [];
    for (let i = 0; i < 8; i++) {
        const triangle = new Triangle({x: 320 + (i % 4) * 400, y: 220 + Math.floor(i/4)*400,
            radius: 45, yMin: 0, yMax: 1000, stroke: '#ff547f'});
        const cube = new Rect({x: 490 + (i % 4)*400, y: 185 + Math.floor(i/4)*400,
            width: 65, height: 65, stroke: '#559dff'});
        triangle.testId = 'triangle' + i; cube.testId = 'cube' + i;
        elements.push(triangle, cube);
    }
    const off = new Triangle({x: -10000, y: -10000, radius: 45, yMin: -11000, yMax: -9000});
    off.testId = 'offscreen'; elements.push(off);
    s.elements = elements;
    s.system = new ParticleSystem(ctx, canvas);
    s.system.drawAmbientMotes = () => {};
    visualEffects.particles = s.system;
    visualEffects.playerTrail.drawSmoothPlayerTrailIfEnabled = () => {};
    visualEffects.playerTrail.shouldDraw = () => false;
    visualEffects.screenEffects.drawShockwaveGlow = () => {};
    grapnel.draw = grapnel.drawHook = () => {};
    s.floors = [{elements, drawGlow() {}}];
    const emit = s.system.emitElementParticles;
    s.system.emitElementParticles = function(e) { s.current = e.testId; emit.call(this, e); };
    const push = s.system.pushParticle;
    s.system.pushParticle = function(...args) {
        push.apply(this, args);
        const p = this.particles[this.particles.length-1];
        s.spawns[s.current] = (s.spawns[s.current] || 0) + 1;
        p.testRecord = {life: p.maxLife, alpha: [0], y: p.y};
        s.records.push(p.testRecord);
    };
    s.lastEmit = 0; __snap.now = 0;
    const fill = ctx.fillRect.bind(ctx);
    ctx.fillRect = (...args) => { if (s.inBloom) s.bloomOps++; fill(...args); };
}'''
STEP = r'''([tick, legacy]) => {
    const s = __emberTest, sys = s.system;
    __snap.now = tick * 1000 / 60;
    if (legacy) {
        sys.updateParticles(1000/60);
        if (__snap.now - s.lastEmit >= STYLE.particles.worldEmitIntervalMs) {
            sys.emitWorldParticles(s.floors); s.lastEmit = __snap.now;
        }
    } else sys.update({floors: s.floors});
    const alive = new Set();
    for (const p of sys.particles) {
        alive.add(p.testRecord);
        p.testRecord.alpha.push(legacy ? p.life / p.maxLife * p.alpha : sys.emberAlpha(p));
        p.testRecord.endY = p.y;
    }
    for (const r of s.records) if (!alive.has(r)) r.alpha.push(0);
    // Execute the real emissive method, not merely the predicate in isolation.
    s.inBloom = true;
    visualEffects.bloom.drawEmissiveShapes({floors: s.floors, ninja: {track: {}}});
    s.inBloom = false;
    ctx.setTransform(1,0,0,1,0,0); ctx.globalAlpha = 1;
    ctx.fillStyle = '#14103c'; ctx.fillRect(0,0,1920,1080);
    for (const e of s.elements) if (e.testId !== 'offscreen') e.draw();
    sys.draw();
}'''


def capture(rev, mode, legacy):
    frames = []
    errors = []
    with ExitStack() as stack:
        root, revision = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        context.add_init_script(SEED_SCRIPT % 1)
        context.add_init_script(snap.CLOCK_SCRIPT)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url + 'index.html', wait_until='load')
        snap.boot_frozen(page)
        page.evaluate(SETUP, mode)
        for tick in range(1, 301):
            page.evaluate(STEP, [tick, legacy])
            if tick % 4 == 0:
                data = page.evaluate('() => canvas.toDataURL()')
                frames.append(Image.open(io.BytesIO(snap.png_bytes(data))).convert('RGB').crop((220, 110, 630, 310)))
        result = page.evaluate('''() => {
            const s = __emberTest;
            return {spawns: s.spawns, min_lifetime_s: Math.min(...s.records.map(r => r.life))/1000,
                max_frame_alpha_change: Math.max(...s.records.flatMap(r => r.alpha.map((a,i) => Math.abs(a-(r.alpha[i-1] || 0))))),
                bloom_pass_ember_ops: s.bloomOps,
                all_rise: s.records.every(r => r.endY <= r.y) && s.records.some(r => r.endY < r.y),
                pooled: s.system.pool.length, active: s.system.particles.length};
        }''')
        result.update(rev=revision, page_errors=errors)
    name = f'{"parent" if legacy else "head"}-{mode}'
    folder = OUT / 'before-after'
    folder.mkdir(parents=True, exist_ok=True)
    frames[0].save(folder / f'{name}.gif', save_all=True, append_images=frames[1:], duration=67, loop=0)
    # Ten consecutive samples 21..30 (ticks 88..124), same window at both revisions.
    strip = Image.new('RGB', (410*5, 200*2))
    for i, frame in enumerate(frames[21:31]):
        strip.paste(frame, ((i%5)*410, (i//5)*200))
    strip.save(folder / f'{name}-strip.png')
    result['per_obstacle_per_second'] = {k: v/5 for k,v in result['spawns'].items()}
    return result


class CalmEmbersTests(unittest.TestCase):
    def test_frozen_emitter_rates_envelope_and_bloom(self):
        # Keep the pre-task parent stable across verification-fix commits.
        first = subprocess.check_output(['git', 'log', '--format=%H', '--grep=^TASK-204:'], cwd=ROOT, text=True).splitlines()[-1]
        parent = os.environ.get('EMBERS_PARENT', first + '^')
        report = {'method': 'Configured-emitter comparison only, NOT actual parent gameplay reduction: pre-task parent emitter is dormant. 5 s / 300 frames, seed 1, 8 triangles + 8 cubes per mode; parent emitter explicitly called at configured cadence; HEAD uses update', 'modes': {}}
        for mode in ('bad', 'classic'):
            old = capture(parent, mode, True)
            new = capture('worktree', mode, False)
            ratios = {}
            for kind in ('triangle', 'cube'):
                before = sum(v for k,v in old['spawns'].items() if k.startswith(kind))/40
                after = sum(v for k,v in new['spawns'].items() if k.startswith(kind))/40
                ratios[kind] = {'parent_per_obstacle_per_second': before, 'head_per_obstacle_per_second': after, 'ratio': after/before}
            report['modes'][mode] = {'parent': old, 'head': new, 'rates': ratios, 'per_obstacle': {
                name: {'parent_spawns': old['spawns'].get(name, 0),
                       'head_spawns': new['spawns'].get(name, 0),
                       'ratio': new['spawns'].get(name, 0) / old['spawns'][name]}
                for name in (f'{kind}{i}' for kind in ('triangle', 'cube') for i in range(8))}}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'embers.json').write_text(json.dumps(report, indent=2)+'\n')
        for mode, data in report['modes'].items():
            new = data['head']
            self.assertEqual(new['page_errors'], [])
            self.assertEqual(data['parent']['page_errors'], [])
            for name, counts in data['per_obstacle'].items():
                self.assertGreater(counts['head_spawns'], 0, (mode, name))
                self.assertLessEqual(counts['ratio'], 1/3, (mode, name, counts))
                print(f'PASS {mode}/{name}: {counts}', flush=True)
            for kind, rates in data['rates'].items():
                self.assertGreater(rates['head_per_obstacle_per_second'], 0)
                self.assertLessEqual(rates['ratio'], 1/3, (mode, kind, rates))
            self.assertGreaterEqual(new['min_lifetime_s'], 1.5)
            self.assertLessEqual(new['max_frame_alpha_change'], .08)
            self.assertEqual(new['bloom_pass_ember_ops'], 0)
            self.assertGreater(data['parent']['bloom_pass_ember_ops'], 0)
            self.assertEqual(new['spawns'].get('offscreen', 0), 0)
            self.assertTrue(new['all_rise'])
            self.assertGreater(new['pooled'], 0)
            print(f'PASS {mode}: {data["rates"]}; lifetime={new["min_lifetime_s"]}, alpha_delta={new["max_frame_alpha_change"]}, bloom_ops=0', flush=True)


if __name__ == '__main__':
    unittest.main()
