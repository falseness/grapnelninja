// Momentum camera: Screen with Y motion riding the camera rail
// (elements/momentumcamerarail.js: the course centre line, every turn a
// quarter circle). Like bad mode (Screen.shouldStartMoveX) the camera moves
// only while the ninja is past its trigger point and moving forward, at the
// ninja's speed along the course, and never goes back; the view is centred
// on the rail, so at a corner its direction turns along the arc. What leaves the view
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
        // The trigger point (where bad mode keeps the ninja) as a distance
        // along the course centre line, like the ninja's own progress. Set
        // on the first cycle from the start view (the course start segment
        // is a right one).
        this.courseS = null
        this.courseEnds = []
        // Rail position of the view centre (railAt(courseS) + lead())
        this.railS = null
        // The ninja's position at the last cycle: its motion since then is
        // its speed (speedX/Y, or more when it is placed further on)
        this.lastNinja = null
        // The trigger point moved on in the last cycle (it keeps moving with
        // the ninja a little behind it)
        this.moving = false
        // The ninja's distance along the course at the last cycle
        this.lastQ = null
        // Weight of that progress in the camera's speed (shouldStartMove)
        this.blend = 0
        // The ninja's averaged progress along the course a cycle
        this.progress = null
        this.segmentIndex = 0
        // The camera's last vertical direction (from its first turn toward a
        // shaft): the far side of the view stays behind through the
        // following right segments
        this.verticalTravel = 0
        // The ninja's side left behind: the direction of the last shaft at or
        // before the trigger point's segment. The camera turns toward the
        // next shaft from lead() before the trigger point, while the ninja
        // can still drop back into the shaft it came out of (a short
        // corridor between opposite shafts)
        this.backTravel = 0
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
    // Rail distance from the trigger point to the view centre: bad mode's
    // borderX from the left edge, rotated with the rail tangent (in a shaft
    // the ninja sits that far behind the centre, centred across)
    lead()
    {
        return width / scale[version] / 2 - this.borderX
    }
    // Course centre line distance of the end of segment index (its join)
    courseEnd(index)
    {
        const ends = this.courseEnds
        while (ends.length <= index)
            ends.push((ends.length ? ends[ends.length - 1] : 0) + this.course.segment(ends.length).length)
        return ends[index]
    }
    // Index of the course segment holding centre line distance q
    segmentAt(q)
    {
        let index = 0
        while (q >= this.courseEnd(index))
            ++index
        return index
    }
    // Knot index (-1: the course start, i: the corner point at the end of
    // segment i) of railAt: centre line distance q, rail position s and slope m
    knot(i)
    {
        if (i < 0)
            return {q: 0, s: 0, m: this.ratio(0)}
        return {q: this.courseEnd(i), s: this.rail.joinAt(i), m: (this.ratio(i) + this.ratio(i + 1)) / 2}
    }
    // Rail / centre line length of segment i, from knot i - 1 to knot i
    ratio(i)
    {
        const q0 = i ? this.courseEnd(i - 1) : 0, s0 = i ? this.rail.joinAt(i - 1) : 0
        return (this.rail.joinAt(i) - s0) / (this.courseEnd(i) - q0)
    }
    // Rail position of course centre line distance q. Each turn join (its
    // corner point) maps to its arc middle, the course start to the rail
    // start; between them a monotone cubic whose slope at each join is the
    // mean of the two segments' rail / centre line length ratios. The arcs
    // are shorter than the corners they cut, so the camera, moving the
    // trigger point as far along the course as the ninja moves, travels a
    // few percent slower along the rail all through a segment instead of
    // slowing down at its corner, and its speed changes only gradually
    // between segments.
    railAt(q)
    {
        const index = this.segmentAt(q)
        const a = this.knot(index - 1), b = this.knot(index)
        const h = b.q - a.q, t = (q - a.q) / h
        const t2 = t * t, t3 = t2 * t
        return (2 * t3 - 3 * t2 + 1) * a.s + (t3 - 2 * t2 + t) * a.m * h + (3 * t2 - 2 * t3) * b.s + (t3 - t2) * b.m * h
    }
    // Inverse of railAt (bisection within the segment holding rail position s)
    courseAt(s)
    {
        let index = 0
        while (s >= this.rail.joinAt(index))
            ++index
        let lo = index ? this.courseEnd(index - 1) : 0, hi = this.courseEnd(index)
        for (let i = 0; i < 50; ++i)
        {
            const mid = (lo + hi) / 2
            if (this.railAt(mid) < s)
                lo = mid
            else
                hi = mid
        }
        return (lo + hi) / 2
    }
    // Camera top-left world corner (-x, -y) for rail position s: the view
    // centred on the rail point, so it travels along the rail at the speed
    // s does and turns its direction along each arc
    viewAt(s)
    {
        const p = this.rail.pointAt(s)
        return {x: p.x - width / scale[version] / 2, y: p.y - this.getViewHeight() / 2}
    }
    // Moves to the next segment once the trigger point passes the join. The
    // vertical direction left behind follows the camera's own: from the
    // start of an arc into a shaft, what it turns away from is behind. The
    // ninja's (backTravel) changes only once the trigger point is in the
    // next shaft.
    updateSegment()
    {
        while (this.courseS >= this.courseEnd(this.segmentIndex))
            ++this.segmentIndex
        for (let i = this.segmentIndex; i >= 0; --i)
        {
            const dir = this.course.segment(i).dir
            if (dir != 'right')
            {
                this.backTravel = dir == 'up' ? -1 : 1
                break
            }
        }
        const tangent = this.rail.tangentAt(this.railS)
        if (Math.abs(tangent.y) > 1e-9)
            this.verticalTravel = Math.sign(tangent.y)
    }
    // The ninja's distance along the course centre line: its nearest point
    // on the segments around the one it is on, or, on an arc of the rail, its
    // position along the arc stretched over the 2 radii of centre line the
    // arc replaces if that is further (on the centre line it is, and it is
    // continuous where the nearest segment changes in a corner box); and its
    // forward speed: its velocity (or its motion since the last cycle, when
    // it was placed further on by a respawn or a scripted drive), the most of
    // its projections on the rail tangent at its rail position and on the
    // direction of the course segment it is on (the one whose join arc
    // middle it has not passed). A ninja turning a corner on the centre line
    // keeps its speed, though its rail projection slows down there.
    ninjaProgress()
    {
        const view = this.getViewHeight()
        const ninjaS = this.rail.project(ninja.x, ninja.y, this.railS - this.lead() - view, view + width / scale[version])
        let index = Math.max(0, this.segmentIndex - 1)
        while (ninjaS >= this.rail.joinAt(index))
            ++index
        const last = this.lastNinja
        const moved = last && last.ninja === ninja ? {x: ninja.x - last.x, y: ninja.y - last.y} : {x: 0, y: 0}
        let speed = -Infinity
        for (const d of [this.rail.tangentAt(ninjaS), segmentDirection(this.course.segment(index).dir)])
            speed = Math.max(speed, moved.x * d.x + moved.y * d.y, ninja.speedX * d.x + ninja.speedY * d.y)
        this.lastNinja = {ninja: ninja, x: ninja.x, y: ninja.y}
        let nearest = null
        for (let i = Math.max(0, index - 1); i <= index + 1; ++i)
        {
            const segment = this.course.segment(i)
            const d = segmentDirection(segment.dir)
            const along = Math.min(segment.length, Math.max(0, (ninja.x - segment.x0) * d.x + (ninja.y - segment.y0) * d.y))
            const dist = Math.hypot(ninja.x - segment.x0 - d.x * along, ninja.y - segment.y0 - d.y * along)
            if (!nearest || dist < nearest.dist - 1e-9)
                nearest = {dist: dist, q: this.courseEnd(i) - segment.length + along}
        }
        const piece = this.rail.pieces[this.rail.pieceAt(ninjaS)]
        for (let k = Math.max(0, index - 1); piece.type == 'arc' && k <= index; ++k)
        {
            const join = this.rail.joinAt(k)
            if (join >= piece.s0 && join <= piece.s0 + piece.length)
                nearest.q = Math.max(nearest.q, this.courseEnd(k) - piece.r + (ninjaS - piece.s0) * 2 * piece.r / piece.length)
        }
        return {q: nearest.q, speed: speed}
    }
    // One physics cycle. Like bad mode (Screen.shouldStartMoveX), along the
    // course centre line: once the ninja is past the trigger point and
    // moving forward the trigger point moves on by the ninja's forward
    // speed; it keeps moving while the ninja is less than
    // GAMEPLAY.momentumCamera.triggerSlackHeightRatio behind it (crossing a
    // corner box the ninja moves along the course slower than along the rail
    // tangent there), otherwise it stays; it never goes back. The view
    // centre is lead() further on along the rail (railAt).
    shouldStartMove()
    {
        if (this.courseS === null)
        {
            this.railS = -this.x - this.course.x0 + width / scale[version] / 2
            this.courseS = this.courseAt(this.railS - this.lead())
        }
        const ninjaAt = this.ninjaProgress()
        const slack = GAMEPLAY.momentumCamera.triggerSlackHeightRatio * this.getViewHeight()
        this.moving = ninjaAt.speed > 0 && ninjaAt.q > this.courseS - (this.moving ? slack : 0)
        // Behind the trigger point (across a corner box the ninja moves along
        // the course slower than its speed) the speed blends into the
        // ninja's progress along the course a cycle (averaged over
        // triggerProgressCycles cycles: it steps where the ninja turns or its
        // nearest segment changes); the blend weight changes by at most
        // triggerBlendRate a cycle
        const options = GAMEPLAY.momentumCamera
        const target = Math.min(1, Math.max(0, this.courseS - ninjaAt.q) /
                                (options.triggerBlendHeightRatio * this.getViewHeight()))
        this.blend += Math.max(-options.triggerBlendRate, Math.min(options.triggerBlendRate, target - this.blend))
        const progress = Math.max(0, this.lastQ === null ? ninjaAt.speed : Math.min(ninjaAt.speed, ninjaAt.q - this.lastQ))
        this.lastQ = ninjaAt.q
        this.progress = this.progress === null ? progress :
                        this.progress + (progress - this.progress) / options.triggerProgressCycles
        if (this.moving)
            this.courseS += ninjaAt.speed + (Math.min(ninjaAt.speed, this.progress) - ninjaAt.speed) * this.blend
        this.railS = this.railAt(this.courseS) + this.lead()
        this.updateSegment()
        const at = this.viewAt(this.railS)
        this.speedX = -at.x - this.x
        this.speedY = -at.y - this.y
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

