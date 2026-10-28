// How long the one-time Grapple Over range upgrade notice stays on the HUD
const CLIMB_RANGE_NOTICE_MS = 3000
const GRAVITY = screenHeightPercent(GAMEPLAY.gravityHeightPercent) / Math.pow(cyclesPerTick, 2)
// Grapple Over: falling strictly below this many world units under the spawn
// returns the player to the spawn without restarting the run.
const CLIMB_FALL_RECOVERY_DEPTH = 1500
// Grapple Over: a fresh start (first run or restart) launches the ninja
// upward from the spawn so its no-input free-flight apex is this high.
const SPAWN_LAUNCH_RISE = 270

// Apex rise of a no-input flight starting at speedY = -speed, integrated
// exactly as calcPhysics/Ninja.move do it (gravity, speed cap, then move).
function spawnLaunchRise(speed)
{
    const maxSpeed = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)
    let speedY = -speed, rise = 0
    for (;;)
    {
        speedY = Math.max(-maxSpeed, Math.min(maxSpeed, speedY + GRAVITY))
        if (speedY >= 0) return rise
        rise -= speedY
    }
}
// Upward speed whose no-input apex is SPAWN_LAUNCH_RISE above the spawn.
function getSpawnLaunchSpeed()
{
    let low = 0, high = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)
    for (let i = 0; i < 60; ++i)
    {
        const mid = (low + high) / 2
        if (spawnLaunchRise(mid) < SPAWN_LAUNCH_RISE) low = mid
        else high = mid
    }
    return (low + high) / 2
}

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

    // Release in the step of entry, before this step's rope pull or acquisition.
    if (version === 'grapple_over') floors[0].applyNoGrappleZones(ninja)
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
        // Before the update, so a new run's buckets start from its saved best height
        climbDesignRun(stats)
        stats.maxHeight = Math.max(stats.maxHeight, stats.currentHeight)
        reportClimbHeight(stats)
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

// Count a Grapple Over hook: a transition into the grappled state, not a
// throw or a rope wrap. Display only; never read by physics.
function countClimbGrapple(wasGrappled)
{
    if (version !== 'grapple_over' || wasGrappled || !floors[0]?.climbStats) return
    floors[0].climbStats.grapples++
    const section = climbDesignRun(floors[0].climbStats).section = CLIMB_UI.currentSection().id
    TELEMETRY.mark('grapple', section)
}

// Design telemetry of the run, never saved: the last 500-unit best height
// bucket reported and the section of the last grapple catch, which the next
// fall is counted against. A new climbStats object is a new or restored run;
// a restored run starts from its saved best height, so no bucket repeats.
const CLIMB_HEIGHT_BUCKET = 500
const climbDesign = {stats: null, bucket: 0, section: null}
function climbDesignRun(stats)
{
    if (climbDesign.stats !== stats)
        Object.assign(climbDesign, {stats, bucket: Math.floor(stats.maxHeight / CLIMB_HEIGHT_BUCKET), section: null})
    return climbDesign
}

// One design event per best height bucket reached for the first time this run
function reportClimbHeight(stats)
{
    const run = climbDesignRun(stats), bucket = Math.floor(stats.maxHeight / CLIMB_HEIGHT_BUCKET)
    while (run.bucket < bucket)
    {
        run.bucket++
        ANALYTICS.design('best_height:' + floors[0].grapnelMode, run.bucket * CLIMB_HEIGHT_BUCKET)
    }
}

// Teleport a fallen Grapple Over player to the spawn and launch it upward
// like a fresh start. Time, best height, upgrades and the world (movers
// included) are kept; only the player, grapple, gameplay input ownership and
// camera are reset.
function recoverClimbFall()
{
    const world = floors[0], spawn = world.level.spawn
    // The fall counts against the section of the last catch (the spawn
    // section when there was none since the launch)
    const run = climbDesignRun(world.climbStats)
    const fallSection = run.section ?? world.level.sections[0].id
    ANALYTICS.design('fall:' + fallSection)
    TELEMETRY.mark('fall', fallSection)
    run.section = null
    ninja.x = spawn.x
    ninja.y = spawn.y
    ninja.speedX = 0
    ninja.speedY = -getSpawnLaunchSpeed()
    ninja.track.pos = []
    ninja.track.addPos(ninja.x, ninja.y, true)
    Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,
        aim: null, clip: null, traveled: 0, speedX: 0, speedY: 0})
    // A press held through the fall cannot grapple again until it is released.
    gameplayPressOwned = false
    stalePress = pressHeld
    world.climbStats.currentHeight = 0
    world.climbStats.falls++
    LONG_FALL.restartTracking()
    screen.trackGrappleOver(true)
    // The run's first recovery in single mode pauses on the double grapnel
    // offer; the launch above plays once it is answered.
    const offer = !world.doubleOfferShown && world.grapnelMode !== 'double'
    world.doubleOfferShown = true
    PROGRESS.flushClimb()
    if (offer) CLIMB_UI.offerDouble()
}
