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
    }
    drawHexagons(width, height, geometry, time)
    {
        const minSize = Math.min(width, height)
        const centerX = width / 2
        const centerY = height / 2
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

            this.ctx.strokeStyle = i % 2 == 0
                ? STYLE.colors.background.hexagonStroke
                : STYLE.colors.background.hexagonAccentStroke
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
        const diagonal = Math.sqrt(width * width + height * height)
        const spacing = Math.max(width, height) * geometry.streakSpacingRatio
        const length = diagonal * geometry.streakLengthRatio
        const offset = (time % STYLE.timing.backgroundStreakMs) / STYLE.timing.backgroundStreakMs * spacing

        this.ctx.save()
        this.ctx.strokeStyle = STYLE.colors.background.streak
        this.ctx.lineWidth = geometry.streakLineWidth

        for (let i = -2; i < geometry.streakCount; ++i)
        {
            const x = i * spacing + offset - spacing * 2
            const y = height + spacing

            this.ctx.beginPath()
            this.ctx.moveTo(x, y)
            this.ctx.lineTo(x + length, y - length)
            this.ctx.stroke()
        }

        this.ctx.restore()
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
        this.drawRadialLight(
            player.x + screen.x,
            player.y + screen.y,
            STYLE.lights.playerRadius,
            STYLE.colors.player.cyan,
            STYLE.lights.alpha
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
            this.drawElementCircleLight(
                element,
                STYLE.lights.hazardRadius,
                STYLE.colors.hazard.red,
                STYLE.lights.alpha
            )
            return
        }

        if (this.isCubeOrPlatform(element))
        {
            this.drawElementCircleLight(
                element,
                STYLE.lights.cubeRadius,
                STYLE.colors.cube.blue,
                STYLE.lights.alpha
            )
        }
    }
    drawElementCircleLight(element, radius, color, alpha)
    {
        const circle = element.getCircumscribedCircle()

        this.drawRadialLight(
            circle.x + screen.x,
            circle.y + screen.y,
            Math.max(radius, circle.radius),
            color,
            alpha
        )
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
    composite()
    {
        if (!this.shouldDraw())
            return

        const viewWidth = this.canvas.width / scale[version]
        const viewHeight = this.canvas.height / scale[version]

        this.ctx.save()
        this.ctx.globalAlpha = STYLE.lights.compositeAlpha
        this.ctx.globalCompositeOperation = 'lighter'
        this.ctx.imageSmoothingEnabled = true
        this.ctx.drawImage(this.lightCanvas, 0, 0, viewWidth, viewHeight)
        this.ctx.restore()
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

        for (let i = 0; i < STYLE.particles.playerEmitCount; ++i)
        {
            this.emitSquare(
                player.x + screen.x + this.randomRange(-player.radius, player.radius),
                player.y + screen.y + this.randomRange(-player.radius, player.radius),
                STYLE.colors.player.cyan,
                STYLE.particles.playerSpeed,
                0.72
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
            if (Math.random() <= STYLE.particles.hazardEmitChance)
                this.emitAroundElement(element, STYLE.colors.hazard.red, STYLE.particles.hazardSpeed, 0.64)

            return
        }

        if (this.isCubeOrPlatform(element) && Math.random() <= STYLE.particles.cubeEmitChance)
        {
            this.emitAroundElement(element, STYLE.colors.cube.blue, STYLE.particles.cubeSpeed, 0.36)
        }
    }
    emitAroundElement(element, color, speed, alpha)
    {
        const circle = element.getCircumscribedCircle()
        const angle = Math.random() * Math.PI * 2
        const radius = circle.radius * Math.sqrt(Math.random())
        const x = circle.x + screen.x + Math.cos(angle) * radius
        const y = circle.y + screen.y + Math.sin(angle) * radius

        this.emitSquare(x, y, color, speed, alpha)
    }
    emitSquare(x, y, color, speed, alpha)
    {
        const angle = Math.random() * Math.PI * 2
        const velocity = this.randomRange(speed * 0.35, speed)
        const life = this.randomRange(STYLE.particles.lifetimeMs * 0.55, STYLE.particles.lifetimeMs)

        this.particles.push({
            x,
            y,
            vx: Math.cos(angle) * velocity,
            vy: Math.sin(angle) * velocity,
            color,
            life,
            maxLife: life,
            size: this.randomRange(STYLE.particles.minSize, STYLE.particles.maxSize),
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
    randomRange(min, max)
    {
        return min + Math.random() * (max - min)
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
        const positions = track.pos
        const width = track.lineWidth * config.widthRatio
        const glowWidth = track.lineWidth * config.glowWidthRatio
        const visibleStart = Math.max(1, Math.floor(positions.length * config.minSegmentRatio))
        const chunkCount = 4
        const visibleCount = positions.length - visibleStart

        ctx.save()
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        ctx.globalCompositeOperation = 'lighter'
        ctx.strokeStyle = STYLE.colors.player.trail
        ctx.shadowColor = STYLE.colors.player.trail

        for (let i = 0; i < chunkCount; ++i)
        {
            const start = Math.max(0, visibleStart + Math.floor(visibleCount * i / chunkCount) - 1)
            const end = visibleStart + Math.floor(visibleCount * (i + 1) / chunkCount) + 1
            const ratio = (i + 1) / chunkCount
            const alpha = config.minAlpha + (config.maxAlpha - config.minAlpha) * ratio

            this.drawSmoothPath(positions, start, Math.min(positions.length, end), width, alpha, glowWidth)
        }

        if (positions.length > visibleStart + 1)
        {
            const tailStart = Math.max(1, positions.length - Math.floor((positions.length - visibleStart) * 0.28))
            this.drawSmoothPath(
                positions,
                tailStart - 1,
                positions.length,
                Math.max(track.lineWidth, width * 0.36),
                config.coreAlpha,
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
}

class ScreenEffects
{
    shouldApply()
    {
        return STYLE.features.screenEffects && QUALITY.screenShake
    }
    begin()
    {
        if (!this.shouldApply())
            return
    }
    end()
    {
        if (!this.shouldApply())
            return
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
        this.screenEffects = new ScreenEffects()
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
