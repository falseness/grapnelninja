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

    screen.draw()
    grapnel.drawHook()
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

// The ball goes over particles, bloom and colour grade, so its dark centre and
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
    drawBackgroundLayer()

    ctx.scale(scale[version], scale[version])

    const gameState = visualEffects.getGameState()
    updateNeonPulse()
    visualEffects.screenEffects.begin(gameState)

    drawLightsLayer(gameState)
    drawBehindForegroundParticlesLayer(gameState)
    drawPlayerTrailLayer(gameState)
    drawWorldLayer()
    drawParticlesAndTrailsLayer(gameState)
    if (STYLE.features.bloom)
        drawBloomLayer(gameState)
    drawColorGradeLayer()
    drawPlayerLayer()
    drawUILayer(gameState)
    drawFpsCounterLayer(gameState)

    visualEffects.screenEffects.end(gameState)

    ctx.scale(1 / scale[version], 1 / scale[version])

}
