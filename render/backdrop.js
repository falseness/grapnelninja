// Fast backdrop for slow canvases (adaptive quality). The background, the
// obstacle light spill and the ambient-mote glow are soft full-frame layers;
// a software canvas such as Firefox's pays every one of their full-frame
// fills and blends per pixel. When the measured frame time stays above
// SLOW_FRAME_MS after a warm-up, they are drawn into one offscreen canvas at
// FAST_SCALE of the frame resolution and copied into the frame with a single
// drawImage. The motes, the world, the player and the HUD stay at full
// resolution. If frames are still slow, later windows lower the whole
// canvas backing resolution (RESOLUTION_STEPS, applied by
// configureCanvasViewport through a resize), which also cuts the browser's
// own cost of painting the canvas. A fast browser never leaves full quality,
// so its frames are unchanged.
//   ?backdrop=<0.25..1>  forces the backdrop scale and turns the switch off
//                        (1: always full quality), for A/B measurements
// Automated browsers (navigator.webdriver: the test harnesses, whose
// headless frame rate says nothing about players) stay at full quality
// unless ?adaptive=1 asks for the switch.
// Momentum lighting caps the backdrop by size (sizeCap), measured or not:
// its ambient multiply, crystal rim, haze, deep shadows and light spill are
// each a full-frame pass over the backdrop, but their sources are no finer
// than LOGICAL_VIEWPORT px (background and edge tiles) and the small light
// canvases. Past MAX_LIT_PX_PER_TILE_PX backing px per logical px the lit
// backdrop is drawn at that density and copied up: 1920x1080 at DPR 3
// (5760x3240, 2-4 s a frame in a software canvas) gets a 2715x1527
// backdrop; the mote glow stays at full resolution there. Smaller backings
// and momentum without lighting are unchanged.
const BACKDROP = (function()
{
    const FAST_SCALE = 0.5
    // Shader compilation and first tile builds make the first seconds slow
    // on every device: they are not judged (no automatic quality
    // downgrade within the first 5-10 s)
    const WARMUP_MS = 10000
    const WINDOW_MS = 2000
    // Below about 45 FPS
    const SLOW_FRAME_MS = 1000 / 45
    // Longer gaps are pauses, hidden tabs or ads, not frame time
    const MAX_FRAME_GAP_MS = 250
    // Canvas resolution after the fast backdrop, one step per slow window
    const RESOLUTION_STEPS = [0.75, 0.5]
    // Backing px per CSS px never goes below this
    const MIN_DEVICE_RESOLUTION = 0.6
    // A step rebuilds caches and sprites: its first frames are not judged
    const SETTLE_MS = 1000
    // Lit backdrop px per logical px (area) at most (sizeCap)
    const MAX_LIT_PX_PER_TILE_PX = 2

    const params = new URLSearchParams(location.search)
    const forced = Number(params.get('backdrop'))
    const isForced = forced >= 0.25 && forced <= 1
    const automated = navigator.webdriver === true && params.get('adaptive') !== '1'

    return {
        scale: isForced ? forced : 1,
        adaptive: !isForced && !automated,
        // Multiplies the canvas backing resolution (configureCanvasViewport)
        resolution: 1,
        active: false,
        // drawFrameId whose mote glow already went into the backdrop
        glowFrame: -1,
        // The frame's mote glow goes into the backdrop (the measured switch
        // only: its blur is sized in backdrop px, so under the size cap alone
        // the glow stays at full resolution)
        glowInBackdrop: false,
        canvas: null,
        ctx: null,
        saved: null,
        firstAt: null,
        settleUntil: 0,
        lastAt: null,
        windowMs: 0,
        windowFrames: 0,
        // Feeds one frame time; takes the next quality step (fast backdrop,
        // then lower resolutions) whenever a whole window after the warm-up
        // averages slower than SLOW_FRAME_MS
        observe(now)
        {
            if (!this.adaptive)
                return
            const last = this.lastAt
            this.lastAt = now
            if (this.firstAt === null)
                this.firstAt = now
            if (last === null || now - this.firstAt < WARMUP_MS || now < this.settleUntil ||
                now - last > MAX_FRAME_GAP_MS)
                return
            this.windowMs += now - last
            ++this.windowFrames
            if (this.windowMs < WINDOW_MS)
                return
            const slow = this.windowMs / this.windowFrames > SLOW_FRAME_MS
            this.windowMs = 0
            this.windowFrames = 0
            if (slow && this.stepDown())
                this.settleUntil = now + SETTLE_MS
        },
        // The next quality step; false when none is left
        stepDown()
        {
            if (this.scale >= 1)
            {
                this.scale = FAST_SCALE
                return true
            }
            const dpr = window.devicePixelRatio || 1
            const next = RESOLUTION_STEPS.find(r => r < this.resolution && r * dpr >= MIN_DEVICE_RESOLUTION)
            if (next === undefined)
            {
                this.adaptive = false
                return false
            }
            this.resolution = next
            // The resize path re-lays out the canvas at the new resolution
            window.dispatchEvent(new Event('resize'))
            return true
        },
        // The backdrop scale momentum lighting allows at this backing size
        // (1: no cap)
        sizeCap()
        {
            if (version != 'momentum' || !MOMENTUM_FX.enabled)
                return 1
            const logical = LOGICAL_VIEWPORT.width * LOGICAL_VIEWPORT.height
            return Math.min(1, Math.sqrt(MAX_LIT_PX_PER_TILE_PX * logical / (canvas.width * canvas.height)))
        },
        // The backdrop canvas width the next frame draws the backdrop
        // renderers into (0: full quality, the frame's own canvas)
        frameWidth()
        {
            const scale = Math.min(this.scale, this.sizeCap())
            return scale >= 1 ? 0 : Math.max(1, Math.round(canvas.width * scale))
        },
        // Frame start, in the frame's base transform: points the backdrop
        // renderers at the offscreen canvas. False at full quality.
        begin()
        {
            const width = this.frameWidth()
            if (!width)
                return false
            if (!this.canvas)
            {
                this.canvas = document.createElement('canvas')
                this.ctx = this.canvas.getContext('2d', {alpha: false})
            }
            const scale = Math.min(this.scale, this.sizeCap())
            const w = width
            const h = Math.max(1, Math.round(canvas.height * scale))
            if (this.canvas.width != w || this.canvas.height != h)
            {
                this.canvas.width = w
                this.canvas.height = h
            }
            this.ctx.globalAlpha = 1
            this.ctx.globalCompositeOperation = 'source-over'
            this.ctx.imageSmoothingEnabled = true
            this.syncTransform()
            this.glowInBackdrop = this.scale < 1
            const renderers = [visualEffects.background, visualEffects.lightmap]
            if (this.glowInBackdrop)
                renderers.push(visualEffects.ambientGlow)
            this.saved = renderers.map(renderer => [renderer, renderer.ctx, renderer.canvas])
            for (const renderer of renderers)
            {
                renderer.ctx = this.ctx
                renderer.canvas = this.canvas
            }
            this.active = true
            return true
        },
        // The frame's current transform (world scale, screen shake) mapped
        // onto the backdrop
        syncTransform()
        {
            const m = ctx.getTransform()
            const sx = this.canvas.width / canvas.width
            const sy = this.canvas.height / canvas.height
            this.ctx.setTransform(m.a * sx, m.b * sy, m.c * sx, m.d * sy, m.e * sx, m.f * sy)
        },
        // Adds the mote glow into the backdrop (glowInBackdrop; under the
        // full-resolution motes), gives the renderers their frame back and
        // copies the backdrop in
        end()
        {
            if (!this.active)
                return
            if (this.glowInBackdrop)
            {
                visualEffects.ambientGlow.drawScreen(() => visualEffects.particles.drawAmbientMotes())
                this.glowFrame = drawFrameId
            }
            for (const [renderer, context, target] of this.saved)
            {
                renderer.ctx = context
                renderer.canvas = target
            }
            this.saved = null
            this.active = false
            ctx.save()
            ctx.setTransform(1, 0, 0, 1, 0, 0)
            ctx.globalAlpha = 1
            ctx.globalCompositeOperation = 'source-over'
            ctx.imageSmoothingEnabled = true
            ctx.drawImage(this.canvas, 0, 0, canvas.width, canvas.height)
            ctx.restore()
        }
    }
})()
