// How long the one-time Grapple Over range upgrade notice stays on the HUD
const CLIMB_RANGE_NOTICE_MS = 3000
const GRAVITY = screenHeightPercent(GAMEPLAY.gravityHeightPercent) / Math.pow(cyclesPerTick, 2)
// Grapple Over: falling strictly below this many world units under the spawn
// returns the player to the spawn without restarting the run.
const CLIMB_FALL_RECOVERY_DEPTH = 1500

function physics()
{
    if (version === 'grapple_over' && (menu.gamePaused || floors[0].climbStats.completed || hostPaused)) return
    firstCycleInThisTick = true
    // A fall recovery ends the tick at the spawn, so the recovery step is observable.
    let recovered = false
    for (cycle = 0; cycle < cyclesPerTick - 1 && !recovered; ++cycle)
    {
        recovered = calcPhysics()
        firstCycleInThisTick = false
    }
    firstCycleInThisTick = true
    if (!recovered) calcPhysics()
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
        LONG_FALL.step()
        if (stats.currentHeight < -CLIMB_FALL_RECOVERY_DEPTH)
        {
            recoverClimbFall()
            return true
        }
        world.rangeNoticeMs = Math.max(0, world.rangeNoticeMs - physicsStepMs / cyclesPerTick)
        const upgrade = world.level.sections.find(s => s.id === grappleOverProfile().rangeUpgradeSection)
        const band = upgrade?.rangeUpgradeZone ?? upgrade?.band
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

// Teleport a fallen Grapple Over player to the spawn. Time, best height,
// upgrades and the world (movers included) are kept; only the player,
// grapple, gameplay input ownership and camera are reset.
function recoverClimbFall()
{
    const world = floors[0], spawn = world.level.spawn
    ninja.x = spawn.x
    ninja.y = spawn.y
    ninja.speedX = ninja.speedY = 0
    ninja.track.pos = []
    ninja.track.addPos(ninja.x, ninja.y, true)
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,
        aim: null, clip: null, traveled: 0, speedX: 0, speedY: 0})
    // A press held through the fall cannot grapple again until it is released.
    gameplayPressOwned = false
    stalePress = pressHeld
    world.climbStats.currentHeight = 0
    LONG_FALL.restartTracking()
    screen.trackGrappleOver(true)
    PROGRESS.flushClimb()
}
