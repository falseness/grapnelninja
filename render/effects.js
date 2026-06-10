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
}

class LightmapRenderer
{
    constructor()
    {
        this.enabled = true
    }
    shouldDraw()
    {
        return this.enabled && STYLE.features.lightmap && QUALITY.lightmap
    }
    clear()
    {

    }
    draw()
    {
        if (!this.shouldDraw())
            return
    }
    composite()
    {
        if (!this.shouldDraw())
            return
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
        this.lightmap = new LightmapRenderer()
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
