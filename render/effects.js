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

        this.drawHexagons(width, height, geometry, time)
        this.drawStreaks(width, height, geometry, time)

        if (this.isBadVersion())
            this.drawBadVersionDepth(width, height, geometry.badVersion, time)
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
    drawStreakSet(width, height, geometry, time, strokeStyle, yOffset)
    {
        const diagonal = Math.sqrt(width * width + height * height)
        const spacing = Math.max(width, height) * geometry.streakSpacingRatio
        const length = diagonal * geometry.streakLengthRatio
        const offset = (time % STYLE.timing.backgroundStreakMs) / STYLE.timing.backgroundStreakMs * spacing

        this.ctx.save()
        this.ctx.strokeStyle = strokeStyle
        this.ctx.lineWidth = geometry.streakLineWidth

        for (let i = -2; i < geometry.streakCount; ++i)
        {
            const x = i * spacing + offset - spacing * 2
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
        const shift = this.getParallaxShift(width, height, geometry)

        this.ctx.save()
        this.ctx.globalCompositeOperation = 'lighter'
        this.drawHexagonSet(
            width,
            height,
            geometry,
            time,
            width * 0.56 + shift.x,
            height * 0.52 + shift.y,
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
            time * 0.72,
            width * 0.25 - shift.x * 0.6,
            height * 0.36 - shift.y * 0.4,
            background.depthHexagonAccentStroke,
            background.depthHexagonStroke
        )
        this.drawStreakSet(width, height, geometry, time, background.depthStreak, -height * 0.08)
        this.drawPolygonAccents(width, height, geometry, time)
        this.ctx.restore()
    }
    getParallaxShift(width, height, geometry)
    {
        if (!QUALITY.backgroundMotion)
            return {x: 0, y: 0}

        const ratio = geometry.parallaxShiftRatio
        const x = Math.sin(performance.now() / 3100) * width * ratio
        const y = Math.cos(performance.now() / 3700) * height * ratio

        return {x, y}
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

        this.ctx.save()
        this.ctx.globalAlpha = this.clampAlpha(STYLE.lights.compositeAlpha * badLights.compositeAlphaMultiplier)
        this.ctx.globalCompositeOperation = 'lighter'
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

        this.emitPlayerParticles(gameState.ninja)

        if (now - this.lastWorldEmitTime >= STYLE.particles.worldEmitIntervalMs)
        {
            this.emitWorldParticles(gameState.floors)
            this.lastWorldEmitTime = now
        }

        this.updateParticles(dt)
    }
    draw()
    {
        if (!this.shouldDraw())
            return

        this.ctx.save()
        this.ctx.globalCompositeOperation = 'lighter'

        for (let i = 0; i < this.particles.length; ++i)
        {
            const particle = this.particles[i]
            const progress = particle.life / particle.maxLife

            this.ctx.globalAlpha = Math.max(0, progress) * particle.alpha
            this.ctx.fillStyle = particle.color
            this.ctx.fillRect(
                particle.x - particle.size / 2,
                particle.y - particle.size / 2,
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
    emitSquare(x, y, color, speed, alpha, particleConfig)
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
            alpha
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
        const positions = track.pos
        const width = track.lineWidth * config.widthRatio * badTrails.widthMultiplier
        const glowWidth = track.lineWidth * config.glowWidthRatio * badTrails.glowWidthMultiplier
        const visibleStart = Math.max(1, Math.floor(positions.length * config.minSegmentRatio))

        ctx.save()
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        ctx.globalCompositeOperation = 'lighter'
        ctx.strokeStyle = STYLE.colors.player.trail
        ctx.shadowColor = STYLE.colors.player.trail

        this.drawSmoothPath(
            positions,
            Math.max(0, visibleStart - 1),
            positions.length,
            width,
            this.clampAlpha(config.maxAlpha * badTrails.alphaMultiplier),
            glowWidth
        )

        if (positions.length > visibleStart + 1)
        {
            const tailStart = Math.max(1, positions.length - Math.floor((positions.length - visibleStart) * badTrails.tailPortion))
            this.drawSmoothPath(
                positions,
                tailStart - 1,
                positions.length,
                Math.max(track.lineWidth, width * 0.36),
                this.clampAlpha(config.coreAlpha * badTrails.alphaMultiplier),
                0
            )
        }

        ctx.restore()
    }
    drawSmoothPath(positions, start, end, width, alpha, glowWidth)
    {
        if (end - start < 2)
            return

        ctx.globalAlpha = alpha
        ctx.lineWidth = width
        ctx.shadowBlur = glowWidth
        ctx.beginPath()
        ctx.moveTo(positions[start].x + screen.x, positions[start].y + screen.y)

        for (let i = start + 1; i < end - 1; ++i)
        {
            const next = positions[i + 1]
            const middleX = (positions[i].x + next.x) / 2 + screen.x
            const middleY = (positions[i].y + next.y) / 2 + screen.y

            ctx.quadraticCurveTo(positions[i].x + screen.x, positions[i].y + screen.y, middleX, middleY)
        }

        ctx.lineTo(positions[end - 1].x + screen.x, positions[end - 1].y + screen.y)
        ctx.stroke()
    }
    getBadVersionTrails()
    {
        if (typeof version != 'undefined' && version == 'bad')
            return STYLE.badVersionEffects.trails

        return {
            widthMultiplier: 1,
            glowWidthMultiplier: 1,
            alphaMultiplier: 1,
            chunkCount: 4,
            tailPortion: 0.28
        }
    }
    clampAlpha(alpha)
    {
        return Math.max(0, Math.min(1, alpha))
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
        this.ctx.globalCompositeOperation = 'lighter'
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

            this.ctx.globalAlpha = config.shockwaveAlpha * (1 - progress)
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
            menu
        }
    }
}
