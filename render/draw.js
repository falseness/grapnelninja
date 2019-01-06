 function draw()
{
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ninja.line.draw()
    grapnel.draw()
    
    
    
    for (let i = 0; i < floors.length; ++i)
    {
        floors[i].draw()
    }
    scoreText.draw()
    
    screen.draw()
    ninja.draw()
}
