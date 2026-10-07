const NO_SHAKE = Object.freeze({x: 0, y: 0})

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
    ninja.draw()
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

function drawUILayer(gameState)
{
    visualEffects.ui.draw(gameState)
}

function drawFpsCounterLayer(gameState)
{
    visualEffects.ui.drawFpsCounter(gameState)
}

function draw()
{
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
    drawBloomLayer(gameState)
    drawUILayer(gameState)
    drawFpsCounterLayer(gameState)

    visualEffects.screenEffects.end(gameState)

    ctx.scale(1 / scale[version], 1 / scale[version])

}
