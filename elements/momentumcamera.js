// Momentum camera: Screen keeping the ninja in the vertical middle of the
// view. Y follows the ninja every cycle (at most at its y speed plus the
// catch-up step, like X), except that in an up shaft it never
// moves down and in a down shaft never up: a ninja dropping back sees the
// BackWall (sprites/backwall.js) on that side, and the camera follows again
// once the ninja is back in the middle. X slides toward its target, at most
// at the ninja's x speed plus a catch-up step
// (GAMEPLAY.momentumCamera.catchUpHeightRatio view heights a cycle), so a lag
// closes even while the ninja keeps moving or moves straight along a shaft:
// in a right corridor the ninja on the borderX line
// (GAMEPLAY.cameraBorderWidthPercent, like bad mode; only while the ninja is
// past it, never left) but never right of the view centred on the next shaft,
// so the ninja runs on from that line toward the shaft centre and enters the
// shaft with the view already centred; in a shaft the shaft's centre line in
// the view centre (it can move left there too, after the ninja drops back from
// the corridor into the shaft it came from, hasLeftBack). Y re-centres the ninja by its last step. What leaves the view
// behind the travel direction is deleted.
// Unit direction of a course segment (tests drive the ninja with it)
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
        // Set on the first cycle, which places the view again (the ninja
        // has not moved since the build in a run; tests may move it first)
        this.placed = false
        // The furthest course segment the ninja has reached (updateSegment);
        // never goes back: spawning and deletion follow it
        this.segmentIndex = 0
        // The segment the ninja is in now, segmentIndex or one before it when
        // it went back (dropping back into the shaft it came from,
        // hasLeftBack): the camera rule follows it
        this.ninjaSegment = 0
        // The direction of the last shaft at or before segmentIndex: its far
        // side is deleted (verticalTravel); and at or before ninjaSegment:
        // the BackWall side and the side the ninja dies on (backTravel)
        this.verticalTravel = 0
        this.backTravel = 0
        // The shaft rule held Y in the last cycle (tests and tools)
        this.holdY = false
        // The catch-up step limited Y in the last cycle (tests and tools)
        this.catchUpY = false
        // Bouncy boundary on that side (sprites/backwall.js)
        this.backWall = new BackWall(this)
        this.deletedBehind = 0
    }
    getViewHeight()
    {
        return height / scale[version]
    }
    // The segment the camera rule follows (the ninja's)
    getSegment()
    {
        return this.course.segment(this.ninjaSegment)
    }
    // The ninja has entered segment index: it is past the end of the one
    // before along its direction, or has left that one's corridor sideways
    // into this one (dropping into a shaft from a corridor, or out of a shaft
    // into the corridor beyond its corner), within this one's width
    hasEntered(index)
    {
        if (index == 0)
            return true
        const segment = this.course.segment(index - 1), next = this.course.segment(index)
        const d = momentumDirection(segment.dir), n = momentumDirection(next.dir)
        const dx = ninja.x - segment.x1, dy = ninja.y - segment.y1
        if (dx * d.x + dy * d.y >= 0)
            return true
        return next.dir != segment.dir && dx * n.x + dy * n.y > momentumSegmentHalfWidth(segment) &&
               Math.abs(dx * n.y - dy * n.x) <= momentumSegmentHalfWidth(next)
    }
    // The ninja has left segment index's corridor backward, into the one
    // before: behind that one's end by more than this one's half width (below
    // the floor line of a corridor after an up shaft, left of a shaft's left
    // wall line). Wider than hasEntered's line, so a ninja at a join does not
    // flicker between the two.
    hasLeftBack(index)
    {
        const segment = this.course.segment(index - 1), d = momentumDirection(segment.dir)
        const behind = (segment.x1 - ninja.x) * d.x + (segment.y1 - ninja.y) * d.y
        return behind > momentumSegmentHalfWidth(this.course.segment(index))
    }
    // The last shaft's direction (-1 up, 1 down, 0 none) at or before index
    shaftTravel(index)
    {
        for (let i = index; i >= 0; --i)
        {
            const dir = this.course.segment(i).dir
            if (dir != 'right')
                return dir == 'up' ? -1 : 1
        }
        return 0
    }
    updateSegment()
    {
        while (this.hasEntered(this.segmentIndex + 1))
            ++this.segmentIndex
        this.ninjaSegment = this.segmentIndex
        while (this.ninjaSegment > 0 && this.hasLeftBack(this.ninjaSegment))
            --this.ninjaSegment
        this.verticalTravel = this.shaftTravel(this.segmentIndex)
        this.backTravel = this.shaftTravel(this.ninjaSegment)
    }
    // Centres the ninja vertically: startMomentumVersion calls it once the
    // ninja exists, so a paused boot or restart draws the placed view before
    // any cycle, and the first cycle again
    place()
    {
        this.y = this.getViewHeight() / 2 - ninja.y
    }
    // One physics cycle (before the ninja moves): sets speedX / speedY.
    shouldStartMove()
    {
        const H = this.getViewHeight()
        if (!this.placed)
        {
            this.place()
            this.placed = true
        }
        this.updateSegment()
        const segment = this.getSegment()
        // X slides toward its target at most at the ninja's x speed plus the
        // catch-up step (the lag closes while the ninja keeps moving): in a
        // right corridor the ninja on the borderX line, only while it is past
        // it (never left) and capped at the next shaft centred; in a shaft
        // the shaft's centre line in the view centre
        const step = Math.abs(ninja.speedX) + GAMEPLAY.momentumCamera.catchUpHeightRatio * H
        if (segment.dir == 'right')
        {
            // Never right of the view centred on the next shaft (past
            // right->right joins), so the view waits there for the ninja
            // instead of sliding back left inside the shaft
            let next = this.ninjaSegment + 1
            while (this.course.segment(next).dir == 'right')
                ++next
            const toTarget = Math.max(this.borderX - ninja.x - this.x,
                                      width / scale[version] / 2 - this.course.segment(next).x0 - this.x)
            this.speedX = Math.max(-step, Math.min(0, toTarget))
        }
        else
            this.speedX = Math.max(-step, Math.min(step, width / scale[version] / 2 - segment.x0 - this.x))
        // Up shaft: the view only goes up (this.y grows), down shaft: only
        // down; holdY: the ninja is not re-centred (tests and tools). Like X
        // at most the ninja's y speed plus the catch-up step a cycle, so a
        // hold released by a sideways exit into the next corridor closes
        // over a few frames instead of in one cycle; catchUpY: the step
        // limited Y this cycle (tests and tools)
        const speedY = H / 2 - ninja.y - this.y
        this.holdY = segment.dir == 'up' && speedY < 0 || segment.dir == 'down' && speedY > 0
        const stepY = Math.abs(ninja.speedY) + GAMEPLAY.momentumCamera.catchUpHeightRatio * H
        this.catchUpY = !this.holdY && Math.abs(speedY) > stepY
        this.speedY = this.holdY ? 0 : Math.max(-stepY, Math.min(stepY, speedY))
        return this.speedX != 0 || this.speedY != 0
    }
    // A box (world coordinates) fully out of view on the vertical side left
    // behind (travel: the camera's verticalTravel unless given)
    isBoxBehind(top, bottom, margin, travel = this.verticalTravel)
    {
        if (travel < 0)
            return top + this.y > this.getViewHeight() + margin
        if (travel > 0)
            return bottom + this.y < -margin
        return false
    }
    hasLeftBehind(who)
    {
        return this.isBoxBehind(who.y - who.radius, who.y + who.radius, 0, this.backTravel)
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
