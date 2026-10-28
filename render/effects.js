// The bars only show soft gradients and faint lines, so the bar canvases
// render at a quarter of their CSS size and CSS stretches them: a
// full-resolution repaint cost ~30% of the frame at 2560x1080
const WINDOW_BACKGROUND_SCALE = 0.25

// The bars background drifts slowly: it is repainted every few frames (and at
// once after a resize or a menu/game switch), which also spares the
// compositor a texture upload on the frames in between
const WINDOW_BARS_EVERY_FRAMES = 4
// Resolution of the smooth baked layers (BackgroundRenderer.getSmoothImage)
const SMOOTH_IMAGE_SCALE = 0.25

// Each bar canvas reaches this far (CSS px) under the play rect, so the bars
// stay opaque under the game canvas's antialiased (fractional) edge row and
// the low-resolution upscale; a full-window canvas would be blended under
// the whole play rect every frame (~7% of the frame at 2560x1080)
const WINDOW_BAR_OVERLAP_PX = 2 + 2 / WINDOW_BACKGROUND_SCALE

// CSS boxes of the two letterbox bars (left/right or top/bottom of the play
// rect), or [] when the play rect fills the window.
function windowBarBoxes(rect)
{
    const overlap = WINDOW_BAR_OVERLAP_PX
    const view = getViewSize()
    const right = rect.left + rect.width
    const bottom = rect.top + rect.height

    if (rect.left >= 0.5)
        return [{left: 0, top: 0, width: rect.left + overlap, height: view.height},
                {left: right - overlap, top: 0, width: view.width - right + overlap, height: view.height}]
    if (rect.top >= 0.5)
        return [{left: 0, top: 0, width: view.width, height: rect.top + overlap},
                {left: 0, top: bottom - overlap, width: view.width, height: view.height - bottom + overlap}]
    return []
}

// Places the two bar canvases behind the game canvas over the letterbox
// bars; their backing stores follow their CSS size at WINDOW_BACKGROUND_SCALE.
function configureWindowBackground()
{
    const boxes = windowBarBoxes(getCanvasCssRect())

    Array.from(document.getElementsByClassName('window-bar')).forEach((barCanvas, i) =>
    {
        const box = boxes[i]

        barCanvas.hidden = !box
        barCanvas.box = box || null
        // Resizing the backing store clears it
        barCanvas.barsKey = null
        if (!box)
            return
        barCanvas.style.left = box.left + 'px'
        barCanvas.style.top = box.top + 'px'
        barCanvas.style.width = box.width + 'px'
        barCanvas.style.height = box.height + 'px'
        barCanvas.width = Math.max(1, Math.ceil(box.width * WINDOW_BACKGROUND_SCALE))
        barCanvas.height = Math.max(1, Math.ceil(box.height * WINDOW_BACKGROUND_SCALE))
    })
}

// Linear mix of two 'rgba(r, g, b, a)' colors, t in [0, 1].
function mixRgba(from, to, t)
{
    const a = from.match(/[\d.]+/g).map(Number)
    const b = to.match(/[\d.]+/g).map(Number)
    const mix = a.map((value, i) => value + ((b[i] === undefined ? 1 : b[i]) - value) * t)

    return 'rgba(' + mix.slice(0, 3).map(Math.round).join(', ') + ', ' + (mix[3] === undefined ? 1 : mix[3]) + ')'
}

