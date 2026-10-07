// Decorative templates use a 720-unit square and fit the shorter canvas axis.
// Keep this isotropic local scale: a radius of 62 is 93 pixels at 1920x1080.
function backgroundTemplateScale(viewWidth, viewHeight)
{
    return Math.min(viewWidth, viewHeight) * (100 / 720) / 100
}

const DEFAULT_BROKEN_FLASH_SEGMENTS = [
    {start: 0, end: 0.34},
    {start: 0.48, end: 0.72},
    {start: 0.84, end: 1}
]
const DEFAULT_FLASH_FRAGMENTS = [
    {x: 0, y: 0, length: 0.22, angleOffset: 0},
    {x: 0.04, y: 0.03, length: 0.16, angleOffset: 0.34},
    {x: -0.03, y: 0.06, length: 0.12, angleOffset: -0.28}
]

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
        this.randomFlashCache = new WeakMap()
        this.randomTriangleCache = new WeakMap()
        this.gradientCache = new Map()
        this.washGradients = null
        this.lastGameGradients = null
        // Offscreen crystal/rock tiles by name ('far', 'near')
        this.layerCache = {}
        // Reused every frame so the background draws without per-frame garbage.
        this.flashSegmentCache = new WeakMap()
        this.trianglePaletteColors = {fill: null, stroke: null}
    }
    draw()
    {
        this.paint()
        this.drawWindowBars('game', () => this.paint())
    }
    drawMenuBackground()
    {
        this.paintMenu()
        this.drawWindowBars('menu', () => this.paintMenu())
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

        const backgroundGeometry = STYLE.backgroundGeometry

        this.drawBaseGradient(width, height)
        this.drawCrystalLayer(width, height, this.getLayerShift(width, height, backgroundGeometry.crystals))
        this.drawHaze(width, height)
        this.drawGeometry(width, height)
        this.drawNearLayer(width, height, this.getLayerShift(width, height, backgroundGeometry.nearRocks))
        this.drawVignette(width, height)
    }
    paintMenu()
    {
        this.clearAll()

        if (!STYLE.features.background)
            return

        const width = LOGICAL_VIEWPORT.width
        const height = LOGICAL_VIEWPORT.height

        this.drawBaseGradient(width, height)
        this.drawCrystalLayer(width, height, {x: 0, y: 0})
        this.drawHaze(width, height)
        this.drawBadVersionDepth(width, height, this.getMenuBackgroundGeometry(), 0, {forceStatic: true})
        this.drawNearLayer(width, height, {x: 0, y: 0})
        this.drawVignette(width, height)
    }
    getMenuBackgroundGeometry()
    {
        return Object.assign(
            {},
            STYLE.backgroundGeometry.badVersion,
            STYLE.backgroundGeometry.menu || {}
        )
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
        const gradient = this.ctx.createLinearGradient(0, 0, 0, height)
        gradient.addColorStop(0, background.gradientTop)
        gradient.addColorStop(0.54, background.gradientMiddle)
        gradient.addColorStop(1, background.gradientBottom)

        // Between the far crystals and the near rocks
        const haze = this.ctx.createLinearGradient(0, 0, 0, height)
        haze.addColorStop(0, background.hazeTop)
        haze.addColorStop(0.24, background.hazeUpper)
        haze.addColorStop(0.5, background.hazeMiddle)
        haze.addColorStop(0.74, background.hazeLower)
        haze.addColorStop(1, background.hazeBottom)

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
    drawBaseGradient(width, height)
    {
        this.ctx.fillStyle = this.getGradients(width, height).gradient
        this.fillAll()
    }
    drawHaze(width, height)
    {
        this.ctx.fillStyle = this.getGradients(width, height).haze
        this.fillAll()
    }
    drawVignette(width, height)
    {
        this.ctx.fillStyle = this.getGradients(width, height).vignette
        this.fillAll()
    }
    getAnimationTime()
    {
        if (!QUALITY.backgroundMotion)
            return 0

        return performance.now() * this.getVersionBackgroundTimeScale()
    }
    getVersionBackgroundTimeScale()
    {
        if (typeof version != 'undefined' && version == 'classic')
            return STYLE.backgroundGeometry.classicMotionTimeScale

        return 1
    }
    drawGeometry(width, height)
    {
        const geometry = STYLE.backgroundGeometry
        const time = this.getAnimationTime()

        if (this.usesDepthBackground())
        {
            this.drawBadVersionDepth(width, height, geometry.badVersion, time)
            return
        }

        this.drawHexagons(width, height, geometry, time)
        this.drawStreaks(width, height, geometry, time)
    }
    drawHexagons(width, height, geometry, time)
    {
        const minSize = Math.min(width, height)
        const centerX = width / 2
        const centerY = height / 2
        const primaryStroke = STYLE.colors.background.hexagonStroke
        const accentStroke = STYLE.colors.background.hexagonAccentStroke

        this.drawHexagonSet(width, height, geometry, time, centerX, centerY, primaryStroke, accentStroke)
    }
    drawHexagonSet(width, height, geometry, time, centerX, centerY, primaryStroke, accentStroke)
    {
        const minSize = Math.min(width, height)
        const baseRadius = minSize * geometry.hexagonRadiusRatio
        const radiusStep = minSize * geometry.hexagonRadiusStepRatio
        const rotationTimeScale = typeof geometry.hexagonRotationTimeScale == 'number'
            ? geometry.hexagonRotationTimeScale
            : 1
        const rotationTime = time * rotationTimeScale
        const rotation = (rotationTime % STYLE.timing.backgroundRotationMs) / STYLE.timing.backgroundRotationMs * Math.PI * 2

        this.ctx.save()
        this.ctx.lineWidth = geometry.hexagonLineWidth

        for (let i = 0; i < geometry.hexagonCount; ++i)
        {
            const radius = baseRadius + radiusStep * i
            const direction = i % 2 == 0 ? 1 : -1
            const angle = rotation * direction + i * Math.PI / 12

            this.ctx.strokeStyle = i % 2 == 0 ? primaryStroke : accentStroke
            this.drawHexagon(centerX, centerY, radius, angle)
        }

        this.ctx.restore()
    }
    drawHexagon(centerX, centerY, radius, rotation)
    {
        this.ctx.beginPath()

        for (let i = 0; i < 6; ++i)
        {
            const angle = rotation + Math.PI / 6 + i * Math.PI / 3
            const x = centerX + Math.cos(angle) * radius
            const y = centerY + Math.sin(angle) * radius

            if (i == 0)
                this.ctx.moveTo(x, y)
            else
                this.ctx.lineTo(x, y)
        }

        this.ctx.closePath()
        this.ctx.stroke()
    }
    drawStreaks(width, height, geometry, time)
    {
        this.drawStreakSet(width, height, geometry, time, STYLE.colors.background.streak, 0)
    }
    drawStreakSet(width, height, geometry, time, strokeStyle, yOffset, xOffset)
    {
        yOffset = yOffset || 0
        xOffset = xOffset || 0
        const diagonal = Math.sqrt(width * width + height * height)
        const spacing = Math.max(width, height) * geometry.streakSpacingRatio
        const length = diagonal * geometry.streakLengthRatio
        const offset = (time % STYLE.timing.backgroundStreakMs) / STYLE.timing.backgroundStreakMs * spacing

        this.ctx.save()
        this.ctx.strokeStyle = strokeStyle
        this.ctx.lineWidth = geometry.streakLineWidth

        for (let i = -2; i < geometry.streakCount; ++i)
        {
            const x = i * spacing + offset - spacing * 2 + xOffset
            const y = height + spacing + yOffset

            this.ctx.beginPath()
            this.ctx.moveTo(x, y)
            this.ctx.lineTo(x + length, y - length)
            this.ctx.stroke()
        }

        this.ctx.restore()
    }
    drawBadVersionDepth(width, height, geometry, time, options)
    {
        if (!geometry)
            return

        options = options || {}
        const background = STYLE.colors.background
        const freezeMotion = options.forceStatic || this.shouldFreezeBadVersionBackgroundMotion()
        const geometryTime = freezeMotion ? 0 : time * geometry.motionTimeScale
        const streakTime = freezeMotion ? 0 : time * geometry.streakTimeScale
        const shift = freezeMotion
            ? {x: 0, y: 0}
            : this.getParallaxShift(width, height, geometry)
        const cameraShift = freezeMotion
            ? {x: 0, y: 0}
            : this.getCameraParallaxShift(geometry)
        const totalShift = {
            x: shift.x + cameraShift.x,
            y: shift.y + cameraShift.y
        }

        this.ctx.save()
        this.ctx.globalCompositeOperation = STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.backgroundCompositeOperation
            : 'lighter'
        this.drawDynamicLightingWash(width, height, geometry)
        this.drawHexagonSet(
            width,
            height,
            geometry,
            geometryTime,
            width * 0.52 + totalShift.x,
            height * 0.50 + totalShift.y,
            background.depthHexagonStroke,
            background.depthHexagonAccentStroke
        )

        const secondaryGeometry = {
            hexagonCount: geometry.secondaryHexagonCount,
            hexagonRadiusRatio: geometry.secondaryHexagonRadiusRatio,
            hexagonRadiusStepRatio: geometry.secondaryHexagonRadiusStepRatio,
            hexagonLineWidth: Math.max(1, geometry.hexagonLineWidth * 0.65)
        }

        this.drawHexagonSet(
            width,
            height,
            secondaryGeometry,
            geometryTime * 0.72,
            width * 0.25 - totalShift.x * 0.6,
            height * 0.36 - totalShift.y * 0.4,
            background.depthHexagonAccentStroke,
            background.depthHexagonStroke
        )
        this.drawDiagonalFlashes(width, height, geometry, geometryTime, totalShift)
        this.drawDecorativeTriangles(width, height, geometry, geometryTime, totalShift)
        this.drawRectangleAccents(width, height, geometry, geometryTime, totalShift)
        this.ctx.restore()
    }
    drawDynamicLightingWash(width, height, geometry)
    {
        const washes = this.getWashGradients(width, height, geometry)

        this.ctx.save()
        this.ctx.fillStyle = washes.blue
        this.fillAll()
        this.ctx.fillStyle = washes.red
        this.fillAll()
        this.ctx.restore()
    }
    // Both washes depend only on the size, the geometry ratios and the colors,
    // so they are built once and reused every frame
    getWashGradients(width, height, geometry)
    {
        const colors = STYLE.colors.background
        const radius = Math.max(width, height) * geometry.washRadiusRatio
        const leftX = width * geometry.washLeftXRatio
        const rightX = width * geometry.washRightXRatio
        const y = height * geometry.washYRatio
        const cached = this.washGradients

        if (cached && cached.radius == radius && cached.leftX == leftX && cached.rightX == rightX &&
            cached.y == y && cached.colors == colors && cached.blueCore == colors.washBlueCore &&
            cached.blueMid == colors.washBlueMid && cached.redCore == colors.washRedCore &&
            cached.redMid == colors.washRedMid && cached.center == colors.washCenter)
            return cached

        this.washGradients = {
            radius, leftX, rightX, y, colors,
            blueCore: colors.washBlueCore, blueMid: colors.washBlueMid,
            redCore: colors.washRedCore, redMid: colors.washRedMid, center: colors.washCenter,
            blue: this.createAmbientWash(leftX, y, radius, colors.washBlueCore, colors.washBlueMid, colors.washCenter),
            red: this.createAmbientWash(rightX, y, radius, colors.washRedCore, colors.washRedMid, colors.washCenter)
        }
        return this.washGradients
    }
    createAmbientWash(centerX, centerY, radius, coreColor, midColor, edgeColor)
    {
        const gradient = this.ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius)
        gradient.addColorStop(0, coreColor)
        gradient.addColorStop(0.42, midColor)
        gradient.addColorStop(1, edgeColor)
        return gradient
    }
    shouldFreezeBadVersionBackgroundMotion()
    {
        return STYLE.visualStability.freezeBadVersionBackground
    }
    drawDiagonalFlashes(width, height, geometry, time, shift)
    {
        const flashTemplates = geometry.flashes || []
        shift = shift || {x: 0, y: 0}

        if (!flashTemplates.length)
            return

        const flashes = this.getRandomizedFlashes(flashTemplates, geometry)
        const colors = STYLE.colors.background
        const diagonal = Math.sqrt(width * width + height * height)
        const animationOffset = QUALITY.backgroundMotion && !this.shouldFreezeBadVersionBackgroundMotion()
            ? Math.sin(time / STYLE.timing.backgroundStreakMs * Math.PI * 2) * width * geometry.flashMotionRatio
            : 0
        const stableMultiplier = STYLE.visualStability.stableBrightness
            ? geometry.stableFlashAlpha
            : geometry.flashAlpha

        this.ctx.save()
        this.ctx.lineCap = 'square'

        for (let i = 0; i < flashes.length; ++i)
        {
            const flash = flashes[i]
            const length = diagonal * (flash.length || geometry.flashLengthRatio)
            const angle = (typeof flash.angle == 'number' ? flash.angle : -45) * Math.PI / 180
            const startX = flash.x * width + animationOffset + shift.x
            const startY = flash.y * height + shift.y
            const alpha = typeof flash.alpha == 'number' ? flash.alpha : 1
            const palette = this.getFlashPalette(flash, geometry)
            const stroke = palette == 'blue' ? colors.flashBlue : colors.flashMagenta
            const glow = palette == 'blue' ? colors.flashBlueGlow : colors.flashMagentaGlow
            const segments = this.getFlashSegments(flash, startX, startY, angle, length)

            this.ctx.globalAlpha = stableMultiplier * alpha
            this.ctx.strokeStyle = glow
            this.ctx.lineWidth = flash.glowWidth || geometry.flashGlowWidth
            this.drawFlashSegments(segments)

            this.ctx.globalAlpha = Math.min(1, stableMultiplier * 1.45 * alpha)
            this.ctx.strokeStyle = stroke
            this.ctx.lineWidth = flash.width || geometry.flashLineWidth
            this.drawFlashSegments(segments)
        }

        this.ctx.restore()
    }
    getFlashPalette(flash, geometry)
    {
        const split = typeof geometry.flashColorSplitRatio == 'number'
            ? geometry.flashColorSplitRatio
            : ((geometry.washLeftXRatio || 0) + (geometry.washRightXRatio || 1)) / 2

        return flash.x < split ? 'blue' : 'magenta'
    }
    getRandomizedFlashes(flashTemplates, geometry)
    {
        const cached = this.randomFlashCache.get(flashTemplates)

        if (cached)
            return cached.flashes

        const flashes = flashTemplates.map(flash => Object.assign({}, flash, {
            x: Math.random(),
            y: Math.random()
        }))

        this.randomFlashCache.set(flashTemplates, {flashes})

        return flashes
    }
    resetRandomFlashes()
    {
        this.randomFlashCache = new WeakMap()
        this.randomTriangleCache = new WeakMap()
    }
    getFlashSegments(flash, startX, startY, angle, length)
    {
        const cos = Math.cos(angle)
        const sin = Math.sin(angle)

        if (flash.form == 'broken')
        {
            const segments = flash.segments || DEFAULT_BROKEN_FLASH_SEGMENTS
            const result = this.getFlashSegmentList(flash, segments.length)

            for (let i = 0; i < segments.length; ++i)
            {
                const segment = segments[i]
                this.setFlashSegment(
                    result[i],
                    startX + cos * length * segment.start,
                    startY + sin * length * segment.start,
                    startX + cos * length * segment.end,
                    startY + sin * length * segment.end
                )
            }

            return result
        }

        if (flash.form == 'fragments')
        {
            const fragments = flash.fragments || DEFAULT_FLASH_FRAGMENTS
            const normalX = -sin
            const normalY = cos
            const result = this.getFlashSegmentList(flash, fragments.length)

            for (let i = 0; i < fragments.length; ++i)
            {
                const fragment = fragments[i]
                const fragmentLength = length * fragment.length
                const fragmentAngle = angle + (fragment.angleOffset || 0)
                const fx = startX + cos * length * (fragment.x || 0) + normalX * length * (fragment.y || 0)
                const fy = startY + sin * length * (fragment.x || 0) + normalY * length * (fragment.y || 0)

                this.setFlashSegment(
                    result[i],
                    fx,
                    fy,
                    fx + Math.cos(fragmentAngle) * fragmentLength,
                    fy + Math.sin(fragmentAngle) * fragmentLength
                )
            }

            return result
        }

        const result = this.getFlashSegmentList(flash, 1)
        this.setFlashSegment(result[0], startX, startY, startX + cos * length, startY + sin * length)
        return result
    }
    getFlashSegmentList(flash, count)
    {
        // One fixed-length list per flash, overwritten by the next getFlashSegments call.
        let list = this.flashSegmentCache.get(flash)

        if (!list || list.length != count)
        {
            list = []

            for (let i = 0; i < count; ++i)
                list.push({x1: 0, y1: 0, x2: 0, y2: 0})

            this.flashSegmentCache.set(flash, list)
        }

        return list
    }
    setFlashSegment(segment, x1, y1, x2, y2)
    {
        segment.x1 = x1
        segment.y1 = y1
        segment.x2 = x2
        segment.y2 = y2
    }
    drawFlashSegments(segments)
    {
        this.ctx.beginPath()

        for (let i = 0; i < segments.length; ++i)
        {
            const segment = segments[i]
            this.ctx.moveTo(segment.x1, segment.y1)
            this.ctx.lineTo(segment.x2, segment.y2)
        }

        this.ctx.stroke()
    }
    drawDecorativeTriangles(width, height, geometry, time, shift)
    {
        const triangleTemplates = geometry.triangles || []
        shift = shift || {x: 0, y: 0}

        if (!triangleTemplates.length)
            return

        const triangles = this.getRandomizedTriangles(triangleTemplates, geometry)
        const sizeScale = backgroundTemplateScale(width, height)
        const motion = QUALITY.backgroundMotion && !this.shouldFreezeBadVersionBackgroundMotion()
            ? time / STYLE.timing.backgroundRotationMs * Math.PI * geometry.triangleRotationScale
            : 0

        this.ctx.save()
        this.ctx.lineWidth = geometry.triangleSilhouetteLineWidth

        for (let i = 0; i < triangles.length; ++i)
        {
            const triangle = triangles[i]
            const direction = i % 2 == 0 ? 1 : -1
            const x = triangle.x * width + shift.x * (0.35 + i * 0.04)
            const y = triangle.y * height + shift.y * (0.28 + i * 0.03)
            const radius = triangle.radius * sizeScale
            const rotation = triangle.rotation + motion * direction
            const palette = this.getTrianglePalette(triangle, geometry, x / width)
            const colors = this.getTrianglePaletteColors(palette)

            this.ctx.globalAlpha = triangle.alpha
            this.ctx.fillStyle = colors.fill
            this.ctx.strokeStyle = colors.stroke
            this.drawDecorativeTriangle(x, y, radius, rotation, triangle.points)
        }

        this.ctx.restore()
    }
    getRandomizedTriangles(triangleTemplates, geometry)
    {
        const cached = this.randomTriangleCache.get(triangleTemplates)

        if (cached)
            return cached.triangles

        const triangles = triangleTemplates.map(triangle => Object.assign({}, triangle, {
            x: Math.random(),
            y: Math.random()
        }))

        this.randomTriangleCache.set(triangleTemplates, {triangles})

        return triangles
    }
    getTrianglePalette(triangle, geometry, screenXRatio)
    {
        if (triangle.palette)
            return triangle.palette

        const split = typeof geometry.triangleColorSplitRatio == 'number'
            ? geometry.triangleColorSplitRatio
            : (typeof geometry.flashColorSplitRatio == 'number'
                ? geometry.flashColorSplitRatio
                : ((geometry.washLeftXRatio || 0) + (geometry.washRightXRatio || 1)) / 2)
        const xRatio = typeof screenXRatio == 'number'
            ? screenXRatio
            : triangle.x

        return xRatio < split ? 'blue' : 'magenta'
    }
    getTrianglePaletteColors(palette)
    {
        const colors = STYLE.colors.background
        const result = this.trianglePaletteColors

        if (palette == 'magenta')
        {
            result.fill = colors.triangleSilhouetteMagentaFill || colors.triangleSilhouetteFill
            result.stroke = colors.triangleSilhouetteMagentaStroke || colors.triangleSilhouetteStroke
            return result
        }

        result.fill = colors.triangleSilhouetteBlueFill || colors.triangleSilhouetteFill
        result.stroke = colors.triangleSilhouetteBlueStroke || colors.triangleSilhouetteStroke
        return result
    }
    drawDecorativeTriangle(centerX, centerY, radius, rotation, points)
    {
        this.ctx.beginPath()

        if (points && points.length >= 3)
        {
            for (let i = 0; i < points.length; ++i)
            {
                const point = points[i]
                const rotatedX = point.x * Math.cos(rotation) - point.y * Math.sin(rotation)
                const rotatedY = point.x * Math.sin(rotation) + point.y * Math.cos(rotation)
                const x = centerX + rotatedX * radius
                const y = centerY + rotatedY * radius

                if (i == 0)
                    this.ctx.moveTo(x, y)
                else
                    this.ctx.lineTo(x, y)
            }
        }
        else
        {
            for (let i = 0; i < 3; ++i)
            {
                const angle = rotation - Math.PI / 2 + i * Math.PI * 2 / 3
                const x = centerX + Math.cos(angle) * radius
                const y = centerY + Math.sin(angle) * radius

                if (i == 0)
                    this.ctx.moveTo(x, y)
                else
                    this.ctx.lineTo(x, y)
            }
        }

        this.ctx.closePath()
        this.ctx.fill()
        this.ctx.stroke()
    }
    getParallaxShift(width, height, geometry)
    {
        if (!QUALITY.backgroundMotion
            || (STYLE.visualStability.freezeBackgroundParallax && !STYLE.visualStability.useDistantBackgroundMotion))
            return {x: 0, y: 0}

        const ratio = geometry.parallaxShiftRatio
        const time = performance.now() * (geometry.ignoreTimeScale ? 1 : this.getVersionBackgroundTimeScale())
        const x = Math.sin(time / 3100) * width * ratio
        const y = Math.cos(time / 3700) * height * ratio

        return {x, y}
    }
    getCameraParallaxShift(geometry)
    {
        if (!QUALITY.backgroundMotion || typeof screen == 'undefined' || typeof scale == 'undefined' || typeof version == 'undefined')
            return {x: 0, y: 0}

        const canvasScale = scale[version] || 1
        const motionScale = geometry.ignoreTimeScale ? 1 : this.getVersionBackgroundTimeScale()
        const ratioX = (geometry.cameraParallaxXRatio || 0) * motionScale
        const ratioY = (geometry.cameraParallaxYRatio || 0) * motionScale

        return {
            x: screen.x * canvasScale * ratioX,
            y: screen.y * canvasScale * ratioY
        }
    }
    // Where a crystal/rock tile sits this frame: it follows a fraction of
    // the camera (against its motion; the far layer a small one, the near
    // rocks a larger one) and of the slow background drift
    getLayerShift(width, height, layer)
    {
        if (this.shouldFreezeBadVersionBackgroundMotion())
            return {x: 0, y: 0}

        const drift = this.getParallaxShift(width, height,
            {parallaxShiftRatio: layer.driftRatio, ignoreTimeScale: true})
        const camera = this.getCameraParallaxShift({
            cameraParallaxXRatio: layer.cameraParallaxXRatio,
            cameraParallaxYRatio: layer.cameraParallaxYRatio,
            ignoreTimeScale: true
        })
        const maxY = height * (layer.maxShiftYRatio || 0.05)

        return {
            x: drift.x - camera.x,
            y: Math.max(-maxY, Math.min(maxY, drift.y - camera.y))
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
    }
    drawCrystalLayer(width, height, shift)
    {
        const layer = this.getLayerTile('far', width, height, STYLE.backgroundGeometry.crystals,
            (...args) => this.paintCrystalTile(...args))
        this.drawLayerTile(layer, width, height, shift, STYLE.colors.background.crystalRock)
    }
    drawNearLayer(width, height, shift)
    {
        const layer = this.getLayerTile('near', width, height, STYLE.backgroundGeometry.nearRocks,
            (...args) => this.paintNearTile(...args))
        this.drawLayerTile(layer, width, height, shift, STYLE.colors.background.nearRock)
    }
    // Tiles a layer across fillBounds() at shift. Tile edges are snapped to
    // device pixels so neighbouring copies neither overlap nor leave a gap;
    // edgeFill covers what the shifted tile leaves uncovered above and below
    drawLayerTile(layer, width, height, shift, edgeFill)
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

        this.ctx.fillStyle = edgeFill
        if (bounds.y < shift.y)
            this.ctx.fillRect(bounds.x, bounds.y, bounds.width, shift.y - bounds.y)
        if (shift.y + height < bounds.y + bounds.height)
            this.ctx.fillRect(bounds.x, shift.y + height, bounds.width, bounds.y + bounds.height - shift.y - height)
    }
    drawPolygonAccents(width, height, geometry, time)
    {
        const accents = geometry.accents || []

        for (let i = 0; i < accents.length; ++i)
        {
            const accent = accents[i]
            const radius = accent.radius * backgroundTemplateScale(width, height)
            const rotation = accent.rotation + time / STYLE.timing.backgroundRotationMs * Math.PI * (i % 2 == 0 ? 1 : -1)
            const x = accent.x * width
            const y = accent.y * height

            this.drawPolygonAccent(x, y, radius, accent.sides, rotation, accent.danger, geometry.accentLineWidth)
        }
    }
    drawPolygonAccent(centerX, centerY, radius, sides, rotation, danger, lineWidth)
    {
        const colors = STYLE.colors.background

        this.ctx.save()
        this.ctx.beginPath()

        for (let i = 0; i < sides; ++i)
        {
            const angle = rotation + i * Math.PI * 2 / sides
            const x = centerX + Math.cos(angle) * radius
            const y = centerY + Math.sin(angle) * radius

            if (i == 0)
                this.ctx.moveTo(x, y)
            else
                this.ctx.lineTo(x, y)
        }

        this.ctx.closePath()
        this.ctx.fillStyle = danger ? colors.polygonDangerFill : colors.polygonAccentFill
        this.ctx.strokeStyle = danger ? colors.polygonDangerStroke : colors.polygonAccentStroke
        this.ctx.lineWidth = lineWidth
        this.ctx.fill()
        this.ctx.stroke()
        this.ctx.restore()
    }
    drawRectangleAccents(width, height, geometry, time, shift)
    {
        const rectangles = geometry.rectangles || []
        shift = shift || {x: 0, y: 0}

        for (let i = 0; i < rectangles.length; ++i)
        {
            const rect = rectangles[i]
            const sizeScale = backgroundTemplateScale(width, height)
            const rotation = rect.rotation + time / STYLE.timing.backgroundRotationMs * Math.PI * geometry.rectangleRotationScale * (i % 2 == 0 ? 1 : -1)
            const x = rect.x * width + shift.x
            const y = rect.y * height + shift.y

            this.drawRectangleAccent(
                x,
                y,
                rect.width * sizeScale,
                rect.height * sizeScale,
                rotation,
                rect.danger,
                geometry.accentLineWidth
            )
        }
    }
    drawRectangleAccent(centerX, centerY, width, height, rotation, danger, lineWidth)
    {
        const colors = STYLE.colors.background

        this.ctx.save()
        this.ctx.translate(centerX, centerY)
        this.ctx.rotate(rotation)
        this.ctx.fillStyle = danger ? colors.polygonDangerFill : colors.polygonAccentFill
        this.ctx.strokeStyle = danger ? colors.polygonDangerStroke : colors.polygonAccentStroke
        this.ctx.lineWidth = lineWidth
        this.ctx.fillRect(-width / 2, -height / 2, width, height)
        this.ctx.strokeRect(-width / 2, -height / 2, width, height)
        this.ctx.restore()
    }
    isBadVersion()
    {
        return typeof version != 'undefined' && version == 'bad'
    }
    usesDepthBackground()
    {
        return typeof version != 'undefined' && (version == 'bad' || version == 'classic')
    }
}

