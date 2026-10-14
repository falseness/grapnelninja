// Opt-in frame profiler (?perf=1 only): times every draw() layer and the
// physics update step with performance.now() over the last WINDOW frames.
// Read it from the console with PERF_PROFILE.snapshot(). It never sends
// anything anywhere. samples is how many of the last WINDOW calls an entry
// holds (0: the layer was not drawn, e.g. bloom off at this quality).
// With the flag a panel in the canvas's bottom-left corner shows the RAF
// FPS, the frame count and the slowest entries, drawn after the HUD and
// refreshed at most every REFRESH_MS (PERF_OVERLAY).
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

        function wrap(name, globalName, owner = window)
        {
            const fn = owner[globalName]
            const entry = {name, samples: new Float64Array(WINDOW), count: 0}
            entries.push(entry)
            owner[globalName] = function()
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
        // Mote glow and copy of the reduced backdrop (render/backdrop.js);
        // no samples while the frame is at full quality
        wrap('backdrop', 'end', BACKDROP)

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

        const REFRESH_MS = 500
        const TOP_ENTRIES = 6
        const FONT_CSS_PX = 12
        const LINE_CSS_PX = 15
        const PADDING_CSS_PX = 6
        const MARGIN_CSS_PX = 8

        // Panel in CSS px relative to the canvas; rect is the last drawn one
        window.PERF_OVERLAY = {
            enabled: true,
            lines: null,
            refreshedAt: -Infinity,
            refreshes: 0,
            rect: null,
            refresh(now)
            {
                const snap = PERF_PROFILE.snapshot()
                this.lines = ['FPS ' + snap.rafFps.toFixed(2) + '  frames ' + snap.frames]
                for (const e of snap.entries.slice(0, TOP_ENTRIES))
                    this.lines.push(e.name + ' ' + e.meanMs.toFixed(2) + ' / ' + e.p95Ms.toFixed(2))
                this.refreshedAt = now
                ++this.refreshes
            },
            draw()
            {
                if (!this.enabled)
                    return
                const now = performance.now()
                if (!this.lines || now - this.refreshedAt >= REFRESH_MS)
                    this.refresh(now)

                const css = getCanvasCssRect()
                ctx.save()
                ctx.setTransform(canvas.width / css.width, 0, 0, canvas.height / css.height, 0, 0)
                ctx.font = FONT_CSS_PX + 'px ' + STYLE.ui.fontFamily
                ctx.textAlign = 'start'
                ctx.textBaseline = 'middle'
                const textWidth = Math.max(...this.lines.map(line => ctx.measureText(line).width))
                const w = Math.min(textWidth + PADDING_CSS_PX * 2, css.width - MARGIN_CSS_PX * 2)
                const h = this.lines.length * LINE_CSS_PX + PADDING_CSS_PX * 2
                const x = MARGIN_CSS_PX
                const y = css.height - MARGIN_CSS_PX - h
                ctx.fillStyle = 'rgba(0, 0, 0, 0.7)'
                ctx.fillRect(x, y, w, h)
                ctx.fillStyle = '#e8fff4'
                this.lines.forEach((line, i) =>
                    ctx.fillText(line, x + PADDING_CSS_PX, y + PADDING_CSS_PX + (i + 0.5) * LINE_CSS_PX))
                this.rect = {x, y, width: w, height: h, fontPx: FONT_CSS_PX}
                LAYOUT_PROBE.rect('perf', 'perf-panel', x, y, w, h)
                ctx.restore()
            },
        }

        const draw = window.draw
        window.draw = function()
        {
            const result = draw.apply(this, arguments)
            PERF_OVERLAY.draw()
            return result
        }
    })()
}
