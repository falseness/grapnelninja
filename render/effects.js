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
    constructor()
    {
        this.particles = []
    }
    shouldDraw()
    {
        return STYLE.features.particles && QUALITY.particles
    }
    update()
    {
        if (!this.shouldDraw())
            return
    }
    draw()
    {
        if (!this.shouldDraw())
            return
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
        gameState.ninja.track.draw()
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
        this.particles = new ParticleSystem()
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
