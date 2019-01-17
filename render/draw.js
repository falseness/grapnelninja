 function draw()
{
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    
    ctx.scale(scale[version], scale[version])
    
    if (trackEnabled)
    {
        for (let i = 0; i < floors.length; ++i)
        {
            floors[i].drawTracks()
        }
        ninja.track.draw()
    }

    grapnel.draw()
    
    
    for (let i = 1; i < floors.length - 1; ++i)
    {
        floors[i].draw()
    }
    floors[0].draw()
    floors[floors.length - 1].draw()
    
    
    scoreText.draw()
    
    screen.draw()
    ninja.draw()
    
    menu.button.draw()
    
    ctx.scale(1 / scale[version], 1 / scale[version])
}
