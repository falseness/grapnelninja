const gravity = 0.05

function physics()
{
    ninja.speedY += gravity
    
    moveScreen()
    prelastBarrierBehindNinja()
    for (let i = 0; i < sprites.length; ++i)
    {
        sprites[i].move()
    }
    ninja.move()
    ninja.collision()
    
    grapnel.move()
    if (grapnel.throwed)
    {
        if (grapnel.speedX == 0 && grapnel.speedY == 0)
        {
            let ratio = grapnel.calcSpeed({x: grapnel.x, y: grapnel.y})
            ninja.speedX += grappleSpeed * ratio.cos
            ninja.speedY += grappleSpeed * ratio.sin
        }
        else if (!grapnel.grappled())
            grapnel.collision()
    }
    
}