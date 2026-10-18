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

    screen.leftWall.draw()
    if (screen.backWall)
        screen.backWall.draw()
    if (version == 'momentum')
        drawMomentumOutsideMask()
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

// Momentum speed streaks behind the ninja (MOMENTUM_FX only)
function drawSpeedStreaksLayer()
{
    visualEffects.lightmap.drawSpeedStreaks(ctx)
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

// Foreground crystal silhouettes in front of the world and the player,
// under the HUD (momentum lighting only)
function drawForegroundLayer()
{
    FOREGROUND.draw()
}

// Colour grade and vignette over the world, under the player and HUD
function drawColorGradeLayer()
{
    visualEffects.colorGrade.draw()
}

// Blue-hit colour fringe over everything drawn so far (momentum lighting
// only, a short while after a blue touch); the HUD boxes are left out
const fringeHudBoxes = []
function drawBlueFringeLayer()
{
    const effects = visualEffects.screenEffects
    if (effects.getBlueFringe(performance.now()) <= 0)
        return
    collectHudBoxes(fringeHudBoxes)
    effects.drawBlueFringe(performance.now(), fringeHudBoxes)
}

// The HUD's boxes this frame in canvas px, padded by its glow: the HUD is
// laid out (LAYOUT_PROBE) into the warmGlowSprites scratch canvas
function collectHudBoxes(out)
{
    out.length = 0
    if (!visualEffects.ui.shouldDraw())
        return
    if (!warmGlowSprites.ctx)
        warmGlowSprites.ctx = document.createElement('canvas').getContext('2d')
    const mainCtx = ctx
    const scratch = warmGlowSprites.ctx
    const boxes = LAYOUT_PROBE.boxes
    scratch.setTransform(mainCtx.getTransform())
    LAYOUT_PROBE.boxes = []
    ctx = scratch
    try
    {
        scoreText.draw()
        menu.button.draw()
        const k = canvas.width / getCanvasCssRect().width
        const pad = 2 * (STYLE.ui.textShadowBlur + STYLE.ui.hudExtraShadowBlur) * canvas.height / height + 2
        for (const b of LAYOUT_PROBE.boxes)
        {
            const x0 = Math.max(0, Math.floor(b.x * k - pad))
            const y0 = Math.max(0, Math.floor(b.y * k - pad))
            out.push([x0, y0, Math.ceil((b.x + b.width) * k + pad) - x0, Math.ceil((b.y + b.height) * k + pad) - y0])
        }
    }
    finally
    {
        ctx = mainCtx
        LAYOUT_PROBE.boxes = boxes
    }
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
    drawSpeedStreaksLayer()
    if (STYLE.features.bloom)
        drawBloomLayer(gameState)
    drawPlayerGlowLayer(gameState)
    drawColorGradeLayer()
    drawPlayerLayer()
    drawForegroundLayer()
    drawBlueFringeLayer()
    if (TUTORIAL_HINT.visible)
        drawTutorialHintLayer()
    drawUILayer(gameState)
    drawFpsCounterLayer(gameState)

    visualEffects.screenEffects.end(gameState)

    ctx.scale(1 / scale[version], 1 / scale[version])

}
