// Fast backdrop for slow canvases (adaptive quality). The background, the
// obstacle light spill and the ambient-mote glow are soft full-frame layers;
// a software canvas such as Firefox's pays every one of their full-frame
// fills and blends per pixel. When the measured frame time stays above
// SLOW_FRAME_MS after a warm-up, they are drawn into one offscreen canvas at
// FAST_SCALE of the frame resolution and copied into the frame with a single
// drawImage. The motes, the world, the player and the HUD stay at full
// resolution. A fast browser never leaves full quality, so its frames are
// unchanged.
//   ?backdrop=<0.25..1>  forces the backdrop scale and turns the switch off
//                        (1: always full quality), for A/B measurements
const BACKDROP = (function()
{
    const FAST_SCALE = 0.5
    // Shader compilation and first tile builds make the first seconds slow
    // on every device: they are not judged
    const WARMUP_MS = 5000
    const WINDOW_MS = 2000
    // Below about 45 FPS
    const SLOW_FRAME_MS = 1000 / 45
    // Longer gaps are pauses, hidden tabs or ads, not frame time
    const MAX_FRAME_GAP_MS = 250

    const forced = Number(new URLSearchParams(location.search).get('backdrop'))
    const isForced = forced >= 0.25 && forced <= 1

    return {
        scale: isForced ? forced : 1,
        adaptive: !isForced,
        active: false,
        // drawFrameId whose mote glow already went into the backdrop
        glowFrame: -1,
        canvas: null,
        ctx: null,
        saved: null,
        firstAt: null,
        lastAt: null,
        windowMs: 0,
        windowFrames: 0,
        // Feeds one frame time; switches to the fast backdrop once a whole
        // window after the warm-up averages slower than SLOW_FRAME_MS
        observe(now)
        {
            if (!this.adaptive || this.scale < 1)
                return
            const last = this.lastAt
            this.lastAt = now
            if (this.firstAt === null)
                this.firstAt = now
            if (last === null || now - this.firstAt < WARMUP_MS || now - last > MAX_FRAME_GAP_MS)
                return
            this.windowMs += now - last
            ++this.windowFrames
            if (this.windowMs < WINDOW_MS)
                return
            if (this.windowMs / this.windowFrames > SLOW_FRAME_MS)
                this.scale = FAST_SCALE
            this.windowMs = 0
            this.windowFrames = 0
        },
        // Frame start, in the frame's base transform: points the backdrop
        // renderers at the offscreen canvas. False at full quality.
        begin()
        {
            if (this.scale >= 1)
                return false
            if (!this.canvas)
            {
                this.canvas = document.createElement('canvas')
                this.ctx = this.canvas.getContext('2d', {alpha: false})
            }
            const w = Math.max(1, Math.round(canvas.width * this.scale))
            const h = Math.max(1, Math.round(canvas.height * this.scale))
            if (this.canvas.width != w || this.canvas.height != h)
            {
                this.canvas.width = w
                this.canvas.height = h
            }
            this.ctx.globalAlpha = 1
            this.ctx.globalCompositeOperation = 'source-over'
            this.ctx.imageSmoothingEnabled = true
            this.syncTransform()
            const renderers = [visualEffects.background, visualEffects.lightmap, visualEffects.ambientGlow]
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
        // Adds the mote glow into the backdrop (under the full-resolution
        // motes), gives the renderers their frame back and copies the backdrop in
        end()
        {
            if (!this.active)
                return
            visualEffects.ambientGlow.drawScreen(() => visualEffects.particles.drawAmbientMotes())
            this.glowFrame = drawFrameId
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
