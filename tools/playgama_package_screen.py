"""One bounded TASK-313 source/package Chill ABBA diagnostic, not acceptance."""
import argparse
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import time
from threading import Thread

from playwright.sync_api import sync_playwright
from playgama_render_compare import TIMING_PROBE, FIXTURE, STATE
from playgama_firefox_perf import SDK, SEED, INPUT, LAYOUT, SEED_SCRIPT, sha, write, QuietHandler, utc
from playgama_fps_gate import active_metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    root = Path('artifacts/TASK-313')
    revision = 'f94d6e29f78644ee23215108f0d7ae11e5922b06'
    source = out/'source'
    source.mkdir()
    inventory = json.loads((root/'release/inventory.json').read_text())
    assert len(inventory) == 38
    for member in inventory:
        data = subprocess.check_output(['git', 'show', revision+':'+member['path']])
        assert sha(data) == member['sha256']
        path = source/member['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    package = (root/'firefox-fps/runtime').resolve()
    expected = json.loads((root/'package-tests/suite.json').read_text())
    archive = root/'release/grapnelninja-2026-10-12-fps-review.zip'
    assert sha(archive.read_bytes()) == expected['zip_sha256']
    members = {p.name: sha(p.read_bytes()) for p in package.iterdir()}
    assert members == expected['extracted_members']
    identities = {'A': {m['path']: m['sha256'] for m in inventory}, 'B': members}
    tools = {p.name: sha(p.read_bytes()) for p in Path('tools').glob('*.py')}
    write(out/'identity.json', dict(revision=revision, source_members=identities,
          zip_sha256=expected['zip_sha256'], tools=tools, fixture_sha256=sha(FIXTURE.encode()),
          probe_sha256=sha(TIMING_PROBE.encode()), seed=SEED, input_policy=INPUT,
          cpu_throttling=False, preferences={}, original_quality_and_effects=True))
    print('PASS immutable source members=38 and exact packaged members=2', flush=True)
    observations = []
    def observe(label):
        observations.append(dict(utc=utc(), label=label, load=Path('/proc/loadavg').read_text(),
            processes=subprocess.check_output(['ps', '-eo', 'pid,ppid,stat,pcpu,comm,args'], text=True)))
        write(out/'concurrency.json', observations)
    runs, network, errors = [], [], []
    started = time.monotonic()
    with ExitStack() as stack:
        origins = {}
        for arm, directory in [('A', source), ('B', package)]:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(directory)))
            stack.callback(server.server_close)
            Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)
            origins[arm] = f'http://127.0.0.1:{server.server_port}'
        pw = stack.enter_context(sync_playwright())
        observe('before browser')
        browser = pw.firefox.launch(headless=True)
        stack.callback(browser.close)
        write(out/'environment.json', dict(os=platform.platform(), browser_version=browser.version,
            executable=pw.firefox.executable_path, executable_sha256=sha(Path(pw.firefox.executable_path).read_bytes()),
            playwright=importlib.metadata.version('playwright'), headless=True, native_android='UNVERIFIED'))
        for i, arm in enumerate('ABBA', 1):
            arm_start = time.monotonic()
            observe(f'{i}-{arm} start')
            origin = origins[arm]
            def route(r):
                url = r.request.url
                action = 'LOCAL' if url.startswith(origin+'/') else 'SDK_STUB' if url == SDK else 'BLOCKED'
                network.append(dict(arm=arm, run=i, url=url, action=action))
                if action == 'LOCAL': r.continue_()
                elif action == 'SDK_STUB': r.fulfill(content_type='application/javascript', body=FIXTURE)
                else: r.abort()
            context = browser.new_context(viewport={'width':844, 'height':390}, device_scale_factor=2,
                                          has_touch=True, locale='en-US', service_workers='block')
            try:
                context.route('**/*', route)
                context.add_init_script(SEED_SCRIPT % SEED)
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(origin+'/index.html')
                page.wait_for_function('bootComplete && document.getElementById("loading").hidden')
                layout = page.evaluate(LAYOUT)
                assert layout['viewport'] == [844,390] and layout['dpr'] == 2 and layout['backing'] == [1688,780]
                page.evaluate(TIMING_PROBE, dict(mode='bad', inputs=INPUT, seed=SEED))
                last_observe = time.monotonic()
                while True:
                    page.wait_for_timeout(200)
                    raw = page.evaluate('perfReceipt')
                    raw.update(layout=layout, source_sha256=identities[arm], seed=SEED,
                               input_policy=INPUT, state=page.evaluate(STATE))
                    write(out/f'{i}-{arm}-raw.json', raw)
                    if time.monotonic()-last_observe >= 5:
                        observe(f'{i}-{arm} active')
                        last_observe = time.monotonic()
                    if time.monotonic()-arm_start > 120 or time.monotonic()-started > 590:
                        raise TimeoutError('bounded screen budget')
                    try: metrics = active_metrics(raw)
                    except ValueError: continue
                    break
                runs.append(dict(arm=arm, run=i, raw=f'{i}-{arm}-raw.json',
                                 duration_seconds=time.monotonic()-arm_start, **metrics))
                print(f"{i}-{arm} FPS={metrics['average_fps']:.9f} p95_ms={metrics['p95_ms']:.9f} gate={metrics['gate']}", flush=True)
            finally:
                context.close()
                observe(f'{i}-{arm} end')
                write(out/'results.json', dict(runs=runs, network=network, errors=errors))
        assert not errors, errors
        for arm, directory in [('A', source), ('B', package)]:
            assert identities[arm] == {str(p.relative_to(directory)):sha(p.read_bytes()) for p in directory.rglob('*') if p.is_file()}
    print('PASS diagnostic capture ABBA complete; not release acceptance', flush=True)


if __name__ == '__main__':
    main()
