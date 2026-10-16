// How long the one-time Grapple Over range upgrade notice stays on the HUD
const CLIMB_RANGE_NOTICE_MS = 3000
const GRAVITY = screenHeightPercent(GAMEPLAY.gravityHeightPercent) / Math.pow(cyclesPerTick, 2)

function physics()
{
    if (version === 'grapple_over' && (menu.gamePaused || floors[0].climbStats.completed || hostPaused)) return
    firstCycleInThisTick = true
    for (cycle = 0; cycle < cyclesPerTick - 1; ++cycle)
    {
        calcPhysics()
        firstCycleInThisTick = false
    }
    firstCycleInThisTick = true
    calcPhysics()
    if (version === 'grapple_over' && !continueOffer.visible) floors[0].applyDragZones(ninja)
    if (version === 'grapple_over' && !continueOffer.visible) screen.trackGrappleOver()
    if (version === 'grapple_over') PROGRESS.climbTick()
    ninja.tickInvulnerability(physicsStepMs)
}
function calcPhysics()
{
    if (version === 'grapple_over' && floors[0].climbStats.completed) return
    // A continue offer freezes the run until the player answers it
    if (continueOffer.visible)
        return

    if (version === 'grapple_over')
        ninja.hazardCooldownMs = Math.max(0, ninja.hazardCooldownMs - physicsStepMs / cyclesPerTick)

    ninja.speedY += GRAVITY

    if (version !== 'grapple_over' && screen.shouldStartMove())
        screen.move()

    for (let i = 0; i < floors.length; ++i)
    {
        floors[i].moveElements()
    }

    if (screen.leftWall) screen.leftWall.update(screen)
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

    if (version === 'grapple_over')
    {
        const world = floors[0], stats = world.climbStats
        stats.elapsedActiveMs += physicsStepMs / cyclesPerTick
        stats.currentHeight = world.level.spawn.y - ninja.y
        stats.maxHeight = Math.max(stats.maxHeight, stats.currentHeight)
        world.rangeNoticeMs = Math.max(0, world.rangeNoticeMs - physicsStepMs / cyclesPerTick)
        const upgrade = world.level.sections.find(s => s.id === MODE_DEFINITIONS.grapple_over.rangeUpgradeSection)
        const band = upgrade?.band
        if (!world.rangeUpgraded && band && ninja.x >= band.left && ninja.x <= band.right &&
            ninja.y >= band.top && ninja.y <= band.bottom)
        {
            world.rangeUpgraded = true
            world.rangeNoticeMs = CLIMB_RANGE_NOTICE_MS
        }
        const finish = world.level.finish
        if (finish && ninja.x >= finish.left && ninja.x <= finish.right &&
            ninja.y >= finish.top && ninja.y <= finish.bottom) CLIMB_UI.complete()
    }

    for (let i = 0; i < floors.length; ++i)
    {
        floors[i].replenishElements()
        floors[i].deleteElements()
    }
}
