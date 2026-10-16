// Momentum camera: Screen with Y motion, driven by the course segment the
// ninja is in. Right segments scroll right like bad mode; up/down segments
// keep the ninja vertically centred, moving only in the segment direction and
// stopping where the next right corridor is centred. The camera never goes
// back: what leaves the view behind the travel direction is deleted, and a
// ninja that leaves it there dies.
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
        }
    }
    shouldStartMove()
    {
        this.updateSegment()
        return this.shouldStartMoveX() | this.shouldStartMoveY()
    }
    // screen.y of a camera centred on world y
    centredOn(y)
    {
        return -(y - this.getViewHeight() / 2)
    }
    shouldStartMoveY()
    {
        const segment = this.getSegment()
        let target
        if (segment.dir == 'right')
        {
            // Settles on the corridor centre after a vertical segment
            const step = GAMEPLAY.momentumCamera.settleHeightRatio * this.getViewHeight()
            const centre = this.centredOn(segment.y0)
            target = this.y + Math.max(-step, Math.min(step, centre - this.y))
        }
        else
        {
            target = this.centredOn(ninja.y)
            const end = this.centredOn(segment.y1)
            // up: screen.y only grows, down: it only shrinks
            target = segment.dir == 'up' ? Math.min(target, end) : Math.max(target, end)
        }
        if (this.verticalTravel < 0)
            target = Math.max(target, this.y)
        else if (this.verticalTravel > 0)
            target = Math.min(target, this.y)
        else
            target = this.y
        this.speedY = target - this.y
        return this.speedY != 0
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
