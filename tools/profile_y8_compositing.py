"""Offline glow ablation diagnostic; disabling effects is NOT a shipping fix.

Use the extracted release as --root. All cases retain DPR2 and a 1560x780
backing canvas. This is neither a performance acceptance gate nor a comparison
of equal visual quality: the ablations deliberately remove visible effects.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys

from browser_test_support import start_browser_test, wait_for_boot
from perf_mobile import SEED_SCRIPT
from y8_fps_baseline import INSTRUMENT, SDK

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ('control', 'without_ambient_glow', 'without_player_glow', 'without_both_glows')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def capture(root, out):
    out.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    runtime = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    runs = []
    with ExitStack() as stack:
        url, browser = start_browser_test(root, stack.callback)
        environment = dict(os=platform.platform(), python=sys.version, browser=browser.version,
                           gpu=browser.new_browser_cdp_session().send('SystemInfo.getInfo')['gpu'])
        for variant in VARIANTS:
            context = browser.new_context(viewport={'width': 780, 'height': 390},
                                          device_scale_factor=2, service_workers='block')
            errors, network = [], []

            def route(request):
                address = request.request.url
                if address == SDK:
                    network.append('FAKE_SDK ' + address)
                    request.fulfill(content_type='text/javascript',
                                    body=(ROOT / 'tools/fixtures/fake-y8-sdk.js').read_text())
                elif address.startswith(url):
                    network.append('LOCAL ' + address)
                    request.continue_()
                else:
                    network.append('BLOCKED ' + address)
                    request.abort()

            context.route('**/*', route)
            context.add_init_script(SEED_SCRIPT % 1)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            page.goto(url, wait_until='domcontentloaded')
            wait_for_boot(page)
            page.evaluate(INSTRUMENT)
            page.evaluate('''variant => {
                window.disabledCalls = {ambient: 0, player: 0};
                if (variant === 'without_ambient_glow' || variant === 'without_both_glows')
                    visualEffects.ambientGlow.drawScreen = () => { disabledCalls.ambient++; };
                if (variant === 'without_player_glow' || variant === 'without_both_glows')
                    window.drawPlayerGlowLayer = () => { disabledCalls.player++; };
                startGame('bad');
            }''', variant)
            page.wait_for_function('measure.done', timeout=180000)
            raw = page.evaluate('({measure, disabledCalls, dimensions: [canvas.width, canvas.height]})')
            raw.update(variant=variant, errors=errors, network=network)
            save(out / (variant + '.json'), raw)
            context.close()
            result = inspect(raw)
            runs.append(result)
            print('PASS diagnostic', variant, json.dumps(result), flush=True)
    save(out / 'manifest.json', dict(
        command=sys.argv, started_utc=started, ended_utc=datetime.now(timezone.utc).isoformat(),
        root=str(root), runtime_sha256=runtime, environment=environment,
        runner_sha256=sha(Path(__file__)), instrumentation_sha256=sha(ROOT / 'tools/y8_fps_baseline.py'),
        fake_sdk_sha256=sha(ROOT / 'tools/fixtures/fake-y8-sdk.js'), runs=runs,
        evidence_sha256={v + '.json': sha(out / (v + '.json')) for v in VARIANTS},
        limitations='Single 30-second sample per variant, sequential shared software host, no native hardware. '
                    'Ablations remove visible effects; no equal-quality gain, shipping fix, causal GPU attribution, '
                    'or acceptance-gate PASS. Fixed seed does not equalize frame-dependent world state.'))


def inspect(raw):
    from y8_performance_gate import metrics
    assert not raw['errors'], raw['errors']
    assert raw['dimensions'] == [1560, 780]
    assert all(f['canvas'] == [1560, 780] for f in raw['measure']['frames'])
    assert any(line.startswith('FAKE_SDK ') for line in raw['network'])
    assert all(line.startswith(('LOCAL ', 'FAKE_SDK ', 'BLOCKED ')) for line in raw['network'])
    variant = raw['variant']
    for layer in ('ambient', 'player'):
        disabled = variant in ('without_' + layer + '_glow', 'without_both_glows')
        assert (raw['disabledCalls'][layer] > 0) == disabled, (variant, layer)
    return dict(variant=variant, metrics=metrics(raw['measure']['frames']),
                disabled_calls=raw['disabledCalls'], canvas=raw['dimensions'], errors=0)


def audit(root, out):
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['runner_sha256'] == sha(Path(__file__))
    assert manifest['instrumentation_sha256'] == sha(ROOT / 'tools/y8_fps_baseline.py')
    assert manifest['fake_sdk_sha256'] == sha(ROOT / 'tools/fixtures/fake-y8-sdk.js')
    assert manifest['runtime_sha256'] == {
        str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    for variant, recorded in zip(VARIANTS, manifest['runs'], strict=True):
        name = variant + '.json'
        assert sha(out / name) == manifest['evidence_sha256'][name]
        result = inspect(json.loads((out / name).read_text()))
        assert result == recorded
        print('PASS recomputed', variant, json.dumps(result))
    print('PASS runtime/evidence/tool hashes; 4 offline 30-second DPR2 diagnostics; no shipping-fix claim')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'audit'))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    (capture if args.action == 'capture' else audit)(args.root.resolve(), args.out.resolve())
