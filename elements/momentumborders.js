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
// direction. outerEnd is set where the line ends on the outside of a turn;
// startMitre / endMitre are the side normal of the segment met at a turn
// (null on a straight join): the drawing is mitred along n + that normal.
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
        const turnIn = previous && previous.dir != segment.dir
        lines.push({
            kind: momentumBorderKind(segment.dir, side),
            segment: index,
            side: side,
            x0: start.x, y0: start.y, x1: end.x, y1: end.y,
            normal: n,
            direction: d,
            outerEnd: next.dir != segment.dir && m.x * d.x + m.y * d.y > 0,
            startMitre: turnIn ? momentumSideNormal(previous.dir, side) : null,
            endMitre: next.dir != segment.dir ? m : null
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
        // outer corner square is solid; it stays outside the corridor. The
        // drawing is the mitred band (getShapePath), not this polygon.
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
        this.thickness = thickness
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
    // Point depth into the strip at its start or end. At a turn it lies on
    // the mitre (the diagonal from the corner point), so the two strips
    // meet along it; the collision polygon (getPoints) is unchanged.
    mitrePoint(end, depth)
    {
        const line = this.line
        const n = line.normal
        const m = (end ? line.endMitre : line.startMitre) || {x: 0, y: 0}
        return {x: (end ? line.x1 : line.x0) + depth * (n.x + m.x) + screen.x,
                y: (end ? line.y1 : line.y0) + depth * (n.y + m.y) + screen.y}
    }
    // The band of the strip from its face to depth, mitred at turns
    getBandPath(depth)
    {
        const points = [this.mitrePoint(false, 0), this.mitrePoint(true, 0),
                        this.mitrePoint(true, depth), this.mitrePoint(false, depth)]
        const shape = new Path2D()
        shape.moveTo(points[0].x, points[0].y)
        for (let i = 1; i < points.length; ++i)
            shape.lineTo(points[i].x, points[i].y)
        shape.closePath()
        return shape
    }
    getShapePath()
    {
        return this.getBandPath(this.thickness)
    }
    // Clips to this strip's side of the mitre at each turn end, so the face
    // lines run on past the corner point and still join on the diagonal
    clipMitres()
    {
        const line = this.line
        const d = line.direction
        const far = Math.hypot(line.x1 - line.x0, line.y1 - line.y0) + 4 * this.thickness
        for (const end of [false, true])
        {
            if (!(end ? line.endMitre : line.startMitre))
                continue
            const p = this.mitrePoint(end, 0)
            const q = this.mitrePoint(end, far)
            const mx = q.x - p.x, my = q.y - p.y
            // Towards the rest of the strip
            const bx = (end ? -far : far) * d.x, by = (end ? -far : far) * d.y
            const half = new Path2D()
            half.moveTo(p.x - mx, p.y - my)
            half.lineTo(p.x + mx, p.y + my)
            half.lineTo(p.x + mx + bx, p.y + my + by)
            half.lineTo(p.x - mx + bx, p.y - my + by)
            half.closePath()
            ctx.clip(half)
        }
    }
    drawGlow()
    {
        this.drawNeonBoundary()
    }
    draw()
    {
        ctx.save()
        ctx.fillStyle = this.fill
        ctx.fill(this.getShapePath())
        this.drawCap(this.capFill)
        ctx.restore()

        this.drawNeonBoundary()
    }
    // The strip along the corridor face
    drawCap(fill)
    {
        const cap = Math.max(2, screenHeightPercent(STYLE.spriteGeometry.capHeightPercent))

        ctx.fillStyle = fill
        ctx.fill(this.getBandPath(cap))
    }
    // Neon only along the corridor face
    drawNeonBoundary()
    {
        const line = this.line
        const d = line.direction
        // At a turn the face runs on past the corner point (its glow fills
        // the strip's half of the corner), cut on the mitre
        const before = line.startMitre ? this.thickness : 0
        const after = line.endMitre ? this.thickness : 0
        ctx.save()
        this.clipMitres()
        ctx.beginPath()
        ctx.moveTo(line.x0 - before * d.x + screen.x, line.y0 - before * d.y + screen.y)
        ctx.lineTo(line.x1 + after * d.x + screen.x, line.y1 + after * d.y + screen.y)
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

// Interior boxes (world units) of the corridor the ninja is in: the segments
// around screen.segmentIndex, as far as they reach into the view without a
// break. Another part of the course coming back into the view is left out.
// Only segments already generated (generating more draws Math.random).
function momentumVisibleCorridor()
{
    const course = momentumCourse
    const view = {l: -screen.x, t: -screen.y}
    view.r = view.l + width / scale[version]
    view.b = view.t + height / scale[version]
    const box = index =>
    {
        const lines = momentumSegmentBorderLines(course, index)
        const xs = lines.flatMap(l => [l.x0, l.x1]), ys = lines.flatMap(l => [l.y0, l.y1])
        return {segment: index, l: Math.min(...xs), r: Math.max(...xs), t: Math.min(...ys), b: Math.max(...ys)}
    }
    const inView = b => b.l < view.r && b.r > view.l && b.t < view.b && b.b > view.t
    const last = course.segments.length - 2
    const current = Math.min(screen.segmentIndex, last)
    const boxes = [box(current)]
    for (let i = current - 1; i >= 0; --i)
    {
        const b = box(i)
        if (!inView(b))
            break
        boxes.unshift(b)
    }
    for (let i = current + 1; i <= last; ++i)
    {
        const b = box(i)
        if (!inView(b))
            break
        boxes.push(b)
    }
    return {view: view, boxes: boxes}
}
// Everything in the view outside that corridor: the cells (world units) of
// the box edge grid not inside any box
function momentumOutsideCells()
{
    const corridor = momentumVisibleCorridor()
    const view = corridor.view
    const boxes = corridor.boxes
    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
    const xs = [...new Set([view.l, view.r, ...boxes.flatMap(b => [clamp(b.l, view.l, view.r), clamp(b.r, view.l, view.r)])])]
        .sort((a, b) => a - b)
    const ys = [...new Set([view.t, view.b, ...boxes.flatMap(b => [clamp(b.t, view.t, view.b), clamp(b.b, view.t, view.b)])])]
        .sort((a, b) => a - b)
    const cells = []
    for (let i = 0; i + 1 < xs.length; ++i)
        for (let j = 0; j + 1 < ys.length; ++j)
        {
            const cx = (xs[i] + xs[i + 1]) / 2, cy = (ys[j] + ys[j + 1]) / 2
            if (!boxes.some(b => b.l < cx && cx < b.r && b.t < cy && cy < b.b))
                cells.push({l: xs[i], r: xs[i + 1], t: ys[j], b: ys[j + 1]})
        }
    return {cells: cells, segments: boxes.map(b => b.segment)}
}
// Those cells as one screen path, so neighbouring cells leave no
// anti-aliased seam
function momentumOutsidePath()
{
    const outside = momentumOutsideCells()
    const path = new Path2D()
    for (const c of outside.cells)
        path.rect(c.l + screen.x, c.t + screen.y, c.r - c.l, c.b - c.t)
    return {path: path, segments: outside.segments}
}
// Momentum: the view outside the current corridor is solid wall mass, over
// the background, other corridors and pieces, under the corridor contents.
// The corridor's own borders get their cap and neon face back on it.
function drawMomentumOutsideMask()
{
    const outside = momentumOutsidePath()
    ctx.save()
    ctx.fillStyle = STYLE.momentum.wallFill
    ctx.fill(outside.path)
    ctx.clip(outside.path)
    for (const floor of floors)
    {
        if (!(floor instanceof MomentumBorderFloor))
            continue
        for (const element of floor.elements)
            if (outside.segments.includes(element.line.segment))
            {
                element.drawCap(STYLE.momentum.wallCapFill)
                element.drawNeonBoundary()
            }
    }
    ctx.restore()
}
