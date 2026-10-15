const NO_SHAKE = Object.freeze({x: 0, y: 0})
// Counts game draw() calls: per-frame layouts shared by several layers
// (ambient motes and their bloom copy) are keyed on it
let drawFrameId = 0

function drawBackgroundLayer()
{
    visualEffects.background.draw()
}

function drawLightsLayer(gameState)
{
    visualEffects.lightmap.clear(gameState)
    visualEffects.lightmap.draw(gameState)
    visualEffects.lightmap.composite(gameState)
}

function drawWorldLayer()
{
    drawAcquisitionCircle()
    grapnel.draw()

    // All back faces first, so no extrusion covers a neighbour's front face
    if (STYLE.features.extrusion)
        for (let i = 1; i < floors.length - 1; ++i)
        {
            floors[i].drawExtrusions()
        }

    for (let i = 1; i < floors.length - 1; ++i)
    {
        floors[i].draw()
    }
    floors[0].draw()
    floors[floors.length - 1].draw()

    if (screen.leftWall) screen.leftWall.draw()
    screen.draw()
    grapnel.drawHook()
}

// Distance guide only: obstacles still determine whether a hook can attach.
function drawAcquisitionCircle()
{
    if (version !== 'grapple_over' || !runInProgress)
        return

    ctx.save()
    ctx.globalAlpha = 0.20
    ctx.globalCompositeOperation = 'source-over'
    ctx.strokeStyle = '#00ffff'
    ctx.shadowBlur = 0
    ctx.shadowOffsetX = ctx.shadowOffsetY = 0
    ctx.setLineDash([])
    ctx.lineWidth = width / getCanvasCssRect().width / scale[version]
    ctx.beginPath()
    ctx.arc(ninja.x + screen.x, ninja.y + screen.y,
        MODE_DEFINITIONS.grapple_over.acquisitionRadius, 0, Math.PI * 2)
    ctx.stroke()
    ctx.restore()
}

function drawPlayerTrailLayer(gameState)
{
    visualEffects.playerTrail.draw(gameState)
}

function drawBehindForegroundParticlesLayer(gameState)
{
    visualEffects.particles.update(gameState)
    visualEffects.particles.drawAmbientMotes()
    visualEffects.particles.drawBehindForeground()
}

function drawParticlesAndTrailsLayer(gameState)
{
    visualEffects.particles.draw(gameState)
    visualEffects.screenEffects.draw(gameState)
}

// Glow halo of the emissive shapes, added before the HUD so text stays crisp
function drawBloomLayer(gameState)
{
    const screenEffects = visualEffects.screenEffects
    visualEffects.bloom.draw(gameState, screenEffects.isShaking ? screenEffects.shakeOffset : NO_SHAKE)
}

function drawPlayerGlowLayer(gameState)
{
    const effects = visualEffects.screenEffects
    visualEffects.playerGlow.draw(gameState, effects.isShaking ? effects.shakeOffset : NO_SHAKE)
}

// The ball goes over particles, bloom and colour grade, so its blue body and
// cyan ring stay readable at the small pre-overhaul size
function drawPlayerLayer()
{
    ninja.draw()
}

// Colour grade and vignette over the world, under the player and HUD
function drawColorGradeLayer()
{
    visualEffects.colorGrade.draw()
}

// First-run control hint: above the world and the player, under the HUD
function drawTutorialHintLayer()
{
    TUTORIAL_HINT.draw(ctx, TUTORIAL_HINT.alpha, TUTORIAL_HINT.time)
}

function drawUILayer(gameState)
{
    visualEffects.ui.draw(gameState)
}

function drawFpsCounterLayer(gameState)
{
    visualEffects.ui.drawFpsCounter(gameState)
}

// Run start: draws the HUD and the ground strips once into a scratch canvas
// in the game transform, so their glow sprites (render/glowsprites.js) are
// built here and the first frames do no shadowBlur work
function warmGlowSprites()
{
    if (!warmGlowSprites.ctx)
        warmGlowSprites.ctx = document.createElement('canvas').getContext('2d')

    const mainCtx = ctx
    const scratch = warmGlowSprites.ctx
    const boxes = LAYOUT_PROBE.boxes
    scratch.setTransform(mainCtx.getTransform())
    scratch.scale(scale[version], scale[version])
    LAYOUT_PROBE.boxes = null
    ctx = scratch
    try
    {
        if (visualEffects.ui.shouldDraw())
        {
            scoreText.draw()
            menu.button.draw()
        }
        warmGroundGlowSprites()
    }
    finally
    {
        ctx = mainCtx
        LAYOUT_PROBE.boxes = boxes
    }
}

function draw()
{
    ++drawFrameId
    BACKDROP.observe(performance.now())
    // Slow canvases: background, light spill and mote glow go into the
    // reduced-resolution backdrop (render/backdrop.js)
    const backdrop = BACKDROP.begin()
    drawBackgroundLayer()

    ctx.scale(scale[version], scale[version])

    const gameState = visualEffects.getGameState()
    updateNeonPulse()
    visualEffects.screenEffects.begin(gameState)
    if (backdrop)
        BACKDROP.syncTransform()

    drawLightsLayer(gameState)
    if (backdrop)
        BACKDROP.end()
    drawBehindForegroundParticlesLayer(gameState)
    drawPlayerTrailLayer(gameState)
    drawWorldLayer()
    drawParticlesAndTrailsLayer(gameState)
    if (STYLE.features.bloom)
        drawBloomLayer(gameState)
    drawPlayerGlowLayer(gameState)
    drawColorGradeLayer()
    drawPlayerLayer()
    if (TUTORIAL_HINT.visible && !(version === 'grapple_over' && menu.gamePaused))
        drawTutorialHintLayer()
    drawUILayer(gameState)
    drawFpsCounterLayer(gameState)

    visualEffects.screenEffects.end(gameState)

    ctx.scale(1 / scale[version], 1 / scale[version])
    if (version === 'grapple_over' && floors[0].climbStats.completed) CLIMB_UI.drawMenu()

}
