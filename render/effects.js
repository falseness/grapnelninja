// The bars only show soft gradients and faint lines, so the bar canvases
// render at a quarter of their CSS size and CSS stretches them: a
// full-resolution repaint cost ~30% of the frame at 2560x1080
const WINDOW_BACKGROUND_SCALE = 0.25

// The bars background drifts slowly: it is repainted every few frames (and at
// once after a resize or a menu/game switch), which also spares the
// compositor a texture upload on the frames in between
const WINDOW_BARS_EVERY_FRAMES = 4

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
        // Offscreen crystal/rock tiles by name ('far', 'near', their edge
        // tiles 'farEdges', 'nearEdges') and how often each was built
        this.layerCache = {}
        this.layerBuilds = {}
        // The game canvas transform the layers were last painted in
        this.paintTransform = null
    }
    draw()
    {
        this.paint()
        // Momentum lighting dims the bars to its ambient with the play rect
        const ambient = visualEffects.lightmap.getMomentumAmbient()
        this.drawWindowBars('game' + (ambient ? ambient : ''), () =>
        {
            this.paint()
            if (ambient)
                this.dimToAmbient(ambient)
        })
    }
    dimToAmbient(ambient)
    {
        this.ctx.save()
        this.ctx.globalCompositeOperation = 'multiply'
        this.ctx.fillStyle = ambient
        this.fillAll()
        this.ctx.restore()
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

        const key = [scene, rect.left, rect.top, rect.width].join()
        if (barCanvases[0].barsKey === key && ++this.barsFramesSkipped < WINDOW_BARS_EVERY_FRAMES)
            return
        this.barsFramesSkipped = 0

        const gameCtx = this.ctx
        const fit = rect.width / LOGICAL_VIEWPORT.width

        for (const barCanvas of barCanvases)
        {
            const box = barCanvas.box
            const ctx = barCanvas.getContext('2d')
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
        }
    }
    paint()
    {
        this.clearAll()

        if (!STYLE.features.background)
            return

        const width = LOGICAL_VIEWPORT.width
        const height = LOGICAL_VIEWPORT.height

        const caveLayers = STYLE.caveLayers
        if (!this.bounds)
            this.paintTransform = this.ctx.getTransform()

        // Base gradient, far crystals and haze come baked in one opaque tile
        this.drawCrystalLayer(width, height, this.getLayerShift(width, height, caveLayers.crystals))
        this.preserveGameplayRandomSequence(1, 40)
        this.drawNearLayer(width, height, this.getLayerShift(width, height, caveLayers.nearRocks))
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
        this.ctx.fillStyle = this.getGradients(width, height).vignette
        this.fillAll()
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
    // (a resize builds a new one)
    getLayerTile(name, width, height, config, paint)
    {
        const pixelScale = Math.max(0.25, Math.min(config.maxPixelScale, this.canvas.width / width || 1))
        const key = [width, height, pixelScale].join('|')
        const cached = this.layerCache[name]

        if (cached && cached.key === key)
            return cached

        const layerCanvas = document.createElement('canvas')
        layerCanvas.width = Math.max(1, Math.round(width * pixelScale))
        layerCanvas.height = Math.max(1, Math.round(height * pixelScale))
        const ctx = layerCanvas.getContext('2d')
        ctx.setTransform(layerCanvas.width / width, 0, 0, layerCanvas.height / height, 0, 0)
        paint(ctx, width, height, config, this.getTileTools(ctx, width, config.seed))

        const layer = {key, canvas: layerCanvas, width, height}
        this.layerCache[name] = layer
        this.layerBuilds[name] = (this.layerBuilds[name] || 0) + 1
        return layer
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
    // edgesOnly: the same shards' edges alone, opaque white (the edge tile
    // the momentum crystal rim masks by the light)
    paintCrystalTile(ctx, width, height, crystals, tools, edgesOnly)
    {
        const colors = STYLE.colors.background
        const {random, between, wrapped} = tools
        const polygon = edgesOnly ? () => {} : tools.polygon
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
                ctx.strokeStyle = edgesOnly ? '#ffffff' : edge
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
        if (edgesOnly)
            return
        // Solid rock rows at both edges: drawLayerTile extends them over
        // whatever the shifted tile leaves uncovered
        ctx.fillStyle = colors.crystalRock
        ctx.fillRect(0, 0, width, height * 0.012)
        ctx.fillRect(0, height * 0.988, width, height * 0.012)
    }
    // Large dark boulders: a shadow, a middle and a lit facet around the
    // summit, and a faint rim along the lit side
    paintNearTile(ctx, width, height, rocks, tools, edgesOnly)
    {
        const colors = STYLE.colors.background
        const {random, between, wrapped} = tools
        const polygon = edgesOnly ? () => {} : tools.polygon
        const boulder = (x, baseY, dir, h, w) =>
        {
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
                ctx.strokeStyle = edgesOnly ? '#ffffff' : colors.nearRim
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
        if (edgesOnly)
            return
        ctx.fillStyle = colors.nearRock
        ctx.fillRect(0, 0, width, height * 0.012)
        ctx.fillRect(0, height * 0.988, width, height * 0.012)
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
            })
        this.drawLayerTile(baked, width, height, shift, STYLE.colors.background.crystalRock,
            this.getGradients(width, height).haze)
    }
    drawNearLayer(width, height, shift)
    {
        const layer = this.getLayerTile('near', width, height, STYLE.caveLayers.nearRocks,
            (...args) => this.paintNearTile(...args))
        this.drawLayerTile(layer, width, height, shift, STYLE.colors.background.nearRock)
    }
    // The crystal and rock edges where this frame's layers lie, opaque white
    // into ctx (a canvas of the game canvas's size, in its px): the far
    // crystals' edges with the near rocks cut out of them, then the near
    // rocks' rims. Edge tiles are built once per viewport like the layers.
    drawLayerEdges(ctx)
    {
        const width = LOGICAL_VIEWPORT.width
        const height = LOGICAL_VIEWPORT.height
        const caveLayers = STYLE.caveLayers
        const near = this.layerCache.near
        if (!this.paintTransform || !near)
            return
        const farEdges = this.getLayerTile('farEdges', width, height, caveLayers.crystals,
            (c, w, h, config, tools) => this.paintCrystalTile(c, w, h, config, tools, true))
        const nearEdges = this.getLayerTile('nearEdges', width, height, caveLayers.nearRocks,
            (c, w, h, config, tools) => this.paintNearTile(c, w, h, config, tools, true))
        const nearShift = this.getLayerShift(width, height, caveLayers.nearRocks)
        const gameCtx = this.ctx
        this.ctx = ctx
        try
        {
            ctx.setTransform(this.paintTransform)
            this.drawLayerTile(farEdges, width, height, this.getLayerShift(width, height, caveLayers.crystals))
            ctx.globalCompositeOperation = 'destination-out'
            this.drawLayerTile(near, width, height, nearShift)
            ctx.globalCompositeOperation = 'source-over'
            this.drawLayerTile(nearEdges, width, height, nearShift)
        }
        finally
        {
            this.ctx = gameCtx
        }
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

        while (left < right)
        {
            const next = fromDevice(toDevice(shift.x + (k + 1) * width))
            this.ctx.drawImage(layer.canvas, left, shift.y, next - left, height)
            left = next
            ++k
        }
        if (!edgeFill)
            return

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
        // Momentum lighting: the ambient grey with the ninja's light, multiplied
        // over the background (same size as lightCanvas)
        this.momentumCanvas = document.createElement('canvas')
        this.momentumCtx = this.momentumCanvas.getContext('2d')
        // Its haze, added over the background after the obstacle spill
        this.hazeCanvas = document.createElement('canvas')
        this.hazeCtx = this.hazeCanvas.getContext('2d')
        // One light at a time with its shadows cut out, added to momentumCanvas
        this.lightLayerCanvas = document.createElement('canvas')
        this.lightLayerCtx = this.lightLayerCanvas.getContext('2d')
        // The pieces' shadows of every light, darkening the background after
        // the obstacle spill
        this.hasDeepShadows = false
        this.shadowLayerCanvas = document.createElement('canvas')
        this.shadowLayerCtx = this.shadowLayerCanvas.getContext('2d')
        this.shadowGradient = null
        // Shadow casters of the frame ({points, alpha, deep, box}, world units)
        // and the lights ({x, y, radius, gradient, alpha}), reused per frame
        this.occluders = []
        this.momentumLights = []
        // drawFrameId of the frame momentumLights were collected for
        this.momentumLightsFrame = -1
        // Extra point lights ({x, y, radius, color, alpha}, world units,
        // radius screen px at 1080) that later effects put here per frame
        this.momentumEmitters = []
        // Those plus the blue pieces' area lights of the frame
        this.emitterCandidates = []
        // The player trail's light samples ({x, y, alpha}, world units) and
        // their lights, reused per frame
        this.trailSamples = []
        this.trailLights = []
        // Speed light (updateSpeedLight): s eased over render time, the
        // ninja light's radius/alpha and the trail gain for frame
        this.speedLight = {s: 0, time: -1, ninja: null, frame: -1, radius: 0, alpha: 0, trailGain: 1, hazeScale: 1}
        // Light px rectangle a radial light covers ({x, y, w, h}, reused)
        this.lightRect = {x: 0, y: 0, w: 0, h: 0}
        // Crystal rim: the frame's momentum lights alone (light px) with the
        // light px box they cover, and the cave edges lit by them (the target
        // canvas's px)
        this.rimLightCanvas = document.createElement('canvas')
        this.rimLightCtx = this.rimLightCanvas.getContext('2d')
        this.rimBox = {left: 0, top: 0, right: 0, bottom: 0}
        this.rimCanvas = document.createElement('canvas')
        this.rimCtx = this.rimCanvas.getContext('2d')
        this.momentumAmbient = null
        this.momentumGradient = null
        this.trailBand = null
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
        this.momentumCanvas.width = nextWidth
        this.momentumCanvas.height = nextHeight
        this.hazeCanvas.width = nextWidth
        this.hazeCanvas.height = nextHeight
        this.lightLayerCanvas.width = nextWidth
        this.lightLayerCanvas.height = nextHeight
        this.shadowLayerCanvas.width = nextWidth
        this.shadowLayerCanvas.height = nextHeight
        this.rimLightCanvas.width = nextWidth
        this.rimLightCanvas.height = nextHeight
    }
    // Momentum lighting runs in momentum mode with the pause-screen switch
    // (MOMENTUM_FX) on; classic and bad keep no player light
    shouldDrawMomentumLight()
    {
        return version == 'momentum' && MOMENTUM_FX.enabled && this.shouldDraw()
    }
    // The ambient as an opaque grey fill, or null while momentum lighting is off
    getMomentumAmbient()
    {
        if (!this.shouldDrawMomentumLight())
            return null
        if (!this.momentumAmbient)
        {
            const level = Math.round(STYLE.momentumLight.ambient * 255)
            this.momentumAmbient = 'rgb(' + level + ', ' + level + ', ' + level + ')'
        }
        return this.momentumAmbient
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
        if (!this.isLightOnScreen(x, y, radius))
            return false

        this.fillRadialLight(this.lightCtx, x, y, radius, this.getLightGradient(color), alpha)
        this.hasLights = true
        return true
    }
    isLightOnScreen(x, y, radius)
    {
        const toLight = this.scale * scale[version]
        const lightX = x * toLight
        const lightY = y * toLight
        const lightRadius = radius * height / 1080 * this.scale

        return !(lightX < -lightRadius || lightY < -lightRadius
            || lightX > this.lightCanvas.width + lightRadius
            || lightY > this.lightCanvas.height + lightRadius)
    }
    // Fills a unit gradient scaled to radius into lightCtx (a context of
    // lightCanvas's size)
    fillRadialLight(lightCtx, x, y, radius, gradient, alpha)
    {
        const toLight = this.scale * scale[version]
        const lightRadius = radius * height / 1080 * this.scale

        lightCtx.setTransform(lightRadius, 0, 0, lightRadius, x * toLight, y * toLight)
        lightCtx.globalAlpha = alpha
        lightCtx.fillStyle = gradient
        lightCtx.fillRect(-1, -1, 2, 2)
    }
    getLightGradient(color)
    {
        let gradient = this.gradients.get(color)

        if (gradient)
            return gradient

        if (this.gradients.size >= 64)
            this.gradients.clear()

        gradient = this.createLightGradient(color)
        this.gradients.set(color, gradient)
        return gradient
    }
    createLightGradient(color)
    {
        const falloff = STYLE.lights.falloff
        const gradient = this.lightCtx.createRadialGradient(0, 0, 0, 0, 0, 1)
        for (let i = 0; i < falloff.length; ++i)
        {
            gradient.addColorStop(falloff[i][0], colorWithAlpha(color, falloff[i][1]))
        }
        return gradient
    }
    // The ninja's light and haze gradient, kept apart from the obstacle
    // light cache so classic and bad see the same cache as before
    getMomentumGradient()
    {
        if (!this.momentumGradient)
            this.momentumGradient = this.createLightGradient(STYLE.colors.player.halo)
        return this.momentumGradient
    }
    draw(gameState)
    {
        if (!this.shouldDraw())
            return

        // Momentum lighting: the pieces (the only spill there) emit no spill,
        // blues are area lights instead (collectMomentumLights). Only under
        // the translucent player trail, whose pixels stay as with the
        // lighting off, the spill is kept (clipToTrailBand).
        const momentum = this.shouldDrawMomentumLight()
        const band = momentum ? visualEffects.playerTrail.getRibbonBand(ninja.track) : null
        if (momentum && !band)
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
        if (momentum && this.hasLights)
            this.clipToTrailBand(band)
    }
    // Keeps lightCanvas only inside the trail band (fillTrailBand, built in
    // the light layer canvas, free until composite)
    clipToTrailBand(band)
    {
        const layer = this.lightLayerCtx
        layer.save()
        layer.setTransform(1, 0, 0, 1, 0, 0)
        layer.globalCompositeOperation = 'source-over'
        layer.globalAlpha = 1
        layer.clearRect(0, 0, this.lightLayerCanvas.width, this.lightLayerCanvas.height)
        layer.fillStyle = '#ffffff'
        layer.strokeStyle = '#ffffff'
        this.fillTrailBand(layer, band)
        layer.restore()
        const lightCtx = this.lightCtx
        lightCtx.save()
        lightCtx.setTransform(1, 0, 0, 1, 0, 0)
        lightCtx.globalAlpha = 1
        lightCtx.globalCompositeOperation = 'destination-in'
        lightCtx.drawImage(this.lightLayerCanvas, 0, 0)
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
        const sprite = this.getShapeLightSprite(element, box, color, spread, toLight)
        this.lightCtx.setTransform(toLight, 0, 0, toLight, 0, 0)
        this.lightCtx.globalAlpha = element instanceof Triangle
            ? STYLE.lights.hazardAlpha : this.isOrangeDangerLight(element)
                ? STYLE.lights.dangerAlpha : STYLE.lights.cubeAlpha
        this.lightCtx.drawImage(sprite, x - spread, y - spread,
            sprite.width / toLight, sprite.height / toLight)
        this.hasLights = true
    }
    // The cached light of element's outline in colour, fading out over spread
    // world units from it: a canvas at toLight px per world unit whose (0, 0)
    // lies spread above and left of box (the element's cull box)
    getShapeLightSprite(element, box, color, spread, toLight)
    {
        const w = box.right - box.left, h = box.bottom - box.top
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
        return sprite
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
    composite(gameState)
    {
        const momentum = this.shouldDrawMomentumLight()
        if (momentum)
            this.compositeMomentumLight(gameState)

        // A fully transparent lightmap cannot affect the frame. Avoid the
        // full-canvas blend when all world lights were culled.
        if (this.shouldDraw() && this.hasLights)
            this.compositeCanvas(this.lightCanvas, STYLE.lights.worldCompositeAlpha,
                STYLE.lights.compositeOperation)

        if (momentum && this.hasDeepShadows)
            this.compositeCanvas(this.shadowLayerCanvas, 1, 'source-over')
        if (momentum)
            this.addMomentumHaze()
    }
    compositeCanvas(source, alpha, operation)
    {
        const viewWidth = LOGICAL_VIEWPORT.width / scale[version]
        const viewHeight = LOGICAL_VIEWPORT.height / scale[version]

        this.ctx.save()
        this.ctx.globalAlpha = alpha
        this.ctx.globalCompositeOperation = operation
        this.ctx.imageSmoothingEnabled = true
        this.ctx.drawImage(source, 0, 0, viewWidth, viewHeight)
        this.ctx.restore()
    }
    // Dims the background to the ambient, lit by the ninja: the ambient grey
    // plus its cyan light, multiplied (before the world, motes and trail)
    compositeMomentumLight(gameState)
    {
        const lightCtx = this.momentumCtx

        lightCtx.save()
        lightCtx.setTransform(1, 0, 0, 1, 0, 0)
        lightCtx.globalAlpha = 1
        lightCtx.fillStyle = this.getMomentumAmbient()
        lightCtx.fillRect(0, 0, this.momentumCanvas.width, this.momentumCanvas.height)
        lightCtx.globalCompositeOperation = 'lighter'
        this.clearRimLight()
        this.collectOccluders(gameState)
        this.hasDeepShadows = false
        const lights = this.collectMomentumLights(gameState)
        for (let i = 0; i < lights.length; ++i)
            this.addShadowedLight(lightCtx, lights[i])
        this.trailBand = visualEffects.playerTrail.getRibbonBand(ninja.track)
        if (this.trailBand)
        {
            lightCtx.globalAlpha = 1
            lightCtx.globalCompositeOperation = 'source-over'
            lightCtx.fillStyle = '#ffffff'
            lightCtx.strokeStyle = '#ffffff'
            this.fillTrailBand(lightCtx, this.trailBand)
            if (this.hasDeepShadows)
            {
                const shadows = this.shadowLayerCtx
                shadows.save()
                shadows.globalAlpha = 1
                shadows.globalCompositeOperation = 'destination-out'
                shadows.fillStyle = '#ffffff'
                shadows.strokeStyle = '#ffffff'
                this.fillTrailBand(shadows, this.trailBand)
                shadows.restore()
            }
        }
        lightCtx.restore()

        this.compositeCanvas(this.momentumCanvas, 1, 'multiply')
        this.addCrystalRim()
    }
    clearRimLight()
    {
        const rim = this.rimLightCtx
        rim.setTransform(1, 0, 0, 1, 0, 0)
        rim.globalAlpha = 1
        rim.globalCompositeOperation = 'source-over'
        rim.clearRect(0, 0, this.rimLightCanvas.width, this.rimLightCanvas.height)
        rim.globalCompositeOperation = 'lighter'
        const box = this.rimBox
        box.left = box.top = Infinity
        box.right = box.bottom = -Infinity
    }
    // The shadowed light in the light layer canvas (inside rect, or all of
    // it) also goes into the rim's light
    addRimLight(rect)
    {
        const box = this.rimBox
        if (rect)
            this.rimLightCtx.drawImage(this.lightLayerCanvas, rect.x, rect.y, rect.w, rect.h,
                rect.x, rect.y, rect.w, rect.h)
        else
            this.rimLightCtx.drawImage(this.lightLayerCanvas, 0, 0)
        box.left = Math.min(box.left, rect ? rect.x : 0)
        box.top = Math.min(box.top, rect ? rect.y : 0)
        box.right = Math.max(box.right, rect ? rect.x + rect.w : this.lightLayerCanvas.width)
        box.bottom = Math.max(box.bottom, rect ? rect.y + rect.h : this.lightLayerCanvas.height)
    }
    // Crystal edges catch the light: the background's edge tiles
    // (drawLayerEdges) masked by the frame's lights (source-in) and added
    // over the dimmed background at momentumLight.rimStrength, only inside
    // the lights' box. The cave under the player trail gets none (it keeps
    // its pixels).
    addCrystalRim()
    {
        const strength = STYLE.momentumLight.rimStrength
        const box = this.rimBox
        const background = visualEffects.background
        const transform = background.paintTransform
        if (!(strength > 0) || !STYLE.features.background || !transform
            || box.right <= box.left || box.bottom <= box.top)
            return
        if (this.trailBand)
        {
            const rimLight = this.rimLightCtx
            rimLight.save()
            rimLight.globalAlpha = 1
            rimLight.globalCompositeOperation = 'destination-out'
            rimLight.fillStyle = '#ffffff'
            rimLight.strokeStyle = '#ffffff'
            this.fillTrailBand(rimLight, this.trailBand)
            rimLight.restore()
        }
        const target = this.ctx.canvas
        const rim = this.rimCanvas
        if (rim.width != target.width || rim.height != target.height)
        {
            rim.width = target.width
            rim.height = target.height
        }
        // The lights' box in target px (the light canvas spans the viewport)
        const toTargetX = transform.a * LOGICAL_VIEWPORT.width / this.lightCanvas.width
        const toTargetY = transform.d * LOGICAL_VIEWPORT.height / this.lightCanvas.height
        const left = Math.max(0, Math.floor(box.left * toTargetX + transform.e) - 2)
        const top = Math.max(0, Math.floor(box.top * toTargetY + transform.f) - 2)
        const right = Math.min(rim.width, Math.ceil(box.right * toTargetX + transform.e) + 2)
        const bottom = Math.min(rim.height, Math.ceil(box.bottom * toTargetY + transform.f) + 2)
        if (right <= left || bottom <= top)
            return
        const rimCtx = this.rimCtx
        rimCtx.save()
        rimCtx.setTransform(1, 0, 0, 1, 0, 0)
        rimCtx.globalAlpha = 1
        rimCtx.globalCompositeOperation = 'source-over'
        rimCtx.clearRect(left, top, right - left, bottom - top)
        rimCtx.beginPath()
        rimCtx.rect(left, top, right - left, bottom - top)
        rimCtx.clip()
        background.drawLayerEdges(rimCtx)
        rimCtx.setTransform(transform)
        rimCtx.globalCompositeOperation = 'source-in'
        rimCtx.imageSmoothingEnabled = true
        rimCtx.drawImage(this.rimLightCanvas, 0, 0, LOGICAL_VIEWPORT.width, LOGICAL_VIEWPORT.height)
        rimCtx.restore()

        this.ctx.save()
        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
        this.ctx.globalAlpha = strength
        this.ctx.globalCompositeOperation = 'lighter'
        this.ctx.drawImage(rim, left, top, right - left, bottom - top, left, top, right - left, bottom - top)
        this.ctx.restore()
    }
    // This frame's momentum lights (collectMomentumLights), or null when
    // momentum lighting is off or has not run this frame
    getFrameLights()
    {
        if (!this.shouldDrawMomentumLight() || this.momentumLightsFrame !== drawFrameId)
            return null
        return this.momentumLights
    }
    // The light of light (a momentumLights entry) at x, y (world units) on
    // the ambient, 0..alpha: the radial falloff of STYLE.lights.falloff, a
    // blue's from its outline (its circumscribed circle) over blueSpread,
    // the radius times reach. No shadows.
    getLightAt(light, x, y, reach)
    {
        const toWorld = reach * height / 1080 / scale[version]
        let distance = Math.hypot(x - light.x, y - light.y)
        let radius = light.radius * toWorld
        if (light.element)
        {
            const circle = light.element.circle
            distance = Math.max(0, distance - circle.radius)
            radius = STYLE.momentumLight.blueSpread * toWorld
        }
        if (!(radius > 0) || distance >= radius)
            return 0
        const falloff = STYLE.lights.falloff
        const r = distance / radius
        for (let i = 1; i < falloff.length; ++i)
            if (r <= falloff[i][0])
            {
                const a = falloff[i - 1], b = falloff[i]
                return light.alpha * (a[1] + (b[1] - a[1]) * (r - a[0]) / (b[0] - a[0]))
            }
        return 0
    }
    // The ninja's light plus the momentumLight.maxEmitters emitters nearest
    // to it (momentumEmitters and the blue pieces), each {x, y, radius,
    // gradient, alpha} with x, y on screen; a blue's light has its element
    // instead of a gradient
    collectMomentumLights(gameState)
    {
        const config = STYLE.momentumLight
        const lights = this.momentumLights
        lights.length = 0
        const speed = this.updateSpeedLight()
        const x = ninja.x + screen.x
        const y = ninja.y + screen.y
        if (this.isLightOnScreen(x, y, speed.radius))
            lights.push({x: x, y: y, radius: speed.radius, color: STYLE.colors.player.halo,
                gradient: this.getMomentumGradient(), alpha: speed.alpha, contact: this.getNinjaContact()})
        const emitters = this.collectEmitters(gameState)
        if (emitters.length > config.maxEmitters)
            emitters.sort((a, b) => Math.hypot(a.x - ninja.x, a.y - ninja.y)
                - Math.hypot(b.x - ninja.x, b.y - ninja.y))
        for (let i = 0; i < emitters.length && i < config.maxEmitters; ++i)
        {
            const e = emitters[i]
            if (this.isLightOnScreen(e.x + screen.x, e.y + screen.y, e.radius))
                lights.push({x: e.x + screen.x, y: e.y + screen.y, radius: e.radius, color: e.color,
                    gradient: e.element ? null : this.getLightGradient(e.color), alpha: e.alpha,
                    contact: 0, element: e.element || null})
        }
        this.collectTrailLights(lights)
        this.momentumLightsFrame = drawFrameId
        return lights
    }
    // Eases speedLight.s toward |ninja speed| / GAMEPLAY.momentumMaxSpeed over
    // momentumLight.speedSmoothMs of render clock (a run's first frame and
    // one after speedResetMs take it as is) and sets the frame's ninja light
    // radius and alpha, haze scale and trail gain (fixed with speedLight off)
    updateSpeedLight()
    {
        const config = STYLE.momentumLight
        const state = this.speedLight
        if (!config.speedLight)
        {
            state.radius = config.ninjaRadius
            state.alpha = config.lightAlpha
            state.trailGain = 1
            state.hazeScale = 1
            state.frame = -1
            return state
        }
        if (state.frame === drawFrameId)
            return state
        const now = performance.now()
        const target = Math.min(1, Math.hypot(ninja.speedX, ninja.speedY) / GAMEPLAY.momentumMaxSpeed) || 0
        const elapsed = now - state.time
        if (state.time < 0 || state.ninja !== ninja || !(elapsed >= 0) || elapsed > config.speedResetMs)
            state.s = target
        else
            state.s += (target - state.s) * (1 - Math.exp(-elapsed / config.speedSmoothMs))
        state.time = now
        state.ninja = ninja
        state.frame = drawFrameId
        const s = state.s, slow = config.slow, fast = config.fast
        state.radius = slow.radius + (fast.radius - slow.radius) * s
        state.alpha = slow.alpha + (fast.alpha - slow.alpha) * s
        state.trailGain = slow.trailGain + (fast.trailGain - slow.trailGain) * s
        state.hazeScale = state.radius / config.ninjaRadius
        return state
    }
    // Speed streaks (momentumLight.streak*) into targetCtx under the game
    // transform: thin lines behind the ninja against its velocity once this
    // frame's speedLight.s reaches streakFrom. Placed by streakHash of each
    // streak's index and cycle of the render clock (no Math.random).
    drawSpeedStreaks(targetCtx)
    {
        const config = STYLE.momentumLight
        const state = this.speedLight
        if (!this.shouldDrawMomentumLight() || !config.speedLight || state.frame !== drawFrameId
            || state.s < config.streakFrom)
            return
        const speed = Math.hypot(ninja.speedX, ninja.speedY)
        if (!(speed > 0))
            return
        // Backward and sideways unit vectors
        const bx = -ninja.speedX / speed, by = -ninja.speedY / speed
        const px = -by, py = bx
        const u = Math.min(1, (state.s - config.streakFrom) / (1 - config.streakFrom))
        const count = Math.round(config.streakMin + (config.streakMax - config.streakMin) * u)
        const alpha = config.streakAlpha * (0.35 + 0.65 * u)
        const toWorld = height / 1080 / scale[version]
        const [shortest, longest] = config.streakLength
        const [nearest, farthest] = config.streakSpread
        const x0 = ninja.x + screen.x, y0 = ninja.y + screen.y
        const clock = performance.now() / config.streakPeriodMs
        targetCtx.save()
        targetCtx.globalCompositeOperation = 'lighter'
        targetCtx.strokeStyle = STYLE.colors.player.halo
        targetCtx.lineWidth = config.streakWidth * toWorld
        targetCtx.lineCap = 'round'
        for (let i = 0; i < count; ++i)
        {
            // Golden-ratio phases keep the streaks out of step
            const phase = clock + i * 0.6180339887
            const cycle = Math.floor(phase)
            const t = phase - cycle
            const offset = streakHash(i, cycle, 1)
            const side = (offset < 0.5 ? -1 : 1) * (nearest + (farthest - nearest) * (2 * offset % 1)) * toWorld
            const length = (shortest + (longest - shortest) * streakHash(i, cycle, 2)) * (0.6 + 0.4 * u) * toWorld
            const back = 1.2 * ninja.radius + t * config.streakTravel * toWorld
            const sx = x0 + bx * back + px * side, sy = y0 + by * back + py * side
            targetCtx.globalAlpha = alpha * Math.sin(Math.PI * t)
            targetCtx.beginPath()
            targetCtx.moveTo(sx, sy)
            targetCtx.lineTo(sx + bx * length, sy + by * length)
            targetCtx.stroke()
        }
        targetCtx.restore()
    }
    // The player trail's lights (momentumLight.trailSamples), outside the
    // emitter cap: the ninja's light at trailIntensity of its alpha, times
    // the trail's own alpha at each sample, cast no deep shadows
    collectTrailLights(lights)
    {
        const config = STYLE.momentumLight
        const samples = this.trailSamples
        const count = visualEffects.playerTrail.getLightSamples(ninja.track, config.trailSamples, samples)
        const pool = this.trailLights
        for (let i = 0; i < count; ++i)
        {
            const x = samples[i].x + screen.x
            const y = samples[i].y + screen.y
            const alpha = config.lightAlpha * config.trailIntensity * samples[i].alpha * this.speedLight.trailGain
            if (alpha <= 0 || !this.isLightOnScreen(x, y, config.trailRadius))
                continue
            if (pool.length <= i)
                pool.push({x: 0, y: 0, radius: 0, color: STYLE.colors.player.halo, gradient: null, alpha: 0,
                    contact: 0, element: null, trail: true})
            const light = pool[i]
            light.x = x
            light.y = y
            light.radius = config.trailRadius
            light.gradient = this.getMomentumGradient()
            light.alpha = alpha
            light.contact = this.getNinjaContact()
            lights.push(light)
        }
    }
    // momentumEmitters plus an area light per visible blue piece: at its
    // centre, reaching blueSpread past its outline, at blueAlpha times its
    // fade alpha (none once faded) and its hit flash (momentumFx)
    collectEmitters(gameState)
    {
        const config = STYLE.momentumLight
        const emitters = this.emitterCandidates
        emitters.length = 0
        for (let i = 0; i < this.momentumEmitters.length; ++i)
            emitters.push(this.momentumEmitters[i])
        const toScreen = scale[version] * 1080 / height
        const now = performance.now()
        const floors = gameState.floors
        for (let i = 0; i < floors.length; ++i)
        {
            const elements = floors[i].elements
            for (let j = 0; j < elements.length; ++j)
            {
                const element = elements[j]
                if (!(element instanceof MomentumBlue))
                    continue
                const alpha = element.getAlpha()
                if (alpha <= 0)
                    continue
                const circle = element.circle
                emitters.push({x: element.x + circle.x, y: element.y + circle.y,
                    radius: config.blueSpread + circle.radius * toScreen,
                    color: STYLE.momentum.blueStroke,
                    alpha: config.blueAlpha * alpha * visualEffects.screenEffects.getBlueFlash(element, now),
                    element: element})
            }
        }
        return emitters
    }
    // The ninja is a light of its own size: a piece it touches (within this
    // many world units of its centre) casts no shadow from it, so a bounce
    // does not black out the half of the view behind the piece
    getNinjaContact()
    {
        return ninja.radius * STYLE.momentumLight.contactRadii
    }
    // Every momentum piece (a fading one by its alpha), the course borders
    // as drawn (mitred bands) and the wall mass outside the corridor, as
    // world polygons with their bounding boxes
    collectOccluders(gameState)
    {
        const occluders = this.occluders
        occluders.length = 0
        const floors = gameState.floors
        for (let i = 0; i < floors.length; ++i)
        {
            const elements = floors[i].elements
            for (let j = 0; j < elements.length; ++j)
            {
                const element = elements[j]
                if (element instanceof MomentumOneTime)
                {
                    const alpha = element.getAlpha()
                    if (alpha > 0)
                        this.addOccluder(element.getPoints(), alpha, true, element)
                }
                else if (element instanceof MomentumBorder)
                {
                    const band = []
                    for (const [end, depth] of [[false, 0], [true, 0], [true, element.thickness], [false, element.thickness]])
                    {
                        const p = element.mitrePoint(end, depth)
                        band.push({x: p.x - screen.x, y: p.y - screen.y})
                    }
                    this.addOccluder(band, 1)
                }
            }
        }
        const cells = momentumOutsideCells().cells
        for (const c of cells)
            this.addOccluder([{x: c.l, y: c.t}, {x: c.r, y: c.t}, {x: c.r, y: c.b}, {x: c.l, y: c.b}], 1)
    }
    // deep: a piece, whose shadow also darkens the ambient (addDeepShadows);
    // element: that piece
    addOccluder(points, alpha, deep, element)
    {
        let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
        for (let i = 0; i < points.length; ++i)
        {
            left = Math.min(left, points[i].x)
            right = Math.max(right, points[i].x)
            top = Math.min(top, points[i].y)
            bottom = Math.max(bottom, points[i].y)
        }
        this.occluders.push({points: points, alpha: alpha, deep: !!deep, element: element || null,
            left: left, top: top, right: right, bottom: bottom})
    }
    // One light into the layer canvas, its shadows cut out, added to target.
    // A blue's area light casts its shadows from its centre (not by itself)
    // and only stops at the pieces and walls: no deep shadows.
    // A radial light is drawn, shadowed and added only inside its square
    // (getLightRect): nothing of it lies outside.
    addShadowedLight(target, light)
    {
        const layer = this.lightLayerCtx
        const rect = light.element ? null : this.getLightRect(light)
        if (rect && (rect.w <= 0 || rect.h <= 0))
            return
        layer.save()
        layer.setTransform(1, 0, 0, 1, 0, 0)
        layer.globalCompositeOperation = 'source-over'
        if (rect)
        {
            layer.clearRect(rect.x, rect.y, rect.w, rect.h)
            layer.beginPath()
            layer.rect(rect.x, rect.y, rect.w, rect.h)
            layer.clip()
        }
        else
            layer.clearRect(0, 0, this.lightLayerCanvas.width, this.lightLayerCanvas.height)
        if (light.element)
            this.fillAreaLight(layer, light.element, light.alpha)
        else
            this.fillRadialLight(layer, light.x, light.y, light.radius, light.gradient, light.alpha)
        this.cutShadows(layer, light.x, light.y, light.radius, light.contact, light.element)
        layer.restore()
        if (rect)
            target.drawImage(this.lightLayerCanvas, rect.x, rect.y, rect.w, rect.h, rect.x, rect.y, rect.w, rect.h)
        else
            target.drawImage(this.lightLayerCanvas, 0, 0)
        this.addRimLight(rect)
        if (!light.element && !light.trail)
            this.addDeepShadows(light)
    }
    // The whole light px square round a radial light's fill (fillRadialLight),
    // within the light canvas
    getLightRect(light)
    {
        const toLight = this.scale * scale[version]
        const lightRadius = light.radius * height / 1080 * this.scale
        const rect = this.lightRect
        const left = Math.max(0, Math.floor(light.x * toLight - lightRadius) - 1)
        const top = Math.max(0, Math.floor(light.y * toLight - lightRadius) - 1)
        const right = Math.min(this.lightLayerCanvas.width, Math.ceil(light.x * toLight + lightRadius) + 1)
        const bottom = Math.min(this.lightLayerCanvas.height, Math.ceil(light.y * toLight + lightRadius) + 1)
        rect.x = left
        rect.y = top
        rect.w = right - left
        rect.h = bottom - top
        return rect
    }
    // A blue's outline light (the obstacle spill sprite, wider) at alpha;
    // past 1 (a hit flash) whole passes are added
    fillAreaLight(lightCtx, element, alpha)
    {
        const box = getElementCullBox(element)
        if (!box)
            return
        const toLight = this.scale * scale[version]
        const spread = STYLE.momentumLight.blueSpread * height / 1080 / scale[version]
        const sprite = this.getShapeLightSprite(element, box, STYLE.momentum.blueStroke, spread, toLight)
        lightCtx.setTransform(toLight, 0, 0, toLight, 0, 0)
        for (let left = alpha; left > 0; left -= 1)
        {
            if (left < alpha)
                lightCtx.globalCompositeOperation = 'lighter'
            lightCtx.globalAlpha = Math.min(1, left)
            lightCtx.drawImage(sprite, box.left + screen.x - spread, box.top + screen.y - spread,
                sprite.width / toLight, sprite.height / toLight)
        }
    }
    // A piece stands in the open between the light and the cave: its shadow
    // also darkens the ambient and the obstacle spill by up to shadowDepth,
    // fading out over shadowRadius from the light. Walls only stop the
    // light: the cave behind them keeps the ambient, so their own shadows
    // are cut out of it. Built in the light layer (free again), merged into
    // shadowLayerCanvas.
    addDeepShadows(light)
    {
        const occluders = this.occluders
        let any = false
        for (let i = 0; i < occluders.length && !any; ++i)
            any = occluders[i].deep
        if (!any)
            return
        const config = STYLE.momentumLight
        const shadows = this.shadowLayerCtx
        if (!this.hasDeepShadows)
        {
            shadows.setTransform(1, 0, 0, 1, 0, 0)
            shadows.clearRect(0, 0, this.shadowLayerCanvas.width, this.shadowLayerCanvas.height)
            this.hasDeepShadows = true
        }
        const layer = this.lightLayerCtx
        layer.save()
        layer.setTransform(1, 0, 0, 1, 0, 0)
        layer.globalCompositeOperation = 'source-over'
        layer.globalAlpha = 1
        layer.clearRect(0, 0, this.lightLayerCanvas.width, this.lightLayerCanvas.height)
        this.traceShadows(layer, light.x, light.y, config.shadowRadius, true, light.contact)
        layer.globalCompositeOperation = 'source-in'
        this.fillRadialLight(layer, light.x, light.y, config.shadowRadius, this.getShadowGradient(), config.shadowDepth)
        layer.globalCompositeOperation = 'destination-out'
        this.traceShadows(layer, light.x, light.y, config.shadowRadius, false, light.contact)
        layer.restore()
        shadows.drawImage(this.lightLayerCanvas, 0, 0)
    }
    // Black, opaque at the light and clear at its radius (unit size)
    getShadowGradient()
    {
        if (!this.shadowGradient)
        {
            const gradient = this.lightCtx.createRadialGradient(0, 0, 0, 0, 0, 1)
            gradient.addColorStop(0, 'rgba(0, 0, 0, 1)')
            gradient.addColorStop(0.65, 'rgba(0, 0, 0, 1)')
            gradient.addColorStop(1, 'rgba(0, 0, 0, 0)')
            this.shadowGradient = gradient
        }
        return this.shadowGradient
    }
    // Hard shadows: every occluder within radius of the light at x, y (on
    // screen) erases, by its alpha, the quads its edges sweep away from the
    // light. The low-resolution canvas softens their edges when enlarged.
    cutShadows(lightCtx, x, y, radius, contact, emitter)
    {
        lightCtx.globalCompositeOperation = 'destination-out'
        this.traceShadows(lightCtx, x, y, radius, null, contact, emitter)
    }
    // Fills those quads white, each occluder at its alpha, in the context's
    // current composite operation; deep true: the pieces' only, false: the
    // walls' only, null: all. Pieces within contact of the light and the
    // emitter (the piece that is the light) are skipped.
    traceShadows(lightCtx, x, y, radius, deep, contact, emitter)
    {
        const toLight = this.scale * scale[version]
        const reach = radius * height / 1080 / scale[version]
        // World position of the light
        const lx = x - screen.x
        const ly = y - screen.y
        const far = 2 * reach
        lightCtx.setTransform(toLight, 0, 0, toLight, screen.x * toLight, screen.y * toLight)
        lightCtx.fillStyle = '#ffffff'
        const occluders = this.occluders
        for (let i = 0; i < occluders.length; ++i)
        {
            const o = occluders[i]
            if ((deep !== null && o.deep !== deep) || (emitter && o.element === emitter))
                continue
            if (o.right < lx - reach || o.left > lx + reach || o.bottom < ly - reach || o.top > ly + reach)
                continue
            if (o.deep && contact > 0 && polygonDistance(o.points, lx, ly) < contact)
                continue
            lightCtx.globalAlpha = o.alpha
            lightCtx.beginPath()
            const points = o.points
            for (let j = 0; j < points.length; ++j)
            {
                const a = points[j]
                const b = points[(j + 1) % points.length]
                const ax = a.x - lx, ay = a.y - ly, bx = b.x - lx, by = b.y - ly
                const da = Math.hypot(ax, ay), db = Math.hypot(bx, by)
                if (da < 1e-6 || db < 1e-6)
                    continue
                const fa = far / da, fb = far / db
                // Same winding for every quad, so the nonzero union has no holes
                if (ax * by - ay * bx >= 0)
                {
                    lightCtx.moveTo(a.x, a.y)
                    lightCtx.lineTo(b.x, b.y)
                    lightCtx.lineTo(b.x + bx * fb, b.y + by * fb)
                    lightCtx.lineTo(a.x + ax * fa, a.y + ay * fa)
                }
                else
                {
                    lightCtx.moveTo(b.x, b.y)
                    lightCtx.lineTo(a.x, a.y)
                    lightCtx.lineTo(a.x + ax * fa, a.y + ay * fa)
                    lightCtx.lineTo(b.x + bx * fb, b.y + by * fb)
                }
                lightCtx.closePath()
            }
            lightCtx.fill()
        }
    }
    // The player trail is translucent and drawn after the lights: the cave
    // under it keeps its undimmed, unhazed pixels so the trail's own pixels
    // stay as with the lighting off. Fills the ribbon's widest outline grown
    // by trailBandMargin light px (filtering keeps its inside exact), its
    // edge feathered over trailBandFeather light px so it reads as a glow.
    fillTrailBand(lightCtx, outline)
    {
        const toLight = this.scale * scale[version]

        lightCtx.setTransform(toLight, 0, 0, toLight, 0, 0)
        lightCtx.shadowColor = '#ffffff'
        lightCtx.shadowBlur = STYLE.momentumLight.trailBandFeather
        lightCtx.lineWidth = 2 * STYLE.momentumLight.trailBandMargin / toLight
        lightCtx.lineJoin = 'round'
        lightCtx.beginPath()
        lightCtx.moveTo(outline[0].x, outline[0].y)
        for (let i = 1; i < outline.length; ++i)
            lightCtx.lineTo(outline[i].x, outline[i].y)
        lightCtx.closePath()
        lightCtx.fill()
        lightCtx.stroke()
    }
    // A faint cyan glow of the air round the ninja and a blue one round each
    // lit blue piece (shadowed like their lights), added from hazeCanvas
    addMomentumHaze()
    {
        const config = STYLE.momentumLight
        const hazeCtx = this.hazeCtx

        hazeCtx.save()
        hazeCtx.setTransform(1, 0, 0, 1, 0, 0)
        hazeCtx.clearRect(0, 0, this.hazeCanvas.width, this.hazeCanvas.height)
        let any = false
        const x = ninja.x + screen.x
        const y = ninja.y + screen.y
        const hazeRadius = config.hazeRadius * this.speedLight.hazeScale
        if (this.isLightOnScreen(x, y, hazeRadius))
        {
            this.fillRadialLight(hazeCtx, x, y, hazeRadius, this.getMomentumGradient(), config.hazeAlpha)
            this.cutShadows(hazeCtx, x, y, hazeRadius, this.getNinjaContact())
            any = true
        }
        const lights = this.momentumLights
        for (let i = 0; i < lights.length; ++i)
        {
            const light = lights[i]
            if (!light.element)
                continue
            const layer = this.lightLayerCtx
            layer.save()
            layer.setTransform(1, 0, 0, 1, 0, 0)
            layer.globalCompositeOperation = 'source-over'
            layer.clearRect(0, 0, this.lightLayerCanvas.width, this.lightLayerCanvas.height)
            this.fillAreaLight(layer, light.element, light.alpha / config.blueAlpha * config.blueHazeAlpha)
            this.cutShadows(layer, light.x, light.y, light.radius, 0, light.element)
            layer.restore()
            hazeCtx.setTransform(1, 0, 0, 1, 0, 0)
            hazeCtx.globalAlpha = 1
            hazeCtx.globalCompositeOperation = 'lighter'
            hazeCtx.drawImage(this.lightLayerCanvas, 0, 0)
            any = true
        }
        if (!any)
        {
            hazeCtx.restore()
            return
        }
        if (this.trailBand)
        {
            hazeCtx.globalAlpha = 1
            hazeCtx.globalCompositeOperation = 'destination-out'
            hazeCtx.fillStyle = '#ffffff'
            hazeCtx.strokeStyle = '#ffffff'
            this.fillTrailBand(hazeCtx, this.trailBand)
        }
        hazeCtx.restore()

        this.compositeCanvas(this.hazeCanvas, 1, 'lighter')
    }
}

// Distance from (x, y) to a convex or concave polygon's outline, 0 inside
function polygonDistance(points, x, y)
{
    let inside = false
    let best = Infinity
    for (let i = 0, j = points.length - 1; i < points.length; j = i++)
    {
        const a = points[j], b = points[i]
        if ((b.y > y) != (a.y > y) && x < (a.x - b.x) * (y - b.y) / (a.y - b.y) + b.x)
            inside = !inside
        const dx = b.x - a.x, dy = b.y - a.y
        const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / (dx * dx + dy * dy || 1)))
        best = Math.min(best, Math.hypot(a.x + t * dx - x, a.y + t * dy - y))
    }
    return inside ? 0 : best
}