class BackgroundRenderer
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
        this.randomSequenceScenes = 0
        this.gradientCache = new Map()
        this.lastGameGradients = null
        // Grapple Over section palette for this frame (drawBackgroundLayer)
        this.palette = null
        // Neighbour palettes to build ahead (grappleOverPaletteAhead)
        this.paletteAhead = []
        // Its parallax silhouettes (render/parallax.js), ?parallax=0 turns
        // them off for A/B measurements; what the last frame used
        this.parallaxEnabled = new URLSearchParams(location.search).get('parallax') !== '0'
        this.parallaxFrame = null
        // Offscreen crystal/rock tiles by name ('far', 'near')
        this.layerCache = {}
    }
    draw()
    {
        this.paint()
        this.drawWindowBars('game', () => this.paint())
    }
    // Area the full-size fills cover: the logical viewport, or a bar canvas
    // (in logical units) while drawWindowBars paints the bars.
    fillBounds()
    {
        return this.bounds || {x: 0, y: 0, width: LOGICAL_VIEWPORT.width, height: LOGICAL_VIEWPORT.height}
    }
    fillAll()
    {
        const bounds = this.fillBounds()
        this.ctx.fillRect(bounds.x, bounds.y, bounds.width, bounds.height)
    }
    clearAll()
    {
        const bounds = this.fillBounds()
        this.ctx.clearRect(bounds.x, bounds.y, bounds.width, bounds.height)
    }
    // Repeats this frame's background on the two bar canvases behind the
    // game canvas, in the same logical coordinates, so the picture continues
    // past the play rect.
    drawWindowBars(scene, paint)
    {
        const barCanvases = Array.from(document.getElementsByClassName('window-bar')).filter(c => c.box)
        const rect = getCanvasCssRect()

        if (!barCanvases.length)
            return

        // A Grapple Over band change repaints them at once; a blend every 1/20
        const palette = this.palette
        const key = [scene, rect.left, rect.top, rect.width,
            palette ? palette.from + ':' + palette.to + ':' + Math.round(palette.t * 20) : ''].join()
        if (barCanvases[0].barsKey === key && ++this.barsFramesSkipped < WINDOW_BARS_EVERY_FRAMES)
            return
        this.barsFramesSkipped = 0

        const gameCtx = this.ctx
        const fit = rect.width / LOGICAL_VIEWPORT.width

        for (const barCanvas of barCanvases)
        {
            const box = barCanvas.box
            // GRADIENT_DITHER: painted into a float16 copy (its gradient fills
            // are not dithered) and copied in
            const target = barCanvas.getContext('2d')
            const ctx = GRADIENT_DITHER.enabled ? this.getBarScratch(barCanvas) : target
            const scaleX = barCanvas.width / box.width
            const scaleY = barCanvas.height / box.height

            barCanvas.barsKey = key
            ctx.setTransform(fit * scaleX, 0, 0, fit * scaleY,
                (rect.left - box.left) * scaleX, (rect.top - box.top) * scaleY)
            this.bounds = {
                x: (box.left - rect.left) / fit,
                y: (box.top - rect.top) / fit,
                width: box.width / fit,
                height: box.height / fit
            }
            this.ctx = ctx
            try
            {
                paint()
            }
            finally
            {
                this.ctx = gameCtx
                this.bounds = null
            }
            if (ctx !== target)
            {
                target.save()
                target.setTransform(1, 0, 0, 1, 0, 0)
                target.globalCompositeOperation = 'copy'
                target.drawImage(ctx.canvas, 0, 0)
                target.restore()
            }
        }
    }
    // A float16 canvas the size of barCanvas (its own, kept on it)
    getBarScratch(barCanvas)
    {
        let scratch = barCanvas.smoothCtx
        if (!scratch)
            scratch = barCanvas.smoothCtx = document.createElement('canvas').getContext('2d', {colorType: 'float16'})
        if (scratch.canvas.width != barCanvas.width || scratch.canvas.height != barCanvas.height)
        {
            scratch.canvas.width = barCanvas.width
            scratch.canvas.height = barCanvas.height
        }
        return scratch
    }
    paint()
    {
        this.clearAll()

        if (!STYLE.features.background)
            return

        const width = LOGICAL_VIEWPORT.width
        const height = LOGICAL_VIEWPORT.height

        const caveLayers = STYLE.caveLayers

        // Base gradient, far crystals and haze come baked in one opaque tile
        this.drawCrystalLayer(width, height, this.getLayerShift(width, height, caveLayers.crystals))
        this.preserveGameplayRandomSequence(1, 40)
        if (this.palette && this.parallaxEnabled)
        {
            const used = drawGrappleOverParallax(this, this.palette)
            if (!this.bounds)
                this.parallaxFrame = used
        }
        this.drawNearLayer(width, height, this.getLayerShift(width, height, caveLayers.nearRocks))
        if (this.palette)
            drawGrappleOverPalette(this.ctx, this.fillBounds(), this.palette, GRADIENT_DITHER.enabled && !this.bounds,
                this.paletteAhead)
        if (this.palette)
            drawGrappleOverLandmarks(this)
        this.drawVignette(width, height)
    }
    // The removed decorations consumed the shared gameplay RNG once per scene
    // per run: 40 draws in game (the title menu's 18 left with the menu,
    // TASK-364). Keep those stream positions so
    // removing visual code cannot change obstacle layouts or seeded replays.
    // There are no stored random values or decorative objects.
    preserveGameplayRandomSequence(scene, count)
    {
        if (this.randomSequenceScenes & scene)
            return
        this.randomSequenceScenes |= scene
        for (let i = 0; i < count; ++i)
            Math.random()
    }
    // The bar canvases fill other bounds than the game canvas, so their
    // vignette differs: the key includes the bounds being filled
    getGradientKey(width, height)
    {
        const background = STYLE.colors.background
        const bounds = this.bounds
        return [
            width,
            height,
            bounds ? [bounds.x, bounds.y, bounds.width, bounds.height].join() : '',
            background.gradientTop,
            background.gradientMiddle,
            background.gradientBottom,
            background.vignetteCenter,
            background.vignetteEdge
        ].join('|')
    }
    getGradients(width, height)
    {
        // The game canvas asks three times a frame: skip building the key string
        const background = STYLE.colors.background
        const last = this.lastGameGradients
        if (!this.bounds && last && last.width == width && last.height == height &&
            last.gradientTop == background.gradientTop && last.gradientMiddle == background.gradientMiddle &&
            last.gradientBottom == background.gradientBottom && last.vignetteCenter == background.vignetteCenter &&
            last.vignetteEdge == background.vignetteEdge)
            return last.gradients

        const key = this.getGradientKey(width, height)
        const cached = this.gradientCache.get(key) || this.buildGradients(key, width, height)
        if (!this.bounds)
            this.lastGameGradients = {
                width, height, gradients: cached,
                gradientTop: background.gradientTop, gradientMiddle: background.gradientMiddle,
                gradientBottom: background.gradientBottom, vignetteCenter: background.vignetteCenter,
                vignetteEdge: background.vignetteEdge
            }
        return cached
    }
    buildGradients(key, width, height)
    {

        const background = STYLE.colors.background
        const {gradient, haze} = this.createVerticalGradients(this.ctx, height)

        const radius = Math.sqrt(width * width + height * height) * 0.58
        const innerRadius = radius * 0.18
        // In the bars the vignette matches the game canvas out to the play
        // rect corners, then fades to half that darkness at the window corners
        const bounds = this.fillBounds()
        const playCorner = Math.sqrt(width * width + height * height) / 2
        const windowCorner = Math.max(
            Math.hypot(width / 2 - bounds.x, height / 2 - bounds.y),
            Math.hypot(bounds.x + bounds.width - width / 2, bounds.y + bounds.height - height / 2)
        )
        const outerRadius = this.bounds && windowCorner > playCorner ? windowCorner : radius
        const vignette = this.ctx.createRadialGradient(
            width / 2,
            height / 2,
            innerRadius,
            width / 2,
            height / 2,
            outerRadius
        )
        vignette.addColorStop(0, background.vignetteCenter)
        if (outerRadius == radius)
            vignette.addColorStop(1, background.vignetteEdge)
        else
        {
            const corner = mixRgba(background.vignetteCenter, background.vignetteEdge,
                (playCorner - innerRadius) / (radius - innerRadius))
            vignette.addColorStop((playCorner - innerRadius) / (outerRadius - innerRadius), corner)
            vignette.addColorStop(1, mixRgba(background.vignetteCenter, corner, 0.5))
        }

        // The game canvas and up to two bars; a resize starts over
        if (this.gradientCache.size >= 3)
            this.gradientCache.clear()
        const entry = {gradient, vignette, haze}
        this.gradientCache.set(key, entry)
        return entry
    }
    // The base gradient and the haze (between the far crystals and the near
    // rocks), top to bottom over height
    createVerticalGradients(ctx, height)
    {
        const background = STYLE.colors.background
        const gradient = ctx.createLinearGradient(0, 0, 0, height)
        gradient.addColorStop(0, background.gradientTop)
        gradient.addColorStop(0.54, background.gradientMiddle)
        gradient.addColorStop(1, background.gradientBottom)

        const haze = ctx.createLinearGradient(0, 0, 0, height)
        haze.addColorStop(0, background.hazeTop)
        haze.addColorStop(0.24, background.hazeUpper)
        haze.addColorStop(0.5, background.hazeMiddle)
        haze.addColorStop(0.74, background.hazeLower)
        haze.addColorStop(1, background.hazeBottom)
        return {gradient, haze}
    }
    drawVignette(width, height)
    {
        const gradients = this.getGradients(width, height)
        if (GRADIENT_DITHER.enabled && !this.bounds)
        {
            // The game canvas: the gradient baked once into a small image.
            // The fast backdrop, enlarged into the frame, would leave its
            // smooth edge steps undithered: there it is dithered at the
            // backdrop resolution (the last soft layer carries the dither)
            const bounds = this.fillBounds()
            const fast = typeof BACKDROP != 'undefined' && BACKDROP.active
            this.ctx.drawImage(this.getSmoothImage(gradients, fast ? 'vignetteFast' : 'vignetteImage', bounds,
                (context, b) =>
                {
                    context.fillStyle = gradients.vignette
                    context.fillRect(b.x, b.y, b.width, b.height)
                }, fast ? 'alpha' : undefined), bounds.x, bounds.y, bounds.width, bounds.height)
            return
        }
        this.ctx.fillStyle = gradients.vignette
        this.fillAll()
    }
    // GRADIENT_DITHER: a soft full-frame layer as an image, kept on
    // owner[name]: paint(context, bounds) fills bounds (logical) in a float16
    // canvas. Dithered (kind 'opaque' or 'alpha', GRADIENT_DITHER.paint8): at
    // the device resolution with the dither noise, drawn 1:1; in the fast
    // backdrop (enlarged into the frame) the noise is blue. Smooth (no kind):
    // at SMOOTH_IMAGE_SCALE of the device resolution, rounded to 8 bits, drawn
    // enlarged (bilinear). No gradient fill reaches the frame, so the browser
    // adds no dither.
    getSmoothImage(owner, name, bounds, paint, kind)
    {
        const m = this.ctx.getTransform()
        const scale = kind ? 1 : SMOOTH_IMAGE_SCALE
        const w = Math.max(1, Math.round(bounds.width * Math.abs(m.a) * scale))
        const h = Math.max(1, Math.round(bounds.height * Math.abs(m.d) * scale))
        const noise = kind && (typeof BACKDROP != 'undefined' && BACKDROP.active ? 'blue' : 'white')
        const key = [w, h, bounds.x, bounds.y, bounds.width, bounds.height, noise].join()
        const cached = owner[name]
        if (cached && cached.key === key)
            return cached.canvas
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        GRADIENT_DITHER.paint8(canvas, context =>
        {
            context.setTransform(w / bounds.width, 0, 0, h / bounds.height,
                -bounds.x * w / bounds.width, -bounds.y * h / bounds.height)
            paint(context, bounds)
        }, noise, kind === 'alpha')
        owner[name] = {key, canvas}
        return canvas
    }
    // Motes retain their original mode-specific drift and twinkle clock.
    getAnimationTime()
    {
        if (!QUALITY.backgroundMotion)
            return 0

        return performance.now() * this.getVersionBackgroundTimeScale()
    }
    getVersionBackgroundTimeScale()
    {
        if (typeof version != 'undefined' && version == 'classic')
            return STYLE.caveLayers.classicMotionTimeScale

        return 1
    }
    // Follow the world translation at a fraction of its speed. Camera
    // parallax is spatial, independent of the animation clock; a stationary
    // camera must leave the cave still in both modes.
    getLayerShift(width, height, layer)
    {
        if (STYLE.visualStability.freezeBadVersionBackground)
            return {x: 0, y: 0}

        const enabled = QUALITY.backgroundMotion && typeof screen != 'undefined'
            && typeof scale != 'undefined' && typeof version != 'undefined'
        const canvasScale = enabled ? (scale[version] || 1) : 0
        const camera = {
            x: enabled ? screen.x * canvasScale * layer.cameraParallaxXRatio : 0,
            y: enabled ? screen.y * canvasScale * layer.cameraParallaxYRatio : 0
        }
        const maxY = height * (layer.maxShiftYRatio || 0.05)

        return {
            x: camera.x,
            y: Math.max(-maxY, Math.min(maxY, camera.y))
        }
    }
    // A crystal/rock tile for this viewport size, built once by paint
    // (a resize builds a new one). A smooth tile (gradient fills) is painted
    // by GRADIENT_DITHER.
    getLayerTile(name, width, height, config, paint, smooth)
    {
        const pixelScale = Math.max(0.25, Math.min(config.maxPixelScale, this.canvas.width / width || 1))
        const key = [width, height, pixelScale].join('|')
        const cached = this.layerCache[name]

        if (cached && cached.key === key)
            return cached

        const layerCanvas = document.createElement('canvas')
        layerCanvas.width = Math.max(1, Math.round(width * pixelScale))
        layerCanvas.height = Math.max(1, Math.round(height * pixelScale))
        const paintTile = ctx =>
        {
            ctx.setTransform(layerCanvas.width / width, 0, 0, layerCanvas.height / height, 0, 0)
            return paint(ctx, width, height, config, this.getTileTools(ctx, width, config.seed))
        }
        const clear = smooth ? GRADIENT_DITHER.paint8(layerCanvas, paintTile, 'white') :
            paintTile(layerCanvas.getContext('2d'))

        const layer = {key, canvas: layerCanvas, width, height, strips: this.getLayerStrips(layerCanvas, height, clear)}
        this.layerCache[name] = layer
        return layer
    }
    // A tile whose paint left the rows between clear.clearTop and
    // clear.clearBottom (logical) transparent is drawn as its top and bottom
    // strips only, with two transparent rows kept past each cut so filtering
    // reads the same pixels. Each frame then references fewer image bytes:
    // Chromium redraws every tile when the frame's tiles outgrow its image
    // cache (a band blend's four parallax tiles did).
    getLayerStrips(layerCanvas, height, clear)
    {
        const ratio = layerCanvas.height / height
        const top = clear ? Math.min(layerCanvas.height, Math.ceil(clear.clearTop * ratio) + 2) : 0
        const bottom = clear ? Math.max(top, Math.floor(clear.clearBottom * ratio) - 2) : 0
        if (!clear || bottom - top < layerCanvas.height / 4)
            return [{y: 0, canvas: layerCanvas}]
        return [[0, top], [bottom, layerCanvas.height]].map(([y0, y1]) =>
        {
            const strip = document.createElement('canvas')
            strip.width = layerCanvas.width
            strip.height = y1 - y0
            strip.getContext('2d').drawImage(layerCanvas, 0, -y0)
            return {y: y0, canvas: strip}
        })
    }
    // Seeded random numbers and wrapped polygon drawing for a tile
    getTileTools(ctx, width, initialSeed)
    {
        let seed = initialSeed >>> 0
        // mulberry32: the same tile on every run and every device
        const random = () =>
        {
            seed = (seed + 0x6D2B79F5) >>> 0
            let t = seed
            t = Math.imul(t ^ (t >>> 15), t | 1)
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296
        }
        const between = range => range[0] + (range[1] - range[0]) * random()
        // Shapes are drawn again one tile width left and right, so whatever
        // leaves one side of the tile comes back on the other: no seam
        const wrapped = draw =>
        {
            for (const dx of [-width, 0, width])
            {
                ctx.save()
                ctx.translate(dx, 0)
                draw()
                ctx.restore()
            }
        }
        const polygon = (points, fill) =>
        {
            ctx.beginPath()
            ctx.moveTo(points[0][0], points[0][1])
            for (let i = 1; i < points.length; ++i)
                ctx.lineTo(points[i][0], points[i][1])
            ctx.closePath()
            ctx.fillStyle = fill
            ctx.fill()
        }

        return {random, between, wrapped, polygon}
    }
    paintCrystalTile(ctx, width, height, crystals, tools)
    {
        const colors = STYLE.colors.background
        const {random, between, wrapped, polygon} = tools
        // A faceted shard from baseY towards dir (-1 up, 1 down): a shadow
        // facet left of the ridge and a lit facet right of it
        const shard = (x, baseY, dir, h, w, lean, shadow, lit, edge) =>
        {
            const tip = [x + lean * w, baseY + dir * h]
            const ridge = [x + w * (0.05 + random() * 0.2), baseY]
            const left = [x - w * 0.85, baseY + dir * h * (0.4 + random() * 0.3)]
            const right = [x + w * 0.8, baseY + dir * h * (0.35 + random() * 0.3)]

            wrapped(() =>
            {
                polygon([[x - w, baseY], left, tip, ridge], shadow)
                polygon([ridge, tip, right, [x + w, baseY]], lit)
                if (!edge)
                    return
                ctx.beginPath()
                ctx.moveTo(left[0], left[1])
                ctx.lineTo(tip[0], tip[1])
                ctx.lineTo(ridge[0], ridge[1])
                ctx.strokeStyle = edge
                ctx.lineWidth = crystals.edgeLineWidth
                ctx.stroke()
            })
        }
        const row = (count, baseY, dir, heights, shadow, lit, edge) =>
        {
            for (let i = 0; i < count; ++i)
            {
                const x = (i + 0.1 + random() * 0.8) * width / count
                const h = between(heights)
                const w = between(crystals.halfWidth)
                const lean = (random() - 0.5) * 0.9

                // Some shards grow a smaller one beside them
                if (random() < 0.5)
                    shard(x + w * (random() < 0.5 ? -0.9 : 0.9), baseY, dir, h * (0.4 + random() * 0.2),
                        w * 0.6, (random() - 0.5) * 0.9, shadow, lit, edge)
                shard(x, baseY, dir, h, w, lean, shadow, lit, edge)
            }
        }
        // Low-poly boulders: two facets split at the summit
        const rocks = (count, baseY, dir, heights) =>
        {
            for (let i = 0; i < count; ++i)
            {
                const x = (i + random()) * width / count
                const h = between(heights)
                const w = between(crystals.rockHalfWidth)
                const top = [x + (random() - 0.5) * w * 0.6, baseY + dir * h]
                const points = [
                    [x - w, baseY],
                    [x - w * 0.6, baseY + dir * h * (0.5 + random() * 0.3)],
                    top,
                    [x + w * 0.5, baseY + dir * h * (0.55 + random() * 0.3)],
                    [x + w, baseY]
                ]

                wrapped(() =>
                {
                    polygon(points.slice(0, 3).concat([[top[0], baseY]]), colors.crystalRock)
                    polygon([[top[0], baseY]].concat(points.slice(2)), colors.crystalRockLit)
                })
            }
        }
        const bottom = height + 2
        const top = -2

        row(crystals.topBackCount, top, 1, crystals.topBackHeight,
            colors.crystalBackShadow, colors.crystalBackLit, colors.crystalEdge)
        row(crystals.bottomBackCount, bottom, -1, crystals.bottomBackHeight,
            colors.crystalBackShadow, colors.crystalBackLit, colors.crystalEdge)
        row(crystals.topFrontCount, top, 1, crystals.topFrontHeight,
            colors.crystalFrontShadow, colors.crystalFrontLit, colors.crystalEdge)
        row(crystals.bottomFrontCount, bottom, -1, crystals.bottomFrontHeight,
            colors.crystalFrontShadow, colors.crystalFrontLit, colors.crystalEdge)
        rocks(crystals.rockCount, bottom, -1, crystals.rockHeight)
        rocks(crystals.rockCount, top, 1, crystals.rockHeight.map(h => h * 0.6))
        // Solid rock rows at both edges: drawLayerTile extends them over
        // whatever the shifted tile leaves uncovered
        ctx.fillStyle = colors.crystalRock
        ctx.fillRect(0, 0, width, height * 0.012)
        ctx.fillRect(0, height * 0.988, width, height * 0.012)
    }
    // Large dark boulders: a shadow, a middle and a lit facet around the
    // summit, and a faint rim along the lit side
    paintNearTile(ctx, width, height, rocks, tools)
    {
        const colors = STYLE.colors.background
        const {random, between, wrapped, polygon} = tools
        // Lowest point the top rocks reach and highest the bottom ones do
        let topReach = height * 0.012, bottomReach = height * 0.988
        const boulder = (x, baseY, dir, h, w) =>
        {
            if (dir > 0)
                topReach = Math.max(topReach, baseY + h)
            else
                bottomReach = Math.min(bottomReach, baseY - h)
            const summit = [x + (random() - 0.5) * w * 0.5, baseY + dir * h]
            const leftShoulder = [x - w * (0.55 + random() * 0.2), baseY + dir * h * (0.45 + random() * 0.3)]
            const rightShoulder = [x + w * (0.45 + random() * 0.2), baseY + dir * h * (0.5 + random() * 0.3)]
            const inner = [x + (random() - 0.5) * w * 0.4, baseY + dir * h * (0.25 + random() * 0.2)]

            wrapped(() =>
            {
                polygon([[x - w, baseY], leftShoulder, summit, inner, [inner[0], baseY]], colors.nearShadow)
                polygon([[inner[0], baseY], inner, summit, rightShoulder, [x + w, baseY]], colors.nearMid)
                polygon([inner, summit, rightShoulder], colors.nearLit)
                ctx.beginPath()
                ctx.moveTo(leftShoulder[0], leftShoulder[1])
                ctx.lineTo(summit[0], summit[1])
                ctx.lineTo(rightShoulder[0], rightShoulder[1])
                ctx.strokeStyle = colors.nearRim
                ctx.lineWidth = rocks.rimLineWidth
                ctx.stroke()
            })
        }
        const row = (count, baseY, dir, heights, halfWidths) =>
        {
            for (let i = 0; i < count; ++i)
                boulder((i + 0.15 + random() * 0.7) * width / count, baseY, dir, between(heights), between(halfWidths))
        }
        const bottom = height + 2
        const top = -2

        row(rocks.outcropCount, bottom, -1, rocks.outcropHeight, rocks.outcropHalfWidth)
        row(rocks.bottomCount, bottom, -1, rocks.bottomHeight, rocks.bottomHalfWidth)
        row(rocks.topCount, top, 1, rocks.topHeight, rocks.topHalfWidth)
        ctx.fillStyle = colors.nearRock
        ctx.fillRect(0, 0, width, height * 0.012)
        ctx.fillRect(0, height * 0.988, width, height * 0.012)
        // Nothing is painted between the two rows of rocks: the summits are
        // their extreme points, plus the rim's miter (limit 10) and antialiasing
        const margin = rocks.rimLineWidth / 2 * 10 + 2
        return {clearTop: topReach + margin, clearBottom: bottomReach - margin}
    }
    // The base gradient and the haze are vertical, so they are baked into
    // the far tile with it (one drawImage instead of two full-frame gradient
    // fills, which software canvases such as Firefox's pay per pixel). They
    // follow the tile's small vertical parallax; the uncovered edge rows get
    // the rock colour and the haze as before.
    drawCrystalLayer(width, height, shift)
    {
        const far = this.getLayerTile('far', width, height, STYLE.caveLayers.crystals,
            (...args) => this.paintCrystalTile(...args))
        const baked = this.getLayerTile('farBaked', width, height, STYLE.caveLayers.crystals,
            (ctx, w, h) =>
            {
                const gradients = this.createVerticalGradients(ctx, h)
                ctx.fillStyle = gradients.gradient
                ctx.fillRect(0, 0, w, h)
                ctx.drawImage(far.canvas, 0, 0, w, h)
                ctx.fillStyle = gradients.haze
                ctx.fillRect(0, 0, w, h)
            }, true)
        this.drawLayerTile(baked, width, height, shift, STYLE.colors.background.crystalRock,
            this.getGradients(width, height).haze)
    }
    drawNearLayer(width, height, shift)
    {
        const layer = this.getLayerTile('near', width, height, STYLE.caveLayers.nearRocks,
            (...args) => this.paintNearTile(...args))
        this.drawLayerTile(layer, width, height, shift, STYLE.colors.background.nearRock)
    }
    // Tiles a layer across fillBounds() at shift. Tile edges are snapped to
    // device pixels so neighbouring copies neither overlap nor leave a gap;
    // edgeFill covers what the shifted tile leaves uncovered above and below
    drawLayerTile(layer, width, height, shift, edgeFill, edgeOverlay)
    {
        const bounds = this.fillBounds()
        const transform = this.ctx.getTransform()
        const toDevice = x => Math.round(transform.a * x + transform.e)
        const fromDevice = x => (x - transform.e) / transform.a
        const right = bounds.x + bounds.width
        let k = Math.floor((bounds.x - shift.x) / width)
        let left = fromDevice(toDevice(shift.x + k * width))
        // Logical height of one tile pixel row
        const unit = height / layer.canvas.height

        while (left < right)
        {
            const next = fromDevice(toDevice(shift.x + (k + 1) * width))
            for (const strip of layer.strips)
                this.ctx.drawImage(strip.canvas, left, shift.y + strip.y * unit, next - left, strip.canvas.height * unit)
            left = next
            ++k
        }

        const edges = []
        if (bounds.y < shift.y)
            edges.push([bounds.x, bounds.y, bounds.width, shift.y - bounds.y])
        if (shift.y + height < bounds.y + bounds.height)
            edges.push([bounds.x, shift.y + height, bounds.width, bounds.y + bounds.height - shift.y - height])
        for (const style of edgeOverlay ? [edgeFill, edgeOverlay] : [edgeFill])
        {
            this.ctx.fillStyle = style
            for (const edge of edges)
                this.ctx.fillRect(...edge)
        }
    }
}

