"""Record whether an immutable control already has an opaque main canvas.

This diagnostic never changes runtime files or claims a performance improvement.
All nonlocal requests are blocked except the TASK-307 SDK fixture.
"""
import argparse
from contextlib import ExitStack
from functools import partial
from http.server import ThreadingHTTPServer
import importlib.metadata
from pathlib import Path
import platform
from threading import Thread

from playwright.sync_api import sync_playwright
from playgama_render_compare import FIXTURE, STATE, hashes
from playgama_firefox_perf import SDK, QuietHandler, SEED_SCRIPT, SEED, sha, write
from render_snapshot import CLOCK_SCRIPT, boot_frozen

CONTEXT_PROBE = '''(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    const contexts = new Map();
    HTMLCanvasElement.prototype.getContext = function(...args) {
        const result = original.apply(this, args);
        if (args[0] === '2d' && result && !contexts.has(this))
            contexts.set(this, {context:result, requested:args[1] || {}});
        return result;
    };
    window.contextReceipt = () => Array.from(contexts, ([c, r], index) => ({
        index, main:c === canvas, id:c.id, className:c.className,
        requested:r.requested, actual:r.context.getContextAttributes(),
        backing:[c.width,c.height], smoothing:r.context.imageSmoothingEnabled,
        composite:r.context.globalCompositeOperation,
        transform:Array.from(r.context.getTransform().toFloat64Array())
    }));
})()'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.control.resolve(), args.out
    before = hashes(root)
    records, errors, network = {}, [], []
    environment = {'os': platform.platform(), 'playwright': importlib.metadata.version('playwright'),
                   'native_android': 'UNVERIFIED', 'browsers': {},
                   'kind': 'headless desktop; touch viewport emulation; deterministic smoke fixtures'}
    with ExitStack() as stack:
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        stack.callback(server.server_close)
        Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.shutdown)
        origin = f'http://127.0.0.1:{server.server_port}'
        def route_request(route):
            url = route.request.url
            action = 'LOCAL' if url.startswith(origin+'/') else 'SDK_STUB' if url == SDK else 'BLOCKED'
            network.append({'url': url, 'action': action})
            if action == 'LOCAL': route.continue_()
            elif action == 'SDK_STUB': route.fulfill(content_type='application/javascript', body=FIXTURE)
            else: route.abort()
        pw = stack.enter_context(sync_playwright())
        try:
            for engine in ('firefox', 'chromium'):
                kind = getattr(pw, engine)
                browser = kind.launch(headless=True)
                try:
                    environment['browsers'][engine] = {'version': browser.version,
                        'executable_sha256': sha(Path(kind.executable_path).read_bytes())}
                    context = browser.new_context(viewport={'width':844,'height':390},
                        device_scale_factor=2, has_touch=True, service_workers='block')
                    context.route('**/*', route_request)
                    for script in (SEED_SCRIPT % SEED, CLOCK_SCRIPT, CONTEXT_PROBE):
                        context.add_init_script(script)
                    page = context.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
                    page.goto(origin+'/index.html')
                    boot_frozen(page)
                    assert page.evaluate('bootComplete && document.getElementById("loading").hidden')
                    print(f'PASS {engine} startup', flush=True)
                    graphics = page.evaluate('''() => {const c=document.createElement('canvas');
                        const g=c.getContext('webgl'); if(!g)return {webgl:false};
                        const d=g.getExtension('WEBGL_debug_renderer_info');
                        return {vendor:g.getParameter(g.VENDOR),renderer:g.getParameter(g.RENDERER),
                          unmasked:d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):null};}''')
                    environment['browsers'][engine]['graphics'] = graphics
                    records[engine] = []
                    steps = [('menu','menu.draw()'),
                        ('classic',"startGame('classic'); gameLoop(__snap.now)"),
                        ('bad',"startGame('bad'); gameLoop(__snap.now)"),
                        ('pause','menu.gamePaused=true; gameLoop(__snap.now)'),
                        ('death','menu.gamePaused=false; continueOffer.visible=true; gameLoop(__snap.now)'),
                        ('touch-portrait','onViewportResize()'),
                        ('touch-landscape','onViewportResize(); gameLoop(__snap.now)'),
                        ('resize','onViewportResize(); gameLoop(__snap.now)')]
                    for checkpoint, script in steps:
                        if checkpoint.startswith('touch-') or checkpoint == 'resize':
                            w,h = (390,844) if checkpoint=='touch-portrait' else (900,390) if checkpoint=='resize' else (844,390)
                            page.set_viewport_size({'width':w,'height':h})
                        page.evaluate(script)
                        state = page.evaluate(STATE)
                        if checkpoint=='menu': assert state['menu']
                        if checkpoint in ('classic','bad'): assert state['mode']==checkpoint and not state['menu']
                        if checkpoint=='pause': assert state['pause']
                        if checkpoint=='death': assert state['death']
                        if checkpoint.startswith('touch-'): assert state['portrait']==(checkpoint=='touch-portrait')
                        attrs = page.evaluate('contextReceipt()')
                        main = [a for a in attrs if a['main']]
                        assert len(main)==1 and main[0]['actual']['alpha'] is False
                        assert any(a['actual']['alpha'] for a in attrs if not a['main'])
                        records[engine].append({'checkpoint':checkpoint,'state':state,'contexts':attrs})
                        print(f'PASS {engine} {checkpoint} main alpha=false; transparent effect contexts retained', flush=True)
                    context.close()
                finally: browser.close()
        finally:
            write(out/'context-attributes.json', records)
            write(out/'environment.json', environment)
            write(out/'network.json', network)
            write(out/'errors.json', errors)
    assert not errors, errors
    assert hashes(root)==before, 'control modified'
    print('PASS no page exceptions; unchanged control already opaque; no distinct candidate', flush=True)


if __name__ == '__main__':
    main()
