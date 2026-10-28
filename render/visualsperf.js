// Opt-in freeze recorder (?visualsPerf=1 only) for the player's own browser:
// this server's headless browser has no GPU, so its frame times say nothing
// about the freezes players see. window.visualsPerf.start(meta) begins a
// report, stop() ends it and returns it, export() returns the last report
// (stopping a running one). It never sends anything anywhere.
//
// A sample is pushed at the start of every requestAnimationFrame callback
// and covers the interval since the previous one: gapMs, and the draw()
// layer (PERF_LAYERS, shared with render/perfprofile.js) and physics times
// of the work done in that interval, i.e. the previous callback. Samples
// are kept in a ring of the newest RING_SIZE (droppedSamples counts the
// rest); every sample with gapMs > FREEZE_MS is also kept in freezes[],
// never dropped, with its slowest entry, the time no layer accounts for and
// the game state (context). start({ringSize}) is a test-only override.
//
// First draws (likely a GPU upload of a CPU-backed image): while recording,
// CanvasRenderingContext2D.prototype.drawImage is wrapped (restored by
// stop()) and a source never drawn before on this page counts once. A
// sample's fd is the px (source width * height) first drawn in its interval,
// omitted when 0; a freeze's context has the 3 largest (firstDraws: src is
// the 'file:line' that created the canvas, else the image url or type) and
// the Grapple Over palette of the last drawn frame ({from, to, t}, else null).
//
// Composes with ?perf=1: both wrap the same globals, each wrapper calling
// the previous one. Without the flag nothing is wrapped, no listener is
// added and window.visualsPerf stays undefined.
//
// With the flag a fixed bottom-left panel (#visuals-perf-controls) has
// Start / Stop / Export buttons (Export downloads visuals-performance.json)
// and shows the live freeze count, the worst gap and the slowest layer of
// the last freeze. Input on the panel never reaches the game.
(function()
{
    if (new URLSearchParams(location.search).get('visualsPerf') !== '1')
        return

    const FREEZE_MS = 50
    const RING_SIZE = 18000

    // Work of the current interval; reset after every sample
    let layers = {}, physicsMs = 0, physicsSteps = 0
    let canvasesCreated = 0, getContextCalls = 0, fallRecoveries = 0, sectionChanges = 0
    let report = null, lastReport = null, ring = null, ringSize = RING_SIZE, next = 0
    let previousT = null, lastSection = null, longTaskObserver = null
    let sectionWorld = null, sectionBounds = null
    let firstDrawPx = 0, firstDraws = []
    // Sources already drawn and the creator of every canvas (kept across recordings)
    const drawnSources = new WeakSet(), canvasCreators = new WeakMap()

    function resetInterval()
    {
        layers = {}
        physicsMs = 0
        physicsSteps = 0
        canvasesCreated = 0
        getContextCalls = 0
        fallRecoveries = 0
        sectionChanges = 0
        firstDrawPx = 0
        firstDraws = []
    }

    function timed(owner, globalName, record)
    {
        const fn = owner[globalName]
        owner[globalName] = function()
        {
            if (!report)
                return fn.apply(this, arguments)
            const start = performance.now()
            let result
            try
            {
                return result = fn.apply(this, arguments)
            }
            finally
            {
                record(performance.now() - start, result)
            }
        }
    }

    function addLayer(name, ms)
    {
        layers[name] = (layers[name] || 0) + ms
    }

    for (const name in PERF_LAYERS)
        timed(window, PERF_LAYERS[name], ms => addLayer(name, ms))
    // Mote glow and copy of the reduced backdrop (render/backdrop.js)
    timed(BACKDROP, 'end', ms => addLayer('backdrop', ms))

    // 'file:line' of the first stack frame outside this file
    function creatorOf(stack)
    {
        for (const line of String(stack || '').split('\n').slice(1))
        {
            const m = line.match(/(?:https?:\/\/[^/]+\/)?([^\s()]+):(\d+):\d+\)?\s*$/)
            if (m && !m[1].endsWith('visualsperf.js'))
                return m[1] + ':' + m[2]
        }
        return '?'
    }

    const createElement = document.createElement
    document.createElement = function(tagName)
    {
        const element = createElement.apply(this, arguments)
        if (String(tagName).toLowerCase() === 'canvas')
        {
            if (report)
                ++canvasesCreated
            canvasCreators.set(element, creatorOf(new Error().stack))
        }
        return element
    }
    const getContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function()
    {
        if (report)
            ++getContextCalls
        return getContext.apply(this, arguments)
    }

    // drawImage as it was at start(), put back by stop(); installed stays
    // true while a later wrapper over drawImageFirst keeps it in the chain
    let drawImage = CanvasRenderingContext2D.prototype.drawImage, installed = false
    function drawImageFirst(image)
    {
        if (report && image && typeof image === 'object' && !drawnSources.has(image))
        {
            drawnSources.add(image)
            const w = image.videoWidth || image.naturalWidth || image.width || 0
            const h = image.videoHeight || image.naturalHeight || image.height || 0
            firstDrawPx += w * h
            const src = canvasCreators.get(image) || (image.currentSrc || image.src ?
                new URL(image.currentSrc || image.src, location.href).pathname : image.constructor.name)
            firstDraws.push({src, w, h})
            if (firstDraws.length > 3)
            {
                firstDraws.sort((a, b) => b.w * b.h - a.w * a.h)
                firstDraws.length = 3
            }
        }
        return drawImage.apply(this, arguments)
    }

    // The game loop, its physics step and the fall recovery live in
    // index.html's inline script and physics.js; all have run by
    // DOMContentLoaded (after render/perfprofile.js's listener)
    document.addEventListener('DOMContentLoaded', () =>
    {
        timed(window, 'runFixedPhysics', (ms, steps) =>
        {
            physicsMs += ms
            physicsSteps += steps || 0
        })
        const recoverClimbFall = window.recoverClimbFall
        window.recoverClimbFall = function()
        {
            if (report)
                ++fallRecoveries
            return recoverClimbFall.apply(this, arguments)
        }
        const gameLoop = window.gameLoop
        window.gameLoop = function(frameTime)
        {
            if (report)
                sample(frameTime)
            return gameLoop.apply(this, arguments)
        }
    })

    function game(read)
    {
        try
        {
            return read()
        }
        catch (error)
        {
            return null
        }
    }

    function grapnelState()
    {
        return game(() => grapnel.isGrappled() ? 'hooked' : grapnel.throwed ? 'flying' : 'none') || 'none'
    }

    // Climb section of the authored element nearest the player (bounding
    // boxes taken once per world); null outside Grapple Over
    function currentSection()
    {
        const world = game(() => version === 'grapple_over' ? floors[0] : null)
        if (!world || !world.level || !world.level.sections)
            return null
        if (world !== sectionWorld)
        {
            sectionWorld = world
            const sectionOf = new Map()
            const encounters = new Map(world.level.encounters.map(e => [e.id, e]))
            for (const section of world.level.sections)
                for (const id of section.encounters)
                    for (const element of (encounters.get(id) || {elements: []}).elements)
                        if (!sectionOf.has(element))
                            sectionOf.set(element, section.id)
            sectionBounds = []
            for (const element of world.elements)
                if (sectionOf.has(element.id))
                    sectionBounds.push({section: sectionOf.get(element.id), ...getElementBounds(element)})
        }
        const x = ninja.x, y = ninja.y
        let best = null, bestD = Infinity
        for (const b of sectionBounds)
        {
            const dx = Math.max(b.left - x, 0, x - b.right)
            const dy = Math.max(b.top - y, 0, y - b.bottom)
            const d = dx * dx + dy * dy
            if (d < bestD)
            {
                bestD = d
                best = b.section
            }
        }
        return best
    }

    function context()
    {
        return {
            ninjaX: game(() => ninja.x),
            ninjaY: game(() => ninja.y),
            grapnel: grapnelState(),
            section: lastSection,
            backdropQuality: BACKDROP.resolution,
            backdropFast: BACKDROP.active,
            canvasesCreated,
            getContextCalls,
            fallRecoveries,
            sectionChanges,
            firstDraws: firstDraws.slice().sort((a, b) => b.w * b.h - a.w * a.h),
            palette: game(() =>
            {
                const p = version === 'grapple_over' ? visualEffects.background.palette : null
                return p ? {from: p.from, to: p.to, t: p.t} : null
            }),
        }
    }

    function sample(t)
    {
        const section = game(currentSection)
        if (section !== lastSection && previousT !== null)
            ++sectionChanges
        lastSection = section
        if (previousT !== null)
        {
            const gapMs = t - previousT
            const entry = {t, gapMs, layers, physicsMs, physicsSteps, hidden: document.hidden}
            if (firstDrawPx)
                entry.fd = firstDrawPx
            if (ring.length < ringSize)
                ring.push(entry)
            else
            {
                ring[next] = entry
                next = (next + 1) % ringSize
                ++report.droppedSamples
            }
            if (gapMs > FREEZE_MS)
            {
                let slowestLayer = 'physics', slowestMs = physicsMs, accounted = physicsMs
                for (const name in layers)
                {
                    accounted += layers[name]
                    if (layers[name] > slowestMs)
                    {
                        slowestMs = layers[name]
                        slowestLayer = name
                    }
                }
                report.freezes.push({t, gapMs, layers, physicsMs, physicsSteps, slowestLayer,
                    unaccountedMs: gapMs - accounted, context: context()})
                const live = window.visualsPerf.live
                ++live.freezes
                live.worstMs = Math.max(live.worstMs, gapMs)
                live.last = {layer: slowestLayer, ms: slowestMs}
            }
        }
        previousT = t
        resetInterval()
    }

    // sha256 of every loaded script (pathname -> hex), resolved later
    function sourceHashes()
    {
        const scripts = [...document.scripts].filter(s => s.src)
        return Promise.all(scripts.map(async script =>
        {
            const bytes = await (await fetch(script.src)).arrayBuffer()
            const digest = await crypto.subtle.digest('SHA-256', bytes)
            return [new URL(script.src).pathname,
                [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, '0')).join('')]
        })).then(Object.fromEntries).catch(error => ({error: String(error)}))
    }

    function onVisibility(event)
    {
        report.visibility.push({t: performance.now(), type: event.type, hidden: document.hidden})
    }

    window.visualsPerf = {
        get active()
        {
            return report !== null
        },
        live: {freezes: 0, worstMs: 0, last: null},
        start(meta = {})
        {
            if (report)
                this.stop()
            ringSize = meta.ringSize > 0 ? Math.floor(meta.ringSize) : RING_SIZE
            ring = []
            next = 0
            previousT = null
            lastSection = null
            resetInterval()
            this.live = {freezes: 0, worstMs: 0, last: null}
            report = {
                schemaVersion: 1,
                environment: 'user-browser',
                performanceStatus: 'user-device-performance-unverified',
                meta,
                userAgent: navigator.userAgent,
                viewport: [innerWidth, innerHeight],
                dpr: devicePixelRatio,
                version: game(() => version),
                levelId: game(() => version === 'grapple_over' ? floors[0].level.layoutId : null),
                sourceHashes: null,
                freezeMs: FREEZE_MS,
                ringSize,
                startedAt: new Date().toISOString(),
                startedAtMs: performance.now(),
                stoppedAtMs: null,
                samples: [],
                droppedSamples: 0,
                freezes: [],
                longTasksSupported: false,
                longTasks: [],
                visibility: [],
            }
            const target = report
            sourceHashes().then(hashes => target.sourceHashes = hashes)
            if (typeof PerformanceObserver !== 'undefined' &&
                (PerformanceObserver.supportedEntryTypes || []).includes('longtask'))
            {
                report.longTasksSupported = true
                longTaskObserver = new PerformanceObserver(list =>
                {
                    for (const e of list.getEntries())
                        target.longTasks.push({t: e.startTime, durationMs: e.duration})
                })
                longTaskObserver.observe({type: 'longtask'})
            }
            document.addEventListener('visibilitychange', onVisibility)
            window.addEventListener('focus', onVisibility)
            window.addEventListener('blur', onVisibility)
            if (!installed)
            {
                drawImage = CanvasRenderingContext2D.prototype.drawImage
                CanvasRenderingContext2D.prototype.drawImage = drawImageFirst
                installed = true
            }
        },
        stop()
        {
            if (!report)
                return lastReport
            if (longTaskObserver)
            {
                for (const e of longTaskObserver.takeRecords())
                    report.longTasks.push({t: e.startTime, durationMs: e.duration})
                longTaskObserver.disconnect()
                longTaskObserver = null
            }
            document.removeEventListener('visibilitychange', onVisibility)
            window.removeEventListener('focus', onVisibility)
            window.removeEventListener('blur', onVisibility)
            // a later wrapper over ours keeps it (it passes through while stopped)
            if (CanvasRenderingContext2D.prototype.drawImage === drawImageFirst)
            {
                CanvasRenderingContext2D.prototype.drawImage = drawImage
                installed = false
            }
            report.samples = ring.slice(next).concat(ring.slice(0, next))
            report.stoppedAtMs = performance.now()
            lastReport = report
            report = null
            ring = null
            return lastReport
        },
        export()
        {
            return this.active ? this.stop() : lastReport
        },
    }

    const PANEL_REFRESH_MS = 500

    function createPanel()
    {
        const panel = document.createElement('section')
        panel.id = 'visuals-perf-controls'
        panel.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:99999;background:#182333;' +
            'color:white;padding:8px;font:12px sans-serif;max-width:calc(100vw - 32px)'
        const line = text =>
        {
            const div = document.createElement('div')
            div.textContent = text
            panel.append(div)
            return div
        }
        line('Visual capture: local diagnostics; device FPS unverified')
        const state = line('Stopped')
        const buttons = document.createElement('div')
        panel.append(buttons)
        const button = (text, action) =>
        {
            const b = document.createElement('button')
            b.textContent = text
            b.style.cssText = 'min-height:32px;padding:5px;margin:2px'
            b.addEventListener('click', () =>
            {
                action()
                b.blur()
                refresh()
            })
            buttons.append(b)
        }
        button('Start', () => visualsPerf.start())
        button('Stop', () => visualsPerf.stop())
        button('Export', () =>
        {
            const blob = new Blob([JSON.stringify(visualsPerf.export(), null, 2)], {type: 'application/json'})
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = 'visuals-performance.json'
            a.click()
            setTimeout(() => URL.revokeObjectURL(url), 1000)
        })
        const freezes = line(''), worst = line(''), last = line('')

        // start() replaces visualsPerf.live, so it is read on every refresh
        function refresh()
        {
            const live = visualsPerf.live
            state.textContent = visualsPerf.active ? 'Recording' : 'Stopped'
            freezes.textContent = 'freezes ' + live.freezes + ' (>' + FREEZE_MS + ' ms)'
            worst.textContent = 'worst ' + Math.round(live.worstMs) + ' ms'
            last.textContent = live.last ? 'last: ' + live.last.layer + ' ' + Math.round(live.last.ms) + ' ms' : 'last: none'
        }
        refresh()
        setInterval(refresh, PANEL_REFRESH_MS)

        // The game listens on document: presses here must not throw or
        // release the grapnel, nor keys on a focused button reach the game
        for (const type of ['mousedown', 'mouseup', 'mousemove', 'click', 'pointerdown', 'pointerup',
            'pointermove', 'touchstart', 'touchmove', 'touchend', 'touchcancel', 'wheel',
            'keydown', 'keyup', 'keypress'])
            panel.addEventListener(type, event => event.stopPropagation())
        document.body.append(panel)
    }
    document.addEventListener('DOMContentLoaded', createPanel)
})()
