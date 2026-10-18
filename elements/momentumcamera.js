// Momentum camera: Screen with Y motion riding the camera rail
// (elements/momentumcamerarail.js: the course centre line, every turn a
// quarter circle). Like bad mode (Screen.shouldStartMoveX) the camera moves
// only while the ninja is past its trigger point and moving forward, at the
// ninja's speed along the rail tangent, and never goes back; at a corner its
// direction turns along the arc at that same speed. What leaves the view
// behind the travel direction is deleted; a camera-owned BackWall
// (sprites/backwall.js) bounces a ninja falling back on that side.
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
        this.rail = new MomentumCameraRail(course)
        // Camera rail position: the trigger point is borderX further on.
        // Set on the first cycle from the start view (the course start
        // segment is a right one).
        this.railS = null
        // The ninja's position at the last cycle: its motion since then is
        // its speed (speedX/Y, or more when it is placed further on)
        this.lastNinja = null
        this.segmentIndex = 0
        // The camera's last vertical direction (from its first turn toward a
        // shaft): the far side of the view stays behind through the
        // following right segments
        this.verticalTravel = 0
        // Bouncy boundary on that side (sprites/backwall.js)
        this.backWall = new BackWall(this)
        this.deletedBehind = 0
    }
    getViewHeight()
    {
        return height / scale[version]
    }
    getSegment()
    {
        return this.course.segment(this.segmentIndex)
    }
    // Camera top-left world corner (-x, -y) for rail position s: the trigger
    // point (s + borderX) where bad mode keeps the ninja, borderX from the
    // view's left edge and vertically centred. On a straight right segment
    // that is the bad camera; through a corner the view travels along the
    // arc, its speed the rail's.
    viewAt(s)
    {
        const p = this.rail.pointAt(s + this.borderX)
        return {x: p.x - this.borderX, y: p.y - this.getViewHeight() / 2}
    }
    // Moves to the next segment once the trigger point passes the join (its
    // arc middle). The vertical direction left behind follows the camera's
    // own: from the start of an arc into a shaft, what it turns away from
    // is behind.
    updateSegment()
    {
        while (this.railS + this.borderX >= this.rail.joinAt(this.segmentIndex))
            ++this.segmentIndex
        const tangent = this.rail.tangentAt(this.railS + this.borderX)
        if (Math.abs(tangent.y) > 1e-9)
            this.verticalTravel = Math.sign(tangent.y)
    }
    // One physics cycle: the ninja's rail position (searched from a view
    // behind the trigger) and its speed along the tangent there (its motion
    // since the last cycle, at least its speed: a ninja moved on faster
    // than speedX, by a respawn or a scripted drive, is followed). Past the
    // trigger and moving forward the camera advances by that speed; within
    // triggerRampHeightRatio short of it, by a share falling to 0 at that
    // distance, so a ninja falling behind the trigger on the outer side of
    // an arc slows the camera instead of stopping it dead.
    shouldStartMove()
    {
        if (this.railS === null)
            this.railS = -this.x - this.course.x0
        const view = this.getViewHeight()
        const trigger = this.railS + this.borderX
        const ninjaS = this.rail.project(ninja.x, ninja.y, trigger - view, view + width / scale[version])
        const tangent = this.rail.tangentAt(ninjaS)
        const last = this.lastNinja
        const moved = last && last.ninja === ninja ? (ninja.x - last.x) * tangent.x + (ninja.y - last.y) * tangent.y : 0
        const along = Math.max(moved, ninja.speedX * tangent.x + ninja.speedY * tangent.y)
        this.lastNinja = {ninja: ninja, x: ninja.x, y: ninja.y}
        const ramp = GAMEPLAY.momentumCamera.triggerRampHeightRatio * view
        const share = Math.min(1, 1 - (trigger - ninjaS) / ramp)
        if (along > 0 && share > 0)
            this.railS += along * share
        this.updateSegment()
        const at = this.viewAt(this.railS)
        this.speedX = -at.x - this.x
        this.speedY = -at.y - this.y
        return this.speedX != 0 || this.speedY != 0
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

