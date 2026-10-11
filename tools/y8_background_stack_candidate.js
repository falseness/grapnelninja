// TASK-279 candidate: cache the far background stack (page-injected for the experiment;
// identical method bodies are what an ACCEPT would paste into render/effects.js).
//
// Target (TASK-277 cache profile, dpr1): the background is 6 full-frame raster passes per frame
// (clear, base gradient fill, far crystal tile copies, haze fill, near tile copies, vignette
// fill) and costs 22-40 ms of a 95-110 ms frame. The gradient, far tile and haze passes depend
// on the viewport, backing store, transform, colours, the far tile and the far layer's y shift
// only; the x shift is a periodic offset that drawLayerTile already applies with device-snapped
// 1:1 copies. So those three passes are painted once into a one-tile-wide "far stack" canvas at
// backing resolution and tiled at the x shift. Hit: clear + stack copies + near copies +
// vignette (4 passes). Miss (key changed): the three passes into the stack + the copies.
// The window bars (other bounds, 1/4 scale, repainted every 4 frames) keep the direct path.
(() => {
const methods = {
    paint()
    {
        this.clearAll()

        if (!STYLE.features.background)
            return

        const width = LOGICAL_VIEWPORT.width
        const height = LOGICAL_VIEWPORT.height

        const caveLayers = STYLE.caveLayers

        this.drawFarStack(width, height, this.getLayerShift(width, height, caveLayers.crystals))
        this.preserveGameplayRandomSequence(1, 40)
        this.drawNearLayer(width, height, this.getLayerShift(width, height, caveLayers.nearRocks))
        this.drawVignette(width, height)
    },
    paintMenu()
    {
        this.clearAll()

        if (!STYLE.features.background)
            return

        const width = LOGICAL_VIEWPORT.width
        const height = LOGICAL_VIEWPORT.height

        this.drawFarStack(width, height, this.getMenuLayerShift(1))
        this.preserveGameplayRandomSequence(2, 18)
        this.drawNearLayer(width, height, this.getMenuLayerShift(1.5))
        this.drawVignette(width, height)
    },
    // Base gradient, far crystal layer and haze. On the game canvas under the
    // base transform these three full-frame passes depend only on the viewport,
    // the backing store, the colours, the far tile and the layer's y shift: they
    // are painted once into a one-tile-wide stack canvas at backing resolution
    // (key below) and tiled at the x shift with device-snapped 1:1 copies,
    // exactly as the crystal tile alone is tiled. Other bounds (the window
    // bars) or another transform paint the three passes directly.
    drawFarStack(width, height, shift)
    {
        const transform = this.ctx.getTransform()
        const baseA = this.canvas.width / width
        const baseD = this.canvas.height / height
        // Only the base transform set by configureCanvasViewport (stored in
        // single precision by the canvas) maps the stack 1:1 onto the canvas.
        // In bad mode draw()'s per-frame scale(s)/scale(1/s) drifts the stored
        // transform by ~5e-8 per frame, so a stack copy would resample: those
        // frames paint directly and stay exact.
        const isBase = (transform.a === baseA || transform.a === Math.fround(baseA))
            && (transform.d === baseD || transform.d === Math.fround(baseD))
            && transform.b === 0 && transform.c === 0 && transform.e === 0 && transform.f === 0
        const direct = this.bounds || !isBase

        if (direct)
        {
            this.drawBaseGradient(width, height)
            this.drawCrystalLayer(width, height, shift)
            this.drawHaze(width, height)
            return
        }

        const colors = STYLE.colors.background
        const layer = this.getLayerTile('far', width, height, STYLE.caveLayers.crystals,
            (...args) => this.paintCrystalTile(...args))
        const key = [
            width, height, this.canvas.width, this.canvas.height, shift.y, layer.key,
            colors.gradientTop, colors.gradientMiddle, colors.gradientBottom,
            colors.hazeTop, colors.hazeUpper, colors.hazeMiddle, colors.hazeLower, colors.hazeBottom,
            colors.crystalRock
        ].join('|')
        let stack = this.farStack

        if (!stack || stack.key !== key)
            stack = this.buildFarStack(key, width, height, shift, layer)
        this.drawLayerTile(stack, width, height, {x: shift.x, y: 0}, colors.crystalRock)
    },
    // Paints the three far passes once into the stack canvas (reused across
    // rebuilds) under the base transform, so its device pixels equal what the
    // direct passes would put on the game canvas at x shift 0
    buildFarStack(key, width, height, shift, layer)
    {
        const stackCanvas = this.farStack ? this.farStack.canvas : document.createElement('canvas')

        if (stackCanvas.width != this.canvas.width)
            stackCanvas.width = this.canvas.width
        if (stackCanvas.height != this.canvas.height)
            stackCanvas.height = this.canvas.height

        const stackCtx = stackCanvas.getContext('2d')
        stackCtx.setTransform(this.canvas.width / width, 0, 0, this.canvas.height / height, 0, 0)
        stackCtx.clearRect(0, 0, width, height)

        const gameCtx = this.ctx
        this.ctx = stackCtx
        try
        {
            this.drawBaseGradient(width, height)
            this.drawLayerTile(layer, width, height, {x: 0, y: shift.y}, STYLE.colors.background.crystalRock)
            this.drawHaze(width, height)
        }
        finally
        {
            this.ctx = gameCtx
        }

        const stack = {key, canvas: stackCanvas, width, height}
        this.farStack = stack
        return stack
    }
}
Object.assign(BackgroundRenderer.prototype, methods)
})()