// '#rrggbb' -> 'rgba(r, g, b, alpha)' (used only when a gradient is built)
function colorWithAlpha(hex, alpha)
{
    const value = parseInt(hex.slice(1, 7), 16)
    return 'rgba(' + (value >> 16 & 255) + ', ' + (value >> 8 & 255) + ', ' + (value & 255) + ', ' + alpha + ')'
}

// Coloured light spill: obstacles add a soft radial light of their own
// colour into a small canvas, which is added over the crystal background before
// the world is drawn, so obstacles themselves are never washed out.
class LightmapRenderer
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
        this.scale = isTouchFirstDevice()
            ? STYLE.lights.touchResolutionScale : STYLE.lights.resolutionScale
        this.enabled = true
        this.hasLights = false
        this.lightCanvas = document.createElement('canvas')
        this.lightCtx = this.lightCanvas.getContext('2d')
        // Unit-radius gradients by colour; drawRadialLight scales them to size
        this.gradients = new Map()
        this.shapeLights = new Map()
        this.resize()
    }
    shouldDraw()
    {
        return this.enabled && STYLE.features.lightmap && QUALITY.lightmap
    }
    resize()
    {
        const nextWidth = Math.max(1, Math.ceil(LOGICAL_VIEWPORT.width * this.scale))
        const nextHeight = Math.max(1, Math.ceil(LOGICAL_VIEWPORT.height * this.scale))

        if (this.lightCanvas.width == nextWidth && this.lightCanvas.height == nextHeight)
            return

        this.lightCanvas.width = nextWidth
        this.lightCanvas.height = nextHeight
    }
    clear()
    {
        if (!this.shouldDraw())
            return

        this.resize()
        this.lightCtx.clearRect(0, 0, this.lightCanvas.width, this.lightCanvas.height)
        this.hasLights = false
    }
    // x, y in world-on-screen units (as drawn under ctx.scale(scale[version])),
    // radius in screen px at 1080. Lights fully off screen are skipped.
    drawRadialLight(x, y, radius, color, alpha)
    {
        const toLight = this.scale * scale[version]
        const lightX = x * toLight
        const lightY = y * toLight
        const lightRadius = radius * height / 1080 * this.scale

        if (lightX < -lightRadius || lightY < -lightRadius
            || lightX > this.lightCanvas.width + lightRadius
            || lightY > this.lightCanvas.height + lightRadius)
            return false

        const lightCtx = this.lightCtx
        lightCtx.setTransform(lightRadius, 0, 0, lightRadius, lightX, lightY)
        lightCtx.globalAlpha = alpha
        lightCtx.fillStyle = this.getLightGradient(color)
        lightCtx.fillRect(-1, -1, 2, 2)
        this.hasLights = true
        return true
    }
    getLightGradient(color)
    {
        let gradient = this.gradients.get(color)

        if (gradient)
            return gradient

        if (this.gradients.size >= 64)
            this.gradients.clear()

        const falloff = STYLE.lights.falloff
        gradient = this.lightCtx.createRadialGradient(0, 0, 0, 0, 0, 1)
        for (let i = 0; i < falloff.length; ++i)
        {
            gradient.addColorStop(falloff[i][0], colorWithAlpha(color, falloff[i][1]))
        }
        this.gradients.set(color, gradient)
        return gradient
    }
    draw(gameState)
    {
        if (!this.shouldDraw())
            return

        const lightCtx = this.lightCtx
        lightCtx.save()
        lightCtx.globalCompositeOperation = 'lighter'
        this.drawWorldLights(gameState.floors)
        // Keep the complete player area unchanged, including its transparent
        // surroundings. Pad for the low-resolution lightmap's bilinear filter.
        const unit = this.scale * scale[version]
        lightCtx.setTransform(unit, 0, 0, unit, 0, 0)
        lightCtx.globalCompositeOperation = 'destination-out'
        lightCtx.globalAlpha = 1
        // Some obstacle faces are translucent. Erase their silhouettes from
        // every overlapping light, not only from their own cached sprite.
        // Fill only: stroking this mask also erases the exterior light and
        // creates a dark moat when the low-resolution map is enlarged.
        for (const floor of gameState.floors)
            for (const element of floor.elements)
            {
                if (!(element instanceof Rect || element instanceof Trampoline || element instanceof Triangle)) continue
                const points = element.getPoints()
                lightCtx.beginPath()
                const last = points[points.length - 1]
                lightCtx.moveTo(last.x + screen.x, last.y + screen.y)
                for (const p of points)
                    if (p.curvature)
                        lightCtx.quadraticCurveTo(p.curvature.x + screen.x, p.curvature.y + screen.y,
                            p.x + screen.x, p.y + screen.y)
                    else lightCtx.lineTo(p.x + screen.x, p.y + screen.y)
                lightCtx.closePath()
                lightCtx.fill()
            }
        lightCtx.beginPath()
        lightCtx.arc(ninja.x + screen.x, ninja.y + screen.y,
            ninja.radius * 1.5 + 2 / unit, 0, Math.PI * 2)
        lightCtx.fill()
        lightCtx.restore()
    }
    drawWorldLights(floors)
    {
        for (let i = 0; i < floors.length; ++i)
        {
            const elements = floors[i].elements
            for (let j = 0; j < elements.length; ++j)
            {
                this.drawElementLight(elements[j])
            }
        }
    }
    drawElementLight(element)
    {
        if (!(element instanceof Triangle) && !this.isCubeOrPlatform(element))
            return
        const box = getElementCullBox(element)
        if (!box) return
        const toLight = this.scale * scale[version]
        const spread = STYLE.lights.shapeSpread * height / 1080 / scale[version]
        const x = box.left + screen.x, y = box.top + screen.y
        const w = box.right - box.left, h = box.bottom - box.top
        if ((x + w + spread) * toLight < 0 || (y + h + spread) * toLight < 0
            || (x - spread) * toLight > this.lightCanvas.width
            || (y - spread) * toLight > this.lightCanvas.height) return
        const color = this.getElementLightColor(element)
        // Translation is deliberately absent from the key: moving hazards reuse
        // their sprite. Quantization removes floating point translation noise.
        // An element whose points, colour and scale did not change keeps its key.
        const worldPoints = element.getPoints()
        let lightKey = element.lightKey
        if (!lightKey || lightKey.points !== worldPoints || lightKey.color !== color ||
            lightKey.spread !== spread || lightKey.toLight !== toLight)
        {
            const relative = worldPoints.map(p => ({x: p.x - box.left, y: p.y - box.top}))
            lightKey = element.lightKey = {points: worldPoints, color, spread, toLight, relative,
                key: JSON.stringify([relative.map(p => [p.x.toFixed(3), p.y.toFixed(3)]),
                    color, spread.toFixed(3), toLight])}
        }
        const points = lightKey.relative
        const key = lightKey.key
        let sprite = this.shapeLights.get(key)
        if (!sprite)
        {
            if (this.shapeLights.size >= 128) this.shapeLights.clear()
            sprite = document.createElement('canvas')
            sprite.width = Math.ceil((w + spread * 2) * toLight) + 2
            sprite.height = Math.ceil((h + spread * 2) * toLight) + 2
            const c = sprite.getContext('2d')
            c.scale(toLight, toLight)
            c.translate(spread, spread)
            c.beginPath()
            points.forEach((p, i) => i ? c.lineTo(p.x, p.y) : c.moveTo(p.x, p.y))
            c.closePath()
            c.lineJoin = 'round'
            c.strokeStyle = color
            // Nested rounded polygon strokes approximate a smooth distance-to-
            // outline falloff. Built once, with no shadowBlur or live gradients.
            for (let i = 32; i >= 1; --i)
            {
                c.lineWidth = 2 * spread * i / 32
                c.globalAlpha = 0.045
                c.stroke()
            }
            this.shapeLights.set(key, sprite)
        }
        this.lightCtx.setTransform(toLight, 0, 0, toLight, 0, 0)
        this.lightCtx.globalAlpha = element instanceof Triangle
            ? STYLE.lights.hazardAlpha : this.isOrangeDangerLight(element)
                ? STYLE.lights.dangerAlpha : STYLE.lights.cubeAlpha
        this.lightCtx.drawImage(sprite, x - spread, y - spread,
            sprite.width / toLight, sprite.height / toLight)
        this.hasLights = true
    }
    isCubeOrPlatform(element)
    {
        // Both surface types span the level. Their boundary renderer supplies
        // the neon outline; neither should emit obstacle light onto the cave.
        if (element instanceof Ground || element instanceof Side)
            return false

        return element instanceof Rect || element instanceof Trampoline
    }
    isOrangeDangerLight(element)
    {
        return element instanceof Rect && element.isDangerRect
            && element.getGlowStroke() == STYLE.colors.cube.dangerStroke
    }
    getElementLightColor(element)
    {
        // Compensate only the orange spill for hard-light on the blue cave.
        // Bodies/outlines, sprite geometry and the shared masks stay unchanged.
        if (this.isOrangeDangerLight(element)) return STYLE.lights.dangerColor
        return element.getGlowStroke() || STYLE.colors.cube.blue
    }
    composite()
    {
        // A fully transparent lightmap cannot affect the frame. Avoid the
        // full-canvas blend when all world lights were culled.
        if (!this.shouldDraw() || !this.hasLights)
            return

        const viewWidth = LOGICAL_VIEWPORT.width / scale[version]
        const viewHeight = LOGICAL_VIEWPORT.height / scale[version]

        this.ctx.save()
        this.ctx.globalAlpha = STYLE.lights.worldCompositeAlpha
        this.ctx.globalCompositeOperation = STYLE.lights.compositeOperation
        this.ctx.imageSmoothingEnabled = true
        this.ctx.drawImage(this.lightCanvas, 0, 0, viewWidth, viewHeight)
        this.ctx.restore()
    }
}

