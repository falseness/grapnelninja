"""Observe real-input bad-mode gameplay served on 127.0.0.1:8018.

Capture >=30 seconds and >=3 gameplay generation events (up to --max-seconds).
Generation/start/restart wrappers only observe; no physics or spawns are injected.
Requires Python Playwright and Chromium. Evidence stays in --output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from playwright.sync_api import sync_playwright

PROBE = r'''() => {
    window.probe = {spawns:[], runs:[], restarts:0, start:performance.now(), initializing:false};
    const begin = (fn, restart) => function(...args) {
        if (restart) probe.restarts++;
        probe.runs.push({id:probe.runs.length, restart, elapsed:(performance.now()-probe.start)/1000});
        probe.initializing = true;
        try { return fn.apply(this,args); }
        finally { probe.initializing = false; }
    };
    startGame = begin(startGame, false);
    reStart = begin(reStart, true);
    const generate = Floor.prototype.generateElements;
    Floor.prototype.generateElements = function(...args) {
        if (version !== 'bad' || this.primaryElementsQuantity !== 1)
            return generate.apply(this,args);
        const id = this.nextGenerationGroupId;
        const preceding = this.elements.length ? this.getGenerationGroup(this.elements.length-1) : null;
        const predecessorRight = preceding ? preceding.rightPointX : null;
        const factory = elementsFactory.create;
        let template;
        elementsFactory.create = function(...args) {
            template = args[2]; return factory.apply(this,args);
        };
        let result;
        try { result = generate.apply(this,args); }
        finally { elementsFactory.create = factory; }
        const group = this.elements.filter(e => e.generationGroupId === id);
        const left = Math.min(...group.map(e => e.getLeftPointX()));
        const right = Math.max(...group.map(e => e.getRightPointX()));
        const visibleRight = -screen.x + width/scale.bad;
        const pixelGap = predecessorRight === null ? null : (left-predecessorRight)*scale.bad;
        const gapPassed = id === 0 || (pixelGap !== null && Math.abs(pixelGap-.1*width) <= 1e-6);
        const offscreenPassed = probe.initializing || left > visibleRight;
        probe.spawns.push({elapsed:(performance.now()-probe.start)/1000,run:probe.runs.length-1,
            initializing:probe.initializing,template,id,left,right,predecessorRight,
            cameraX:screen.x,visibleRight,scale:scale.bad,canvasWidth:width,canvasHeight:height,
            pixelLeft:(left+screen.x)*scale.bad,pixelGap,expectedPixelGap:.1*width,
            gapPassed,offscreenPassed,passed:gapPassed && offscreenPassed});
        return result;
    };
    startGame('bad');
}'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/TASK-018')
    parser.add_argument('--max-seconds', type=int, default=180)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()
    hashes = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
              for name in names if name.endswith(('.js', '.html', '.py'))}
    with sync_playwright() as p:
        browser = (p.chromium.connect_over_cdp(os.environ['BROWSER_CDP_URL'])
                   if os.environ.get('BROWSER_CDP_URL') else
                   p.chromium.launch(headless=True, args=['--no-sandbox']))
        page = browser.new_page(viewport={'width': 772, 'height': 630})
        console, errors, samples = [], [], []
        page.on('console', lambda m: console.append({'type': m.type, 'text': m.text}))
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:8018/')
        page.evaluate(PROBE)
        start = time.monotonic()
        target = 0
        while True:
            page.wait_for_timeout(max(0, (start + target - time.monotonic()) * 1000))
            result = page.evaluate('probe')
            events = [e for e in result['spawns'] if not e['initializing']]
            if target % 3 == 0:
                state = page.evaluate('''() => ({elapsed:(performance.now()-probe.start)/1000,
                    run:probe.runs.length-1, playerX:ninja.x,playerY:ninja.y,cameraX:screen.x,
                    scale:scale.bad,objects:floors[1].elements.map(e=>({group:e.generationGroupId,
                    pixelLeft:(e.getLeftPointX()+screen.x)*scale.bad,
                    pixelRight:(e.getRightPointX()+screen.x)*scale.bad}))})''')
                state['screenshot'] = f'current-{target:03d}.png'
                page.screenshot(path=str(out / state['screenshot']))
                samples.append(state)
                print(f"Captured {state['elapsed']:.2f}s; run={state['run']}; gameplay events={len(events)}", flush=True)
            if any(not e['passed'] for e in result['spawns']):
                break
            if time.monotonic()-start >= 30 and len(events) >= 3:
                break
            if time.monotonic()-start >= args.max_seconds:
                break
            page.mouse.up()
            # Aim nearly upward periodically to climb walls, then pull forward.
            # Read player position only; all movement still comes from mouse input.
            player_x = page.evaluate('(ninja.x+screen.x)*scale.bad')
            aim_x = min(700, max(20, player_x + 20)) if target % 8 < 4 else 700
            page.mouse.move(aim_x, 58)
            page.mouse.down()
            target += 1
        result.update(samples=samples, wallSeconds=time.monotonic()-start,
                      gameplayEventCount=len(events), sourceHashes=hashes,
                      sourceCommit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                      method='Real mouse throws once per second: four upward throws (player pixel X+20,58), then four forward (700,58); observational wrappers only.')
        console_errors = [m['text'] for m in console if m['type'] == 'error']
        result['passed'] = (result['wallSeconds'] >= 30 and len(events) >= 3 and
                            all(e['passed'] for e in result['spawns']) and not errors and not console_errors)
        (out / 'run.json').write_text(json.dumps(result, indent=2) + '\n')
        (out / 'console.log').write_text(''.join(f"{m['type']}: {m['text']}\n" for m in console))
        (out / 'console-errors.log').write_text(''.join(e + '\n' for e in console_errors))
        (out / 'page-errors.log').write_text(''.join(e + '\n' for e in errors))
        for event in events:
            print(('PASS' if event['passed'] else 'FAIL') + ' gameplay spawn ' + json.dumps(event))
        print(('PASS' if result['passed'] else 'FAIL') +
              f" live capture: seconds={result['wallSeconds']:.3f}; gameplay events={len(events)}; restarts={result['restarts']}")
        browser.close()
        return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