// '#rrggbb' -> 'rgba(r, g, b, alpha)' (used only when a gradient is built)
function colorWithAlpha(hex, alpha)
{
    const value = parseInt(hex.slice(1, 7), 16)
    return 'rgba(' + (value >> 16 & 255) + ', ' + (value >> 8 & 255) + ', ' + (value & 255) + ', ' + alpha + ')'
}

// Coloured light spill: every neon object adds a soft radial light of its own
// colour into a small canvas, which is added over the crystal background before
// the world is drawn, so obstacles themselves are never washed out.
class LightmapRenderer
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
        this.scale = STYLE.lights.resolutionScale
        this.enabled = true
        this.lightCanvas = document.createElement('canvas')
        this.lightCtx = this.lightCanvas.getContext('2d')
        // Unit-radius gradients by colour; drawRadialLight scales them to size
        this.gradients = new Map()
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
        this.drawPlayerLight(gameState.ninja)
        lightCtx.restore()
    }
    drawPlayerLight(player)
    {
        const lights = STYLE.lights
        this.drawRadialLight(
            player.x + screen.x,
            player.y + screen.y,
            lights.playerRadius,
            STYLE.colors.player.halo,
            lights.playerAlpha
        )
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
        const lights = STYLE.lights
        let radius
        let alpha

        // Every triangle gets the same light, so classic traps stay hidden
        if (element instanceof Triangle)
        {
            radius = lights.hazardRadius
            alpha = lights.hazardAlpha
        }
        else if (this.isCubeOrPlatform(element))
        {
            radius = lights.cubeRadius
            alpha = lights.cubeAlpha
        }
        else
            return

        // The drawn box, not getCircumscribedCircle(): that collision helper's
        // centre and radius can lie off the shape (Trampoline, Rect)
        const box = getElementCullBox(element)
        if (!box)
            return

        const halfWidth = (box.right - box.left) / 2
        const halfHeight = (box.bottom - box.top) / 2
        const elementScreenRadius = Math.sqrt(halfWidth * halfWidth + halfHeight * halfHeight)
            * scale[version] * 1080 / height
        let x = box.left + halfWidth
        let y = box.top + halfHeight

        // A big block (classic walls) can have its centre far off screen: the
        // light moves to the centre clamped into the view (still on the block).
        // Floor/ceiling strips spanning the view give no light, the bloom does that
        if (elementScreenRadius > lights.maxElementRadius)
        {
            const viewWidth = width / scale[version]
            const viewHeight = height / scale[version]

            if (box.right < -screen.x || box.left > -screen.x + viewWidth
                || box.bottom < -screen.y || box.top > -screen.y + viewHeight)
                return

            y = Math.max(-screen.y, Math.min(-screen.y + viewHeight, y))

            if (box.right - box.left > viewWidth * lights.maxBlockViewWidthRatio)
            {
                // Wider than the view: only its vertical edge facing the view
                // centre glows, fading out as that edge nears the centre
                const centerX = -screen.x + viewWidth / 2
                const distance = Math.max(box.left - centerX, centerX - box.right)
                if (distance <= 0)
                    return

                alpha *= Math.min(1, distance / (viewWidth * lights.edgeFadeViewRatio))
                x = centerX < box.left ? box.left : box.right
            }
            else
                x = Math.max(-screen.x, Math.min(-screen.x + viewWidth, x))
        }

        // Bigger blocks light a wider area, up to maxElementRadius more
        this.drawRadialLight(
            x + screen.x,
            y + screen.y,
            radius + Math.min(elementScreenRadius, lights.maxElementRadius),
            this.getElementLightColor(element),
            alpha
        )
    }
    isCubeOrPlatform(element)
    {
        // The floor/ceiling strips span the whole level; their glow is the bloom's job
        if (element instanceof Ground)
            return false

        return element instanceof Rect || element instanceof Trampoline
    }
    getElementLightColor(element)
    {
        return element.getGlowStroke() || STYLE.colors.cube.blue
    }
    composite()
    {
        if (!this.shouldDraw())
            return

        const viewWidth = LOGICAL_VIEWPORT.width / scale[version]
        const viewHeight = LOGICAL_VIEWPORT.height / scale[version]

        this.ctx.save()
        this.ctx.globalAlpha = STYLE.lights.compositeAlpha
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
        const alpha = particle.alpha * Math.max(0, Math.min(1, (1 - progress) * 6, progress))
        const haloSize = particle.size * config.sparkHaloRatio

        this.ctx.globalAlpha = alpha * config.sparkHaloAlpha
        this.ctx.fillStyle = STYLE.colors.playerTrail.sparkHalo
        this.ctx.fillRect(drawX - haloSize / 2, drawY - haloSize / 2, haloSize, haloSize)

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
        if (!this.isVisible(element))
            return

        if (this.isHazard(element))
        {
            const badParticles = this.getBadVersionParticles()
            const chance = Math.min(1, STYLE.particles.hazardEmitChance
                * badParticles.worldChanceMultiplier
                * badParticles.hazardChanceMultiplier)

            if (Math.random() <= chance)
            {
                for (let i = 0; i < badParticles.hazardEmitCount; ++i)
                {
                    this.emitAroundElement(
                        element,
                        STYLE.colors.hazard.red,
                        STYLE.particles.hazardSpeed * badParticles.speedMultiplier,
                        this.clampAlpha(STYLE.particles.hazardAlpha * badParticles.alphaMultiplier),
                        badParticles
                    )
                }
            }

            return
        }

        const badParticles = this.getBadVersionParticles()
        const chance = Math.min(1, STYLE.particles.cubeEmitChance * badParticles.worldChanceMultiplier)

        if (this.isCubeOrPlatform(element) && Math.random() <= chance)
        {
            this.emitAroundElement(
                element,
                this.getElementParticleColor(element),
                STYLE.particles.cubeSpeed * badParticles.speedMultiplier,
                this.clampAlpha(STYLE.particles.cubeAlpha * badParticles.alphaMultiplier),
                badParticles
            )
        }
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

        const outline = this.getRibbonOutline(positions, start, width)

        if (!outline.length)
            return

        ctx.globalAlpha = this.clampAlpha(alpha)
        ctx.fillStyle = color
        this.drawRibbonOutline(outline)
        ctx.fill()
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
    // Level 0 is the glow canvas; each next level is half the previous one.
    resize()
    {
        const config = STYLE.bloom
        while (this.levels.length < config.blurLevels)
        {
            const levelCanvas = document.createElement('canvas')
            const levelCtx = levelCanvas.getContext('2d', {alpha: false})
            this.levels.push({canvas: levelCanvas, ctx: levelCtx})
        }

        let levelWidth = Math.max(1, Math.floor(this.canvas.width * config.resolutionScale))
        let levelHeight = Math.max(1, Math.floor(this.canvas.height * config.resolutionScale))
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
        this.composite()
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
        for (let i = 0; i < floors.length; ++i)
            floors[i].drawGlow()
        // Hazard trail envelopes and shockwave rings: no shadowBlur, their
        // glow comes from here
        if (version == 'bad' && visualEffects.playerTrail.shouldDraw())
            for (let i = 0; i < floors.length; ++i)
                floors[i].drawTracks()
        visualEffects.screenEffects.drawShockwaveGlow()
        grapnel.drawHook()
        this.drawNinjaRing(gameState.ninja)
        visualEffects.particles.drawLayer(BloomRenderer.anyParticle)
    }
    static anyParticle()
    {
        return true
    }
    drawNinjaRing(player)
    {
        const radius = player.getVisualRadius()

        ctx.beginPath()
        ctx.arc(player.x + screen.x, player.y + screen.y, radius, 0, Math.PI * 2, false)
        ctx.globalAlpha = player.getBlinkAlpha()
        ctx.strokeStyle = player.stroke
        ctx.lineWidth = radius * STYLE.playerVisuals.ringWidthRatio
        ctx.stroke()
        ctx.globalAlpha = 1
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
    composite()
    {
        const config = STYLE.bloom

        this.ctx.save()
        this.ctx.setTransform(1, 0, 0, 1, 0, 0)
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
        this.shakeUntil = 0
        this.shakeStart = 0
        this.shakeOffset = {x: 0, y: 0}
        this.isShaking = false
    }
    shouldApply()
    {
        return STYLE.features.screenEffects
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
