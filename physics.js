const GRAVITY = 0.00006297229219143577 * height / Math.pow(cyclesPerTick, 2)

function physics()
{
    firstCycleInThisTick = true
    for (cycle = 0; cycle < cyclesPerTick - 1; ++cycle)
    {
        calcPhysics()
        firstCycleInThisTick = false
    }
    firstCycleInThisTick = true
    calcPhysics()
}
function calcPhysics()
{
    ninja.speedY += GRAVITY

        if (screen.shouldStartMove())
            screen.move()

        for (let i = 0; i < floors.length; ++i)
        {
            floors[i].moveElements()
        }

        ninja.move()

        grapnel.move()
        if (grapnel.throwed)
        {
            if (grapnel.isGrappled())
            {
                let ratio = grapnel.calcSpeed({x: grapnel.pos[grapnel.pos.length - 1][0], y: grapnel.pos[grapnel.pos.length - 1][1]})
                ninja.speedX += grappleSpeed * ratio.cos
                ninja.speedY += grappleSpeed * ratio.sin
            }
            grapnel.collision()
        }

        for (let i = 0; i < floors.length; ++i)
        {
            floors[i].deleteElements()
        }
}
