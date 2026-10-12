// Owner-operated offline benchmark overlay for Grapnel Ninja (TASK-283).
//
// Loaded by the served game/index.html in place of the public Y8 SDK <script>
// tag (the only change to the committed runtime). It never contacts anything
// but the local serving machine, never pins render density, never replaces a
// drawing or physics function and only wraps gameLoop/reStart while a run is
// recording. Primary FPS is timed from the requestAnimationFrame timestamp
// handed to gameLoop, exactly like tools/y8_feature_cost.py: one wrapper, no
// tracing, no readback, no per-call wrappers.
(function () {
    'use strict'
    const SCHEMA = 'grapnelninja-bench-result/1'
    const INACTIVE_SAMPLES_PER_STRETCH = 50  // + the stretch's last sample; the compact stretch itself is always recorded
    const DEFAULTS = {seed: '4', replay: 'auto', input: 'auto', warmup_ms: 5000, run_ms: 60000, reps: 3,
                      autosend: '1', autostart: '0', mode: 'bad'}
    const params = new URLSearchParams(location.search)
    const get = (k, d) => params.has(k) ? params.get(k) : d
    const settings = {
        seed: get('seed', DEFAULTS.seed),
        replay_kind: get('replay', DEFAULTS.replay) === 'manual' ? 'manual' : 'auto',
        input_kind: get('input', DEFAULTS.input),
        warmup_ms: Number(get('warmup_ms', DEFAULTS.warmup_ms)),
        run_ms: Number(get('run_ms', DEFAULTS.run_ms)),
        repetitions_target: Number(get('reps', DEFAULTS.reps)),
        autosend: get('autosend', DEFAULTS.autosend) !== '0',
        autostart: get('autostart', DEFAULTS.autostart) === '1'
    }
    settings.protocol = (settings.warmup_ms === 5000 && settings.run_ms === 60000 && settings.repetitions_target === 3)
        ? 'standard' : 'custom'
    const seedValue = settings.seed === 'none' ? null : (Number(settings.seed) >>> 0)

    // ------------------------------------------------------------ PRNG --
    // Same generator as the TASK-271 harness SEED_SCRIPT (mulberry32).
    function mulberry32(a) {
        a = a >>> 0
        return function () {
            a = (a + 0x6D2B79F5) >>> 0
            let t = a
            t = Math.imul(t ^ (t >>> 15), t | 1)
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296
        }
    }
    const nativeRandom = Math.random
    function installSeed() {
        if (seedValue === null) { Math.random = nativeRandom; return 'none (native Math.random)' }
        Math.random = mulberry32(seedValue)
        return 'mulberry32(' + seedValue + ')'
    }
    const seedInstalledAtLoad = installSeed()

    // Bounded seeded grapnel throws as fractions of the stage, mirrored by
    // benchtool.replay_fractions (Python) so the validator can re-derive and
    // seal the exact sequence. x in [0.40, 0.85] / y in [0.15, 0.60] of the view
    // avoids the HUD menu button (top-right) and the left edge.
    function replayFractions(seed, totalMs) {
        const rnd = mulberry32((seed * 1000003 + totalMs) >>> 0)
        const randint = (a, b) => a + Math.floor(rnd() * (b - a + 1))
        const uniform = (a, b) => a + rnd() * (b - a)
        const r4 = x => Math.floor(x * 10000 + 0.5) / 10000
        const events = []
        let t = 400
        for (;;) {
            const hold = randint(250, 900)
            if (t + hold > totalMs) break
            const fx = r4(uniform(0.40, 0.85)), fy = r4(uniform(0.15, 0.60))
            events.push({t_ms: t, type: 'start', fx, fy})
            events.push({t_ms: t + hold, type: 'end', fx, fy})
            t += hold + randint(80, 450)
        }
        return events
    }

    // ---------------------------------------------------------- SHA-256 --
    // Pure JS: crypto.subtle is unavailable on plain http:// LAN origins.
    function sha256Hex(str) {
        const bytes = new TextEncoder().encode(str)
        const K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]
        const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
        const l = bytes.length
        const padded = new Uint8Array(((l + 9 + 63) >> 6) << 6)
        padded.set(bytes)
        padded[l] = 0x80
        const dv = new DataView(padded.buffer)
        dv.setUint32(padded.length - 4, (l * 8) >>> 0)
        dv.setUint32(padded.length - 8, Math.floor(l * 8 / 4294967296))
        const w = new Uint32Array(64)
        const rotr = (x, n) => (x >>> n) | (x << (32 - n))
        for (let i = 0; i < padded.length; i += 64) {
            for (let j = 0; j < 16; j++) w[j] = dv.getUint32(i + j * 4)
            for (let j = 16; j < 64; j++) {
                const s0 = rotr(w[j - 15], 7) ^ rotr(w[j - 15], 18) ^ (w[j - 15] >>> 3)
                const s1 = rotr(w[j - 2], 17) ^ rotr(w[j - 2], 19) ^ (w[j - 2] >>> 10)
                w[j] = (w[j - 16] + s0 + w[j - 7] + s1) >>> 0
            }
            let [a, b, c, d, e, f, g, h] = H
            for (let j = 0; j < 64; j++) {
                const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
                const ch = (e & f) ^ (~e & g)
                const t1 = (h + S1 + ch + K[j] + w[j]) >>> 0
                const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
                const maj = (a & b) ^ (a & c) ^ (b & c)
                const t2 = (S0 + maj) >>> 0
                h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0
            }
            H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0
            H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0
        }
        return H.map(x => x.toString(16).padStart(8, '0')).join('')
    }
    // Canonical JSON (sorted keys, no spaces) == Python json.dumps(sort_keys=True, separators=(',', ':'))
    function canonical(v) {
        if (v === null || typeof v !== 'object') return JSON.stringify(v)
        if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']'
        return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}'
    }

    // ---------------------------------------------------------- metrics --
    // frames: [[t, dt|null], ...]; dt null = first frame after an inactive gap.
    function percentile(ordered, p) {
        return ordered[Math.min(ordered.length - 1, Math.max(0, Math.ceil(ordered.length * p / 100) - 1))]
    }
    function metrics(frames) {
        const dts = frames.slice(1).map(f => f[1]).filter(dt => dt !== null)
        if (!dts.length) return null
        const ordered = dts.slice().sort((a, b) => a - b)
        const active = dts.reduce((a, b) => a + b, 0)
        return {frames: frames.length, intervals: dts.length,
                gaps: frames.slice(1).filter(f => f[1] === null).length,
                active_ms: active, wall_ms: frames[frames.length - 1][0] - frames[0][0],
                average_fps: dts.length * 1000 / active,
                frame_ms: {p50: percentile(ordered, 50), p95: percentile(ordered, 95),
                           p99: percentile(ordered, 99), max: ordered[ordered.length - 1]}}
    }
    // Rolling windows of >= windowMs contiguous active intervals, one per start frame.
    function rollingWindows(frames, windowMs) {
        const out = []
        for (let i = 0; i < frames.length; i++) {
            let acc = 0, n = 0, j = i + 1
            for (; j < frames.length; j++) {
                if (frames[j][1] === null) break
                acc += frames[j][1]; n++
                if (acc >= windowMs) break
            }
            if (acc >= windowMs) out.push({start: i, end: j, intervals: n, active_ms: acc, fps: n * 1000 / acc})
        }
        return out
    }
    // Measured region: starts at the first frame whose cumulative active time
    // reaches warmupMs (its own interval belongs to the warmup, so dt -> null).
    function measuredRegion(frames, warmupMs) {
        let acc = 0
        for (let i = 0; i < frames.length; i++) {
            if (frames[i][1] !== null) acc += frames[i][1]
            if (acc >= warmupMs) return {start: i, frames: [[frames[i][0], null]].concat(frames.slice(i + 1))}
        }
        return null
    }

    // ------------------------------------------------------ environment --
    function gpuInfo() {
        try {
            const c = document.createElement('canvas')
            const gl = c.getContext('webgl') || c.getContext('experimental-webgl')
            if (!gl) return {available: false, reason: 'no WebGL context'}
            const ext = gl.getExtension('WEBGL_debug_renderer_info')
            const info = ext
                ? {available: true, vendor: gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),
                   renderer: gl.getParameter(ext.UNMASKED_RENDERER_WEBGL), source: 'WEBGL_debug_renderer_info'}
                : {available: true, vendor: gl.getParameter(gl.VENDOR), renderer: gl.getParameter(gl.RENDERER),
                   source: 'VENDOR/RENDERER (unmasked renderer info not exposed)'}
            const lose = gl.getExtension('WEBGL_lose_context')
            if (lose) lose.loseContext()
            return info
        } catch (e) { return {available: false, reason: String(e)} }
    }
    function osFamily(ua) {
        if (/iPhone|iPad|iPod/.test(ua)) return 'iOS'
        if (/Android/.test(ua)) return 'Android'
        if (/Windows/.test(ua)) return 'Windows'
        if (/Mac OS X/.test(ua)) return 'macOS'
        if (/CrOS/.test(ua)) return 'ChromeOS'
        if (/Linux/.test(ua)) return 'Linux'
        return null
    }
    function browserFamily(ua) {
        if (/Edg\//.test(ua)) return 'Edge'
        if (/OPR\//.test(ua)) return 'Opera'
        if (/SamsungBrowser/.test(ua)) return 'Samsung Internet'
        if (/Firefox\//.test(ua)) return 'Firefox'
        if (/CriOS\//.test(ua)) return 'Chrome (iOS, WebKit)'
        if (/Chrome\//.test(ua)) return 'Chrome'
        if (/Safari\//.test(ua) && /Version\//.test(ua)) return 'Safari'
        return null
    }
    async function deviceInfo() {
        const ua = navigator.userAgent
        const info = {user_agent: ua, os_family_detected: osFamily(ua), browser_family_detected: browserFamily(ua),
                      detected_from: 'navigator.userAgent', navigator_platform: navigator.platform || null,
                      max_touch_points: navigator.maxTouchPoints, hardware_concurrency: navigator.hardwareConcurrency || null,
                      device_memory_gb: navigator.deviceMemory || null, language: navigator.language || null,
                      ua_client_hints: null, touch_constructor: typeof Touch === 'function' ? (touchConstructible().ok ? 'OK' : 'THROWS ' + touchConstructible().error) : 'absent',
                      input_kind_fallback: inputKindDetail().fallback}
        try {
            if (navigator.userAgentData) {
                const d = navigator.userAgentData
                info.ua_client_hints = {brands: d.brands, mobile: d.mobile, platform: d.platform}
                try {
                    const h = await d.getHighEntropyValues(['platformVersion', 'model', 'fullVersionList', 'architecture'])
                    info.ua_client_hints.high_entropy = h
                } catch (_) { info.ua_client_hints.high_entropy = null }
            }
        } catch (_) { /* keep null */ }
        return info
    }
    function displayInfo() {
        const vv = window.visualViewport
        // The game's own `let screen` (the camera) shadows window.screen here.
        const scr = window.screen
        let orientation = null
        try { orientation = (scr.orientation && scr.orientation.type) || null } catch (_) { }
        return {screen: [scr.width, scr.height], screen_available: [scr.availWidth, scr.availHeight],
                color_depth: scr.colorDepth, dpr: window.devicePixelRatio, orientation,
                visual_viewport_scale: vv ? vv.scale : null, viewport: [innerWidth, innerHeight]}
    }
    function rafEstimate() {
        // Median rAF cadence over ~1 s on the static menu: an estimate, never
        // a measured refresh rate (recorded next to the owner-supplied value).
        return new Promise(resolve => {
            const stamps = []
            const tick = t => { stamps.push(t); if (stamps.length < 61 && t - stamps[0] < 1500) requestAnimationFrame(tick); else finish() }
            const finish = () => {
                const d = []
                for (let i = 1; i < stamps.length; i++) d.push(stamps[i] - stamps[i - 1])
                d.sort((a, b) => a - b)
                resolve(d.length ? {hz: Math.round(1000 / d[Math.floor(d.length / 2)] * 10) / 10, samples: d.length,
                                    method: 'median requestAnimationFrame interval on the menu (estimate only)'} : null)
            }
            requestAnimationFrame(tick)
        })
    }

    // ---------------------------------------------------------- game io --
    const gameBooted = () => typeof menu !== 'undefined' && typeof startGame === 'function'
        && (!document.getElementById('loading') || document.getElementById('loading').hidden)
        && (typeof PLATFORM === 'undefined' || PLATFORM.environment !== 'pending')
    const gameState = () => ({menu: !!menu.visible, paused: !!menu.gamePaused,
        offer: typeof continueOffer !== 'undefined' && !!continueOffer.visible, hidden: !!document.hidden,
        ad: (typeof adOpen !== 'undefined' && !!adOpen) || (typeof interstitialPending !== 'undefined' && !!interstitialPending)})
    const isActive = s => !s.menu && !s.paused && !s.offer && !s.hidden && !s.ad
    function dimensions() {
        const r = canvas.getBoundingClientRect()
        return {canvas_backing: [canvas.width, canvas.height], canvas_css: [r.width, r.height],
                dpr: window.devicePixelRatio, viewport: [innerWidth, innerHeight], logical: [width, height],
                rotated: typeof isViewRotated === 'function' ? !!isViewRotated() : null,
                render_density: typeof getRenderDensity === 'function' ? getRenderDensity() : null,
                density_limit: typeof RENDER_BUDGET !== 'undefined' ? (isFinite(RENDER_BUDGET.densityLimit) ? RENDER_BUDGET.densityLimit : 'Infinity') : null,
                platform: typeof PLATFORM !== 'undefined' ? PLATFORM.environment : 'absent',
                build_version: typeof PLATFORM !== 'undefined' ? PLATFORM.buildVersion : null,
                fps_counter_enabled: typeof fpsCounter !== 'undefined' ? !!fpsCounter.enabled : null,
                version: typeof version !== 'undefined' ? version : null}
    }
    // Stage fraction -> window client coordinates (inverse of viewportCoordsToStageCoords).
    function stagePoint(fx, fy) {
        const rotated = typeof isViewRotated === 'function' && isViewRotated()
        const view = rotated ? getViewSize() : {width: innerWidth, height: innerHeight}
        const sx = fx * view.width, sy = fy * view.height
        if (!rotated) return {x: Math.round(sx * 10) / 10, y: Math.round(sy * 10) / 10}
        return {x: Math.round((view.height / 2 - sy + innerWidth / 2) * 10) / 10,
                y: Math.round((sx - view.width / 2 + innerHeight / 2) * 10) / 10}
    }
    // WebKit (iPhone Safari, Playwright WebKit) exposes `typeof Touch === 'function'` but `new Touch({...})`
    // throws TypeError: Illegal constructor (TASK-286 finding). Probe the constructor once and fall back to the
    // MouseEvent path: events.js listens for mousedown/mouseup on document, so the replay still drives the game.
    let touchProbe = null
    function touchConstructible() {
        if (touchProbe === null) {
            try { new Touch({identifier: 0, target: document.body, clientX: 0, clientY: 0}); touchProbe = {ok: true, error: null} }
            catch (e) { touchProbe = {ok: false, error: String(e && e.name ? e.name + ': ' + e.message : e)} }
        }
        return touchProbe
    }
    // {wanted, used, fallback}: wanted = forced ?input= or the maxTouchPoints/Touch detection, used = what fire() dispatches.
    function inputKindDetail() {
        const forced = settings.input_kind === 'mouse' || settings.input_kind === 'touch'
        const wanted = forced ? settings.input_kind : ((navigator.maxTouchPoints > 0 && typeof Touch === 'function') ? 'touch' : 'mouse')
        if (wanted === 'touch' && !touchConstructible().ok)
            return {wanted, used: 'mouse', forced, fallback: {from: 'touch', to: 'mouse', reason: 'new Touch() threw ' + touchConstructible().error +
                    '; replay dispatches mousedown/mouseup on document instead'}}
        return {wanted, used: wanted, forced, fallback: null}
    }
    function inputKind() { return inputKindDetail().used }

    // --------------------------------------------------------------- UI --
    const BENCH = window.__bench = {schema: SCHEMA, settings, session: null, run: null, panel: null,
                                    seed_installed_at_load: seedInstalledAtLoad, log: [], build: null, refused: null}
    const el = (tag, attrs, children) => {
        const e = document.createElement(tag)
        for (const k in attrs || {}) { if (k === 'text') e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]) }
        for (const c of children || []) e.appendChild(c)
        return e
    }
    const field = (label, input) => el('label', {class: 'bench-field'}, [el('span', {text: label}), input])
    const option = (value, text, selected) => { const o = el('option', {value, text}); if (selected) o.selected = true; return o }
    let ui = null
    function buildPanel() {
        const style = el('style', {text: `
            #bench-panel{position:fixed;left:0;right:0;bottom:0;z-index:50;background:rgba(10,12,20,.94);color:#eee;
              font:14px/1.35 system-ui,sans-serif;padding:8px 10px;max-height:70vh;overflow:auto;touch-action:auto;
              -webkit-user-select:text;user-select:text;box-sizing:border-box}
            #bench-panel[hidden]{display:none}
            #bench-panel .bench-row{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;margin:4px 0}
            #bench-panel .bench-field{display:inline-flex;flex-direction:column;font-size:12px;color:#bbb}
            #bench-panel input,#bench-panel select{font:13px system-ui,sans-serif;min-width:130px;padding:3px}
            #bench-panel button{font:14px system-ui,sans-serif;padding:6px 12px}
            #bench-panel .bench-status{color:#9cf;white-space:pre-wrap}
            #bench-panel .bench-warn{color:#fc6}
            #bench-panel textarea{width:100%;height:80px;font:11px monospace}
            #bench-panel h3{margin:2px 0 4px;font-size:15px}`})
        const inputs = {
            model: el('input', {id: 'bench-model', placeholder: 'e.g. Pixel 8 / iPhone 15 / ThinkPad T14', value: get('model', '')}),
            refresh: el('input', {id: 'bench-refresh', placeholder: 'Hz or unknown', value: get('refresh', 'unknown')}),
            devtools: el('select', {id: 'bench-devtools'}, ['closed', 'docked', 'undocked', 'unknown'].map(v => option(v, v, get('devtools', 'closed') === v))),
            throttle: el('input', {id: 'bench-throttle', value: get('throttle', 'none (1x)')}),
            emulation: el('select', {id: 'bench-emulation'}, [['none', 'none (native device)'], ['emulated', 'DevTools device emulation (NOT a native result)'], ['unknown', 'unknown']].map(([v, t]) => option(v, t, get('emulation', 'none') === v))),
            mode: el('select', {id: 'bench-mode'}, [['bad', 'Main version (bad)'], ['classic', 'Chill version (classic)']].map(([v, t]) => option(v, t, get('mode', DEFAULTS.mode) === v))),
            replay: el('select', {id: 'bench-replay'}, [['auto', 'auto (seeded synthetic throws)'], ['manual', 'manual (owner plays the documented script)']].map(([v, t]) => option(v, t, settings.replay_kind === v))),
            notes: el('input', {id: 'bench-notes', placeholder: 'optional notes', value: get('notes', '')})
        }
        const buttons = {
            start: el('button', {id: 'bench-start', text: 'Start run'}),
            abort: el('button', {id: 'bench-abort', text: 'Abort run', hidden: ''}),
            download: el('button', {id: 'bench-download', text: 'Download results'}),
            send: el('button', {id: 'bench-send', text: 'Send to serving machine'}),
            show: el('button', {id: 'bench-show', text: 'Show JSON'}),
            reset: el('button', {id: 'bench-reset', text: 'Reset session'})
        }
        const status = el('div', {id: 'bench-status', class: 'bench-status', text: 'waiting for the game to boot…'})
        const summary = el('div', {id: 'bench-summary'})
        const json = el('textarea', {id: 'bench-json', hidden: '', readonly: ''})
        const panel = el('div', {id: 'bench-panel'}, [
            el('h3', {id: 'bench-title', text: 'Grapnel Ninja benchmark'}),
            el('div', {class: 'bench-row'}, [field('Device model (required, actual hardware)', inputs.model),
                field('Display refresh rate (Hz, or unknown)', inputs.refresh), field('DevTools', inputs.devtools),
                field('CPU throttle', inputs.throttle), field('Emulation', inputs.emulation)]),
            el('div', {class: 'bench-row'}, [field('Mode', inputs.mode), field('Replay', inputs.replay), field('Notes', inputs.notes)]),
            el('div', {class: 'bench-row'}, [buttons.start, buttons.abort, buttons.download, buttons.send, buttons.show, buttons.reset]),
            status, summary, json])
        for (const type of ['mousedown', 'mouseup', 'touchstart', 'touchend', 'touchcancel', 'keydown', 'contextmenu', 'wheel'])
            panel.addEventListener(type, e => e.stopPropagation())
        document.head.appendChild(style)
        document.body.appendChild(panel)
        ui = {panel, inputs, buttons, status, summary, json}
        BENCH.panel = panel
        buttons.start.addEventListener('click', () => startRun().catch(e => setStatus('ERROR ' + e, true)))
        buttons.abort.addEventListener('click', () => finishRun('ABORTED by owner'))
        buttons.download.addEventListener('click', () => download())
        buttons.send.addEventListener('click', () => send().catch(e => setStatus('send failed: ' + e, true)))
        buttons.show.addEventListener('click', () => { json.hidden = !json.hidden; if (!json.hidden) json.value = JSON.stringify(exportSession(), null, 1) })
        buttons.reset.addEventListener('click', () => { if (confirm('Discard all runs of this session?')) { BENCH.session = null; renderSummary(); setStatus('session reset') } })
    }
    function setStatus(text, warn) {
        BENCH.log.push({t: Math.round(performance.now()), text})
        if (ui) { ui.status.textContent = text; ui.status.className = warn ? 'bench-status bench-warn' : 'bench-status' }
    }
    function renderSummary() {
        if (!ui) return
        const s = BENCH.session
        ui.summary.textContent = ''
        if (!s) return
        const lines = s.runs.map(r => {
            const m = r.verdict_inputs && r.verdict_inputs.measured
            return `run ${r.index} ${r.mode} ${r.result}: ` + (m ? `avg ${m.average_fps.toFixed(2)} fps, p95 ${m.frame_ms.p95.toFixed(2)} ms, ` +
                `min 10 s window ${r.verdict_inputs.rolling_10s_min_fps === null ? 'n/a' : r.verdict_inputs.rolling_10s_min_fps.toFixed(2)} fps, ` +
                `${m.intervals} intervals / ${m.active_ms.toFixed(0)} active ms, gaps ${m.gaps}, deaths ${r.deaths.length}, ` +
                `backing ${r.backing.initial.join('x')}${r.backing.changes.length ? ' CHANGED x' + r.backing.changes.length : ''}` : 'no measured frames')
        })
        const counts = {}
        for (const r of s.runs) if (r.result === 'COMPLETE') counts[r.mode] = (counts[r.mode] || 0) + 1
        lines.push(`complete runs: bad ${counts.bad || 0}/${settings.repetitions_target}, classic ${counts.classic || 0}/${settings.repetitions_target}`)
        for (const l of lines) ui.summary.appendChild(el('div', {text: l}))
    }

    // ------------------------------------------------------------ session --
    // TASK-301: build.json is read once at boot. Without build.served_tree_sha256 (game/ opened from disk
    // over file://, a copied folder without build.json, a foreign server) every exported result would be
    // REJECTED by the result schema, so the panel refuses to start a run instead of recording one that can
    // never be accepted. The refusal is shown in the status line and startRun() throws it.
    async function fetchBuild() {
        try { return await (await fetch('build.json', {cache: 'no-store'})).json() }
        catch (e) { return {error: 'build.json unavailable: ' + e} }
    }
    function buildRefusal(build) {
        if (build && typeof build.served_tree_sha256 === 'string' && build.served_tree_sha256.length === 64) return null
        return 'REFUSED: no served build identity (' + (build && build.error ? build.error : 'build.json carries no served_tree_sha256') +
            '; page protocol ' + location.protocol + '). Results without build.served_tree_sha256 are rejected by the result schema. ' +
            'Serve the package with `python3 benchtool.py serve` and open the game through that server address (port 8765), not from disk (file://).'
    }
    async function newSession(form) {
        const build = BENCH.build || await fetchBuild()
        const refusal = buildRefusal(build)
        if (refusal) throw new Error(refusal)
        const dims = dimensions()
        return {schema: SCHEMA, bench_js: 'bench.js', build,
                device: Object.assign({model_supplied: form.model}, await deviceInfo()),
                display: Object.assign({refresh_rate_hz_supplied: form.refresh_hz, refresh_rate_marker: form.refresh_marker,
                                        raf_estimate: await rafEstimate()}, displayInfo()),
                gpu: gpuInfo(),
                settings: Object.assign({}, settings, {devtools: form.devtools, cpu_throttle: form.throttle, emulation: form.emulation,
                    notes: form.notes, seed_installed_at_load: seedInstalledAtLoad,
                    density: 'NOT pinned: shipped adaptive RENDER_BUDGET untouched; backing size recorded per run',
                    sdk_isolation: 'served index.html carries no cdn.y8.com script; PLATFORM.environment=' + dims.platform +
                        '; the page requests only same-origin files and POSTs results only to the serving machine',
                    hooks: 'gameLoop and reStart wrapped only while a run records; no draw/physics/density function replaced'}),
                platform_at_session_start: dims.platform, build_version: dims.build_version,
                page_url: location.pathname + location.search, started_utc: new Date().toISOString(), runs: []}
    }
    function readForm() {
        const i = ui.inputs
        const model = i.model.value.trim()
        if (!model) throw new Error('Device model is required (actual hardware name)')
        const refreshRaw = i.refresh.value.trim().toLowerCase()
        const hz = parseFloat(refreshRaw)
        const form = {model, devtools: i.devtools.value, throttle: i.throttle.value.trim() || 'unknown', emulation: i.emulation.value,
                      notes: i.notes.value.trim(), mode: i.mode.value, replay_kind: i.replay.value}
        if (refreshRaw === '' || refreshRaw === 'unknown') { form.refresh_hz = null; form.refresh_marker = 'unknown' }
        else if (isFinite(hz) && hz > 0) { form.refresh_hz = hz; form.refresh_marker = 'manual' }
        else throw new Error('Display refresh rate must be a number in Hz or "unknown"')
        return form
    }

    // ---------------------------------------------------------------- run --
    async function startRun() {
        if (BENCH.refused) throw new Error(BENCH.refused)
        if (BENCH.run) throw new Error('a run is already recording')
        if (!gameBooted()) throw new Error('game not booted yet')
        const form = readForm()
        if (!BENCH.session) BENCH.session = await newSession(form)
        else if (BENCH.session.device.model_supplied !== form.model) throw new Error('device model changed; reset the session first')
        settings.replay_kind = form.replay_kind
        BENCH.session.settings.replay_kind = form.replay_kind
        const total = settings.warmup_ms + settings.run_ms + 1000
        const kind = inputKind()
        const replay = settings.replay_kind === 'auto' ? replayFractions(seedValue === null ? 0 : seedValue, total) : []
        const seedNote = installSeed()
        if (typeof menu !== 'undefined' && menu.gamePaused && typeof menu.unPause === 'function') menu.unPause()
        const run = BENCH.run = {index: BENCH.session.runs.length + 1, mode: form.mode, started_utc: new Date().toISOString(),
            seed_installed: seedNote, replay_kind: settings.replay_kind, input_kind: kind,
            replay_fractions_sha256: sha256Hex(canonical(replay)), replay_events: replay.length,
            dimensions_at_start: null, frames: [], excluded: 0, excluded_samples: [], inactive_stretches: [], interruptions: [], deaths: [], dispatched: [],
            backing: {initial: null, changes: []}, warmup_end_active_ms: null, active_ms: 0, result: 'RECORDING', error: null}
        const queue = replay.slice()
        let previous = null, touch = null, done = false, stretch = null
        const fire = ev => {
            const p = stagePoint(ev.fx, ev.fy)
            const target = document.elementFromPoint(p.x, p.y) || document.body
            if (kind === 'touch') {
                if (ev.type === 'start') touch = new Touch({identifier: 0, target, clientX: p.x, clientY: p.y})
                target.dispatchEvent(new TouchEvent(ev.type === 'start' ? 'touchstart' : 'touchend',
                    {bubbles: true, cancelable: true, changedTouches: [touch], touches: ev.type === 'start' ? [touch] : []}))
            } else {
                document.dispatchEvent(new MouseEvent(ev.type === 'start' ? 'mousedown' : 'mouseup',
                    {bubbles: true, cancelable: true, clientX: p.x, clientY: p.y, button: 0}))
            }
            run.dispatched.push({t_ms: ev.t_ms, type: ev.type, x: p.x, y: p.y, active_ms: Math.round(run.active_ms * 10) / 10})
        }
        // Inactive stretches (TASK-300): every maximal run of inactive gameLoop calls between two active
        // frames is one compact entry {first_t, last_t, frames, state} in run.inactive_stretches, recorded in
        // full however many stretches there are; excluded_samples keeps at most INACTIVE_SAMPLES_PER_STRETCH
        // samples per stretch plus its last one (the old cap was 500 samples per RUN, so a 12 s menu pause in
        // the warmup exhausted it and a later 1 s pause inside the measured region left no evidence at all).
        let stretchSamples = 0, stretchLastState = null
        const recordInactive = (ts, s) => {
            if (stretch === null) {
                stretch = {first_t: ts, last_t: ts, frames: 1, state: s}
                run.inactive_stretches.push(stretch)
                stretchSamples = 1; stretchLastState = s
                run.excluded_samples.push({t: ts, state: s, stretch: run.inactive_stretches.length - 1})
                return
            }
            stretch.last_t = ts; stretch.frames++; stretchLastState = s
            if (stretchSamples < INACTIVE_SAMPLES_PER_STRETCH) { stretchSamples++; run.excluded_samples.push({t: ts, state: s, stretch: run.inactive_stretches.length - 1}) }
        }
        const closeStretch = () => {
            if (stretch.frames > stretchSamples) run.excluded_samples.push({t: stretch.last_t, state: stretchLastState, stretch: run.inactive_stretches.length - 1, last: true})
            stretch = null
        }
        const onVis = () => run.interruptions.push({t: Math.round(performance.now() * 10) / 10, kind: document.hidden ? 'hidden' : 'visible'})
        const onBlur = () => run.interruptions.push({t: Math.round(performance.now() * 10) / 10, kind: 'blur'})
        document.addEventListener('visibilitychange', onVis)
        window.addEventListener('blur', onBlur)
        const originalLoop = window.gameLoop, originalRestart = window.reStart
        window.reStart = function () { run.deaths.push({active_ms: Math.round(run.active_ms * 10) / 10, t: Math.round(performance.now() * 10) / 10}); return originalRestart.apply(this, arguments) }
        window.gameLoop = function (t) {
            if (!done) {
                const s = gameState()
                if (isActive(s)) {
                    if (stretch !== null) closeStretch()
                    const dt = previous === null ? null : t - previous
                    previous = t
                    if (dt !== null) run.active_ms += dt
                    run.frames.push([t, dt])
                    if (run.backing.initial === null) run.backing.initial = [canvas.width, canvas.height]
                    const last = run.backing.changes.length ? run.backing.changes[run.backing.changes.length - 1].backing : run.backing.initial
                    if (canvas.width !== last[0] || canvas.height !== last[1])
                        run.backing.changes.push({frame: run.frames.length - 1, backing: [canvas.width, canvas.height], density_limit: isFinite(RENDER_BUDGET.densityLimit) ? RENDER_BUDGET.densityLimit : 'Infinity'})
                    while (queue.length && run.active_ms >= queue[0].t_ms) fire(queue.shift())
                    if (run.warmup_end_active_ms === null && run.active_ms >= settings.warmup_ms) run.warmup_end_active_ms = run.active_ms
                    if (run.warmup_end_active_ms !== null && run.active_ms >= run.warmup_end_active_ms + settings.run_ms) { done = true; setTimeout(() => finishRun('COMPLETE'), 0) }
                    if (ui && !ui.panel.hidden) ui.panel.hidden = true
                } else {
                    run.excluded++
                    recordInactive(Math.round(t * 10) / 10, s)
                    previous = null
                    if (ui && ui.panel.hidden) { ui.panel.hidden = false; setStatus(`run ${run.index} paused/inactive: ${run.active_ms.toFixed(0)} active ms of ${settings.warmup_ms + settings.run_ms}. Resume in the game, or abort.`, true) }
                }
            }
            try { return originalLoop.call(this, t) }
            catch (e) { run.error = String(e && e.stack || e); throw e }
        }
        run._cleanup = () => {
            done = true
            if (stretch !== null) closeStretch()
            window.gameLoop = originalLoop; window.reStart = originalRestart
            document.removeEventListener('visibilitychange', onVis); window.removeEventListener('blur', onBlur)
        }
        ui.buttons.abort.hidden = false
        ui.buttons.start.disabled = true
        setStatus(`run ${run.index} (${form.mode}) recording: ${settings.warmup_ms} ms warmup + ${settings.run_ms} ms measured active time`)
        startGame(form.mode)
        run.dimensions_at_start = dimensions()
        ui.panel.hidden = true
    }
    function finishRun(result) {
        const run = BENCH.run
        if (!run) return
        run._cleanup(); delete run._cleanup
        BENCH.run = null
        run.ended_utc = new Date().toISOString()
        run.dimensions_at_end = dimensions()
        run.result = result
        run.frames_sha256 = sha256Hex(canonical(run.frames))
        const region = measuredRegion(run.frames, settings.warmup_ms)
        const measured = region ? metrics(region.frames) : null
        const windows = region ? rollingWindows(region.frames, 10000) : []
        run.verdict_inputs = {
            warmup_ms: settings.warmup_ms, run_ms: settings.run_ms, measured_start_frame: region ? region.start : null,
            measured, rolling_10s_windows: windows.length,
            rolling_10s_min_fps: windows.length ? Math.min.apply(null, windows.map(w => w.fps)) : null,
            backing_constant: run.backing.changes.length === 0, backing_sizes: [run.backing.initial].concat(run.backing.changes.map(c => c.backing)),
            inactive_frames_excluded: run.excluded, inactive_stretches: run.inactive_stretches.length, deaths: run.deaths.length, dispatched_inputs: run.dispatched.length,
            measured_active_ms_reached: !!(measured && measured.active_ms >= settings.run_ms)}
        if (result === 'COMPLETE' && !run.verdict_inputs.measured_active_ms_reached) run.result = 'FAILED: measured active time short'
        BENCH.session.runs.push(run)
        ui.buttons.abort.hidden = true
        ui.buttons.start.disabled = false
        ui.panel.hidden = false
        renderSummary()
        setStatus(`run ${run.index} ${run.result}. Use the in-game menu to pause; tap Start run for the next repetition.`)
        if (settings.autosend) send().catch(e => setStatus(`run ${run.index} ${run.result}; auto-send failed (${e}); use Download results`, true))
    }

    // ------------------------------------------------------------ export --
    function exportSession() {
        const s = BENCH.session
        if (!s) return null
        const out = Object.assign({}, s, {exported_utc: new Date().toISOString(), runs: s.runs.map(r => { const c = Object.assign({}, r); delete c._cleanup; return c })})
        return out
    }
    function fileName() {
        const s = BENCH.session
        const slug = (s ? s.device.model_supplied : 'session').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'device'
        return 'bench-' + new Date().toISOString().replace(/[:.]/g, '-') + '-' + slug + '.json'
    }
    function download() {
        const data = exportSession()
        if (!data) { setStatus('nothing to export yet', true); return }
        const blob = new Blob([JSON.stringify(data, null, 1)], {type: 'application/json'})
        const a = el('a', {href: URL.createObjectURL(blob), download: fileName()})
        document.body.appendChild(a); a.click(); a.remove()
        setStatus('download offered: ' + a.download + ' (' + blob.size + ' bytes)')
    }
    async function send() {
        const data = exportSession()
        if (!data) { setStatus('nothing to send yet', true); return }
        const r = await fetch('../save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)})
        const body = await r.json()
        if (!r.ok || !body.saved) throw new Error(body.error || ('HTTP ' + r.status))
        setStatus('saved on the serving machine as ' + body.saved)
        return body
    }

    // --------------------------------------------------------------- boot --
    document.addEventListener('DOMContentLoaded', async () => {
        buildPanel()
        BENCH.build = await fetchBuild()
        BENCH.refused = buildRefusal(BENCH.build)
        if (BENCH.refused) { ui.buttons.start.disabled = true; setStatus(BENCH.refused, true); return }
        const wait = () => {
            if (!gameBooted()) { setTimeout(wait, 200); return }
            const d = dimensions()
            setStatus(`ready: platform ${d.platform}, viewport ${d.viewport.join('x')}, DPR ${d.dpr}, backing ${d.canvas_backing.join('x')}, ` +
                      `${settings.protocol} protocol (${settings.warmup_ms} + ${settings.run_ms} ms x ${settings.repetitions_target} per mode)`)
            BENCH.ready = true
            if (settings.autostart) startRun().catch(e => setStatus('autostart failed: ' + e, true))
        }
        wait()
    })
    BENCH.internal = {metrics, rollingWindows, measuredRegion, replayFractions, sha256Hex, canonical, exportSession, startRun, finishRun}
})()