function positiveModulo(value, modulus)
{
    return ((value % modulus) + modulus) % modulus
}

// Numbers per mote in ParticleSystem.moteLayout
const MOTE_LAYOUT_STRIDE = 8

class ParticleSystem
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
        this.particles = []
        // Expired particles, reused by acquireParticle (capped at maxCount).
        this.pool = []
        // Ambient mote rects of the current game frame (layoutAmbientMotes)
        this.moteLayout = null
        this.moteLayoutFrame = -1
        this.lastTime = 0
        this.lastWorldEmitTime = 0
        this.emberBounds = {left: 0, right: 0, top: 0, bottom: 0}
        this.trailSparkBudget = 0
        // Sparks draw from their own stream: Math.random is shared with level
        // generation (seeded in the captures), so using it here would change gameplay.
        this.sparkSeed = 181
    }
    shouldDraw()
    {
        return STYLE.features.particles && QUALITY.particles
    }
    update(gameState)
    {
        if (!this.shouldDraw())
        {
            this.particles = []
            this.lastTime = 0
            return
        }

        const now = performance.now()
        const dt = this.lastTime ? Math.min(33, now - this.lastTime) : 16
        this.lastTime = now

        this.releaseTrampolineSplashLocks(gameState)
        this.updateParticles(dt)
        this.emitTrailSparks(gameState, dt)
        if (gameState && gameState.floors)
            this.emitWorldParticles(gameState.floors)
    }
    draw()
    {
        this.drawLayer(function(particle) {
            return !particle.drawBeforeForeground
        })
    }
    drawBehindForeground()
    {
        this.drawLayer(function(particle) {
            return particle.drawBeforeForeground
        })
    }
    drawLayer(shouldDrawParticle)
    {
        if (!this.shouldDraw())
            return

        this.ctx.save()
        this.ctx.globalCompositeOperation = this.getEffectCompositeOperation()

        for (let i = 0; i < this.particles.length; ++i)
        {
            const particle = this.particles[i]

            if (!shouldDrawParticle(particle))
                continue

            const progress = particle.life / particle.maxLife
            const drawX = particle.worldAnchored ? particle.x + screen.x : particle.x
            const drawY = particle.worldAnchored ? particle.y + screen.y : particle.y

            if (particle.ember)
            {
                this.ctx.globalAlpha = this.emberAlpha(particle)
                this.ctx.fillStyle = particle.color
                this.ctx.fillRect(drawX - particle.size / 2, drawY - particle.size / 2, particle.size, particle.size)
                continue
            }

            if (particle.spark)
            {
                this.drawSpark(particle, progress, drawX, drawY)
                continue
            }

            this.ctx.globalAlpha = Math.max(0, progress) * particle.alpha * this.getStableAlphaMultiplier()
            this.ctx.fillStyle = particle.color
            this.ctx.fillRect(
                drawX - particle.size / 2,
                drawY - particle.size / 2,
                particle.size,
                particle.size
            )
        }

        this.ctx.restore()
    }
    drawSpark(particle, progress, drawX, drawY)
    {
        // Quick fade in, long fade out, so sparks never pop between frames.
        const config = STYLE.trails.player
        const alpha = particle.alpha * Math.max(0, Math.min(1, (1 - progress) * 6, progress)) * STYLE.player.effectOpacity
        const haloSize = particle.size * config.sparkHaloRatio

        if (STYLE.player.outerGlow)
        {
            this.ctx.globalAlpha = alpha * config.sparkHaloAlpha
            this.ctx.fillStyle = STYLE.colors.playerTrail.sparkHalo
            this.ctx.fillRect(drawX - haloSize / 2, drawY - haloSize / 2, haloSize, haloSize)
        }

        this.ctx.globalAlpha = alpha
        this.ctx.fillStyle = particle.color
        this.ctx.fillRect(drawX - particle.size / 2, drawY - particle.size / 2, particle.size, particle.size)
    }
    updateParticles(dt)
    {
        // In-place compaction: keeps the draw order without splice garbage.
        const particles = this.particles
        let kept = 0

        for (let i = 0; i < particles.length; ++i)
        {
            const particle = particles[i]

            if (particle.ember)
            {
                const config = STYLE.particles.embers
                const age = particle.maxLife - particle.life
                particle.x += config.sway * (Math.sin((age + dt) / config.swayPeriodMs + particle.phase)
                    - Math.sin(age / config.swayPeriodMs + particle.phase))
            }
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.life -= dt

            if (particle.life > 0)
                particles[kept++] = particle
            else
                this.release(particle)
        }

        particles.length = kept
    }
    acquireParticle()
    {
        return this.pool.length ? this.pool.pop() : {}
    }
    release(particle)
    {
        if (this.pool.length < STYLE.particles.maxCount)
            this.pool.push(particle)
    }
    emitTrampolineSplash(player, trampoline)
    {
        if (!this.shouldDraw())
            return

        if (trampoline.particleSplashActive)
            return

        trampoline.particleSplashActive = true

        const badParticles = this.getBadVersionParticles()
        const splashParticles = Object.assign({}, badParticles, {
            sizeMultiplier: badParticles.sizeMultiplier * STYLE.particles.trampolineSplashSizeMultiplier,
            lifetimeMultiplier: badParticles.lifetimeMultiplier * STYLE.particles.trampolineSplashLifetimeMultiplier
        })
        const originX = player.x
        const originY = player.y
        const color = this.getTrampolineSplashColor(trampoline)
        const count = STYLE.particles.trampolineSplashCount
        const dispersionX = STYLE.particles.trampolineSplashDispersionX
        const dispersionY = STYLE.particles.trampolineSplashDispersionY

        for (let i = 0; i < count; ++i)
        {
            this.emitSquare(
                originX + this.randomRange(-dispersionX, dispersionX),
                originY + this.randomRange(-dispersionY, dispersionY),
                color,
                STYLE.particles.trampolineSplashSpeed * splashParticles.speedMultiplier,
                this.clampAlpha(STYLE.particles.trampolineSplashAlpha * badParticles.alphaMultiplier),
                splashParticles,
                true,
                true
            )
        }
    }
    getTrampolineSplashColor(trampoline)
    {
        if (version == 'bad' && (trampoline instanceof Ground || trampoline instanceof Side))
            return STYLE.colors.cube.greenStroke

        return trampoline.stroke || STYLE.colors.cube.greenStroke
    }
    releaseTrampolineSplashLocks(gameState)
    {
        if (!gameState || !gameState.ninja || !gameState.floors)
            return

        for (let i = 0; i < gameState.floors.length; ++i)
        {
            for (let j = 0; j < gameState.floors[i].elements.length; ++j)
            {
                const element = gameState.floors[i].elements[j]

                if (!(element instanceof Trampoline) || !element.particleSplashActive)
                    continue

                if (!this.isPlayerCollidingWithElement(gameState.ninja, element))
                    element.particleSplashActive = false
            }
        }
    }
    isPlayerCollidingWithElement(player, element)
    {
        if (!twoCirclesIntersect(player.x, player.y, player.radius, element.getCircumscribedCircle()))
            return false

        const lines = element.getLines()

        for (let i = 0; i < lines.length; ++i)
        {
            if (collisionCircleWithLine(lines[i], player.x, player.y, player.radius))
                return true
        }

        return false
    }
    emitPlayerParticles(player)
    {
        if (!this.isPlayerMoving(player))
            return

        const badParticles = this.getBadVersionParticles()
        const emitCount = Math.ceil(STYLE.particles.playerEmitCount * badParticles.playerEmitMultiplier)

        for (let i = 0; i < emitCount; ++i)
        {
            this.emitSquare(
                player.x + screen.x + this.randomRange(-player.radius, player.radius),
                player.y + screen.y + this.randomRange(-player.radius, player.radius),
                STYLE.colors.player.cyan,
                STYLE.particles.playerSpeed * badParticles.speedMultiplier,
                this.clampAlpha(STYLE.particles.playerAlpha * badParticles.alphaMultiplier),
                badParticles
            )
        }
    }
    emitWorldParticles(floors)
    {
        for (let i = 0; i < floors.length; ++i)
        {
            for (let j = 0; j < floors[i].elements.length; ++j)
            {
                this.emitElementParticles(floors[i].elements[j])
            }
        }
    }
    emitElementParticles(element)
    {
        const hazard = this.isHazard(element)
        if (!hazard && !this.isCubeOrPlatform(element))
            return

        const config = STYLE.particles.embers
        const interval = version == 'bad'
            ? (hazard ? config.badHazardIntervalMs : config.badCubeIntervalMs)
            : (hazard ? config.hazardIntervalMs : config.cubeIntervalMs)
        // Cache the phase before moving obstacles change position. No shared RNG:
        // visual emissions must never consume level-generation randomness.
        if (element.emberPhase === undefined)
            element.emberPhase = positiveModulo(element.x * 73 + element.y * 151, interval)
        const beat = Math.floor((performance.now() + element.emberPhase) / interval)
        const previous = element.emberBeat
        element.emberBeat = beat
        if (previous === undefined || previous === beat)
            return

        const bounds = element.writeBounds(this.emberBounds)
        if (bounds.right + screen.x < 0 || bounds.left + screen.x > LOGICAL_VIEWPORT.width / scale[version]
            || bounds.bottom + screen.y < 0 || bounds.top + screen.y > LOGICAL_VIEWPORT.height / scale[version])
            return
        const centerX = (bounds.left + bounds.right) / 2
        const centerY = (bounds.top + bounds.bottom) / 2
        const halfWidth = (bounds.right - bounds.left) / 2
        const halfHeight = (bounds.bottom - bounds.top) / 2
        const angle = this.sparkRandom() * Math.PI * 2
        const radius = Math.sqrt(halfWidth * halfWidth + halfHeight * halfHeight) * config.radiusRatio
        const life = this.sparkRange(config.minLifetimeMs, config.maxLifetimeMs)
        this.pushParticle(centerX + Math.cos(angle) * radius,
            centerY + Math.sin(angle) * radius, 0, -config.riseSpeed,
            hazard ? config.hazardColor : config.cubeColor, life,
            // Keep dim embers legible at the main mode's wider camera scale.
            this.sparkRange(config.minSize, config.maxSize) / scale[version],
            hazard ? config.alpha : config.cubeAlpha, true, false, false)
        const particle = this.particles[this.particles.length - 1]
        particle.ember = true
        particle.phase = angle
    }
    emberAlpha(particle)
    {
        const config = STYLE.particles.embers
        const fade = Math.max(0, Math.min(1,
            (particle.maxLife - particle.life) / config.fadeInMs,
            particle.life / config.fadeOutMs))
        return particle.alpha * fade * fade * (3 - 2 * fade)
    }
    emitAroundElement(element, color, speed, alpha, particleConfig)
    {
        const circle = element.getCircumscribedCircle()
        const angle = Math.random() * Math.PI * 2
        const radius = circle.radius * Math.sqrt(Math.random())
        const x = circle.x + screen.x + Math.cos(angle) * radius
        const y = circle.y + screen.y + Math.sin(angle) * radius

        this.emitSquare(x, y, color, speed, alpha, particleConfig)
    }
    emitSquare(x, y, color, speed, alpha, particleConfig, worldAnchored, drawBeforeForeground)
    {
        const config = particleConfig || this.getBadVersionParticles()
        const angle = Math.random() * Math.PI * 2
        const velocity = this.randomRange(speed * 0.35, speed)
        const lifetime = STYLE.particles.lifetimeMs * config.lifetimeMultiplier
        const life = this.randomRange(lifetime * 0.55, lifetime)
        const size = this.randomRange(
            STYLE.particles.minSize * config.sizeMultiplier,
            STYLE.particles.maxSize * config.sizeMultiplier
        )

        this.pushParticle(x, y, Math.cos(angle) * velocity, Math.sin(angle) * velocity,
            color, life, size, alpha, !!worldAnchored, !!drawBeforeForeground, false)
    }
    pushParticle(x, y, vx, vy, color, life, size, alpha, worldAnchored, drawBeforeForeground, spark)
    {
        const particle = this.acquireParticle()

        particle.x = x
        particle.y = y
        particle.vx = vx
        particle.vy = vy
        particle.color = color
        particle.life = life
        particle.maxLife = life
        particle.size = size
        particle.alpha = alpha
        particle.worldAnchored = worldAnchored
        particle.drawBeforeForeground = drawBeforeForeground
        particle.spark = spark
        particle.ember = false
        particle.phase = 0

        this.particles.push(particle)
        this.enforceCap()
    }
    emitTrailSparks(gameState, dt)
    {
        const ninja = gameState && gameState.ninja
        const track = ninja && ninja.track
        const config = STYLE.trails.player

        if (!track || !trackEnabled || !STYLE.features.playerTrail || !QUALITY.playerTrail
            || track.pos.length < 4 || !this.isPlayerMoving(ninja))
        {
            this.trailSparkBudget = 0
            return
        }

        this.trailSparkBudget += dt * config.sparkRatePerMs

        const positions = track.pos
        const first = Math.floor(positions.length * config.sparkTailRatio)
        const last = Math.max(first + 1, Math.floor(positions.length * config.sparkHeadRatio))
        const spread = Math.max(track.lineWidth * config.widthRatio * 0.5, config.minScreenWidth / scale[version])
        const pixelScale = 1 / scale[version]

        while (this.trailSparkBudget >= 1)
        {
            this.trailSparkBudget -= 1

            const point = positions[Math.min(positions.length - 1, first + Math.floor(this.sparkRandom() * (last - first)))]
            const angle = this.sparkRandom() * Math.PI * 2
            const speed = config.sparkSpeed * pixelScale * this.sparkRange(config.sparkMinSpeedRatio, 1)
            const life = this.sparkRange(config.sparkLifetimeMs * 0.5, config.sparkLifetimeMs)

            this.pushParticle(
                point.x + this.sparkRange(-spread, spread),
                point.y + this.sparkRange(-spread, spread),
                Math.cos(angle) * speed,
                Math.sin(angle) * speed,
                STYLE.colors.playerTrail.spark,
                life,
                this.sparkRange(config.sparkMinScreenSize, config.sparkMaxScreenSize) * pixelScale,
                config.sparkAlpha,
                true,
                false,
                true
            )
        }
    }
    sparkRandom()
    {
        // mulberry32
        this.sparkSeed = (this.sparkSeed + 0x6D2B79F5) | 0
        let t = this.sparkSeed
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    sparkRange(min, max)
    {
        return min + this.sparkRandom() * (max - min)
    }
    shouldDrawAmbientMotes()
    {
        return STYLE.features.ambient && QUALITY.ambient
    }
    // Ambient motes: a fixed set seeded once from their own stream. Position and
    // alpha are pure functions of the clock and the camera, so nothing spawns
    // or allocates per frame and a frozen clock gives the same picture.
    getAmbientMotes()
    {
        if (this.ambientMotes)
            return this.ambientMotes

        const config = STYLE.ambient
        const savedSeed = this.sparkSeed
        this.sparkSeed = config.moteSeed
        this.ambientMotes = []
        for (let i = 0; i < config.moteCount; ++i)
        {
            const speed = this.sparkRange(config.moteMinSpeed, config.moteMaxSpeed)
            const rise = config.moteRiseRatio
            const side = this.sparkRandom() < 0.5 ? -1 : 1
            this.ambientMotes.push({
                u: this.sparkRandom(),
                v: this.sparkRandom(),
                vx: side * speed * Math.sqrt(1 - rise * rise),
                vy: -speed * rise,
                size: this.sparkRange(config.moteMinSize, config.moteMaxSize),
                alpha: this.sparkRange(config.moteMinAlpha, config.moteMaxAlpha),
                twinkleMs: this.sparkRange(config.moteMinTwinkleMs, config.moteMaxTwinkleMs),
                phase: this.sparkRandom() * Math.PI * 2,
                // Nearer (bigger) motes follow the camera more
                parallax: config.moteParallax * (0.5 + this.sparkRandom()),
                color: config.moteColors[i % config.moteColors.length]
            })
        }
        this.sparkSeed = savedSeed
        return this.ambientMotes
    }
    // view: {unit, cameraX, cameraY} for screens without a camera (menu),
    // else the game camera
    drawAmbientMotes(view)
    {
        if (!this.shouldDrawAmbientMotes())
            return

        const motes = this.getAmbientMotes()
        // The game frame's motes and their bloom copy share one layout
        const layout = view ? this.layoutAmbientMotes(motes, view) : this.getFrameMoteLayout(motes)
        const ctx = this.ctx

        ctx.save()
        ctx.globalCompositeOperation = 'source-over'
        for (let i = 0, j = 0; i < motes.length; ++i, j += MOTE_LAYOUT_STRIDE)
        {
            ctx.fillStyle = motes[i].color
            ctx.globalAlpha = layout[j]
            ctx.fillRect(layout[j + 1], layout[j + 2], layout[j + 3], layout[j + 3])
            ctx.globalAlpha = layout[j + 4]
            ctx.fillRect(layout[j + 5], layout[j + 6], layout[j + 7], layout[j + 7])
        }
        ctx.restore()
        // Restore only the motes' historical bloom, without reviving world or
        // control bloom. The glow pass calls back here with recursion guarded.
        if (!bloomPassActive && BACKDROP.glowFrame !== drawFrameId)
            visualEffects.ambientGlow.drawScreen(() => this.drawAmbientMotes(view))
    }
    getFrameMoteLayout(motes)
    {
        if (this.moteLayoutFrame !== drawFrameId || !this.moteLayout ||
            this.moteLayout.length != motes.length * MOTE_LAYOUT_STRIDE)
        {
            this.layoutAmbientMotes(motes, null)
            this.moteLayoutFrame = drawFrameId
        }
        return this.moteLayout
    }
    // Fills this.moteLayout (reused) for view, or the game camera, and returns
    // it: per mote the halo alpha, x, y, size, then the core alpha, x, y, size
    layoutAmbientMotes(motes, view)
    {
        const config = STYLE.ambient
        const unit = view ? view.unit : 1 / scale[version]
        const seconds = performance.now() / 1000
        // Motes live in screen px at 1080 on a field one halo wider than the view
        const margin = config.moteMaxSize * config.moteHaloRatio
        const fieldWidth = LOGICAL_VIEWPORT.width + margin * 2
        const fieldHeight = LOGICAL_VIEWPORT.height + margin * 2
        const cameraX = view ? view.cameraX : screen.x * scale[version]
        const cameraY = view ? view.cameraY : screen.y * scale[version]

        if (!this.moteLayout || this.moteLayout.length != motes.length * MOTE_LAYOUT_STRIDE)
            this.moteLayout = new Float64Array(motes.length * MOTE_LAYOUT_STRIDE)
        const layout = this.moteLayout
        // A menu layout must not pass for a game frame's
        this.moteLayoutFrame = -1

        for (let i = 0, j = 0; i < motes.length; ++i, j += MOTE_LAYOUT_STRIDE)
        {
            const mote = motes[i]
            const x = positiveModulo(mote.u * fieldWidth + mote.vx * seconds + cameraX * mote.parallax, fieldWidth) - margin
            const y = positiveModulo(mote.v * fieldHeight + mote.vy * seconds + cameraY * mote.parallax, fieldHeight) - margin
            const twinkle = 0.5 + 0.5 * Math.sin(seconds * 1000 * 2 * Math.PI / mote.twinkleMs + mote.phase)
            const alpha = mote.alpha * (0.3 + 0.7 * twinkle)
            const size = mote.size * unit
            const haloSize = size * config.moteHaloRatio

            layout[j] = alpha * config.moteHaloAlpha
            layout[j + 1] = x * unit - haloSize / 2
            layout[j + 2] = y * unit - haloSize / 2
            layout[j + 3] = haloSize
            layout[j + 4] = alpha
            layout[j + 5] = x * unit - size / 2
            layout[j + 6] = y * unit - size / 2
            layout[j + 7] = size
        }
        return layout
    }
    isPlayerMoving(player)
    {
        const speed = Math.sqrt(player.speedX * player.speedX + player.speedY * player.speedY)

        return speed >= STYLE.particles.playerMinSpeed
    }
    enforceCap()
    {
        const overage = this.particles.length - STYLE.particles.maxCount

        if (overage <= 0)
            return

        const particles = this.particles

        for (let i = 0; i < overage; ++i)
            this.release(particles[i])

        for (let i = overage; i < particles.length; ++i)
            particles[i - overage] = particles[i]

        particles.length -= overage
    }
    isVisible(element)
    {
        const circle = element.getCircumscribedCircle()
        const x = circle.x + screen.x
        const y = circle.y + screen.y
        const margin = circle.radius + STYLE.particles.maxSize
        const viewWidth = LOGICAL_VIEWPORT.width / scale[version]
        const viewHeight = LOGICAL_VIEWPORT.height / scale[version]

        return x > -margin && x < viewWidth + margin && y > -margin && y < viewHeight + margin
    }
    isHazard(element)
    {
        return element instanceof Triangle && !(element instanceof HarmlessTriangle)
    }
    isCubeOrPlatform(element)
    {
        // The floor/ceiling strips span the whole level; their glow is the bloom's job
        if (element instanceof Ground)
            return false

        return element instanceof Rect || element instanceof Trampoline || element instanceof HarmlessTriangle
    }
    getElementParticleColor(element)
    {
        if (element instanceof Triangle)
            return element.getGlowStroke()
        return element.stroke || STYLE.colors.cube.blue
    }
    randomRange(min, max)
    {
        return min + Math.random() * (max - min)
    }
    getBadVersionParticles()
    {
        if (typeof version != 'undefined' && version == 'bad')
            return STYLE.badVersionEffects.particles

        return {
            playerEmitMultiplier: 1,
            worldChanceMultiplier: 1,
            hazardChanceMultiplier: 1,
            hazardEmitCount: 1,
            alphaMultiplier: 1,
            sizeMultiplier: 1,
            speedMultiplier: 1,
            lifetimeMultiplier: 1
        }
    }
    clampAlpha(alpha)
    {
        return Math.max(0, Math.min(1, alpha))
    }
    getEffectCompositeOperation()
    {
        return STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.effectCompositeOperation
            : 'lighter'
    }
    getStableAlphaMultiplier()
    {
        return STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.stableEffectAlphaMultiplier
            : 1
    }
}

