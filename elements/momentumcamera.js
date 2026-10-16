// Momentum camera: Screen with Y motion, driven by the course segment the
// ninja is in. A damped follow (follow()): right segments scroll right like
// bad mode; up/down segments keep the ninja vertically centred, moving only in
// the segment direction and stopping where the next right corridor is
// centred. The camera never goes back: what leaves the view behind the
// travel direction is deleted, and a ninja that leaves it there dies.
function segmentDirection(dir)
{
    return dir == 'right' ? {x: 1, y: 0} : dir == 'up' ? {x: 0, y: -1} : {x: 0, y: 1}
}

class MomentumScreen extends Screen
{
    constructor(course)
    {
        super(true, 0)
        this.course = course
        this.segmentIndex = 0
        // Direction of the last vertical segment entered: its far side of the
        // view stays behind through the following right segments
        this.verticalTravel = 0
        this.deletedBehind = 0
        // Damped follow state, world units per second (camera top-left)
        this.velocityX = this.velocityY = 0
        this.accelX = this.accelY = 0
        this.turnFrom = this.turnTo = segmentDirection('right')
        this.turnElapsedMs = 0
    }
    getViewHeight()
    {
        return height / scale[version]
    }
    getSegment()
    {
        return this.course.segment(this.segmentIndex)
    }
    // Moves to the next segment once the ninja passes the end of this one
    updateSegment()
    {
        for (;;)
        {
            const segment = this.getSegment()
            const passed = segment.dir == 'right' ? ninja.x >= segment.x1
                         : segment.dir == 'up' ? ninja.y <= segment.y1 : ninja.y >= segment.y1
            if (!passed)
                return
            ++this.segmentIndex
            const next = this.getSegment()
            if (next.dir != 'right')
                this.verticalTravel = next.dir == 'up' ? -1 : 1
            if (next.dir != segment.dir)
                this.startTurn(next.dir)
        }
    }
    shouldStartMove()
    {
        this.updateSegment()
        this.follow(physicsStepMs / cyclesPerTick)
        return this.speedX != 0 || this.speedY != 0
    }
    // screen.y of a camera centred on world y
    centredOn(y)
    {
        return -(y - this.getViewHeight() / 2)
    }
    // Look-ahead direction: eased from the previous segment direction to the
    // current one over turnMs (smoothstep), not a unit vector mid-turn
    getLookDirection()
    {
        const t = Math.min(1, this.turnElapsedMs / GAMEPLAY.momentumCamera.turnMs)
        const k = t * t * (3 - 2 * t)
        return {x: this.turnFrom.x + (this.turnTo.x - this.turnFrom.x) * k,
                y: this.turnFrom.y + (this.turnTo.y - this.turnFrom.y) * k}
    }
    startTurn(dir)
    {
        this.turnFrom = this.getLookDirection()
        this.turnTo = segmentDirection(dir)
        this.turnElapsedMs = 0
    }
    // Damped follow of the camera's top-left world corner (-x, -y), one
    // physics cycle of dtMs. The target is the base bad-mode x (ninja at
    // borderX) / the vertical TASK-005 target, both shifted by lookAhead along
    // the eased direction. The desired velocity is a feed-forward of the
    // ninja's speed along the segment plus a braking-curve pull on the target
    // error; the camera velocity moves toward it with acceleration clamped to
    // maxAccel and its change clamped to maxJerk. The camera never goes back:
    // x only grows, y only moves in the last vertical direction.
    follow(dtMs)
    {
        const options = GAMEPLAY.momentumCamera
        const view = this.getViewHeight()
        const dt = dtMs / 1000
        const maxAccel = options.maxAccel * view, maxJerk = options.maxJerk * view
        const brakeAccel = 0.5 * maxAccel
        const brake = e => Math.sign(e) * Math.min(options.stiffness * Math.abs(e),
                                                   Math.sqrt(2 * brakeAccel * Math.abs(e)))
        const stopSpeed = d => Math.sqrt(2 * brakeAccel * Math.max(0, d))
        this.turnElapsedMs += dtMs
        const segment = this.getSegment()
        const look = this.getLookDirection()
        const lookAhead = options.lookAhead * view
        const camX = -this.x, camY = -this.y
        // Ninja speed along the segment, world units per second
        const seg = segmentDirection(segment.dir)
        const along = Math.max(0, ninja.speedX * seg.x + ninja.speedY * seg.y) / dt

        let wantX = 0
        const targetX = ninja.x - this.borderX + lookAhead * look.x
        if (targetX >= camX)
            wantX = look.x * along + brake(targetX - camX)

        let wantY = 0
        if (this.verticalTravel)
        {
            // Vertical segments: ninja centred, up to where the next right
            // corridor is centred; right segments: the corridor centre
            const stop = -this.centredOn(segment.dir == 'right' ? segment.y0 : segment.y1)
            let targetY = segment.dir == 'right' ? stop : ninja.y - view / 2 + lookAhead * look.y
            const travel = this.verticalTravel
            targetY = travel < 0 ? Math.max(targetY, stop) : Math.min(targetY, stop)
            if ((targetY - camY) * travel >= 0)
                wantY = (segment.dir == 'right' ? 0 : look.y * along) + brake(targetY - camY)
            // Never past the stop: slow down in time
            wantY = travel < 0 ? Math.max(wantY, -stopSpeed(camY - stop))
                               : Math.min(wantY, stopSpeed(stop - camY))
        }

        // Acceleration toward the wanted velocity, limited by maxAccel, its
        // change by maxJerk; the sqrt term lets it reach zero in time
        const dvX = wantX - this.velocityX, dvY = wantY - this.velocityY
        const dv = Math.hypot(dvX, dvY)
        let ax = 0, ay = 0
        if (dv > 0)
        {
            const a = Math.min(dv / dt, Math.sqrt(maxJerk * dv), maxAccel, 4 * options.stiffness * dv)
            ax = dvX / dv * a
            ay = dvY / dv * a
        }
        const jx = ax - this.accelX, jy = ay - this.accelY
        const j = Math.hypot(jx, jy)
        if (j > maxJerk * dt)
        {
            ax = this.accelX + jx / j * maxJerk * dt
            ay = this.accelY + jy / j * maxJerk * dt
        }
        const a = Math.hypot(ax, ay)
        if (a > maxAccel)
        {
            ax *= maxAccel / a
            ay *= maxAccel / a
        }
        let vx = this.velocityX + ax * dt, vy = this.velocityY + ay * dt
        // Never back
        if (vx < 0)
            vx = ax = 0
        if (vy * this.verticalTravel < 0 || !this.verticalTravel)
            vy = ay = 0
        this.accelX = ax; this.accelY = ay
        this.velocityX = vx; this.velocityY = vy
        this.speedX = -vx * dt
        this.speedY = -vy * dt
    }
    // A box (world coordinates) fully out of view on the vertical side left behind
    isBoxBehind(top, bottom, margin)
    {
        if (this.verticalTravel < 0)
            return top + this.y > this.getViewHeight() + margin
        if (this.verticalTravel > 0)
            return bottom + this.y < -margin
        return false
    }
    hasLeftBehind(who)
    {
        return this.isBoxBehind(who.y - who.radius, who.y + who.radius, 0)
    }
    // Removes whole generation groups of floor whose elements are all behind
    // vertically. keepLast keeps the newest group, the floor replenishes from it.
    deleteBehind(floor, keepLast)
    {
        if (!this.verticalTravel || !floor.elements.length)
            return
        const margin = GAMEPLAY.momentumCamera.deletionMarginHeightRatio * this.getViewHeight()
        const elements = floor.elements
        const lastGroup = elements[elements.length - 1].generationGroupId
        const kept = new Set()
        for (const element of elements)
        {
            const box = getElementCullBox(element)
            if (!box || !this.isBoxBehind(box.top, box.bottom, margin) ||
                (keepLast && element.generationGroupId === lastGroup))
                kept.add(element.generationGroupId === undefined ? element : element.generationGroupId)
        }
        const remaining = elements.filter(element =>
            kept.has(element.generationGroupId === undefined ? element : element.generationGroupId))
        this.deletedBehind += elements.length - remaining.length
        floor.elements = remaining
    }
}

// The bad obstacle floor in momentum, also deleting what the camera leaves
// behind vertically
class MomentumObstacleFloor extends Floor
{
    deleteElements()
    {
        super.deleteElements()
        screen.deleteBehind(this, true)
    }
}
