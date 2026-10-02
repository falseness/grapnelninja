// Safe respawn after a continue: the ninja reappears at rest at a chosen
// point inside the visible area, the lethal elements around and ahead of
// that point are removed, and RESPAWN_INVULNERABLE_MS of invulnerability
// covers the first moments of the resumed run.

const respawnScreenXRatio = 0.25
const respawnZoneBackRatio = 0.05
const respawnZoneAheadRatio = 0.15
const respawnClearanceRadii = 3

function isLethalElement(element)
{
    return element.collision === Element.prototype.collision
}
function isMovingElement(element)
{
    return element instanceof JumpingCube || element.speedX != 0 || element.speedY != 0
}
function getElementBounds(element)
{
    const points = element.getPoints()
    return {
        left: Math.min(...points.map(point => point.x)),
        right: Math.max(...points.map(point => point.x)),
        top: Math.min(...points.map(point => point.y)),
        bottom: Math.max(...points.map(point => point.y))
    }
}
function boundsIntersect(a, b)
{
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
}
// Cycles the safe zone has to stay clear for: the invulnerability plus a margin.
function getRespawnWindowCycles()
{
    return Math.ceil((RESPAWN_INVULNERABLE_MS + RESPAWN_SAFE_MARGIN_MS) / physicsStepMs) * cyclesPerTick
}
// Distance a ninja at rest falls over the window (gravity, speed cap).
function getRespawnFallDistance()
{
    const maxSpeed = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)
    const cycles = getRespawnWindowCycles()
    let speed = 0
    let distance = 0
    for (let i = 0; i < cycles; ++i)
    {
        speed = Math.min(speed + GRAVITY, maxSpeed)
        distance += speed
    }
    return distance
}
function getPlayFloors()
{
    return floors.filter(floor => !(floor instanceof SideFloor))
}
// Largest vertical gap free of static lethal elements over [left, right].
function findLargestLethalFreeGap(left, right, top, bottom)
{
    const intervals = []
    for (const floor of getPlayFloors())
    {
        for (const element of floor.elements)
        {
            if (!isLethalElement(element) || isMovingElement(element))
                continue
            const bounds = getElementBounds(element)
            if (bounds.right > left && bounds.left < right)
                intervals.push(bounds)
        }
    }
    intervals.sort((a, b) => a.top - b.top)

    let best = {top: top, bottom: top}
    let cursor = top
    for (const bounds of intervals)
    {
        if (bounds.top - cursor > best.bottom - best.top)
            best = {top: cursor, bottom: Math.min(bounds.top, bottom)}
        cursor = Math.max(cursor, bounds.bottom)
    }
    if (bottom - cursor > best.bottom - best.top)
        best = {top: cursor, bottom: bottom}
    return best
}
function chooseRespawnPoint()
{
    const visibleWidth = width / scale[version]
    const visibleHeight = height / scale[version]
    const radius = ninja.radius
    const clearance = respawnClearanceRadii * radius
    const playFloors = getPlayFloors()
    const bandTop = Math.max(Math.min(...playFloors.map(floor => floor.top)), -screen.y)
    const bandBottom = Math.min(Math.max(...playFloors.map(floor => floor.bottom)), -screen.y + visibleHeight)

    const x = -screen.x + respawnScreenXRatio * visibleWidth
    const gap = findLargestLethalFreeGap(x - clearance, x + clearance, bandTop, bandBottom)
    const fall = getRespawnFallDistance()
    // Bad mode lands on bouncing ground; classic falls into a lethal side,
    // so leave room for the whole fall over the window.
    const bottomBounces = floors.some(floor => floor instanceof SideFloor &&
        floor.top >= bandBottom - 1 && floor.elements.length && floor.elements[0] instanceof Trampoline)

    let y = gap.top + clearance
    if (!bottomBounces)
        y = Math.min(y, bandBottom - fall - clearance)
    y = Math.max(y, bandTop + clearance)

    const fallBottom = Math.min(y + fall, bandBottom)
    return {
        x: x,
        y: y,
        gap: gap,
        fall: fall,
        bottomBounces: bottomBounces,
        zone: {
            left: x - Math.max(clearance, respawnZoneBackRatio * visibleWidth),
            right: x + respawnZoneAheadRatio * visibleWidth,
            top: y - clearance,
            bottom: fallBottom + clearance
        },
        column: {left: x - clearance, right: x + clearance, top: y - clearance, bottom: fallBottom + clearance}
    }
}
// Removes the elements that could hit the ninja over the window: static
// lethal elements in the zone, moving lethal elements that can reach its
// columns, and trampolines in the fall column (they would throw it aside).
function clearRespawnZone(point)
{
    const cycles = getRespawnWindowCycles()
    const removed = []

    for (const floor of getPlayFloors())
    {
        const groupIds = new Set(floor.elements.map(element => element.generationGroupId))
        floor.elements = floor.elements.filter(function(element)
        {
            const bounds = getElementBounds(element)
            let hit = false
            if (isLethalElement(element) && isMovingElement(element))
            {
                const reach = Math.abs(element.speedX) * cycles
                hit = bounds.right + reach > point.zone.left && bounds.left - reach < point.zone.right
            }
            else if (isLethalElement(element))
                hit = boundsIntersect(bounds, point.zone)
            else if (element instanceof Trampoline)
                hit = boundsIntersect(bounds, point.column)

            if (hit)
                removed.push({type: element.constructor.name, bounds: bounds})
            return !hit
        })

        // Delete-driven floors (classic) keep a fixed group count: append one
        // group per fully removed group, with the usual spacing.
        if (version == 'bad' && floor.primaryElementsQuantity == 1)
            continue
        const remaining = new Set(floor.elements.map(element => element.generationGroupId))
        for (const id of groupIds)
        {
            if (remaining.has(id))
                continue
            let right = -screen.x
            for (const element of floor.elements)
                right = Math.max(right, element.getRightPointX())
            floor.generateElements(right)
        }
    }
    return removed
}
function respawnNinja()
{
    grapnel.setGrappled(false)
    grapnel.throwed = false
    grapnel.pos = []

    const point = chooseRespawnPoint()
    point.removed = clearRespawnZone(point)

    ninja.x = point.x
    ninja.y = point.y
    ninja.speedX = 0
    ninja.speedY = 0
    ninja.track.pos = []
    ninja.track.addPos(ninja.x, ninja.y, true)
    ninja.invulnerableMs = RESPAWN_INVULNERABLE_MS

    lastRespawn = point
    return point
}
let lastRespawn = null
