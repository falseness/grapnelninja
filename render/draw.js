 function draw()
{
    visualEffects.background.draw()
    
    ctx.scale(scale[version], scale[version])
    
    const gameState = visualEffects.getGameState()
    visualEffects.screenEffects.begin(gameState)
    visualEffects.lightmap.clear(gameState)
    visualEffects.lightmap.draw(gameState)
    visualEffects.lightmap.composite(gameState)
    visualEffects.playerTrail.draw(gameState)
    visualEffects.particles.update(gameState)

    grapnel.draw()
    
    
    for (let i = 1; i < floors.length - 1; ++i)
    {
        floors[i].draw()
    }
    floors[0].draw()
    floors[floors.length - 1].draw()
    
    
    screen.draw()
    ninja.draw()
    visualEffects.particles.draw(gameState)
    
    visualEffects.ui.draw(gameState)
    visualEffects.screenEffects.end(gameState)
    
    ctx.scale(1 / scale[version], 1 / scale[version])
}
