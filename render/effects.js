class BackgroundRenderer
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
    }
    draw()
    {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)

        if (!STYLE.features.background)
            return

        const background = STYLE.colors.background
        const width = this.canvas.width
        const height = this.canvas.height

        const gradient = this.ctx.createLinearGradient(0, 0, 0, height)
        gradient.addColorStop(0, background.gradientTop)
        gradient.addColorStop(0.54, background.gradientMiddle)
        gradient.addColorStop(1, background.gradientBottom)
        this.ctx.fillStyle = gradient
        this.ctx.fillRect(0, 0, width, height)

        this.drawGeometry(width, height)

        const radius = Math.sqrt(width * width + height * height) * 0.58
        const vignette = this.ctx.createRadialGradient(
            width / 2,
            height / 2,
            radius * 0.18,
            width / 2,
            height / 2,
            radius
        )
        vignette.addColorStop(0, background.vignetteCenter)
        vignette.addColorStop(1, background.vignetteEdge)
        this.ctx.fillStyle = vignette
        this.ctx.fillRect(0, 0, width, height)
    }
    getAnimationTime()
    {
        if (!QUALITY.backgroundMotion)
            return 0

        return performance.now()
    }
    drawGeometry(width, height)
    {
        const geometry = STYLE.backgroundGeometry
        const time = this.getAnimationTime()

        if (this.isBadVersion())
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
        const rotation = (time % STYLE.timing.backgroundRotationMs) / STYLE.timing.backgroundRotationMs * Math.PI * 2

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
    drawBadVersionDepth(width, height, geometry, time)
    {
        if (!geometry)
            return

        const background = STYLE.colors.background
        const freezeMotion = this.shouldFreezeBadVersionBackgroundMotion()
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
        this.drawStreakSet(width, height, geometry, streakTime, background.depthStreak, -height * 0.08 + totalShift.y, totalShift.x)
        this.drawDiagonalFlashes(width, height, geometry, geometryTime)
        this.drawDecorativeTriangles(width, height, geometry, geometryTime, totalShift)
        this.drawRectangleAccents(width, height, geometry, geometryTime, totalShift)
        this.ctx.restore()
    }
    shouldFreezeBadVersionBackgroundMotion()
    {
        return STYLE.visualStability.freezeBadVersionBackground
    }
    drawDiagonalFlashes(width, height, geometry, time)
    {
        const flashes = geometry.flashes || []

        if (!flashes.length)
            return

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
            const startX = flash.x * width + animationOffset
            const startY = flash.y * height
            const endX = startX + length
            const endY = startY - length
            const stroke = flash.color == 'blue' ? colors.flashBlue : colors.flashMagenta
            const glow = flash.color == 'blue' ? colors.flashBlueGlow : colors.flashMagentaGlow

            this.ctx.globalAlpha = stableMultiplier
            this.ctx.strokeStyle = glow
            this.ctx.lineWidth = geometry.flashGlowWidth
            this.ctx.beginPath()
            this.ctx.moveTo(startX, startY)
            this.ctx.lineTo(endX, endY)
            this.ctx.stroke()

            this.ctx.globalAlpha = Math.min(1, stableMultiplier * 1.45)
            this.ctx.strokeStyle = stroke
            this.ctx.lineWidth = geometry.flashLineWidth
            this.ctx.beginPath()
            this.ctx.moveTo(startX, startY)
            this.ctx.lineTo(endX, endY)
            this.ctx.stroke()
        }

        this.ctx.restore()
    }
    drawDecorativeTriangles(width, height, geometry, time, shift)
    {
        const triangles = geometry.triangles || []
        shift = shift || {x: 0, y: 0}

        if (!triangles.length)
            return

        const sizeScale = Math.min(width, height) / 720
        const motion = QUALITY.backgroundMotion && !this.shouldFreezeBadVersionBackgroundMotion()
            ? time / STYLE.timing.backgroundRotationMs * Math.PI * geometry.triangleRotationScale
            : 0

        this.ctx.save()
        this.ctx.fillStyle = STYLE.colors.background.triangleSilhouetteFill
        this.ctx.strokeStyle = STYLE.colors.background.triangleSilhouetteStroke
        this.ctx.lineWidth = geometry.triangleSilhouetteLineWidth

        for (let i = 0; i < triangles.length; ++i)
        {
            const triangle = triangles[i]
            const direction = i % 2 == 0 ? 1 : -1
            const x = triangle.x * width + shift.x * (0.35 + i * 0.04)
            const y = triangle.y * height + shift.y * (0.28 + i * 0.03)
            const radius = triangle.radius * sizeScale
            const rotation = triangle.rotation + motion * direction

            this.ctx.globalAlpha = triangle.alpha
            this.drawDecorativeTriangle(x, y, radius, rotation)
        }

        this.ctx.restore()
    }
    drawDecorativeTriangle(centerX, centerY, radius, rotation)
    {
        this.ctx.beginPath()

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
        const x = Math.sin(performance.now() / 3100) * width * ratio
        const y = Math.cos(performance.now() / 3700) * height * ratio

        return {x, y}
    }
    getCameraParallaxShift(geometry)
    {
        if (!QUALITY.backgroundMotion || typeof screen == 'undefined' || typeof scale == 'undefined' || typeof version == 'undefined')
            return {x: 0, y: 0}

        const canvasScale = scale[version] || 1
        const ratioX = geometry.cameraParallaxXRatio || 0
        const ratioY = geometry.cameraParallaxYRatio || 0

        return {
            x: screen.x * canvasScale * ratioX,
            y: screen.y * canvasScale * ratioY
        }
    }
    drawPolygonAccents(width, height, geometry, time)
    {
        const accents = geometry.accents || []

        for (let i = 0; i < accents.length; ++i)
        {
            const accent = accents[i]
            const radius = accent.radius * Math.min(width, height) / 720
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
            const sizeScale = Math.min(width, height) / 720
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
}

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
        this.resize()
    }
    shouldDraw()
    {
        return this.enabled && STYLE.features.lightmap && QUALITY.lightmap
    }
    resize()
    {
        const nextWidth = Math.max(1, Math.ceil(this.canvas.width * this.scale))
        const nextHeight = Math.max(1, Math.ceil(this.canvas.height * this.scale))

        if (this.lightCanvas.width == nextWidth && this.lightCanvas.height == nextHeight)
            return

        this.lightCanvas.width = nextWidth
        this.lightCanvas.height = nextHeight
    }
    clear()
    {
        this.resize()
        this.lightCtx.clearRect(0, 0, this.lightCanvas.width, this.lightCanvas.height)
    }
    drawRadialLight(x, y, radius, color, alpha)
    {
        const lightX = x * this.scale
        const lightY = y * this.scale
        const lightRadius = radius * this.scale
        const gradient = this.lightCtx.createRadialGradient(lightX, lightY, 0, lightX, lightY, lightRadius)

        gradient.addColorStop(0, color)
        gradient.addColorStop(1, 'rgba(0, 0, 0, 0)')

        this.lightCtx.save()
        this.lightCtx.globalAlpha = alpha
        this.lightCtx.globalCompositeOperation = 'lighter'
        this.lightCtx.fillStyle = gradient
        this.lightCtx.fillRect(lightX - lightRadius, lightY - lightRadius, lightRadius * 2, lightRadius * 2)
        this.lightCtx.restore()
    }
    draw(gameState)
    {
        if (!this.shouldDraw())
            return

        this.drawAmbientLight()
        this.drawPlayerLight(gameState.ninja)
        this.drawWorldLights(gameState.floors)
    }
    drawAmbientLight()
    {
        const viewWidth = this.canvas.width / scale[version]
        const viewHeight = this.canvas.height / scale[version]
        const radius = Math.max(viewWidth, viewHeight) * STYLE.lights.ambientRadiusRatio

        this.drawRadialLight(
            viewWidth * 0.5,
            viewHeight * 0.45,
            radius,
            STYLE.colors.cube.blue,
            STYLE.lights.ambientAlpha
        )
    }
    drawPlayerLight(player)
    {
        const badLights = this.getBadVersionLights()

        this.drawRadialLight(
            player.x + screen.x,
            player.y + screen.y,
            STYLE.lights.playerRadius * badLights.radiusMultiplier,
            STYLE.colors.player.cyan,
            this.clampAlpha(STYLE.lights.alpha * badLights.alphaMultiplier)
        )

        this.drawBadVersionBloom(
            player.x + screen.x,
            player.y + screen.y,
            STYLE.lights.playerRadius,
            STYLE.colors.player.cyan
        )
    }
    drawWorldLights(floors)
    {
        for (let i = 0; i < floors.length; ++i)
        {
            for (let j = 0; j < floors[i].elements.length; ++j)
            {
                this.drawElementLight(floors[i].elements[j])
            }
        }
    }
    drawElementLight(element)
    {
        if (this.isHazard(element))
        {
            this.drawHazardPulseLight(element)
            return
        }

        if (this.isCubeOrPlatform(element))
        {
            const badLights = this.getBadVersionLights()
            const circle = element.getCircumscribedCircle()
            const lightColor = this.getElementLightColor(element)

            this.drawElementCircleLight(
                element,
                STYLE.lights.cubeRadius * badLights.radiusMultiplier,
                lightColor,
                this.clampAlpha(STYLE.lights.alpha * badLights.alphaMultiplier)
            )
            this.drawBadVersionBloom(
                circle.x + screen.x,
                circle.y + screen.y,
                Math.max(STYLE.lights.cubeRadius, circle.radius),
                lightColor
            )
        }
    }
    drawHazardPulseLight(element)
    {
        const circle = this.getScreenCircle(element)

        if (!this.isScreenCircleVisible(circle))
            return

        const badLights = this.getBadVersionLights()
        const pulse = this.getPulseRatio(STYLE.timing.hazardPulseMs)
        const alpha = STYLE.lights.hazardPulseMinAlpha
            + (STYLE.lights.hazardPulseMaxAlpha - STYLE.lights.hazardPulseMinAlpha) * pulse
        const radius = (STYLE.lights.hazardRadius + STYLE.lights.hazardPulseRadiusBoost * pulse)
            * badLights.hazardRadiusMultiplier

        this.drawElementCircleLight(
            element,
            radius,
            STYLE.colors.hazard.red,
            this.clampAlpha(alpha * badLights.hazardAlphaMultiplier)
        )

        this.drawBadVersionBloom(
            circle.x,
            circle.y,
            radius,
            STYLE.colors.hazard.red
        )
    }
    getPulseRatio(durationMs)
    {
        if (STYLE.visualStability.freezeHazardPulse)
            return 0.5

        const duration = Math.max(1, durationMs)
        const phase = (performance.now() % duration) / duration

        return 0.5 + Math.sin(phase * Math.PI * 2) * 0.5
    }
    drawElementCircleLight(element, radius, color, alpha)
    {
        const circle = this.getScreenCircle(element)

        this.drawRadialLight(
            circle.x,
            circle.y,
            Math.max(radius, circle.radius),
            color,
            alpha
        )
    }
    getScreenCircle(element)
    {
        const circle = element.getCircumscribedCircle()

        return {
            x: circle.x + screen.x,
            y: circle.y + screen.y,
            radius: circle.radius
        }
    }
    isScreenCircleVisible(circle)
    {
        const viewWidth = this.canvas.width / scale[version]
        const viewHeight = this.canvas.height / scale[version]
        const margin = circle.radius

        return circle.x > -margin
            && circle.x < viewWidth + margin
            && circle.y > -margin
            && circle.y < viewHeight + margin
    }
    isHazard(element)
    {
        return element instanceof Triangle && !(element instanceof HarmlessTriangle)
    }
    isCubeOrPlatform(element)
    {
        if (element instanceof Ground || element instanceof Side)
            return false

        return element instanceof Rect || element instanceof Trampoline || element instanceof HarmlessTriangle
    }
    getElementLightColor(element)
    {
        return element.stroke || STYLE.colors.cube.blue
    }
    composite()
    {
        if (!this.shouldDraw())
            return

        const viewWidth = this.canvas.width / scale[version]
        const viewHeight = this.canvas.height / scale[version]
        const badLights = this.getBadVersionLights()
        const stableLightMultiplier = STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.stableLightCompositeMultiplier
            : 1

        this.ctx.save()
        this.ctx.globalAlpha = this.clampAlpha(
            STYLE.lights.compositeAlpha
            * badLights.compositeAlphaMultiplier
            * stableLightMultiplier
        )
        this.ctx.globalCompositeOperation = this.getEffectCompositeOperation()
        this.ctx.imageSmoothingEnabled = true
        this.ctx.drawImage(this.lightCanvas, 0, 0, viewWidth, viewHeight)
        this.ctx.restore()
    }
    drawBadVersionBloom(x, y, radius, color)
    {
        if (!this.isBadVersion())
            return

        const badLights = STYLE.badVersionEffects.lights

        this.drawRadialLight(
            x,
            y,
            radius * badLights.bloomRadiusMultiplier,
            color,
            badLights.bloomAlphaMultiplier
        )
    }
    getBadVersionLights()
    {
        if (!this.isBadVersion())
        {
            return {
                radiusMultiplier: 1,
                alphaMultiplier: 1,
                hazardRadiusMultiplier: 1,
                hazardAlphaMultiplier: 1,
                compositeAlphaMultiplier: 1
            }
        }

        return STYLE.badVersionEffects.lights
    }
    getEffectCompositeOperation()
    {
        return STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.effectCompositeOperation
            : 'lighter'
    }
    isBadVersion()
    {
        return typeof version != 'undefined' && version == 'bad'
    }
    clampAlpha(alpha)
    {
        return Math.max(0, Math.min(1, alpha))
    }
}

