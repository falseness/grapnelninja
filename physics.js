const GRAVITY = 0.00006297229219143577 * height

function physics()
{
    ninja.speedY += GRAVITY
    
    
   
    /*screen.shouldStartMoveByBarrier()*/
    screen.shouldStartMove()
    
    
    screen.move()
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
        else if (!grapnel.grappled)
            grapnel.collision()
    }
    deleteObstacles(obstacles)
}

/*
function calcFiniteAcceleration(v, v0, s)
{
    // s = (v^2 - v0^2) / (2 * a)
    //a = (v^2 - v0^2) / (2 * s)
    return ((Math.pow(v, 2) - Math.pow(v0, 2)) / (2 * s))
}
function calcPrimaryAcceleration(t, v0, s)
{
    // s = v0 * t + (a * t ^ 2) / 2
    // a = 2 * (s - v0 * t) / t ^ 2
    return (2 * (s - v0 * t) / Math.pow(t, 2))
}*/