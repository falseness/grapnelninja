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
// Composes with ?perf=1: both wrap the same globals, each wrapper calling
// the previous one. Without the flag nothing is wrapped, no listener is
// added and window.visualsPerf stays undefined.
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

    function resetInterval()
    {
        layers = {}
        physicsMs = 0
        physicsSteps = 0
        canvasesCreated = 0
        getContextCalls = 0
        fallRecoveries = 0
        sectionChanges = 0
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

    const createElement = document.createElement
    document.createElement = function(tagName)
    {
        if (report && String(tagName).toLowerCase() === 'canvas')
            ++canvasesCreated
        return createElement.apply(this, arguments)
    }
    const getContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function()
    {
        if (report)
            ++getContextCalls
        return getContext.apply(this, arguments)
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
})()