class PlayerTrailRenderer
{
    constructor()
    {
        // Reused every frame: the returned arrays are only valid until the next call.
        this.ribbonPoints = []
        this.ribbonOutline = []
        this.ribbonLeft = []
        this.ribbonRight = []
        this.ribbonPaths = []
        this.ribbonPathFrame = -1
    }
    shouldDraw()
    {
        return trackEnabled && STYLE.features.playerTrail && QUALITY.playerTrail
    }
    draw(gameState)
    {
        if (!this.shouldDraw())
            return

        for (let i = 0; i < gameState.floors.length; ++i)
        {
            gameState.floors[i].drawTracks()
        }
        this.drawSmoothPlayerTrail(gameState.ninja.track)
    }
    drawSmoothPlayerTrailIfEnabled(track)
    {
        if (this.shouldDraw())
            this.drawSmoothPlayerTrail(track)
    }
    drawSmoothPlayerTrail(track)
    {
        if (!track || track.pos.length < 2)
            return

        const config = STYLE.trails.player
        // The main pass and bloom use the same world-space outline this frame.
        // Keep paths until the next frame; never retain geometry across physics steps.
        if (this.ribbonPathFrame !== drawFrameId || this.ribbonPathTrack !== track)
        {
            this.ribbonPaths.length = 0
            this.ribbonPathFrame = drawFrameId
            this.ribbonPathTrack = track
        }
        this.ribbonPathIndex = 0
        const positions = this.getRibbonPoints(track.pos, track.lineWidth * config.minPointDistanceRatio)
        const width = this.getRibbonWidth(track)
        const visibleStart = Math.max(1, Math.floor(positions.length * config.minSegmentRatio))
        const alpha = this.clampAlpha(config.maxAlpha * this.getBadVersionTrails().alphaMultiplier)

        ctx.save()
        ctx.globalCompositeOperation = this.getEffectCompositeOperation()

        this.drawRibbon(positions, visibleStart, width, alpha)

        ctx.restore()
    }
    getRibbonWidth(track)
    {
        const config = STYLE.trails.player
        const width = track.lineWidth * config.widthRatio * this.getBadVersionTrails().widthMultiplier

        return Math.max(width, config.minScreenWidth / scale[version])
    }
    getRibbonPoints(positions, minDistance)
    {
        if (positions.length < 3 || minDistance <= 0)
            return positions

        const ribbonPoints = this.ribbonPoints
        let last = positions[0]
        let count = 1

        // Overwrite in place: length = 0 would drop the backing store every frame.
        ribbonPoints[0] = last

        for (let i = 1; i < positions.length - 1; ++i)
        {
            const dx = positions[i].x - last.x
            const dy = positions[i].y - last.y

            if (Math.sqrt(dx * dx + dy * dy) >= minDistance)
            {
                ribbonPoints[count++] = positions[i]
                last = positions[i]
            }
        }

        ribbonPoints[count++] = positions[positions.length - 1]
        ribbonPoints.length = count
        return ribbonPoints
    }
    drawRibbon(positions, visibleStart, width, alpha)
    {
        // No shadowBlur and no gradient: the fade toward the tail comes from
        // stacked wedges that each taper to their own start, so alpha builds up
        // smoothly toward the head.
        const config = STYLE.trails.player
        const colors = STYLE.colors.playerTrail
        const count = positions.length - visibleStart

        if (count < 2)
            return

        if (STYLE.player.outerGlow)
            this.fillRibbon(positions, visibleStart, width * config.haloWidthRatio, colors.halo, alpha * config.haloAlpha)

        for (let i = 0; i < config.bodyLayers; ++i)
        {
            const start = visibleStart + Math.floor(count * i / config.bodyLayers)

            this.fillRibbon(positions, start, width, colors.body, alpha * config.bodyAlpha)
        }

        const coreStart = visibleStart + Math.floor(count * config.coreStartRatio)

        this.fillRibbon(positions, coreStart, width * config.coreWidthRatio, colors.core, alpha * config.coreAlpha)
    }
    fillRibbon(positions, start, width, color, alpha)
    {
        if (positions.length - start < 2)
            return

        const index = this.ribbonPathIndex++
        let path = this.ribbonPaths[index]
        if (!path)
        {
            const outline = this.getRibbonOutline(positions, start, width)
            if (!outline.length)
                return
            path = new Path2D()
            path.moveTo(outline[0].x, outline[0].y)
            for (let i = 1; i < outline.length; ++i)
                path.lineTo(outline[i].x, outline[i].y)
            path.closePath()
            this.ribbonPaths[index] = path
        }

        ctx.globalAlpha = this.clampAlpha(alpha) * STYLE.player.effectOpacity
        ctx.fillStyle = color
        ctx.fill(path)
    }
    getRibbonOutline(positions, visibleStart, width)
    {
        const config = STYLE.trails.player
        const left = this.ribbonLeft
        const right = this.ribbonRight
        const outline = this.ribbonOutline
        let count = 0
        const start = Math.max(0, visibleStart - 1)
        const end = positions.length - 1
        const span = Math.max(1, end - start)

        for (let i = start; i <= end; ++i)
        {
            const previous = positions[Math.max(start, i - 1)]
            const current = positions[i]
            const next = positions[Math.min(end, i + 1)]
            const dx = next.x - previous.x
            const dy = next.y - previous.y
            const length = Math.sqrt(dx * dx + dy * dy)

            if (length <= 0)
                continue

            const progress = (i - start) / span
            const eased = progress * progress * (3 - 2 * progress)
            const localWidth = width * (config.tailWidthRatio + (config.headWidthRatio - config.tailWidthRatio) * eased)
            const normalX = -dy / length
            const normalY = dx / length
            const centerX = current.x + screen.x
            const centerY = current.y + screen.y
            const halfWidth = localWidth / 2

            if (count == left.length)
            {
                left.push({x: 0, y: 0})
                right.push({x: 0, y: 0})
            }

            left[count].x = centerX + normalX * halfWidth
            left[count].y = centerY + normalY * halfWidth
            right[count].x = centerX - normalX * halfWidth
            right[count].y = centerY - normalY * halfWidth
            ++count
        }

        outline.length = count * 2

        for (let i = 0; i < count; ++i)
        {
            outline[i] = left[i]
            outline[count * 2 - 1 - i] = right[i]
        }

        return outline
    }
    drawRibbonOutline(outline)
    {
        ctx.beginPath()
        ctx.moveTo(outline[0].x, outline[0].y)

        for (let i = 1; i < outline.length; ++i)
            ctx.lineTo(outline[i].x, outline[i].y)

        ctx.closePath()
    }
    getBadVersionTrails()
    {
        if (typeof version != 'undefined' && version == 'bad')
            return STYLE.badVersionEffects.trails

        return {
            widthMultiplier: 0.5,
            alphaMultiplier: 1
        }
    }
    clampAlpha(alpha)
    {
        return Math.max(0, Math.min(1, alpha))
    }
    getEffectCompositeOperation()
    {
        return STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.effectCompositeOperation
            : 'lighter'
    }
}

