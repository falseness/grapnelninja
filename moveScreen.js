const whereMove = 0 * width

function moveScreen()
{
    let speed
    if (ninja.x > whereMove && ninja.speedX > 0 && !grapnel.grappled())
        speed = -ninja.speedX
    else
        speed = 0
    for (let i = sides.length; i < sprites.length; ++i)
    {
        sprites[i].speedX = speed
    }
    ninja.x += speed
}