class ParticleSystem
{
    constructor(context, targetCanvas)
    {
        this.ctx = context
        this.canvas = targetCanvas
        this.particles = []
        this.lastTime = 0
        this.lastWorldEmitTime = 0
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
    updateParticles(dt)
    {
        for (let i = this.particles.length - 1; i >= 0; --i)
        {
            const particle = this.particles[i]

            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
            particle.life -= dt

            if (particle.life <= 0)
                this.particles.splice(i, 1)
        }
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
        const circle = trampoline.getCircumscribedCircle()
        const originX = player.x
        const originY = player.y
        const color = trampoline.stroke || STYLE.colors.cube.greenStroke
        const count = STYLE.particles.trampolineSplashCount
        const dispersion = circle.radius * STYLE.particles.trampolineSplashDispersionRatio

        for (let i = 0; i < count; ++i)
        {
            this.emitSquare(
                originX + this.randomRange(-dispersion, dispersion),
                originY + this.randomRange(-dispersion, dispersion),
                color,
                STYLE.particles.trampolineSplashSpeed * splashParticles.speedMultiplier,
                this.clampAlpha(STYLE.particles.trampolineSplashAlpha * badParticles.alphaMultiplier),
                splashParticles,
                true,
                true
            )
        }
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
        const speed = Math.sqrt(player.speedX * player.speedX + player.speedY * player.speedY)

        if (speed < 0.08)
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

        this.particles.push({
            x,
            y,
            vx: Math.cos(angle) * velocity,
            vy: Math.sin(angle) * velocity,
            color,
            life,
            maxLife: life,
            size: this.randomRange(
                STYLE.particles.minSize * config.sizeMultiplier,
                STYLE.particles.maxSize * config.sizeMultiplier
            ),
            alpha,
            worldAnchored: !!worldAnchored,
            drawBeforeForeground: !!drawBeforeForeground
        })

        this.enforceCap()
    }
    enforceCap()
    {
        const overage = this.particles.length - STYLE.particles.maxCount

        if (overage > 0)
            this.particles.splice(0, overage)
    }
    isVisible(element)
    {
        const circle = element.getCircumscribedCircle()
        const x = circle.x + screen.x
        const y = circle.y + screen.y
        const margin = circle.radius + STYLE.particles.maxSize
        const viewWidth = this.canvas.width / scale[version]
        const viewHeight = this.canvas.height / scale[version]

        return x > -margin && x < viewWidth + margin && y > -margin && y < viewHeight + margin
    }
    isHazard(element)
    {
        return element instanceof Triangle && !(element instanceof HarmlessTriangle)
    }
    isCubeOrPlatform(element)
    {
        if (element instanceof Ground || element instanceof Side)
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
    drawSmoothPlayerTrail(track)
    {
        if (!track || track.pos.length < 2)
            return

        const config = STYLE.trails.player
        const badTrails = this.getBadVersionTrails()
        const positions = this.getRibbonPoints(track.pos, track.lineWidth * config.minPointDistanceRatio)
        const width = track.lineWidth * config.widthRatio * badTrails.widthMultiplier
        const glowWidth = track.lineWidth * config.glowWidthRatio * badTrails.glowWidthMultiplier
        const visibleStart = Math.max(1, Math.floor(positions.length * config.minSegmentRatio))
        const stableAlpha = badTrails.alphaMultiplier * this.getStableAlphaMultiplier()

        ctx.save()
        ctx.globalCompositeOperation = this.getEffectCompositeOperation()
        ctx.shadowColor = STYLE.colors.player.trail

        this.drawRibbon(
            positions,
            visibleStart,
            width,
            glowWidth,
            this.clampAlpha(config.maxAlpha * stableAlpha)
        )

        ctx.restore()
    }
    getRibbonPoints(positions, minDistance)
    {
        if (positions.length < 3 || minDistance <= 0)
            return positions

        const ribbonPoints = [positions[0]]
        let last = positions[0]

        for (let i = 1; i < positions.length - 1; ++i)
        {
            const dx = positions[i].x - last.x
            const dy = positions[i].y - last.y

            if (Math.sqrt(dx * dx + dy * dy) >= minDistance)
            {
                ribbonPoints.push(positions[i])
                last = positions[i]
            }
        }

        ribbonPoints.push(positions[positions.length - 1])
        return ribbonPoints
    }
    drawRibbon(positions, visibleStart, width, glowWidth, alpha)
    {
        if (positions.length - visibleStart < 2)
            return

        const outline = this.getRibbonOutline(positions, visibleStart, width)

        if (!outline.length)
            return

        ctx.fillStyle = STYLE.colors.player.trail
        ctx.strokeStyle = STYLE.colors.player.trail

        ctx.globalAlpha = this.clampAlpha(alpha * 0.5)
        ctx.shadowBlur = glowWidth
        this.drawRibbonOutline(outline)
        ctx.fill()

        ctx.globalAlpha = alpha
        ctx.shadowBlur = 0
        this.drawRibbonOutline(outline)
        ctx.fill()

        ctx.globalAlpha = this.clampAlpha(STYLE.trails.player.edgeAlpha * alpha)
        ctx.lineWidth = Math.max(1, width * 0.12)
        ctx.lineJoin = 'round'
        this.drawRibbonOutline(outline)
        ctx.stroke()
    }
    getRibbonOutline(positions, visibleStart, width)
    {
        const config = STYLE.trails.player
        const left = []
        const right = []
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

            left.push({x: centerX + normalX * halfWidth, y: centerY + normalY * halfWidth})
            right.push({x: centerX - normalX * halfWidth, y: centerY - normalY * halfWidth})
        }

        return left.concat(right.reverse())
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
            glowWidthMultiplier: 0.5,
            alphaMultiplier: 1,
            chunkCount: 4,
            tailPortion: 0.28
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
        const magnitude = STYLE.screenEffects.shakeMagnitude * (1 - progress)
        const angle = now * 0.07

        this.shakeOffset.x = Math.cos(angle * 1.7) * magnitude
        this.shakeOffset.y = Math.sin(angle * 2.1) * magnitude

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

        this.ctx.save()
        this.ctx.globalCompositeOperation = STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.effectCompositeOperation
            : 'lighter'
        this.ctx.strokeStyle = STYLE.colors.player.cyan
        this.ctx.shadowColor = STYLE.colors.player.cyan
        this.ctx.lineWidth = config.shockwaveLineWidth
        this.ctx.shadowBlur = config.shockwaveGlowWidth

        for (let i = this.shockwaves.length - 1; i >= 0; --i)
        {
            const shockwave = this.shockwaves[i]

            if (now >= shockwave.end)
            {
                this.shockwaves.splice(i, 1)
                continue
            }

            const progress = (now - shockwave.start) / Math.max(1, config.shockwaveDurationMs)
            const eased = 1 - Math.pow(1 - progress, 2)
            const radius = config.shockwaveStartRadius
                + (config.shockwaveEndRadius - config.shockwaveStartRadius) * eased

            const stableAlpha = STYLE.visualStability.stableBrightness
                ? STYLE.visualStability.stableEffectAlphaMultiplier
                : 1

            this.ctx.globalAlpha = config.shockwaveAlpha * stableAlpha * (1 - progress)
            this.ctx.beginPath()
            this.ctx.arc(shockwave.x, shockwave.y, radius, 0, Math.PI * 2)
            this.ctx.stroke()
            this.ctx.closePath()
        }

        this.ctx.restore()
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
    draw(gameState)
    {
        if (!this.shouldDraw())
            return

        gameState.scoreText.draw()
        gameState.menu.button.draw()
        gameState.fpsCounter.draw()
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
