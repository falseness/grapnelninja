// Product milestones measure active runs, independently of Bridge's built-in
// time-since-ready milestones. No identifiers or unbounded fields are sent.
const TELEMETRY = (() =>
{
    let last = null, total = 0, nextMilestone = 30
    let frames = [], active = 0, windowStart = null
    const percentile = (sorted, p) => sorted[Math.floor((sorted.length - 1) * p)]
    function resetClock() { last = null }
    document.addEventListener('visibilitychange', resetClock)
    window.addEventListener('blur', resetClock)
    return {
        frame(now, playing, mode)
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
        }
    }
})()
