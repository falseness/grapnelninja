// Product milestones measure active runs, independently of Bridge's built-in
// time-since-ready milestones. No identifiers or unbounded fields are sent.
const TELEMETRY = (() =>
{
    let last = null, total = 0, nextMilestone = 30
    let frames = [], active = 0, windowStart = null
    // Active play ms per grapnel mode, flushed as whole seconds
    const modeMs = {single: 0, double: 0}
    // The last thing that happened in the run, sent once on pagehide
    let lastEvent = null, quitSent = false
    // A pause screen is open (ui:pause:open sent, no ui:pause:close yet)
    let pauseOpen = false
    const session = createSession()
    const falls = createFallTelemetry()
    const percentile = (sorted, p) => sorted[Math.floor((sorted.length - 1) * p)]
    function resetClock() { last = null }
    document.addEventListener('visibilitychange', resetClock)
    window.addEventListener('blur', resetClock)
    // The climb section the player is in; null outside a Grapple Over run
    function section()
    {
        try
        {
            if (version === 'grapple_over' && floors[0]?.level?.sections?.length)
                return CLIMB_UI.currentSection().id
        }
        catch (e) {}
        return null
    }
    return {
        // grapnelMode: 'single' | 'double' while a climb world exists
        frame(now, playing, mode, grapnelMode)
        {
            if (!playing) { resetClock(); return }
            if (last === null) { last = now; return }
            const dt = now - last
            last = now
            if (!(dt > 0)) return
            if (windowStart === null) windowStart = now - dt
            total += dt
            active += dt
            frames.push(dt)
            if (grapnelMode in modeMs) modeMs[grapnelMode] += dt
            session.frame(dt, grapnelMode)
            while (nextMilestone <= 60 && total >= nextMilestone * 1000)
            {
                PLATFORM.track('active_play_milestone', {seconds: nextMilestone, mode})
                nextMilestone += 30
            }
            if (active < 30000) return
            const sorted = frames.slice().sort((a, b) => a - b)
            const sample = {
                target_fps: 60, window_ms: now - windowStart, active_ms: active,
                frame_count: frames.length, fps_avg: 1000 * frames.length / active,
                fps_p10: 1000 / percentile(sorted, .9),
                frame_time_p50_ms: percentile(sorted, .5),
                frame_time_p95_ms: percentile(sorted, .95),
                frame_time_p99_ms: percentile(sorted, .99),
                frame_time_max_ms: sorted[sorted.length - 1], mode
            }
            for (const threshold of [50, 100, 250, 500, 1000])
                sample['frames_over_' + threshold + 'ms'] = frames.filter(dt => dt > threshold).length
            PLATFORM.track('performance_sample', sample)
            frames = []; active = 0; windowStart = now
        },
        // design('mode_time:<mode>', seconds) for each mode with a whole
        // second played since the last flush; the remainder carries over
        flushModeTime()
        {
            for (const mode in modeMs)
            {
                const seconds = Math.floor(modeMs[mode] / 1000)
                if (seconds <= 0) continue
                modeMs[mode] -= seconds * 1000
                ANALYTICS.design('mode_time:' + mode, seconds)
            }
        },
        // type: fall | grapple | pause | restart | death | section | complete;
        // sectionId defaults to the player's current section
        mark(type, sectionId)
        {
            lastEvent = {type, sectionId: sectionId === undefined ? section() : sectionId}
        },
        lastEvent: () => lastEvent,
        // ui:pause:open:<user|auto> once per opening, ui:pause:close once
        // when the game unpauses after it
        pauseScreen(open, source)
        {
            if (open === pauseOpen) return
            pauseOpen = open
            ANALYTICS.design(open ? 'ui:pause:open:' + (source === 'user' ? 'user' : 'auto') : 'ui:pause:close')
        },
        // Gameplay falls (TASK-862), see createFallTelemetry
        falling: displacement => falls.falling(displacement),
        sendLongestFall: tag => falls.sendLongest(tag),
        sendQuitAfterLongFall: () => falls.sendQuitAfterLongFall(),
        fallBucket: displacement => falls.bucket(displacement),
        fallState: () => falls.state(),
        sendEnvironment: () => session.sendEnvironment(),
        classify: info => session.classify(info),
        flushPlayTime: () => session.flushPlayTime(),
        // PROGRESS: stored totals in, the totals to write out
        loadPlayTime: json => session.loadTotals(json),
        playTimeJson: () => session.savedTotals(),
        updatePlayTime: () => session.updateTotals(),
        playTime: () => session.playTime(),
        // pagehide: design('quit:<type>:<sectionId>') once per page
        sendQuit()
        {
            if (quitSent || !lastEvent) return
            quitSent = true
            ANALYTICS.design('quit:' + lastEvent.type + (lastEvent.sectionId ? ':' + lastEvent.sectionId : ''))
        }
    }
})()