// Bloom (STYLE.bloom): the emissive shapes are drawn a second time, as plain
// colour lines, into a glow canvas of at most 1/4 of the backing size. Smaller
// copies of it (each half the previous) blur it; all of them are stretched
// back over the frame with 'lighter', so the outlines get a soft halo while
// the HUD, drawn afterwards, stays crisp. No ctx.filter: the downsample chain
// looks the same in every browser.
class BloomRenderer
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
        this.levels = []
    }
    shouldDraw()
    {
        return STYLE.features.bloom && QUALITY.bloom
    }
    getConfig()
    {
        return STYLE.bloom
    }
    // Level 0 is the glow canvas; each next level is half the previous one.
    resize()
    {
        const config = this.getConfig()
        while (this.levels.length < config.blurLevels)
        {
            const levelCanvas = document.createElement('canvas')
            const levelCtx = levelCanvas.getContext('2d', {alpha: false})
            this.levels.push({canvas: levelCanvas, ctx: levelCtx})
        }

        const resolutionScale = isTouchFirstDevice()
            ? config.touchResolutionScale : config.resolutionScale
        let levelWidth = Math.max(1, Math.floor(this.canvas.width * resolutionScale))
        let levelHeight = Math.max(1, Math.floor(this.canvas.height * resolutionScale))
        for (let i = 0; i < config.blurLevels; ++i)
        {
            const level = this.levels[i]
            // Resizing a canvas clears it and resets its state: only on change
            if (level.canvas.width != levelWidth || level.canvas.height != levelHeight)
            {
                level.canvas.width = levelWidth
                level.canvas.height = levelHeight
                level.ctx.imageSmoothingEnabled = true
            }
            levelWidth = Math.max(1, Math.floor(levelWidth / 2))
            levelHeight = Math.max(1, Math.floor(levelHeight / 2))
        }
    }
    draw(gameState, shakeOffset)
    {
        if (!this.shouldDraw())
            return

        this.resize()
        this.drawGlowPass(gameState, shakeOffset)
        this.blur()
        this.composite(gameState.ninja)
    }
    // Same world transform as the frame (scale[version], screen shake), mapped
    // onto the glow canvas; the global ctx points at it while the sprites draw.
    drawGlowPass(gameState, shakeOffset)
    {
        const glow = this.levels[0]
        const scaleX = glow.canvas.width / width * scale[version]
        const scaleY = glow.canvas.height / height * scale[version]

        this.renderGlow(scaleX, 0, 0, scaleY, shakeOffset.x * scaleX, shakeOffset.y * scaleY,
            this.drawEmissiveShapes, gameState)
    }
    // Menu and pause screens: glow of what drawShapes draws in the current
    // ctx transform (logical units), added under the crisp controls
    drawScreen(drawShapes)
    {
        if (!this.shouldDraw())
            return

        this.resize()
        const glow = this.levels[0].canvas
        const sx = glow.width / this.canvas.width
        const sy = glow.height / this.canvas.height
        const m = this.ctx.getTransform()
        this.renderGlow(m.a * sx, m.b * sy, m.c * sx, m.d * sy, m.e * sx, m.f * sy, drawShapes)
        this.blur()
        this.composite()
    }
    // Clears the glow canvas, sets its transform and calls drawShapes(arg)
    // with the global ctx pointing at it
    renderGlow(a, b, c, d, e, f, drawShapes, arg)
    {
        const glow = this.levels[0]
        const glowCtx = glow.ctx

        glowCtx.setTransform(1, 0, 0, 1, 0, 0)
        glowCtx.globalCompositeOperation = 'source-over'
        glowCtx.globalAlpha = 1
        glowCtx.fillStyle = 'black'
        glowCtx.fillRect(0, 0, glow.canvas.width, glow.canvas.height)
        glowCtx.setTransform(a, b, c, d, e, f)

        const mainCtx = ctx
        const particlesCtx = visualEffects.particles.ctx
        ctx = glowCtx
        visualEffects.particles.ctx = glowCtx
        bloomPassActive = true
        try
        {
            glowCtx.save()
            glowCtx.lineCap = 'round'
            drawShapes.call(this, arg)
            glowCtx.restore()
        }
        finally
        {
            bloomPassActive = false
            visualEffects.particles.ctx = particlesCtx
            ctx = mainCtx
        }
    }
    drawEmissiveShapes(gameState)
    {
        const floors = gameState.floors

        visualEffects.particles.drawAmbientMotes()
        visualEffects.playerTrail.drawSmoothPlayerTrailIfEnabled(gameState.ninja.track)
        grapnel.draw()
        // Obstacle light is clipped inside each full-resolution shape.
        // Hazard trail envelopes and shockwave rings: no shadowBlur, their
        // glow comes from here
        if (version == 'bad' && visualEffects.playerTrail.shouldDraw())
            for (let i = 0; i < floors.length; ++i)
                floors[i].drawTracks()
        visualEffects.screenEffects.drawShockwaveGlow()
        grapnel.drawHook()
        visualEffects.particles.drawLayer(BloomRenderer.anyParticle)
    }
    static anyParticle(particle)
    {
        return !particle.ember
    }
    blur()
    {
        for (let i = 1; i < this.levels.length; ++i)
        {
            const source = this.levels[i - 1].canvas
            const target = this.levels[i]
            target.ctx.drawImage(source, 0, 0, target.canvas.width, target.canvas.height)
        }
    }
    composite(player, exclusionRadiusRatio = 2)
    {
        const config = this.getConfig()

        this.ctx.save()
        const world = this.ctx.getTransform()
        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        if (player)
        {
            // Clip the final blurred light, including rope/particle spill, out
            // of the ring and its neighbourhood. Use the frame transform so
            // the exclusion follows camera shake, game scale and device DPR.
            this.ctx.beginPath()
            this.ctx.rect(0, 0, this.canvas.width, this.canvas.height)
            this.ctx.setTransform(world)
            this.ctx.moveTo(player.x + screen.x + player.getRingOuterRadius() * exclusionRadiusRatio, player.y + screen.y)
            this.ctx.arc(player.x + screen.x, player.y + screen.y,
                player.getRingOuterRadius() * exclusionRadiusRatio, 0, Math.PI * 2)
            this.ctx.clip('evenodd')
            this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        }
        this.ctx.globalCompositeOperation = config.compositeOperation
        this.ctx.imageSmoothingEnabled = true
        for (let i = 0; i < this.levels.length; ++i)
        {
            this.ctx.globalAlpha = Math.max(0, Math.min(1, config.levelAlphas[i] * config.strength * neonPulse))
            this.ctx.drawImage(this.levels[i].canvas, 0, 0, this.canvas.width, this.canvas.height)
        }
        this.ctx.restore()
    }
}