// 0..1 from a speed streak's index, cycle and a salt (integer hash)
function streakHash(index, cycle, salt)
{
    let h = Math.imul(index + 1, 0x9e3779b1) ^ Math.imul(cycle | 0, 0x85ebca77) ^ Math.imul(salt, 0xc2b2ae3d)
    h ^= h >>> 15
    h = Math.imul(h, 0x2c1b3c6d)
    h ^= h >>> 12
    h = Math.imul(h, 0x297a2d39)
    h ^= h >>> 15
    return (h >>> 0) / 4294967296
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
        // Lit mote fill styles: base colour -> light colour -> one per
        // momentumLight.moteSteps step (getLitMoteColor)
        this.litMoteColors = new Map()
        // The light at the mote being drawn: amount (moteGain applied, 0..1)
        // and the brightest light's colour (litMoteLight)
        this.moteLight = {amount: 0, color: null}
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
        if ((version == 'bad' || version == 'momentum') && (trampoline instanceof Ground || trampoline instanceof Side))
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
        const interval = (version == 'bad' || version == 'momentum')
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
        // Momentum lighting: motes in the frame's lights brighten and tint
        const lights = view ? null : visualEffects.lightmap.getFrameLights()

        ctx.save()
        ctx.globalCompositeOperation = 'source-over'
        for (let i = 0, j = 0; i < motes.length; ++i, j += MOTE_LAYOUT_STRIDE)
        {
            const light = lights ? this.litMoteLight(lights, layout, j) : null
            if (light)
            {
                this.drawLitMote(motes[i].color, layout, j, light)
                continue
            }
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
    // The light (this.moteLight, reused) at the mote at layout[j], or null
    // outside every light: momentumLight.moteGain times the sum of the
    // lights there, up to 1, in moteSteps steps, and the brightest one's colour
    litMoteLight(lights, layout, j)
    {
        const config = STYLE.momentumLight
        const x = layout[j + 5] + layout[j + 7] / 2
        const y = layout[j + 6] + layout[j + 7] / 2
        const lightmap = visualEffects.lightmap
        let sum = 0, best = 0, color = null
        for (let k = 0; k < lights.length; ++k)
        {
            const amount = lightmap.getLightAt(lights[k], x, y, config.moteReach)
            sum += amount
            if (amount > best && lights[k].color)
            {
                best = amount
                color = lights[k].color
            }
        }
        const step = Math.round(Math.min(1, sum * config.moteGain) * config.moteSteps)
        if (step <= 0 || !color)
            return null
        this.moteLight.amount = step / config.moteSteps
        this.moteLight.color = color
        return this.moteLight
    }
    // The mote at layout[j] (halo and core) grown and brightened by
    // light.amount x moteBoost about its centre, in its lit colour
    drawLitMote(baseColor, layout, j, light)
    {
        const ctx = this.ctx
        const boost = light.amount * STYLE.momentumLight.moteBoost
        const grow = 1 + boost
        ctx.fillStyle = this.getLitMoteColor(baseColor, light.color, light.amount)
        for (let k = j; k < j + 8; k += 4)
        {
            const size = layout[k + 3] * grow
            ctx.globalAlpha = Math.min(1, layout[k] * grow)
            ctx.fillRect(layout[k + 1] - (size - layout[k + 3]) / 2, layout[k + 2] - (size - layout[k + 3]) / 2,
                size, size)
        }
    }
    // baseColor moved amount (0..1, a moteSteps step) of the way to
    // lightColor lifted moteWhite toward white ('#rrggbb' both), cached
    getLitMoteColor(baseColor, lightColor, amount)
    {
        const steps = STYLE.momentumLight.moteSteps
        const white = STYLE.momentumLight.moteWhite
        let byLight = this.litMoteColors.get(baseColor)
        if (!byLight)
            this.litMoteColors.set(baseColor, byLight = new Map())
        let colors = byLight.get(lightColor)
        if (!colors)
        {
            const from = parseInt(baseColor.slice(1, 7), 16)
            const to = parseInt(lightColor.slice(1, 7), 16)
            colors = []
            for (let i = 0; i <= steps; ++i)
            {
                const t = i / steps
                const lit = shift => (to >> shift & 255) * (1 - white) + 255 * white
                const channel = shift => Math.round((from >> shift & 255) * (1 - t) + lit(shift) * t)
                colors.push('rgb(' + channel(16) + ', ' + channel(8) + ', ' + channel(0) + ')')
            }
            byLight.set(lightColor, colors)
        }
        return colors[Math.round(amount * steps)]
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
        if (typeof version != 'undefined' && (version == 'bad' || version == 'momentum'))
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
    // The widest ribbon layer's outline this frame (world-on-screen units),
    // or null when no ribbon is drawn; the momentum light keeps the cave
    // under it undimmed
    getRibbonBand(track)
    {
        if (!this.shouldDraw() || !track || track.pos.length < 2)
            return null

        const config = STYLE.trails.player
        const positions = this.getRibbonPoints(track.pos, track.lineWidth * config.minPointDistanceRatio)
        const visibleStart = Math.max(1, Math.floor(positions.length * config.minSegmentRatio))
        if (positions.length - visibleStart < 2)
            return null

        const widthRatio = STYLE.player.outerGlow ? Math.max(1, config.haloWidthRatio) : 1
        const outline = this.getRibbonOutline(positions, visibleStart, this.getRibbonWidth(track) * widthRatio)
        return outline.length ? outline : null
    }
    // Fills out with count points ({x, y, alpha}, world units, objects
    // reused) spread evenly by length along the visible ribbon, tail first;
    // alpha is the ribbon's fade there (0 at its tail, 1 at the head).
    // Returns how many were filled (0 with no ribbon).
    getLightSamples(track, count, out)
    {
        if (!this.shouldDraw() || !track || track.pos.length < 2 || count <= 0)
            return 0

        const config = STYLE.trails.player
        const positions = this.getRibbonPoints(track.pos, track.lineWidth * config.minPointDistanceRatio)
        const visibleStart = Math.max(1, Math.floor(positions.length * config.minSegmentRatio))
        if (positions.length - visibleStart < 2)
            return 0

        // Same span as getRibbonOutline
        const start = Math.max(0, visibleStart - 1)
        const end = positions.length - 1
        let total = 0
        for (let i = start; i < end; ++i)
            total += Math.hypot(positions[i + 1].x - positions[i].x, positions[i + 1].y - positions[i].y)
        if (total <= 0)
            return 0

        let i = start
        let walked = 0
        for (let k = 0; k < count; ++k)
        {
            const target = total * (k + 0.5) / count
            let step = Math.hypot(positions[i + 1].x - positions[i].x, positions[i + 1].y - positions[i].y)
            while (walked + step < target && i < end - 1)
            {
                walked += step
                ++i
                step = Math.hypot(positions[i + 1].x - positions[i].x, positions[i + 1].y - positions[i].y)
            }
            const t = step > 0 ? Math.min(1, (target - walked) / step) : 0
            if (out.length <= k)
                out.push({x: 0, y: 0, alpha: 0})
            const sample = out[k]
            sample.x = positions[i].x + (positions[i + 1].x - positions[i].x) * t
            sample.y = positions[i].y + (positions[i + 1].y - positions[i].y) * t
            sample.alpha = this.clampAlpha((i - start + t) / Math.max(1, end - start))
        }
        return count
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
        if (typeof version != 'undefined' && (version == 'bad' || version == 'momentum'))
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
        if ((version == 'bad' || version == 'momentum') && visualEffects.playerTrail.shouldDraw())
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
        sumCtx.globalCompositeOperation = 'lighter'
        sumCtx.imageSmoothingEnabled = true
        for (let i = 0; i < this.levels.length; ++i)
        {
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
        // Blue hits {element, start} of the momentumFx flash and ring
        this.blueHits = []
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
    // A blue piece was touched (MomentumBlue.onNinjaPass): its flash and
    // ring start now. Only recorded; nothing of the game reads it.
    triggerBlueHit(element)
    {
        const now = performance.now()
        this.pruneBlueHits(now)
        this.blueHits.push({element: element, start: now})
    }
    pruneBlueHits(now)
    {
        const duration = STYLE.momentumFx.blueHitMs
        for (let i = this.blueHits.length - 1; i >= 0; --i)
            if (now - this.blueHits[i].start >= duration)
                this.blueHits.splice(i, 1)
    }
    // 0..1 of the blue hit effect at now, or -1 outside it
    getBlueHitProgress(hit, now)
    {
        const t = (now - hit.start) / STYLE.momentumFx.blueHitMs
        return t >= 0 && t < 1 ? t : -1
    }
    // The light gain of element's hit flash at now (1 without one)
    getBlueFlash(element, now)
    {
        const hits = this.blueHits
        for (let i = hits.length - 1; i >= 0; --i)
            if (hits[i].element === element)
            {
                const t = this.getBlueHitProgress(hits[i], now)
                return t < 0 ? 1 : 1 + (STYLE.momentumFx.flashGain - 1) * (1 - t) * (1 - t)
            }
        return 1
    }
    // The blue hits' rings (momentum lighting only), 'lighter' strokes: a
    // wide faint halo and the core line of the ring and of its echo
    drawBlueHits(now)
    {
        if (!this.blueHits.length || version != 'momentum' || !MOMENTUM_FX.enabled)
            return
        this.pruneBlueHits(now)
        const config = STYLE.momentumFx
        const context = this.ctx
        context.save()
        context.globalCompositeOperation = 'lighter'
        context.strokeStyle = STYLE.momentum.blueStroke
        for (const hit of this.blueHits)
        {
            const t = this.getBlueHitProgress(hit, now)
            if (t < 0)
                continue
            const element = hit.element
            const x = element.x + element.circle.x + screen.x
            const y = element.y + element.circle.y + screen.y
            const rx = this.getBlueRingRadius(element, t)
            this.strokeBlueRing(x, y, rx, config.ringAlpha * (1 - t))
            this.strokeBlueRing(x, y, rx * config.ringEcho, config.ringAlpha * config.ringEchoAlpha * (1 - t))
        }
        context.restore()
    }
    // The ring's x radius (world units) at progress t: ringFrom -> ringTo
    // times the blue's circumscribed radius, eased out
    getBlueRingRadius(element, t)
    {
        const config = STYLE.momentumFx
        const eased = 1 - (1 - t) * (1 - t)
        return element.circle.radius * (config.ringFrom + (config.ringTo - config.ringFrom) * eased)
    }
    strokeBlueRing(x, y, rx, alpha)
    {
        const config = STYLE.momentumFx
        const toWorld = height / 1080 / scale[version]
        const context = this.ctx
        context.beginPath()
        context.ellipse(x, y, rx, rx * config.ringAspect, 0, 0, Math.PI * 2)
        context.lineWidth = config.ringHaloWidth * toWorld
        context.globalAlpha = alpha * config.ringHaloAlpha
        context.stroke()
        context.lineWidth = config.ringWidth * toWorld
        context.globalAlpha = alpha
        context.stroke()
    }
    // 0..1 strength of the colour fringe at now: 1 - t^2 over fringeMs after
    // the newest blue hit, 0 outside it (momentum lighting only)
    getBlueFringe(now)
    {
        if (!this.blueHits.length || version != 'momentum' || !MOMENTUM_FX.enabled)
            return 0
        const t = (now - this.blueHits[this.blueHits.length - 1].start) / STYLE.momentumFx.fringeMs
        return t >= 0 && t < 1 ? 1 - t * t : 0
    }
    // Chromatic aberration over the frame drawn so far: the red channel
    // scaled away from the screen centre and the blue toward it by up to
    // fringePx at the edges (an axis scale each, so every edge gets the full
    // shift and the centre none), green kept. hudBoxes [x, y, w, h] (integer
    // canvas px) are copied back unfringed and keep their exact pixels.
    // Offscreen canvases are made once and reused; nothing is drawn at
    // strength 0.
    drawBlueFringe(now, hudBoxes)
    {
        const strength = this.getBlueFringe(now)
        if (strength <= 0)
            return
        const main = this.ctx.canvas
        const w = main.width
        const h = main.height
        const shift = STYLE.momentumFx.fringePx * h / 1080 * strength
        if (!this.fringe)
            this.fringe = [0, 1, 2].map(() => document.createElement('canvas').getContext('2d'))
        const [source, red, blue] = this.fringe
        for (const c of this.fringe)
            if (c.canvas.width != w || c.canvas.height != h)
            {
                c.canvas.width = w
                c.canvas.height = h
            }
        source.globalCompositeOperation = 'copy'
        source.drawImage(main, 0, 0)
        this.drawFringeChannel(red, source.canvas, shift, '#ff0000')
        this.drawFringeChannel(blue, source.canvas, -shift, '#0000ff')

        const context = this.ctx
        context.save()
        context.setTransform(1, 0, 0, 1, 0, 0)
        context.globalAlpha = 1
        context.globalCompositeOperation = 'multiply'
        context.fillStyle = '#00ff00'
        context.fillRect(0, 0, w, h)
        context.globalCompositeOperation = 'lighter'
        context.drawImage(red.canvas, 0, 0)
        context.drawImage(blue.canvas, 0, 0)
        // The HUD boxes back from the unfringed copy (opaque, 1:1: exact)
        context.globalCompositeOperation = 'source-over'
        for (const box of hudBoxes)
            context.drawImage(source.canvas, box[0], box[1], box[2], box[3], box[0], box[1], box[2], box[3])
        context.restore()
    }
    // One channel of the frame scaled about the centre so its edges move by
    // shift px (the unscaled frame under it fills the border of a shrink)
    drawFringeChannel(c, source, shift, colour)
    {
        const w = source.width
        const h = source.height
        const sx = 1 + shift / (w / 2)
        const sy = 1 + shift / (h / 2)
        c.setTransform(1, 0, 0, 1, 0, 0)
        c.globalCompositeOperation = 'copy'
        c.drawImage(source, 0, 0)
        c.globalCompositeOperation = 'source-over'
        c.setTransform(sx, 0, 0, sy, w / 2 * (1 - sx), h / 2 * (1 - sy))
        c.drawImage(source, 0, 0)
        c.setTransform(1, 0, 0, 1, 0, 0)
        c.globalCompositeOperation = 'multiply'
        c.fillStyle = colour
        c.fillRect(0, 0, w, h)
    }
    draw()
    {
        const now = performance.now()
        this.drawBlueHits(now)
        if (!this.shouldApply())
            return

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

        gameState.scoreText.draw()
        gameState.menu.button.draw()
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
