// Opt-in frame profiler (?perf=1 only): times every draw() layer and the
// physics update step with performance.now() over the last WINDOW frames.
// Read it from the console with PERF_PROFILE.snapshot(). It never sends
// anything anywhere. samples is how many of the last WINDOW calls an entry
// holds (0: the layer was not drawn, e.g. bloom off at this quality).
// Without the flag nothing is wrapped and PERF_PROFILE stays undefined.
if (new URLSearchParams(location.search).get('perf') === '1')
{
    (function()
    {
        const WINDOW = 120
        const LAYERS = {
            background: 'drawBackgroundLayer',
            lights: 'drawLightsLayer',
            behindForegroundParticles: 'drawBehindForegroundParticlesLayer',
            playerTrail: 'drawPlayerTrailLayer',
            world: 'drawWorldLayer',
            particlesAndTrails: 'drawParticlesAndTrailsLayer',
            bloom: 'drawBloomLayer',
            playerGlow: 'drawPlayerGlowLayer',
            colorGrade: 'drawColorGradeLayer',
            player: 'drawPlayerLayer',
            tutorialHint: 'drawTutorialHintLayer',
            ui: 'drawUILayer',
            fpsCounter: 'drawFpsCounterLayer',
        }
        const entries = []
        const frameTimes = new Float64Array(WINDOW)
        let frames = 0

        function wrap(name, globalName)
        {
            const fn = window[globalName]
            const entry = {name, samples: new Float64Array(WINDOW), count: 0}
            entries.push(entry)
            window[globalName] = function()
            {
                const start = performance.now()
                try
                {
                    return fn.apply(this, arguments)
                }
                finally
                {
                    entry.samples[entry.count++ % WINDOW] = performance.now() - start
                }
            }
        }

        for (const name in LAYERS)
            wrap(name, LAYERS[name])

        // The game loop and its physics step live in index.html's inline
        // script, which has run by DOMContentLoaded
        document.addEventListener('DOMContentLoaded', () =>
        {
            wrap('update', 'runFixedPhysics')
            const gameLoop = window.gameLoop
            window.gameLoop = function()
            {
                frameTimes[frames++ % WINDOW] = performance.now()
                return gameLoop.apply(this, arguments)
            }
        })

        function stats(entry)
        {
            const n = Math.min(entry.count, WINDOW)
            if (!n)
                return {name: entry.name, meanMs: 0, p95Ms: 0, samples: 0}
            const sorted = Array.from(entry.samples.subarray(0, n)).sort((a, b) => a - b)
            const mean = sorted.reduce((sum, v) => sum + v, 0) / n
            return {name: entry.name, meanMs: mean, p95Ms: sorted[Math.ceil(n * 0.95) - 1], samples: n}
        }

        window.PERF_PROFILE = {
            snapshot()
            {
                const n = Math.min(frames, WINDOW)
                const newest = frameTimes[(frames - 1) % WINDOW]
                const oldest = frameTimes[frames > WINDOW ? frames % WINDOW : 0]
                const rafFps = n > 1 && newest > oldest ? (n - 1) * 1000 / (newest - oldest) : 0
                return {
                    frames,
                    rafFps,
                    entries: entries.map(stats).sort((a, b) => b.meanMs - a.meanMs),
                }
            },
        }
    })()
}
