// Momentum camera: Screen with Y motion, driven by the course segment the
// ninja is in. A damped follow (follow()): right segments scroll right like
// bad mode; up/down segments keep the ninja vertically centred, moving only in
// the segment direction and stopping where the next right corridor is
// centred. The camera never goes back: what leaves the view behind the
// travel direction is deleted; a camera-owned BackWall (sprites/backwall.js)
// bounces a ninja falling back on that side.
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
        // Bouncy boundary on that side (sprites/backwall.js)
        this.backWall = new BackWall(this)
        this.deletedBehind = 0
        // Damped follow state, world units per second (camera top-left)
        this.velocityX = this.velocityY = 0
        this.accelX = this.accelY = 0
        this.turnFrom = this.turnTo = segmentDirection('right')
        this.turnElapsedMs = 0
        // Peak camera speed since the last turn, and that peak at the last
        // turn (the catch-up limit after it)
        this.peakSpeed = this.turnPeakSpeed = 0
    }
    getViewHeight()
    {
        return height / scale[version]
    }
    getSegment()
    {
        return this.course.segment(this.segmentIndex)
    }
    // Whether the ninja has left the segment for the next one. On a straight
    // join, past its end; on a turn, out of the corner box (the overlap of
    // the two corridors around the join) into the next corridor, so a ninja
    // cutting the corner does not turn the camera early; or, in the box,
    // once it is closer than holdMargin to the view edge ahead along the
    // next axis (holding on would let it run out of the view).
    hasPassed(segment, next)
    {
        if (next.dir == segment.dir)
            return segment.dir == 'right' ? ninja.x >= segment.x1
                 : segment.dir == 'up' ? ninja.y <= segment.y1 : ninja.y >= segment.y1
        const halfWidth = momentumSegmentHalfWidth(segment), nextHalfWidth = momentumSegmentHalfWidth(next)
        const out = next.dir == 'right' ? ninja.x >= segment.x1 + halfWidth
                  : next.dir == 'up' ? ninja.y <= segment.y1 - halfWidth : ninja.y >= segment.y1 + halfWidth
        const inBox = segment.dir == 'right' ? ninja.x >= segment.x1 - nextHalfWidth
                    : segment.dir == 'up' ? ninja.y <= segment.y1 + nextHalfWidth : ninja.y >= segment.y1 - nextHalfWidth
        return out || inBox && this.nextAxisMargin(next.dir) < GAMEPLAY.momentumCamera.holdMargin
    }
    // The ninja's distance to the view edge ahead along dir, share of the view
    nextAxisMargin(dir)
    {
        const view = this.getViewHeight(), viewW = width / scale[version]
        return dir == 'right' ? (viewW - this.x - ninja.x) / viewW
             : dir == 'up' ? (ninja.y + this.y) / view : (view - this.y - ninja.y) / view
    }
    // Moves to the next segment once the ninja passes the end of this one
    updateSegment()
    {
        for (;;)
        {
            const segment = this.getSegment()
            if (!this.hasPassed(segment, this.course.segment(this.segmentIndex + 1)))
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
        this.turnPeakSpeed = this.peakSpeed
        this.peakSpeed = 0
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
        let targetX = ninja.x - this.borderX + lookAhead * look.x
        // In a vertical segment, or a right one leading into one, the shaft's
        // left wall stays in view: x stops short of its face like y does
        const capX = this.getShaftCapX()
        targetX = Math.min(targetX, capX)
        if (targetX >= camX)
            wantX = look.x * along + brake(targetX - camX)
        // The y braking curve, aimed a buffer short of the cap: the jerk
        // limited acceleration trails the curve and runs on a little. The
        // buffer shrinks with the x speed below the curve's speed at it, so
        // a slow camera creeps on to the cap (the view centred on the shaft).
        const buffer = options.shaftBrakeBufferHeightRatio * view
        const bufferNow = buffer * Math.min(1, Math.max(0, this.velocityX) / (options.stiffness * buffer))
        wantX = Math.min(wantX, brake(Math.max(0, capX - bufferNow - camX)))
        // Right after a turn the camera along the next axis is no faster
        // than it was along the previous segment (or the ninja, its full
        // speed: in the box it may still run along the old axis): a camera
        // held in the corner box catches up the ninja's lead later, not as a
        // burst at the turn
        const catchUp = this.turnElapsedMs >= options.turnCatchUpMs ? Infinity
                      : options.turnCatchUpSpeedRatio * Math.max(this.turnPeakSpeed, Math.hypot(ninja.speedX, ninja.speedY) / dt)
        if (segment.dir == 'right')
            wantX = Math.min(wantX, catchUp)

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
            // Never past the stop: slow down in time, on a curve aimed the
            // same speed-scaled buffer short of it as x (the jerk limited
            // braking trails the curve), so a ninja climbing on through the
            // corner box does not carry the camera past the corridor centre
            const bufferY = buffer * Math.min(1, Math.abs(this.velocityY) / (options.stiffness * buffer))
            wantY = travel < 0 ? Math.max(wantY, -stopSpeed(camY - stop - bufferY))
                               : Math.min(wantY, stopSpeed(stop - camY - bufferY))
            if (segment.dir != 'right')
                wantY = Math.max(-catchUp, Math.min(catchUp, wantY))
        }

        // Acceleration toward the wanted velocity, limited by maxAccel, its
        // change by maxJerk; the sqrt term lets it reach zero in time. An
        // axis braking (wanted velocity against its motion: the old axis
        // stopping at its cap at a turn) gets its share first, the other one
        // the rest: the next axis starting hard as the ninja leaves a corner
        // box must not make the old one overrun its cap.
        const dvX = wantX - this.velocityX, dvY = wantY - this.velocityY
        const accelFor = d => Math.min(d / dt, Math.sqrt(maxJerk * d), maxAccel, 4 * options.stiffness * d)
        const brakeX = dvX * this.velocityX < 0, brakeY = dvY * this.velocityY < 0
        const dv = Math.hypot(dvX, dvY)
        let ax = 0, ay = 0
        if (brakeX != brakeY)
        {
            const first = accelFor(Math.abs(brakeX ? dvX : dvY))
            const rest = Math.min(accelFor(Math.abs(brakeX ? dvY : dvX)), Math.sqrt(maxAccel * maxAccel - first * first))
            ax = Math.sign(dvX) * (brakeX ? first : rest)
            ay = Math.sign(dvY) * (brakeX ? rest : first)
        }
        else if (dv > 0)
        {
            const a = accelFor(dv)
            ax = dvX / dv * a
            ay = dvY / dv * a
        }
        const jx = ax - this.accelX, jy = ay - this.accelY
        const j = Math.hypot(jx, jy)
        const maxJ = maxJerk * dt
        if (j > maxJ)
        {
            // An axis easing its acceleration off (toward a stop) gets its
            // share first, the other one the rest: a camera x starting from
            // rest at a shaft exit must not make y overrun its stop. Else
            // the braking axis does.
            const easeX = jx * this.accelX < 0, easeY = jy * this.accelY < 0
            const firstX = easeX != easeY ? easeX : brakeX != brakeY ? brakeX : null
            if (firstX !== null)
            {
                const first = Math.max(-maxJ, Math.min(maxJ, firstX ? jx : jy))
                const rest = Math.sign(firstX ? jy : jx) * Math.sqrt(maxJ * maxJ - first * first)
                ax = this.accelX + (firstX ? first : rest)
                ay = this.accelY + (firstX ? rest : first)
            }
            else
            {
                ax = this.accelX + jx / j * maxJ
                ay = this.accelY + jy / j * maxJ
            }
        }
        const a = Math.hypot(ax, ay)
        if (a > maxAccel)
        {
            ax *= maxAccel / a
            ay *= maxAccel / a
        }
        let vx = this.velocityX + ax * dt, vy = this.velocityY + ay * dt
        // Last resort, inert when braking in time: never past the shaft cap
        if (camX + vx * dt > capX)
            vx = Math.max(0, (capX - camX) / dt)
        // Never back
        if (vx < 0)
            vx = ax = 0
        if (vy * this.verticalTravel < 0 || !this.verticalTravel)
            vy = ay = 0
        this.accelX = ax; this.accelY = ay
        this.velocityX = vx; this.velocityY = vy
        this.peakSpeed = Math.max(this.peakSpeed, Math.hypot(vx, vy))
        this.speedX = -vx * dt
        this.speedY = -vy * dt
    }
    // Largest camera x (-screen.x): the view centred on the current vertical
    // segment, or on the next one from a right segment, where it shows only
    // the shaft and its walls (momentumShaftHalfWidth); Infinity when there
    // is none
    getShaftCapX()
    {
        let shaft = this.getSegment()
        if (shaft.dir == 'right')
            shaft = this.course.segment(this.segmentIndex + 1)
        if (shaft.dir == 'right')
            return Infinity
        return shaft.x0 - width / scale[version] / 2
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