// The historical bloom chain restricted to ambient motes. It follows ambient
// quality, independently of the disabled global bloom feature.
class AmbientGlowRenderer extends BloomRenderer
{
    getConfig()
    {
        return STYLE.ambient.glow
    }
    shouldDraw()
    {
        return visualEffects.particles.shouldDrawAmbientMotes()
    }
    // The blur levels are added together at glow resolution first, so the
    // frame gets one upscaled full-frame draw instead of one per level (a
    // software canvas such as Firefox's pays each of them per pixel). The
    // levels are added either way ('lighter'), so the sum is the same.
    composite(player, exclusionRadiusRatio)
    {
        const config = this.getConfig()
        if (player || config.compositeOperation !== 'lighter')
            return super.composite(player, exclusionRadiusRatio)

        const glow = this.levels[0].canvas
        if (!this.sum)
        {
            const canvas = document.createElement('canvas')
            this.sum = {canvas, ctx: canvas.getContext('2d', {alpha: false})}
        }
        const sum = this.sum
        if (sum.canvas.width != glow.width || sum.canvas.height != glow.height)
        {
            sum.canvas.width = glow.width
            sum.canvas.height = glow.height
        }
        const sumCtx = sum.ctx
        sumCtx.globalCompositeOperation = 'source-over'
        sumCtx.globalAlpha = 1
        sumCtx.fillStyle = 'black'
        sumCtx.fillRect(0, 0, glow.width, glow.height)
        sumCtx.imageSmoothingEnabled = true
        // The smallest level goes first, over black: there source-over adds
        // it as 'lighter' would (up to rounding, a few 8-bit steps in the
        // halos) and costs less per upscaled pixel in Chromium. The others
        // add in any order.
        for (let k = 0; k < this.levels.length; ++k)
        {
            const i = (k + this.levels.length - 1) % this.levels.length
            sumCtx.globalCompositeOperation = k ? 'lighter' : 'source-over'
            sumCtx.globalAlpha = Math.max(0, Math.min(1, config.levelAlphas[i] * config.strength * neonPulse))
            sumCtx.drawImage(this.levels[i].canvas, 0, 0, glow.width, glow.height)
        }

        this.ctx.save()
        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        this.ctx.globalCompositeOperation = 'lighter'
        this.ctx.globalAlpha = 1
        this.ctx.imageSmoothingEnabled = true
        this.ctx.drawImage(sum.canvas, 0, 0, this.canvas.width, this.canvas.height)
        this.ctx.restore()
    }
}

// Player-only glow textures retain the historical downsampled soft halo. The
// canvases and ribbon paths are reused; no per-frame shadowBlur or filter.
// Only the player ribbon, square sparks and ring enter these textures: world
// outlines, rope, ambient particles and obstacle trails cannot emit here.
class PlayerGlowRenderer extends BloomRenderer
{
    // Experimental cropped intermediates. Full-grid dimensions remain the
    // authority for transforms; allocated dimensions never set effect scale.
    draw(gameState, shakeOffset)
    {
        if (!this.shouldDraw()) return
        const config = this.getConfig()
        const ratio = isTouchFirstDevice() ? config.touchResolutionScale : config.resolutionScale
        let fw = Math.max(1, Math.floor(this.canvas.width * ratio))
        let fh = Math.max(1, Math.floor(this.canvas.height * ratio))
        // Per-level full-grid sizes, reused from frame to frame
        const full = this.fullSizes || (this.fullSizes = [])
        full.length = config.blurLevels
        for (let i = 0; i < config.blurLevels; ++i) {
            const size = full[i] || (full[i] = [0, 0])
            size[0] = fw; size[1] = fh; fw = Math.max(1, Math.floor(fw / 2)); fh = Math.max(1, Math.floor(fh / 2))
        }
        const sx = full[0][0] / width * scale[version]
        const sy = full[0][1] / height * scale[version]
        const player = gameState.ninja
        // Bounds of the glow sources on the level-0 grid (inlined: a closure
        // over these numbers would allocate on every assignment)
        const ox = shakeOffset.x, oy = shakeOffset.y
        const ringRadius = player.getRingOuterRadius()
        let left = (player.x+screen.x+ox-ringRadius)*sx, right = (player.x+screen.x+ox+ringRadius)*sx
        let top = (player.y+screen.y+oy-ringRadius)*sy, bottom = (player.y+screen.y+oy+ringRadius)*sy
        const trail = visualEffects.playerTrail
        if (trail.shouldDraw()) {
            const radius = trail.getRibbonWidth(player.track) * Math.max(1, STYLE.trails.player.headWidthRatio)
            const pos = player.track.pos
            for (let i = 0; i < pos.length; ++i) {
                const x = pos[i].x+screen.x+ox, y = pos[i].y+screen.y+oy
                if ((x-radius)*sx < left) left = (x-radius)*sx
                if ((x+radius)*sx > right) right = (x+radius)*sx
                if ((y-radius)*sy < top) top = (y-radius)*sy
                if ((y+radius)*sy > bottom) bottom = (y+radius)*sy
            }
        }
        const particles = visualEffects.particles.particles
        for (let i = 0; i < particles.length; ++i) {
            const p = particles[i]
            if (!p.spark) continue
            const x = p.x+(p.worldAnchored?screen.x:0)+ox, y = p.y+(p.worldAnchored?screen.y:0)+oy, r = p.size
            if ((x-r)*sx < left) left = (x-r)*sx
            if ((x+r)*sx > right) right = (x+r)*sx
            if ((y-r)*sy < top) top = (y-r)*sy
            if ((y+r)*sy > bottom) bottom = (y+r)*sy
        }
        // Four texels at the coarsest level cover the bilinear chain and halo.
        const padding = 4 * Math.max(full[0][0]/full.at(-1)[0], full[0][1]/full.at(-1)[1])
        left -= padding; top -= padding; right += padding; bottom += padding
        for (let i = 0; i < full.length; ++i) {
            const [w,h] = full[i], rx = w/full[0][0], ry = h/full[0][1]
            const x = Math.max(0, Math.min(w-1, Math.floor(left*rx)))
            const y = Math.max(0, Math.min(h-1, Math.floor(top*ry)))
            // Bucket capacity to reuse canvases as the trail moves.
            const cw = Math.max(1, Math.min(w-x, Math.ceil((Math.min(w,Math.ceil(right*rx))-x)/16)*16))
            const ch = Math.max(1, Math.min(h-y, Math.ceil((Math.min(h,Math.ceil(bottom*ry))-y)/16)*16))
            if (!this.levels[i]) {
                const canvas = document.createElement('canvas')
                this.levels[i] = {canvas, ctx:canvas.getContext('2d',{alpha:false})}
            }
            const level = this.levels[i]
            if (level.canvas.width !== cw || level.canvas.height !== ch) {
                level.canvas.width = cw; level.canvas.height = ch
            }
            if (!level.origin) { level.origin = [0,0]; level.full = [0,0] }
            level.origin[0] = x; level.origin[1] = y; level.full[0] = w; level.full[1] = h
        }
        const first = this.levels[0]
        this.renderGlow(sx,0,0,sy,shakeOffset.x*sx-first.origin[0],shakeOffset.y*sy-first.origin[1],this.drawEmissiveShapes,gameState)
        for (let i=1;i<this.levels.length;++i) {
            const a=this.levels[i-1], b=this.levels[i]
            const rx=b.full[0]/a.full[0], ry=b.full[1]/a.full[1]
            b.ctx.setTransform(1,0,0,1,0,0); b.ctx.fillStyle='black'
            b.ctx.fillRect(0,0,b.canvas.width,b.canvas.height)
            b.ctx.drawImage(a.canvas,a.origin[0]*rx-b.origin[0],a.origin[1]*ry-b.origin[1],a.canvas.width*rx,a.canvas.height*ry)
        }
        const context=this.ctx, world=context.getTransform()
        context.save(); context.setTransform(1,0,0,1,0,0)
        context.beginPath(); context.rect(0,0,this.canvas.width,this.canvas.height)
        context.setTransform(world)
        const radius=player.getRingOuterRadius()*config.ringClearanceRatio
        context.moveTo(player.x+screen.x+radius,player.y+screen.y)
        context.arc(player.x+screen.x,player.y+screen.y,radius,0,Math.PI*2)
        context.clip('evenodd'); context.setTransform(1,0,0,1,0,0)
        context.globalCompositeOperation=config.compositeOperation; context.imageSmoothingEnabled=true
        if (config.compositeOperation === 'lighter') this.compositeSummed(context, config)
        else for(let i=0;i<this.levels.length;++i) {
            const l=this.levels[i], rx=this.canvas.width/l.full[0], ry=this.canvas.height/l.full[1]
            context.globalAlpha=Math.max(0,Math.min(1,config.levelAlphas[i]*config.strength*neonPulse))
            context.drawImage(l.canvas,l.origin[0]*rx,l.origin[1]*ry,l.canvas.width*rx,l.canvas.height*ry)
        }
        context.restore()
    }
    // Adds the levels together on the level-0 grid over the union of their
    // crops, then draws that once through the ring clip: the frame pays one
    // upscaled blend instead of one per level ('lighter' adds either way).
    compositeSummed(context, config)
    {
        const full = this.levels[0].full
        let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
        for (const l of this.levels) {
            const rx = full[0]/l.full[0], ry = full[1]/l.full[1]
            left = Math.min(left, l.origin[0]*rx); top = Math.min(top, l.origin[1]*ry)
            right = Math.max(right, (l.origin[0]+l.canvas.width)*rx); bottom = Math.max(bottom, (l.origin[1]+l.canvas.height)*ry)
        }
        left = Math.floor(left); top = Math.floor(top)
        const w = Math.max(1, Math.ceil(right-left)), h = Math.max(1, Math.ceil(bottom-top))
        if (!this.sum) {
            const canvas = document.createElement('canvas')
            this.sum = {canvas, ctx:canvas.getContext('2d',{alpha:false})}
        }
        const sum = this.sum
        // Bucketed like the levels, so a moving trail rarely reallocates
        const cw = Math.ceil(w/16)*16, ch = Math.ceil(h/16)*16
        if (sum.canvas.width < cw || sum.canvas.height < ch || sum.canvas.width > cw*2 || sum.canvas.height > ch*2) {
            sum.canvas.width = cw; sum.canvas.height = ch
        }
        const c = sum.ctx
        c.setTransform(1,0,0,1,0,0); c.globalCompositeOperation='source-over'; c.globalAlpha=1
        c.fillStyle='black'; c.fillRect(0,0,w,h)
        c.globalCompositeOperation='lighter'; c.imageSmoothingEnabled=true
        for (let i=0;i<this.levels.length;++i) {
            const l=this.levels[i], rx=full[0]/l.full[0], ry=full[1]/l.full[1]
            c.globalAlpha=Math.max(0,Math.min(1,config.levelAlphas[i]*config.strength*neonPulse))
            c.drawImage(l.canvas,l.origin[0]*rx-left,l.origin[1]*ry-top,l.canvas.width*rx,l.canvas.height*ry)
        }
        const rx=this.canvas.width/full[0], ry=this.canvas.height/full[1]
        context.globalAlpha=1
        context.drawImage(sum.canvas,0,0,w,h,left*rx,top*ry,w*rx,h*ry)
    }

