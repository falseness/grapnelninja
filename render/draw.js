 function draw()
{
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    
    if (trackEnabled)
    {
        for (let i = 0; i < floors.length; ++i)
        {
            floors[i].drawTracks()
        }
        ninja.track.draw()
    }

    grapnel.draw()
    
    
    
    for (let i = 0; i < floors.length; ++i)
    {
        floors[i].draw()
    }
    scoreText.draw()
    
    screen.draw()
    ninja.draw()
}
