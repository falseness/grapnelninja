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
// Attribution (schemaVersion 2), all only while recording and torn down by
// stop(): long animation frames where supported (loafs, each freeze's
// context.loafs = those overlapping its interval); a MessageChannel heartbeat
// (at most one beat per HEARTBEAT_MS) whose longest silence inside a freeze
// is mainThreadSilenceMs (close to gapMs: main thread blocked; small: it was
// free, so GPU/compositor/vsync/OS); heapMB per sample (performance.memory)
// with heapBeforeMB/heapAfterMB/heapDropMB per freeze; rafLagMs per sample
// (callback start minus the rAF timestamp). start({heartbeat: false}) is a
// test-only switch.
//
// Retention and memory (schemaVersion 3): each freeze (up to WINDOW_CAP,
// droppedWindows counts the rest) gets freezeWindows[] = {freezeIndex,
// freezeAt, samples}: the WINDOW_SAMPLES samples before it, then the freeze
// sample (samples[freezeAt]) and the samples after it up to 2 *
// WINDOW_SAMPLES, kept outside the ring so droppedSamples never loses them.
// Every canvas from createElement (or in the DOM at start()) is held by a
// WeakRef; freezes have context.liveCanvases/liveCanvasMB (width * height * 4
// of the live ones) and a sample carries liveCanvasMB once per
// CANVAS_SAMPLE_MS. sourceHashes hashes each script on its own (a failure is
// {error, url}); buildId is the sha256 of the sorted 'path:hash' lines.
//
// buildIdMethod (TASK-787) says how buildId was made: 'fetch' is the above
// (unchanged); 'globals' is the fallback when no script could be fetched
// (file://: Chrome's fetch has no file scheme, and file pages can't read
// another file's text either). It needs no fetch: the sha256 of the sorted
// 'kind name:text' lines of the game's global bindings as the page sees them
// - every non-native function on window, then every name found in those
// sources (and in each newly found one, to a fixpoint) that resolves to a
// global lexical binding: functions and classes by their source text, const
// primitives by value, const frozen objects by a walk that only enters frozen
// children (others are '<mutable>'). A lexical binding is const when 'x = x'
// throws a TypeError; let bindings (game state), vars that are not functions
// and unfrozen objects are left out, so the id is the same on every boot of
// the same files. Limits: it fingerprints the code as parsed, not the files'
// bytes (comments outside functions and whitespace between them don't count;
// a function's own comments do), so it is never equal to the 'fetch' id; a
// change only in top-level statements, in a let/var initial value, in an
// unfrozen const object, or in a global no function names, is missed. null
// (buildIdMethod null) when neither works.
//
// Canvas owners and tab return (schemaVersion 4): each freeze's context and
// report.canvasSnapshot (taken by stop() and again by every export()) have
// liveCanvasByCreator {creator: {count, mb}}, the live canvases grouped by
// the 'file:line' that created them ('unknown' for canvases already in the
// DOM); mb is rounded to 0.01 so the groups add up to liveCanvasMB. Each
// freeze has sinceVisibleMs: ms since the last hidden-to-visible change while
// recording (null if the tab never went hidden). Readers of older exports
// treat the missing fields as unknown (tools/freeze_report.py).
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
    const LOAF_CAP = 2000
    const HEARTBEAT_MS = 4
    const WINDOW_SAMPLES = 30
    const WINDOW_CAP = 200
    const CANVAS_SAMPLE_MS = 1000

    // Work of the current interval; reset after every sample
    let layers = {}, physicsMs = 0, physicsSteps = 0
    let canvasesCreated = 0, getContextCalls = 0, fallRecoveries = 0, sectionChanges = 0
    let report = null, lastReport = null, ring = null, ringSize = RING_SIZE, next = 0
    let previousT = null, lastSection = null, longTaskObserver = null
    let sectionWorld = null, sectionBounds = null
    let firstDrawPx = 0, firstDraws = []
    let loafObserver = null, heapMB = null
    // Heartbeat: beat times since the previous sample, lifetime beat count
    let heartbeat = null, beats = [], beatCount = 0
    // The newest WINDOW_SAMPLES samples and the freeze windows still filling
    let recent = [], filling = []
    let lastCanvasSampleT = -Infinity
    // performance.now() of the last hidden-to-visible change while recording
    let visibleSince = null
    // Sources already drawn and the creator of every canvas (kept across recordings)
    const drawnSources = new WeakSet(), canvasCreators = new WeakMap()
    // Every canvas seen (createElement, or in the DOM at start()), held weakly;
    // a collected canvas drops out through the registry
    const liveCanvases = new Set(), registeredCanvases = new WeakSet()
    const canvasRegistry = typeof FinalizationRegistry === 'function' ?
        new FinalizationRegistry(ref => liveCanvases.delete(ref)) : null

    function registerCanvas(canvas)
    {
        if (typeof WeakRef !== 'function' || registeredCanvases.has(canvas))
            return
        registeredCanvases.add(canvas)
        const ref = new WeakRef(canvas)
        liveCanvases.add(ref)
        if (canvasRegistry)
            canvasRegistry.register(canvas, ref)
    }

    // {count, mb}: live canvases and their backing store (width * height * 4);
    // byCreator also adds {creator: {count, mb}} (mb to 0.01)
    function canvasMemory(byCreator = false)
    {
        let count = 0, bytes = 0
        const creators = byCreator ? {} : null
        for (const ref of liveCanvases)
        {
            const canvas = ref.deref()
            if (!canvas)
            {
                liveCanvases.delete(ref)
                continue
            }
            ++count
            const size = canvas.width * canvas.height * 4
            bytes += size
            if (creators)
            {
                const creator = canvasCreators.get(canvas) || 'unknown'
                const row = creators[creator] || (creators[creator] = {count: 0, mb: 0})
                ++row.count
                row.mb += size
            }
        }
        const memory = {count, mb: Math.round(bytes / 1048576 * 10) / 10}
        if (creators)
        {
            for (const creator in creators)
                creators[creator].mb = Math.round(creators[creator].mb / 1048576 * 100) / 100
            memory.byCreator = creators
        }
        return memory
    }

    function canvasSnapshot()
    {
        const canvases = canvasMemory(true)
        return {t: performance.now(), liveCanvases: canvases.count, liveCanvasMB: canvases.mb,
            liveCanvasByCreator: canvases.byCreator}
    }

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
            registerCanvas(element)
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
        const canvases = canvasMemory(true)
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
            liveCanvases: canvases.count,
            liveCanvasMB: canvases.mb,
            liveCanvasByCreator: canvases.byCreator,
            firstDraws: firstDraws.slice().sort((a, b) => b.w * b.h - a.w * a.h),
            palette: game(() =>
            {
                const p = version === 'grapple_over' ? visualEffects.background.palette : null
                return p ? {from: p.from, to: p.to, t: p.t} : null
            }),
        }
    }

    const round1 = ms => Math.round(ms * 10) / 10

    function readHeapMB()
    {
        const memory = performance.memory
        return memory ? round1(memory.usedJSHeapSize / 1048576) : null
    }

    // Longest time inside [from, to] with no heartbeat
    function silence(from, to)
    {
        let longest = 0, last = from
        for (const b of beats)
            if (b > from && b < to)
            {
                longest = Math.max(longest, b - last)
                last = b
            }
        return round1(Math.max(longest, to - last))
    }

    // A MessageChannel ping-pong; after a beat the next ping waits until
    // HEARTBEAT_MS have passed, so it never spins
    function startHeartbeat()
    {
        const channel = new MessageChannel()
        let lastBeat = -Infinity, timer = null
        const ping = () =>
        {
            timer = null
            channel.port2.postMessage(0)
        }
        channel.port1.onmessage = () =>
        {
            if (heartbeat !== channel)
                return
            const now = performance.now()
            if (now - lastBeat >= HEARTBEAT_MS)
            {
                lastBeat = now
                beats.push(now)
                ++beatCount
            }
            timer = setTimeout(ping, Math.max(0, HEARTBEAT_MS - (performance.now() - lastBeat)))
        }
        channel.stop = () =>
        {
            clearTimeout(timer)
            channel.port1.onmessage = null
            channel.port1.close()
            channel.port2.close()
        }
        heartbeat = channel
        ping()
    }

    function stopHeartbeat()
    {
        if (heartbeat)
        {
            const channel = heartbeat
            heartbeat = null
            channel.stop()
        }
        beats = []
    }

    function loafEntry(e)
    {
        return {
            startTime: e.startTime,
            duration: e.duration,
            blockingDuration: e.blockingDuration,
            renderStart: e.renderStart,
            styleAndLayoutStart: e.styleAndLayoutStart,
            scripts: [...(e.scripts || [])].sort((a, b) => b.duration - a.duration).slice(0, 3)
                .map(s => ({sourceURL: s.sourceURL, sourceFunctionName: s.sourceFunctionName,
                    invoker: s.invoker, duration: s.duration})),
        }
    }

    function addLoafs(target, entries)
    {
        for (const e of entries)
            if (target.loafs.length < LOAF_CAP)
                target.loafs.push(loafEntry(e))
    }

    function sample(t)
    {
        const rafLagMs = round1(performance.now() - t)
        const heapBeforeMB = heapMB
        heapMB = readHeapMB()
        const section = game(currentSection)
        if (section !== lastSection && previousT !== null)
            ++sectionChanges
        lastSection = section
        if (previousT !== null)
        {
            const gapMs = t - previousT
            const entry = {t, gapMs, layers, physicsMs, physicsSteps, hidden: document.hidden, rafLagMs}
            if (firstDrawPx)
                entry.fd = firstDrawPx
            if (heapMB !== null)
                entry.heapMB = heapMB
            if (t - lastCanvasSampleT >= CANVAS_SAMPLE_MS)
            {
                lastCanvasSampleT = t
                entry.liveCanvasMB = canvasMemory().mb
            }
            for (const w of filling)
                w.samples.push(entry)
            filling = filling.filter(w => w.samples.length < w.freezeAt + WINDOW_SAMPLES)
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
                const freeze = {t, gapMs, layers, physicsMs, physicsSteps, slowestLayer,
                    unaccountedMs: gapMs - accounted, rafLagMs,
                    mainThreadSilenceMs: heartbeat ? silence(previousT, t) : null,
                    sinceVisibleMs: visibleSince === null ? null : round1(Math.max(0, t - visibleSince)),
                    context: context()}
                if (heapMB !== null)
                {
                    freeze.heapBeforeMB = heapBeforeMB
                    freeze.heapAfterMB = heapMB
                    freeze.heapDropMB = heapBeforeMB === null ? 0 : round1(Math.max(0, heapBeforeMB - heapMB))
                }
                report.freezes.push(freeze)
                if (report.freezeWindows.length < WINDOW_CAP)
                {
                    const w = {freezeIndex: report.freezes.length - 1, freezeAt: recent.length,
                        samples: recent.concat([entry])}
                    report.freezeWindows.push(w)
                    filling.push(w)
                }
                else
                    ++report.droppedWindows
                const live = window.visualsPerf.live
                ++live.freezes
                live.worstMs = Math.max(live.worstMs, gapMs)
                live.last = {layer: slowestLayer, ms: slowestMs}
            }
            recent.push(entry)
            if (recent.length > WINDOW_SAMPLES)
                recent.shift()
        }
        previousT = t
        beats = []
        resetInterval()
    }

    async function sha256(bytes)
    {
        const digest = await crypto.subtle.digest('SHA-256', bytes)
        return [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, '0')).join('')
    }

    // sha256 of every loaded script, each on its own (pathname -> hex, or
    // {error, url} when that one fails), and buildId = sha256 of the sorted
    // 'path:hash' lines of the scripts that hashed; resolved later
    async function sourceHashes()
    {
        const scripts = [...document.scripts].filter(s => s.src)
        const entries = await Promise.all(scripts.map(async script =>
        {
            const path = new URL(script.src).pathname
            try
            {
                const response = await fetch(script.src)
                if (!response.ok)
                    throw new Error('HTTP ' + response.status)
                return [path, await sha256(await response.arrayBuffer())]
            }
            catch (error)
            {
                return [path, {error: String(error), url: script.src}]
            }
        }))
        const hashed = entries.filter(([, hash]) => typeof hash === 'string')
        let buildId = null, buildIdMethod = null
        try
        {
            if (hashed.length)
            {
                buildId = await sha256(new TextEncoder().encode(
                    hashed.map(([path, hash]) => path + ':' + hash).sort().join('\n')))
                buildIdMethod = 'fetch'
            }
            else
            {
                buildId = await sha256(new TextEncoder().encode(globalsFingerprint()))
                buildIdMethod = 'globals'
            }
        }
        catch (error)
        {
            buildId = null
            buildIdMethod = null
        }
        return {sourceHashes: Object.fromEntries(entries), buildId, buildIdMethod,
            sourceHashFailures: entries.length - hashed.length}
    }

    // The 'globals' buildId input (see the header): sorted 'kind name:text'
    // lines of the game's functions, classes, const primitives and const
    // frozen objects, read without fetching anything
    function globalsFingerprint()
    {
        const isNative = f => /\{\s*\[native code\]\s*\}\s*$/.test(Function.prototype.toString.call(f))
        const source = f => Function.prototype.toString.call(f)
        const lines = new Map(), queue = [], seen = new Set()
        const harvest = text =>
        {
            for (const name of text.match(/[A-Za-z_$][\w$]*/g) || [])
                if (!seen.has(name))
                {
                    seen.add(name)
                    queue.push(name)
                }
        }
        const frozen = (value, depth, stack) =>
        {
            if (typeof value === 'function')
                return source(value)
            if (value === null || typeof value !== 'object')
                return typeof value === 'string' ? JSON.stringify(value) : String(value)
            if (!Object.isFrozen(value))
                return '<mutable>'
            if (depth > 12 || stack.includes(value))
                return '<cycle>'
            stack.push(value)
            const parts = Object.keys(value).map(key => JSON.stringify(key) + ':' + frozen(value[key], depth + 1, stack))
            stack.pop()
            return (Array.isArray(value) ? '[' : '{') + parts.join(',') + (Array.isArray(value) ? ']' : '}')
        }
        for (const name of Object.getOwnPropertyNames(window))
        {
            const descriptor = Object.getOwnPropertyDescriptor(window, name)
            const value = descriptor && descriptor.value
            if (typeof value === 'function' && !isNative(value) && value !== window.visualsPerf)
            {
                lines.set(name, 'function ' + name + ':' + source(value))
                seen.add(name)
                harvest(source(value))
            }
        }
        while (queue.length)
        {
            const name = queue.shift()
            if (name in window)
                continue
            let value
            try
            {
                const read = new Function('return typeof ' + name + ' === "undefined" ? [false] : [true, ' + name + ']')()
                if (!read[0])
                    continue
                value = read[1]
            }
            catch (error)
            {
                // A keyword, or a lexical binding still in its temporal dead zone
                continue
            }
            if (typeof value === 'function')
            {
                if (isNative(value))
                    continue
                lines.set(name, (/^class\b/.test(source(value)) ? 'class ' : 'function ') + name + ':' + source(value))
                harvest(source(value))
                continue
            }
            let constant = false
            try
            {
                new Function(name + ' = ' + name)()
            }
            catch (error)
            {
                constant = error instanceof TypeError
            }
            if (!constant)
                continue
            if (value !== null && typeof value === 'object')
            {
                if (!Object.isFrozen(value))
                    continue
                const text = frozen(value, 0, [])
                lines.set(name, 'frozen ' + name + ':' + text)
                harvest(text)
            }
            else
                lines.set(name, 'const ' + name + ':' + (typeof value === 'string' ? JSON.stringify(value) : String(value)))
        }
        return [...lines.keys()].sort().map(name => lines.get(name)).join('\n')
    }

    function onVisibility(event)
    {
        const t = performance.now()
        // visibilitychange only fires on a change, so a visible one ends a hidden period
        if (event.type === 'visibilitychange' && !document.hidden)
            visibleSince = t
        report.visibility.push({t, type: event.type, hidden: document.hidden})
    }

    window.visualsPerf = {
        get active()
        {
            return report !== null
        },
        live: {freezes: 0, worstMs: 0, last: null},
        // Heartbeats since page load (tests check that stop() ends them)
        get beats()
        {
            return beatCount
        },
        start(meta = {})
        {
            if (report)
                this.stop()
            ringSize = meta.ringSize > 0 ? Math.floor(meta.ringSize) : RING_SIZE
            ring = []
            next = 0
            previousT = null
            lastSection = null
            heapMB = null
            recent = []
            filling = []
            lastCanvasSampleT = -Infinity
            visibleSince = null
            for (const canvas of document.querySelectorAll('canvas'))
                registerCanvas(canvas)
            resetInterval()
            this.live = {freezes: 0, worstMs: 0, last: null}
            report = {
                schemaVersion: 4,
                environment: 'user-browser',
                performanceStatus: 'user-device-performance-unverified',
                meta,
                userAgent: navigator.userAgent,
                viewport: [innerWidth, innerHeight],
                dpr: devicePixelRatio,
                version: game(() => version),
                levelId: game(() => version === 'grapple_over' ? floors[0].level.layoutId : null),
                sourceHashes: null,
                buildId: null,
                buildIdMethod: null,
                sourceHashFailures: null,
                freezeMs: FREEZE_MS,
                ringSize,
                startedAt: new Date().toISOString(),
                startedAtMs: performance.now(),
                stoppedAtMs: null,
                samples: [],
                droppedSamples: 0,
                freezes: [],
                freezeWindows: [],
                droppedWindows: 0,
                longTasksSupported: false,
                longTasks: [],
                loafSupported: false,
                loafs: [],
                heartbeat: meta.heartbeat !== false,
                heartbeatMs: HEARTBEAT_MS,
                visibility: [],
                canvasSnapshot: null,
            }
            const target = report
            sourceHashes().then(result => Object.assign(target, result),
                error => target.sourceHashes = {error: String(error)})
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
            if (typeof PerformanceObserver !== 'undefined' &&
                (PerformanceObserver.supportedEntryTypes || []).includes('long-animation-frame'))
            {
                report.loafSupported = true
                loafObserver = new PerformanceObserver(list => addLoafs(target, list.getEntries()))
                loafObserver.observe({type: 'long-animation-frame', buffered: false})
            }
            if (report.heartbeat)
                startHeartbeat()
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
            if (loafObserver)
            {
                addLoafs(report, loafObserver.takeRecords())
                loafObserver.disconnect()
                loafObserver = null
            }
            stopHeartbeat()
            // A frame's entry arrives after the frame, so freezes get theirs here
            for (const freeze of report.freezes)
                freeze.context.loafs = report.loafs.filter(e =>
                    e.startTime < freeze.t && e.startTime + e.duration > freeze.t - freeze.gapMs)
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
            report.canvasSnapshot = canvasSnapshot()
            lastReport = report
            report = null
            ring = null
            recent = []
            filling = []
            return lastReport
        },
        export()
        {
            const exported = this.active ? this.stop() : lastReport
            if (exported)
                exported.canvasSnapshot = canvasSnapshot()
            return exported
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
