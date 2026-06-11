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

    for (let i = 1; i < floors.length - 1; ++i)
    {
        floors[i].draw()
    }
    floors[0].draw()
    floors[floors.length - 1].draw()

    screen.draw()
    ninja.draw()
}

function drawParticlesAndTrailsLayer(gameState)
{
    visualEffects.playerTrail.draw(gameState)
    visualEffects.particles.update(gameState)
    visualEffects.particles.draw(gameState)
    visualEffects.screenEffects.draw(gameState)
}

function drawUILayer(gameState)
{
    visualEffects.ui.draw(gameState)
}

function draw()
{
    drawBackgroundLayer()

    ctx.scale(scale[version], scale[version])

    const gameState = visualEffects.getGameState()
    visualEffects.screenEffects.begin(gameState)

    drawLightsLayer(gameState)
    drawWorldLayer()
    drawParticlesAndTrailsLayer(gameState)
    drawUILayer(gameState)

    visualEffects.screenEffects.end(gameState)

    ctx.scale(1 / scale[version], 1 / scale[version])
}