    getConfig()
    {
        return STYLE.player.glow
    }
    shouldDraw()
    {
        return STYLE.player.outerGlow && QUALITY.playerTrail
    }
    drawEmissiveShapes(gameState)
    {
        visualEffects.playerTrail.drawSmoothPlayerTrailIfEnabled(gameState.ninja.track)
        visualEffects.particles.drawLayer(PlayerGlowRenderer.isSpark)
        const player = gameState.ninja
        const radius = player.getRingOuterRadius()
        const ringWidth = radius * STYLE.playerVisuals.ringWidthRatio
        ctx.beginPath()
        ctx.arc(player.x + screen.x, player.y + screen.y,
            radius - ringWidth * 0.5, 0, Math.PI * 2)
        ctx.globalAlpha = player.getBlinkAlpha() * STYLE.player.effectOpacity
        ctx.strokeStyle = player.stroke
        ctx.lineWidth = ringWidth
        ctx.stroke()
        ctx.globalAlpha = 1
    }
    static isSpark(particle)
    {
        return particle.spark
    }
    composite(player)
    {
        // Leave a narrow contrast margin at the original ring edge. The
        // cached ball halo still fills it; broad ribbon light starts beyond it.
        super.composite(player, STYLE.player.glow.ringClearanceRatio)
    }
}

class ColorGradeRenderer
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
        this.gradients = null
        this.gradientKey = ''
    }
    shouldDraw()
    {
        return STYLE.features.colorGrade
    }
    // Built once per backing size; the grade itself never creates gradients
    getGradients(width, height)
    {
        const key = width + 'x' + height
        if (this.gradientKey == key)
            return this.gradients

        const config = STYLE.colorGrade
        const ctx = this.ctx

        const shadows = ctx.createLinearGradient(0, 0, 0, height)
        shadows.addColorStop(0, config.shadowTop)
        shadows.addColorStop(1, config.shadowBottom)

        const highlights = ctx.createRadialGradient(
            width * config.highlightCenterX, height * config.highlightCenterY, 0,
            width * config.highlightCenterX, height * config.highlightCenterY, Math.hypot(width, height) * 0.6)
        highlights.addColorStop(0, config.highlightCenter)
        highlights.addColorStop(1, config.highlightEdge)

        const radius = Math.hypot(width, height) / 2
        const vignette = ctx.createRadialGradient(width / 2, height / 2, radius * config.vignetteInner,
            width / 2, height / 2, radius)
        vignette.addColorStop(0, 'rgba(0, 0, 0, 0)')
        vignette.addColorStop(1, config.vignetteEdge)

        this.gradients = {shadows, highlights, vignette}
        this.gradientKey = key
        return this.gradients
    }
    // Screen-fixed full-frame fills over the world (not the HUD): shadows lifted
    // toward blue, highlights pushed toward magenta, then the corner vignette
    draw()
    {
        if (!this.shouldDraw())
            return

        const config = STYLE.colorGrade
        const ctx = this.ctx
        const width = this.canvas.width
        const height = this.canvas.height
        const gradients = this.getGradients(width, height)

        ctx.save()
        ctx.setTransform(1, 0, 0, 1, 0, 0)
        ctx.globalCompositeOperation = config.shadowOperation
        ctx.fillStyle = gradients.shadows
        ctx.fillRect(0, 0, width, height)
        ctx.globalCompositeOperation = config.highlightOperation
        ctx.fillStyle = gradients.highlights
        ctx.fillRect(0, 0, width, height)
        ctx.globalCompositeOperation = 'source-over'
        ctx.fillStyle = gradients.vignette
        ctx.fillRect(0, 0, width, height)
        ctx.restore()
    }
}

class ScreenEffects
{
    constructor(context)
    {
        this.ctx = context
        this.shockwaves = []
        this.landings = []
        this.shakeUntil = 0
        this.shakeStart = 0
        this.shakeOffset = {x: 0, y: 0}
        this.isShaking = false
    }
    shouldApply()
    {
        return STYLE.features.screenEffects
    }
    triggerLanding(contact)
    {
        if (!this.shouldApply())
            return
        const now = performance.now()
        const config = STYLE.screenEffects
        if (this.landings.length >= config.landingMaxCount)
            this.landings.shift()
        this.landings.push({x: contact.x, y: contact.y,
            angle: Math.atan2(contact.ny, contact.nx), start: now})
    }
    drawLandings(now)
    {
        const config = STYLE.screenEffects
        for (let i = this.landings.length - 1; i >= 0; --i)
            if (now - this.landings[i].start >= config.landingDurationMs)
                this.landings.splice(i, 1)
        if (!this.landings.length)
            return

        const context = this.ctx
        const unit = 1 / scale[version]
        context.save()
        context.globalCompositeOperation = 'source-over'
        context.lineCap = 'round'
        // Two plain strokes keep the impact crisp without per-frame blur.
        for (const impact of this.landings)
        {
            const progress = Math.max(0, (now - impact.start) / config.landingDurationMs)
            const eased = 1 - (1 - progress) * (1 - progress)
            const radius = (config.landingStartRadius
                + (config.landingEndRadius - config.landingStartRadius) * eased) * unit
            context.save()
            context.translate(impact.x + screen.x, impact.y + screen.y)
            context.rotate(impact.angle)
            // Local +x is the contact normal: keep the entire stroke on the
            // exposed side, including its rounded caps at the surface.
            context.beginPath()
            context.rect(0, -radius * 2, radius * 2, radius * 4)
            context.clip()
            for (let pass = 0; pass < 2; ++pass)
            {
                context.strokeStyle = pass ? '#d8ffff' : STYLE.colors.player.cyan
                context.lineWidth = config.landingLineWidth * unit * (pass ? 1 : 2.5)
                context.globalAlpha = config.landingAlpha * (1 - progress) * (pass ? 1 : 0.25)
                context.beginPath()
                context.arc(0, 0, radius, -Math.PI / 2, Math.PI / 2)
                context.stroke()
            }
            context.restore()
        }
        context.restore()
    }
    triggerDeath(x, y)
    {
        if (!this.shouldApply())
            return

        const now = performance.now()

        this.shockwaves.push({
            x,
            y,
            start: now,
            end: now + STYLE.screenEffects.shockwaveDurationMs
        })

        if (QUALITY.screenShake)
        {
            this.shakeStart = now
            this.shakeUntil = now + STYLE.screenEffects.shakeDurationMs
        }
    }
    begin()
    {
        if (!this.shouldApply())
            return

        this.isShaking = false

        if (!QUALITY.screenShake)
            return

        const now = performance.now()

        if (now >= this.shakeUntil)
            return

        const duration = Math.max(1, STYLE.screenEffects.shakeDurationMs)
        const progress = Math.min(1, (now - this.shakeStart) / duration)
        const magnitudeX = STYLE.screenEffects.shakeMagnitudeX * (1 - progress)
        const magnitudeY = STYLE.screenEffects.shakeMagnitudeY * (1 - progress)
        const angle = now * 0.07

        this.shakeOffset.x = Math.cos(angle * 1.7) * magnitudeX
        this.shakeOffset.y = Math.sin(angle * 2.1) * magnitudeY

        this.ctx.save()
        this.ctx.translate(this.shakeOffset.x, this.shakeOffset.y)
        this.isShaking = true
    }
    draw()
    {
        if (!this.shouldApply())
            return

        const now = performance.now()
        const config = STYLE.screenEffects

        this.drawLandings(now)
        for (let i = this.shockwaves.length - 1; i >= 0; --i)
        {
            if (now >= this.shockwaves[i].end)
                this.shockwaves.splice(i, 1)
        }
        if (!this.shockwaves.length)
            return

        this.ctx.save()
        this.ctx.globalCompositeOperation = STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.effectCompositeOperation
            : 'lighter'
        this.ctx.strokeStyle = STYLE.colors.player.cyan

        // The radius changes every frame, so the glow is not a sprite: soft
        // halo strokes as wide as the old shadowBlur (canvas px), plus bloom
        const blur = config.shockwaveGlowWidth / this.ctx.getTransform().a
        for (let i = 0; i < config.shockwaveHaloAlphas.length; ++i)
        {
            this.strokeShockwaves(this.ctx, now, config.shockwaveLineWidth + blur * config.shockwaveHaloWidths[i],
                config.shockwaveHaloAlphas[i])
        }
        this.strokeShockwaves(this.ctx, now, config.shockwaveLineWidth, 1)

        this.ctx.restore()
    }
    // Bloom pass (global ctx is the glow canvas): the rings as plain lines
    drawShockwaveGlow()
    {
        if (!this.shouldApply() || !this.shockwaves.length)
            return

        ctx.strokeStyle = STYLE.colors.player.cyan
        this.strokeShockwaves(ctx, performance.now(), STYLE.screenEffects.shockwaveLineWidth, 1)
        ctx.globalAlpha = 1
    }
    strokeShockwaves(context, now, lineWidth, alpha)
    {
        const config = STYLE.screenEffects
        const stableAlpha = STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.stableEffectAlphaMultiplier
            : 1

        context.lineWidth = lineWidth
        for (let i = this.shockwaves.length - 1; i >= 0; --i)
        {
            const shockwave = this.shockwaves[i]
            if (now >= shockwave.end)
                continue

            const progress = (now - shockwave.start) / Math.max(1, config.shockwaveDurationMs)
            const eased = 1 - Math.pow(1 - progress, 2)
            const radius = config.shockwaveStartRadius
                + (config.shockwaveEndRadius - config.shockwaveStartRadius) * eased

            context.globalAlpha = config.shockwaveAlpha * stableAlpha * (1 - progress) * alpha
            context.beginPath()
            context.arc(shockwave.x, shockwave.y, radius, 0, Math.PI * 2)
            context.stroke()
            context.closePath()
        }
    }
    end()
    {
        if (!this.shouldApply())
            return

        if (this.isShaking)
        {
            this.ctx.restore()
            this.isShaking = false
        }
    }
}

class UIStylingHooks
{
    shouldDraw()
    {
        return STYLE.features.uiStyling
    }
    drawFpsCounter(gameState)
    {
        if (!this.shouldDraw())
            return

        gameState.fpsCounter.draw()
    }
    draw(gameState)
    {
        if (!this.shouldDraw())
            return

        if (version === 'grapple_over')
            CLIMB_UI.drawHud(gameState.menu.button)
        else
        {
            gameState.scoreText.draw()
            gameState.menu.button.draw()
        }
    }
}

class VisualEffects
{
    constructor(context, targetCanvas)
    {
        this.background = new BackgroundRenderer(context, targetCanvas)
        this.lightmap = new LightmapRenderer(context, targetCanvas)
        this.particles = new ParticleSystem(context, targetCanvas)
        this.playerTrail = new PlayerTrailRenderer()
        this.screenEffects = new ScreenEffects(context)
        this.bloom = new BloomRenderer(context, targetCanvas)
        this.ambientGlow = new AmbientGlowRenderer(context, targetCanvas)
        this.playerGlow = new PlayerGlowRenderer(context, targetCanvas)
        this.colorGrade = new ColorGradeRenderer(context, targetCanvas)
        this.ui = new UIStylingHooks()
    }
    getGameState()
    {
        return {
            floors,
            ninja,
            scoreText,
            menu,
            fpsCounter
        }
    }
}
