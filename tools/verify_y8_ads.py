"""Offline Y8 ad callback/continue evidence against an exact local ZIP.

Scripted SDK fixtures only; no real SDK or production ad traffic is exercised.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import zipfile

from browser_test_support import start_browser_test, wait_for_boot
from game_harness import canvas_to_viewport
from verify_y8_release import SDK, FAKE
from verify_y8_mobile_lifecycle import INIT

STATE = '''() => ({adOpen, pending: continueOffer.adPending, offer: continueOffer.visible,
    paused: menu.gamePaused, menu: menu.visible, score: scoreText.count[version],
    rewards: __rewards, physics: __physics, events: __events, results: __results})'''
KINDS = ['viewed', 'dismissed', 'noAdPreloaded', 'frequencyCapped', 'notReady',
         'reject', 'throw', 'timeout', 'playingTimeout', 'late', 'unverifiedViewed', 'missing']


def click(page, expr):
    point = page.evaluate('() => { const b = ' + expr + '; return {x:b.x+b.width/2,y:b.y+b.height/2} }')
    if expr == 'menu.button.background':
        scale = page.evaluate('scale[version]')
        point = {k: v * scale for k, v in point.items()}
    point = canvas_to_viewport(page, point['x'], point['y'])
    page.mouse.click(point['x'], point['y'])


def run(archive, out):
    rows, traces = [], []
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        url, browser = start_browser_test(Path(tmp), stack.callback)
        for mode in ['classic', 'bad']:
            for kind in KINDS:
                context = browser.new_context(viewport={'width': 1280, 'height': 720}, service_workers='block')
                try:
                    if kind != 'missing':
                        context.route(SDK, lambda r: r.fulfill(content_type='text/javascript', body=FAKE))
                    context.add_init_script(INIT)
                    page = context.new_page()
                    page.set_default_timeout(10000)
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(url)
                    wait_for_boot(page)
                    page.evaluate('''kind => {
                        window.__events=[]; window.__results=[]; window.__rewards=0; window.__physics=0;
                        // Keep the test ninja stationary between real physics steps so a
                        // second unrelated death cannot race the recovery-button click.
                        const p=physics; physics=function(){
                            __physics++; const x=ninja.x,y=ninja.y;
                            const result=p.apply(this,arguments);
                            if(!continueOffer.visible){ninja.x=x;ninja.y=y;ninja.speedX=0;ninja.speedY=0}
                            return result;
                        };
                        const c=continueRun; continueRun=function(){__rewards++; return c.apply(this,arguments)};
                        PLATFORM.rewardTimeoutMs=4000; PLATFORM.rewardPlayingTimeoutMs=4000;
                        PLATFORM.onAdState(s=>__events.push({event:s,t:performance.now(),adOpen}));
                        const r=PLATFORM.requestRewarded;
                        PLATFORM.requestRewarded=function(){return r.apply(this,arguments).then(x=>{__results.push(x);return x})};
                        if(window.y8) y8.sdk().showAd=opts=>{
                            __events.push({event:'showAd',t:performance.now()});
                            window.__cb={};
                            for(const [k,v] of Object.entries(opts)) if(typeof v==='function')
                                __cb[k]=(...a)=>{__events.push({event:k,t:performance.now(),args:a.map(x=>typeof x==='function'?'function':x)});return v(...a)};
                            if(kind==='throw') throw Error('fixture throw');
                            if(kind==='reject') return Promise.reject(Error('fixture reject'));
                            return Promise.resolve().then(()=>__events.push({event:'showAd promise resolved',t:performance.now()}));
                        };
                    }''', kind)
                    click(page, 'menu.' + ('classicVersionButton' if mode == 'classic' else 'badVersionButton') + '.background')
                    page.wait_for_function('!menu.visible')
                    page.evaluate('scoreText.count[version]=9; onLethalDeath()')
                    if kind == 'missing':
                        page.wait_for_function('!continueOffer.visible && scoreText.count[version]===0')
                        result = page.evaluate('PLATFORM.requestRewarded()')
                        assert result['reason'] == 'unsupported'
                        before = page.evaluate(STATE)
                        terminal = before
                    else:
                        page.wait_for_function('continueOffer.visible && !unTouch')
                        click(page, 'continueOffer.continueButton.background')
                        if kind not in ['throw', 'reject']:
                            page.wait_for_function('__cb && __events.some(e=>e.event==="showAd promise resolved")')
                            assert page.evaluate('continueOffer.adPending && __rewards===0')
                            busy = page.evaluate('PLATFORM.requestRewarded()')
                            assert busy['reason'] == 'busy'
                            page.evaluate('watchAdToContinue()')
                            assert page.evaluate('__events.filter(e=>e.event==="showAd").length') == 1
                            before = page.evaluate(STATE)
                            page.wait_for_timeout(60)
                            assert page.evaluate('__physics') == before['physics']
                            if kind in ['viewed', 'dismissed', 'playingTimeout']:
                                page.evaluate('__cb.beforeReward(()=>{}); __cb.beforeAd()')
                                assert page.evaluate('adOpen')
                            if kind == 'viewed':
                                page.evaluate('__cb.adViewed()')
                                assert page.evaluate('__rewards===0 && continueOffer.adPending')
                                page.evaluate('__cb.adBreakDone({breakStatus:"viewed"}); __cb.adBreakDone({breakStatus:"viewed"})')
                            elif kind == 'dismissed':
                                page.evaluate('__cb.adDismissed(); __cb.adBreakDone({breakStatus:"dismissed"})')
                            elif kind in ['noAdPreloaded', 'frequencyCapped', 'notReady', 'unverifiedViewed']:
                                page.evaluate('s=>__cb.adBreakDone({breakStatus:s})', 'viewed' if kind == 'unverifiedViewed' else kind)
                        else:
                            before = page.evaluate(STATE)
                        page.wait_for_function('!continueOffer.adPending && !adOpen')
                        terminal = page.evaluate(STATE)
                        assert terminal['rewards'] == (1 if kind == 'viewed' else 0)
                        # All terminal paths ignore late callbacks, including a late beforeAd.
                        page.evaluate('__cb.beforeAd(); __cb.adViewed(); __cb.adBreakDone({breakStatus:"viewed"})')
                        page.wait_for_timeout(40)
                        assert page.evaluate('__rewards') == terminal['rewards']
                        assert not page.evaluate('adOpen')
                        events = page.evaluate('__events')
                        assert sum(e['event'] == 'closed' for e in events) == 1
                        assert sum(e['event'] == 'opened' for e in events) == (1 if kind in ['viewed','dismissed','playingTimeout'] else 0)
                        if kind != 'viewed':
                            assert terminal['offer']
                            page.wait_for_function('!unTouch')
                            click(page, 'continueOffer.restartButton.background')
                            page.wait_for_function('!continueOffer.visible && scoreText.count[version]===0')
                    n = page.evaluate('__physics')
                    page.wait_for_function('n=>__physics>n', arg=n)
                    recovered = page.evaluate(STATE)
                    page.wait_for_function('!unTouch')
                    click(page, 'menu.button.background')
                    page.wait_for_function('menu.gamePaused && menu.resume.clickable && menu.backToMenu.clickable')
                    paused = page.evaluate(STATE)
                    audio = page.evaluate('__lc.audio')
                    assert sum(audio.values()) == 0
                    assert page.evaluate('document.querySelectorAll("audio,video").length') == 0
                    assert not errors, errors
                    row = dict(mode=mode, flow=kind, verdict='PASS', before=before, terminal=terminal,
                               reward_count=terminal['rewards'], recovered=recovered, pause_menu=paused, recovery='PASS physics resumes; restart/menu usable',
                               audio=dict(status='N/A: silent game; no audio subsystem', probes=audio),
                               bounded_wait_ms=10000, watchdog_ms=4000, page_errors=errors)
                    rows.append(row)
                    traces.append(dict(mode=mode, flow=kind, events=page.evaluate('__events'), results=page.evaluate('__results')))
                    print(f'PASS fixture {mode} {kind} reward_count={row["reward_count"]} recovery pause/input audio=N/A', flush=True)
                finally:
                    context.close()
    common = dict(test_kind='OFFLINE SCRIPTED SDK FIXTURE; not actual SDK behavior',
                  actual_sdk='NOT RUN: no controlled real ad transport available; hosted/native checks remain owner-only',
                  production_traffic=False, archive=str(archive))
    (out/'ad-outcomes.json').write_text(json.dumps(dict(**common, verdict='PASS', flows=rows), indent=2)+'\n')
    (out/'callback-traces.json').write_text(json.dumps(dict(**common, verdict='PASS', traces=traces), indent=2)+'\n')
    print(f'OVERALL PASS {len(rows)} fixture flows; actual SDK NOT RUN; production traffic=0')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--archive', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    run(args.archive, args.out)
