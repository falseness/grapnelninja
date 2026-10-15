"""Shared constants for browser tests of the SDK-free game.

The game loads no platform SDK (platform.js is the local adapter), so a
test that routes the Playgama Bridge URL never sees a request for it: SDK is
the URL those routes name and FAKE is the (empty) script they would serve.
"""
from browser_test_support import SDK_URL

SDK = SDK_URL
FAKE = ''


# The android_runner probe (moved from the removed playgama_firefox_perf.py).
# The local adapter defines no hostPaused, so the probe reads it guarded.
# Each row brackets the actual gameLoop callback. Its RAF timestamp, rather than
# a timer or a sampled FPS counter, is the basis of every reported interval.
PROBE = r'''async ({mode, inputs, seed}) => {
    const state = () => ({pause: menu.gamePaused,
        death: continueOffer.visible, ad: adOpen || interstitialPending,
        host: typeof hostPaused !== 'undefined' && hostPaused, portrait: isViewRotated(), hidden: document.hidden});
    const active = s => !Object.values(s).some(Boolean);
    const p = window.perfReceipt = {frames: [], inputs: [], transitions: [],
        activeMs: 0, done: false, accepted_input_ms: null, first_active_frame_ms: null};
    let previous = null, nextInput = 0, lastRestart = -Infinity, lastState = '';
    function dispatch(type, x, y) {
        document.dispatchEvent(new MouseEvent(type, {bubbles:true, clientX:x, clientY:y}));
    }
    function button(b, s = 1) {
        const r = canvas.getBoundingClientRect();
        const x = r.x + (b.x + b.width/2) * s * r.width/width;
        const y = r.y + (b.y + b.height/2) * s * r.height/height;
        dispatch('mousedown', x, y); dispatch('mouseup', x, y);
    }
    const frame = () => new Promise(requestAnimationFrame);
    async function until(test) {
        for (let i = 0; i < 600 && !test(); i++) await frame();
        if (!test()) throw new Error('START timed out in '+version);
    }
    // Reset immediately before the start input so boot-run and pause frame
    // counts do not consume a different portion of the seeded random sequence.
    function seedRandom() {
        let a = seed >>> 0;
        Math.random = () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
            t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    }
    // Explicitly select the requested benchmark mode from the pause selector.
    await until(() => bootComplete && runInProgress && !unTouch);
    if (version !== mode) {
        if (!menu.gamePaused) button(menu.button.background, scale[version]);
        await until(() => menu.gamePaused && !unTouch);
        seedRandom();
        button(menu.modeButtons[['grapple_over','bad','classic'].indexOf(mode)].background);
        // The switch leaves the paused run first (leaveFinishedRun)
        await until(() => version === mode && runInProgress && !menu.gamePaused);
        p.accepted_input_ms = performance.now();
    } else {
        await until(() => !menu.gamePaused && !continueOffer.visible && !grapnel.throwed);
        seedRandom();
        const r = canvas.getBoundingClientRect();
        dispatch('mousedown', r.x + r.width*.7, r.y + r.height*.3);
        if (grapnel.throwed) p.accepted_input_ms = performance.now();
        dispatch('mouseup', r.x + r.width*.7, r.y + r.height*.3);
    }
    if (p.accepted_input_ms === null) throw new Error('START input not accepted in '+version);
    // Measure from the started run only; the boot run before it is not counted.
    const original = gameLoop;
    gameLoop = function(t) {
        const before = state();
        if (previous && active(previous.after) && active(before))
            p.activeMs += t - previous.t;
        const signature = JSON.stringify(before);
        if (signature !== lastState) {
            p.transitions.push({t, state: before}); lastState = signature;
        }
        if (active(before)) {
            if (p.first_active_frame_ms === null) p.first_active_frame_ms = t;
            while (nextInput < inputs.length && inputs[nextInput].at_active_ms <= p.activeMs) {
                const input = inputs[nextInput++];
                dispatch(input.type, input.x, input.y);
                p.inputs.push({...input, actual_active_ms:p.activeMs, t});
            }
        } else if (before.death && !before.ad && t - lastRestart >= 500) {
            p.transitions.push({t, action:'restart-button'});
            button(continueOffer.restartButton.background); lastRestart = t;
        }
        original(t);
        const row = {t, before, after:state(), activeMs:p.activeMs};
        p.frames.push(row); previous = row;
        if (p.activeMs >= 35000) p.done = true;
    };
}'''
