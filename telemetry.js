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
        // pagehide: design('quit:<type>:<sectionId>') once per page
        sendQuit()
        {
            if (quitSent || !lastEvent) return
            quitSent = true
            ANALYTICS.design('quit:' + lastEvent.type + (lastEvent.sectionId ? ':' + lastEvent.sectionId : ''))
        }
    }
})()
