const GRAVITY = screenHeightPercent(GAMEPLAY.gravityHeightPercent) / Math.pow(cyclesPerTick, 2)

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
    // A continue offer freezes the run until the player answers it
    if (continueOffer.visible)
        return

    ninja.speedY += GRAVITY

    if (screen.shouldStartMove())
        screen.move()

    for (let i = 0; i < floors.length; ++i)
    {
        floors[i].moveElements()
    }

    ninja.move()
    if (continueOffer.visible)
        return

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
        floors[i].replenishElements()
        floors[i].deleteElements()
    }
}