// Session and environment telemetry (TASK-861), through ANALYTICS only (so
// it reaches GameAnalytics on the itch.io build alone). Ids and value ranges
// are listed in docs/platform-sdk.md ("Session telemetry"). No user agent
// string, no free text: the user agent is only parsed here into a family.
//
// Per frame (TELEMETRY.frame, active play only): one histogram increment and
// a few additions, no allocation. Every PERF_WINDOW_MS of active play: the
// perf:* events and the play time events; pagehide: the play time events.
// Total play time per grapnel mode is saved by PROGRESS through
// PLATFORM.storage (key grapnelninja_playtime_v1, read in the one boot get).
function createSession()
{
    const PERF_WINDOW_MS = 60000
    const MODES = ['single', 'double']
    // Frame-time histogram: BIN_MS bins up to MAX_MS, the last bin overflows
    const BIN_MS = 0.1, MAX_MS = 250, FREEZE_MS = 250
    // A longer frame (a stall, a sleep without blur) counts as this much play
    const MAX_PLAY_DT_MS = 1000
    const bins = new Uint32Array(Math.round(MAX_MS / BIN_MS) + 1)
    let windowFrames = 0, windowMs = 0, freezes = 0, envSent = false
    const sessionMs = {single: 0, double: 0}
    const baseMs = {single: 0, double: 0}

    // Rounded totals as last handed to PROGRESS (its snapshot reads them)
    let savedTotals = JSON.stringify(baseMs)

    // PROGRESS.load / recovery: the stored totals JSON (null when none); a
    // later or recovered read never lowers a total
    function loadTotals(json)
    {
        let saved = {}
        try { saved = JSON.parse(json || '{}') || {} } catch (e) {}
        for (const mode of MODES)
            if (typeof saved[mode] === 'number' && isFinite(saved[mode]) && saved[mode] > baseMs[mode])
                baseMs[mode] = saved[mode]
        savedTotals = currentTotals()
    }
    function currentTotals()
    {
        const totals = {}
        for (const mode of MODES) totals[mode] = Math.round(baseMs[mode] + sessionMs[mode])
        return JSON.stringify(totals)
    }
    // The totals go out in PROGRESS's next setMany (never per frame: every
    // PERF_WINDOW_MS of play and on pagehide)
    function saveTotals()
    {
        savedTotals = currentTotals()
        try { PROGRESS.save() } catch (e) {}
    }
    const clamp = (value, max) => Math.max(0, Math.min(max, value))
    // The histogram value below which `p` of the window's frames fall
    function histogramPercentile(p)
    {
        const rank = Math.ceil(windowFrames * p)
        let seen = 0
        for (let i = 0; i < bins.length; i++)
        {
            seen += bins[i]
            if (seen >= rank) return (i + 0.5) * BIN_MS
        }
        return MAX_MS
    }
    function sendPerf()
    {
        const p50 = histogramPercentile(0.5), p95 = histogramPercentile(0.95)
        ANALYTICS.design('perf:fps_p50', Math.round(clamp(1000 / p50, 240)))
        ANALYTICS.design('perf:fps_p5', Math.round(clamp(1000 / p95, 240)))
        ANALYTICS.design('perf:frame_ms_p95', Math.round(clamp(p95, MAX_MS) * 10) / 10)
        ANALYTICS.design('perf:freezes', clamp(freezes, 1000))
        bins.fill(0)
        // At most one window per frame, whatever the backlog
        windowFrames = 0; windowMs %= PERF_WINDOW_MS; freezes = 0
    }
    // Whole seconds this session and in total, for each mode played at all
    function flushPlayTime()
    {
        saveTotals()
        for (const mode of MODES)
        {
            const total = Math.floor((baseMs[mode] + sessionMs[mode]) / 1000)
            if (total <= 0) continue
            ANALYTICS.design('playtime:session:' + mode, clamp(Math.floor(sessionMs[mode] / 1000), 1e8))
            ANALYTICS.design('playtime:total:' + mode, clamp(total, 1e8))
        }
    }

    // Lower bound of the bucket `value` falls in (the first bucket below it)
    function bucket(value, bounds)
    {
        let result = bounds[0]
        for (const b of bounds) if (value >= b) result = b
        return result
    }
    function major(ua, pattern)
    {
        const m = ua.match(pattern)
        return m ? clamp(parseInt(m[1], 10) || 0, 999) : 0
    }
    // info: {ua, maxTouchPoints, coarse, screenWidth, screenHeight,
    // viewWidth, viewHeight, dpr, browserLanguage, gameLanguage}
    // -> [[id, value?], ...] (pure; the ids need no sanitizing)
    function classify(info)
    {
        const ua = String(info.ua || '')
        const browsers = [
            ['edge', /Edg(?:e|A|iOS)?\/(\d+)/], ['opera', /(?:OPR|Opera)\/(\d+)/],
            ['samsung', /SamsungBrowser\/(\d+)/], ['yandex', /YaBrowser\/(\d+)/],
            ['firefox', /(?:Firefox|FxiOS)\/(\d+)/], ['chrome', /(?:Chrome|CriOS)\/(\d+)/],
            ['safari', /Version\/(\d+)[.\d]* (?:Mobile\/\S+ )?Safari\//]]
        let browser = ['other', 0]
        for (const [name, pattern] of browsers)
            if (pattern.test(ua)) { browser = [name, major(ua, pattern)]; break }
        const touchMac = /Macintosh/.test(ua) && info.maxTouchPoints > 1
        const os = /Windows/.test(ua) ? 'windows'
            : /iPhone|iPad|iPod/.test(ua) || touchMac ? 'ios'
            : /Android/.test(ua) ? 'android'
            : /CrOS/.test(ua) ? 'chromeos'
            : /Macintosh|Mac OS X/.test(ua) ? 'macos'
            : /Linux/.test(ua) ? 'linux' : 'other'
        const device = /iPad/.test(ua) || touchMac || (/Android/.test(ua) && !/Mobile/.test(ua)) ? 'tablet'
            : /iPhone|iPod|Mobi|Android/.test(ua) ? 'phone' : 'desktop'
        const widths = [0, 320, 360, 400, 480, 600, 768, 1024, 1280, 1366, 1440, 1600, 1920, 2560, 3840]
        const heights = [0, 320, 360, 480, 540, 600, 720, 768, 800, 900, 1080, 1200, 1440, 2160]
        const size = (w, h) => bucket(w, widths) + 'x' + bucket(h, heights)
        const dpr = bucket(Number(info.dpr) || 1, [1, 1.25, 1.5, 2, 2.5, 3, 4])
        const browserLanguage = String(info.browserLanguage || '').toLowerCase().split('-')[0]
        const gameLanguage = String(info.gameLanguage || '')
        return [
            ['env:browser:' + browser[0], browser[1]],
            ['env:os:' + os],
            ['env:device:' + device],
            ['env:input:' + (info.coarse ? 'touch' : 'mouse')],
            ['env:screen:' + size(info.screenWidth, info.screenHeight) + ':dpr' + dpr],
            ['env:viewport:' + size(info.viewWidth, info.viewHeight)],
            ['env:lang:' + (/^[a-z]{2}$/.test(gameLanguage) ? gameLanguage : 'other') + ':' +
                (/^[a-z]{2,3}$/.test(browserLanguage) ? browserLanguage : 'other')]]
    }

    return {
        frame(dt, grapnelMode)
        {
            bins[dt < MAX_MS ? Math.floor(dt / BIN_MS) : bins.length - 1]++
            windowFrames++
            if (dt > FREEZE_MS) freezes++
            const played = dt < MAX_PLAY_DT_MS ? dt : MAX_PLAY_DT_MS
            windowMs += played
            if (grapnelMode === 'single' || grapnelMode === 'double') sessionMs[grapnelMode] += played
            if (windowMs >= PERF_WINDOW_MS)
            {
                sendPerf()
                flushPlayTime()
            }
        },
        // Once per page, after the game language is known
        // (window.screen: the game has its own global `screen`); never throws
        sendEnvironment()
        {
            if (envSent) return
            envSent = true
            try
            {
                let coarse = false
                try { coarse = matchMedia('(pointer: coarse)').matches } catch (e) {}
                const device = window.screen || {}
                const events = classify({
                    ua: navigator.userAgent, maxTouchPoints: navigator.maxTouchPoints || 0, coarse,
                    screenWidth: device.width, screenHeight: device.height,
                    viewWidth: window.innerWidth, viewHeight: window.innerHeight,
                    dpr: window.devicePixelRatio, browserLanguage: navigator.language,
                    gameLanguage: typeof I18N !== 'undefined' ? I18N.language : ''})
                for (const [id, value] of events) ANALYTICS.design(id, value)
            }
            catch (e) {}
        },
        classify,
        flushPlayTime,
        loadTotals,
        savedTotals: () => savedTotals,
        updateTotals() { savedTotals = currentTotals() },
        // ms, for tests: {session: {single, double}, total: {single, double}}
        playTime: () => ({session: {...sessionMs},
            total: {single: baseMs.single + sessionMs.single, double: baseMs.double + sessionMs.double}})
    }
}

// Gameplay fall telemetry (TASK-862), through ANALYTICS only. A fall is the
// continuous drop LONG_FALL measures (from the last catch or apex: y - startY,
// game units). Ids and buckets are listed in docs/platform-sdk.md ("Gameplay
// and UI telemetry").
//
// falling(): every physics cycle of a Grapple Over run (LONG_FALL.step), so
// it only compares numbers; past LONG_FALL_THRESHOLD it also remembers the
// fall's section and the wall-clock time for the quit-after-long-fall check.
function createFallTelemetry()
{
    const BUCKETS = [0, 1000, 2000, 4000, 6000, 10000, 15000, 20000, 30000, 50000, 75000, 100000, 150000]
    const QUIT_WINDOW_MS = 30000
    // The session's longest single fall (raw units), the last long fall
    let longest = 0, longFall = null, quitSent = false, previous = 0

    // Lower bound of the bucket the distance falls in
    function bucket(displacement)
    {
        let result = 0
        for (const b of BUCKETS) if (displacement >= b) result = b
        return result
    }
    return {
        bucket,
        falling(displacement)
        {
            const before = previous
            previous = displacement
            if (!(displacement > 0)) return
            if (displacement > longest) longest = displacement
            if (displacement <= LONG_FALL_THRESHOLD) return
            // A new long fall unless the same one just went on growing
            if (!longFall || before <= LONG_FALL_THRESHOLD || displacement < before)
                longFall = {section: climbFallSection()}
            longFall.displacement = displacement
            longFall.at = Date.now()
        },
        // design('longest_fall:<tag>', bucket): 'session' on pagehide,
        // 'complete' at the summit; nothing before any fall
        sendLongest(tag)
        {
            if (longest > 0) ANALYTICS.design('longest_fall:' + tag, bucket(longest))
        },
        // pagehide within QUIT_WINDOW_MS after the last moment of a fall
        // longer than LONG_FALL_THRESHOLD: design('quit_long_fall:<section>', bucket)
        sendQuitAfterLongFall()
        {
            if (quitSent || !longFall || Date.now() - longFall.at > QUIT_WINDOW_MS) return
            quitSent = true
            ANALYTICS.design('quit_long_fall:' + longFall.section, bucket(longFall.displacement))
        },
        // For tests
        state: () => ({longest, longFall: longFall && {...longFall}})
    }
}
