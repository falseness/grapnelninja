// Momentum borders: the course (elements/momentumcourse.js) is the centre
// line of a corridor halfWidth wide on each side (vertical segments: their
// own, wider half width, momentumSegmentHalfWidth). A 'right' segment gets a
// floor and a ceiling, an 'up'/'down' segment a wall on each side. Each side
// of the corridor is one continuous offset polyline: the end of a border is
// the start of the next one on the same side, so corners have no gap.

// Unit normal of side (+1 or -1) of a segment, pointing away from the centre
// line. Side +1 is the floor of a right segment; the sides keep their place
// through turns, so side +1 of an up segment is its right wall.
function momentumSideNormal(dir, side)
{
    if (dir == 'right')
        return {x: 0, y: side}
    if (dir == 'up')
        return {x: side, y: 0}
    return {x: -side, y: 0}
}
function momentumDirection(dir)
{
    if (dir == 'right')
        return {x: 1, y: 0}
    return {x: 0, y: dir == 'up' ? -1 : 1}
}
// Half width of a vertical segment built now: shaftWidthScale of the width
// that lets a view centred on it show only the corridor and its walls (their
// outer edges shaftMargin past the view edges, never under halfWidth)
function momentumShaftHalfWidth()
{
    const options = GAMEPLAY.momentumBorders
    return options.shaftWidthScale *
        Math.max(options.halfWidth,
                 width / scale.momentum / 2 - options.thickness + options.shaftMargin)
}
// Half width of a course segment's corridor. A vertical segment keeps the
// one of the viewport it was first measured in (stored on the segment).
function momentumSegmentHalfWidth(segment)
{
    if (segment.dir == 'right')
        return GAMEPLAY.momentumBorders.halfWidth
    if (segment.halfWidth === undefined)
        segment.halfWidth = momentumShaftHalfWidth()
    return segment.halfWidth
}
// Where side meets the next segment: on a straight join the shared end
// point, on a turn the meeting point of the two offset lines (each at its
// own segment's half width).
function momentumBorderCorner(segment, next, side)
{
    const n = momentumSideNormal(segment.dir, side)
    const halfWidth = momentumSegmentHalfWidth(segment)
    let x = segment.x1 + halfWidth * n.x
    let y = segment.y1 + halfWidth * n.y
    if (next.dir != segment.dir)
    {
        const m = momentumSideNormal(next.dir, side)
        const nextHalfWidth = momentumSegmentHalfWidth(next)
        x += nextHalfWidth * m.x
        y += nextHalfWidth * m.y
    }
    return {x: x, y: y}
}
function momentumBorderKind(dir, side)
{
    if (dir != 'right')
        return 'wall'
    return side > 0 ? 'floor' : 'ceiling'
}
// The two border lines of course segment index, start to end in the travel
// direction. outerEnd is set where the line ends on the outside of a turn.
function momentumSegmentBorderLines(course, index)
{
    const segment = course.segment(index)
    const next = course.segment(index + 1)
    const previous = index > 0 ? course.segment(index - 1) : null
    const halfWidth = momentumSegmentHalfWidth(segment)
    const lines = []
    for (const side of [1, -1])
    {
        const n = momentumSideNormal(segment.dir, side)
        const start = previous ? momentumBorderCorner(previous, segment, side)
                               : {x: segment.x0 + halfWidth * n.x, y: segment.y0 + halfWidth * n.y}
        const end = momentumBorderCorner(segment, next, side)
        const d = momentumDirection(segment.dir)
        const m = momentumSideNormal(next.dir, side)
        lines.push({
            kind: momentumBorderKind(segment.dir, side),
            segment: index,
            side: side,
            x0: start.x, y0: start.y, x1: end.x, y1: end.y,
            normal: n,
            direction: d,
            outerEnd: next.dir != segment.dir && m.x * d.x + m.y * d.y > 0
        })
    }
    return lines
}

// One border line as a bouncy strip behind it. Every edge bounces like the
// bad ceiling (Trampoline -> bounceSpeed) and the strip never goes away.
class MomentumBorder extends Ground
{
    constructor(line, thickness)
    {
        const o = line.normal
        // On the outside of a turn the strip runs on past the corner, so its
        // outer corner square is filled; it stays outside the corridor.
        const extend = line.outerEnd ? thickness : 0
        const ex = line.x1 + extend * line.direction.x
        const ey = line.y1 + extend * line.direction.y
        super({x: 0, y: 0, points: [
            {x: line.x0, y: line.y0},
            {x: ex, y: ey},
            {x: ex + thickness * o.x, y: ey + thickness * o.y},
            {x: line.x0 + thickness * o.x, y: line.y0 + thickness * o.y}
        ]})
        this.line = line
        this.kind = line.kind
        if (line.kind == 'wall')
        {
            this.fill = STYLE.momentum.wallFill
            this.stroke = STYLE.momentum.wallStroke
            this.capFill = STYLE.momentum.wallCapFill
            this.coreColor = STYLE.momentum.wallCore
        }
        else
        {
            this.fill = STYLE.badVersionEffects.obstacles.groundFill
            this.stroke = STYLE.badVersionEffects.obstacles.groundStroke
            this.capFill = STYLE.badVersionEffects.obstacles.groundCapFill
            this.coreColor = undefined
        }
    }
    // A bounce off a course border keeps hp and the green streak
    onNinjaBounce()
    {
        momentumState.onBorderTouch()
    }
    getShapePath()
    {
        const points = this.getPoints()
        const shape = new Path2D()
        shape.moveTo(points[0].x + screen.x, points[0].y + screen.y)
        for (let i = 1; i < points.length; ++i)
            shape.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        shape.closePath()
        return shape
    }
    drawGlow()
    {
        this.drawNeonBoundary()
    }
    draw()
    {
        const line = this.line
        const o = line.normal
        const cap = Math.max(2, screenHeightPercent(STYLE.spriteGeometry.capHeightPercent))

        ctx.save()
        ctx.fillStyle = this.fill
        ctx.fill(this.getShapePath())
        ctx.fillStyle = this.capFill
        ctx.beginPath()
        ctx.moveTo(line.x0 + screen.x, line.y0 + screen.y)
        ctx.lineTo(line.x1 + screen.x, line.y1 + screen.y)
        ctx.lineTo(line.x1 + cap * o.x + screen.x, line.y1 + cap * o.y + screen.y)
        ctx.lineTo(line.x0 + cap * o.x + screen.x, line.y0 + cap * o.y + screen.y)
        ctx.closePath()
        ctx.fill()
        ctx.restore()

        this.drawNeonBoundary()
    }
    // Neon only along the corridor face
    drawNeonBoundary()
    {
        const line = this.line
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(line.x0 + screen.x, line.y0 + screen.y)
        ctx.lineTo(line.x1 + screen.x, line.y1 + screen.y)
        strokeNeonPath(this.stroke, undefined, undefined, this.getShapePath(), this.coreColor)
        ctx.restore()
    }
}

// The momentum borders of the given kinds along a course, generated
// 3 viewports ahead of the camera like the bad SideFloor surfaces.
// A SideFloor, so respawn does not treat it as an obstacle floor.
class MomentumBorderFloor extends SideFloor
{
    constructor(course, kinds, top, bottom)
    {
        super(bottom, top, [])
        this.top = top
        this.bottom = bottom
        this.course = course
        this.kinds = kinds
        this.nextSegment = 0
    }
    generatePrimaryElements()
    {
        this.elements = []
        this.nextSegment = 0
        this.replenishElements()
    }
    replenishElements()
    {
        const options = GAMEPLAY.momentumBorders
        const targetRight = -screen.x + 3 * width / scale[version]
        while (this.course.segment(this.nextSegment).x0 < targetRight)
        {
            const lines = momentumSegmentBorderLines(this.course, this.nextSegment)
            for (const line of lines)
                if (this.kinds.includes(line.kind))
                    this.elements.push(new MomentumBorder(line, options.thickness + options.backing))
            ++this.nextSegment
        }
    }
    deleteElements()
    {
        const border = screen.getDeletionBorder()
        if (this.elements.some(element => element.getRightPointX() + screen.x < border))
            this.elements = this.elements.filter(element => element.getRightPointX() + screen.x >= border)
        // Behind vertically: only borders of segments already passed. Ones
        // ahead can lie there too (a course that went up comes back down)
        const ahead = this.elements.filter(element => element.line.segment >= screen.segmentIndex)
        this.elements = this.elements.filter(element => element.line.segment < screen.segmentIndex)
        screen.deleteBehind(this, false)
        this.elements = this.elements.concat(ahead)
    }
    draw()
    {
        Floor.prototype.draw.call(this)
    }
    drawGlow()
    {
        Floor.prototype.drawGlow.call(this)
    }
    drawExtrusions() {}
}

// The live momentum border lines, for tests and tools
function momentumBorders()
{
    if (version != 'momentum' || !floors)
        return []
    const lines = []
    for (const floor of floors)
    {
        if (!(floor instanceof MomentumBorderFloor))
            continue
        for (const element of floor.elements)
        {
            const line = element.line
            lines.push({kind: line.kind, segment: line.segment, side: line.side,
                        x0: line.x0, y0: line.y0, x1: line.x1, y1: line.y1})
        }
    }
    return lines.sort((a, b) => a.segment - b.segment || b.side - a.side)
}
