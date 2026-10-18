// Momentum one-time objects (greens and blues): the first ninja contact
// uses them up (use()); from then on they let the ninja and the grapnel
// through (a grapnel hooked on them is released, Grapnel.releaseElement) and fade out linearly over GAMEPLAY.momentumFadeMs of render clock
// (performance.now()); blues vanish at once instead (vanishesOnUse). Their floor drops them once the fade is over
// (Floor.moveElements reads `faded`). Trampoline geometry (any convex
// polygon: boxes, rotated rectangles, triangles), own colours.
// object.motion {speedY, yMin, yMax, gravity} adds the bad-mode vertical
// motion: speedY reverses whenever the shape would leave [yMin, yMax]
// (Triangle.changeSpeed), with gravity it falls and bounces like a
// JumpingCube. setMotionCandidates opens a side past a used piece:
// moveY bounces on the nearest unused candidate of that side instead.
class MomentumOneTime extends Trampoline
{
    constructor(object, stroke, fill, badVersionFill)
    {
        super(object)
        this.stroke = stroke
        this.fill = fill
        this.badVersionFill = badVersionFill
        this.fadeStartMs = null
        this.passThrough = false
        this.faded = false
        this.innerCache = null
        this.measureShape()
        this.motion = null
        if (object.motion)
        {
            const motion = object.motion
            this.motion = {yMin: motion.yMin, yMax: motion.yMax, gravity: !!motion.gravity}
            this.speedY = (motion.speedY || 0) * momentumMotionScale(1)
        }
        this.motionCandidates = null
    }
    // side 'yMin' | 'yMax': ordered candidates (nearest first), each
    // {element, value} (a static face) or {element, face: 'top' | 'bottom',
    // gap} (a moving sibling's live face), then {value} (the corridor limit)
    setMotionCandidates(side, candidates)
    {
        if (!this.motionCandidates)
            this.motionCandidates = {}
        this.motionCandidates[side] = candidates
    }
    // Effective bound of that side: the nearest candidate not used yet (the
    // catalog bound while nothing is used), else the last one
    getMotionBound(side)
    {
        const candidates = this.motionCandidates && this.motionCandidates[side]
        if (!candidates)
            return this.motion[side]
        for (const candidate of candidates)
        {
            const element = candidate.element
            if (element && element.passThrough)
                continue
            if (candidate.face == 'top')
                return element.y + element.topOffset - candidate.gap
            if (candidate.face == 'bottom')
                return element.y + element.bottomOffset + candidate.gap
            return candidate.value
        }
        return candidates[candidates.length - 1].value
    }
    // Extents and circle over every point (the Trampoline constructor
    // reads every other point, which misses a triangle's corner)
    measureShape()
    {
        const points = this.points
        let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity
        let cx = 0, cy = 0
        for (const point of points)
        {
            left = Math.min(left, point.x)
            right = Math.max(right, point.x)
            top = Math.min(top, point.y)
            bottom = Math.max(bottom, point.y)
            cx += point.x
            cy += point.y
        }
        cx /= points.length
        cy /= points.length
        let r = 0
        for (const point of points)
            r = Math.max(r, Math.hypot(point.x - cx, point.y - cy))
        this.leftPointX = left
        this.rightPointX = right
        this.topOffset = top
        this.bottomOffset = bottom
        this.circle = {x: cx, y: cy, radius: r}
    }
    // Axis-aligned w x h box points with the top-left corner at (x, y)
    static boxObject(x, y, w, h)
    {
        return {x: x, y: y, points: [
            {x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}
        ]}
    }
    // Shape description -> constructor object, centred on (spec.x, spec.y):
    // shape 'rect' (w, h), 'triangle' (radius: centre to corner, pointing
    // down like a bad Triangle at angle 0) or 'polygon' (points relative to
    // the centre); angle in radians (clockwise on screen); motion as above
    static shapeObject(spec)
    {
        let points
        if (spec.shape == 'rect')
            points = [{x: -spec.w / 2, y: -spec.h / 2}, {x: spec.w / 2, y: -spec.h / 2},
                      {x: spec.w / 2, y: spec.h / 2}, {x: -spec.w / 2, y: spec.h / 2}]
        else if (spec.shape == 'triangle')
        {
            const side = spec.radius * Math.sqrt(3)
            const h = side * Math.sin(Math.PI / 3)
            points = [{x: -side / 2, y: -h / 3}, {x: side / 2, y: -h / 3}, {x: 0, y: 2 * h / 3}]
        }
        else
            points = spec.points.map(point => ({x: point.x, y: point.y}))
        const angle = spec.angle || 0
        if (angle)
        {
            const c = Math.cos(angle)
            const s = Math.sin(angle)
            points = points.map(point => ({x: point.x * c - point.y * s, y: point.x * s + point.y * c}))
        }
        return {x: spec.x, y: spec.y, points: points, motion: spec.motion}
    }
    // Starts the fade (gone at once for one that vanishes on use); false if
    // it was used already
    use()
    {
        if (this.passThrough)
            return false
        this.passThrough = true
        this.fadeStartMs = performance.now()
        if (this.vanishesOnUse())
            this.faded = true
        // A used object no longer holds the grapnel
        if (grapnel)
            grapnel.releaseElement(this)
        return true
    }
    // Used blues skip the fade: not drawn, lit or occluding from the touch on,
    // and their floor drops them on its next pass
    vanishesOnUse()
    {
        return false
    }
    getAlpha(now)
    {
        if (this.faded)
            return 0
        if (this.fadeStartMs === null)
            return 1
        const t = ((now === undefined ? performance.now() : now) - this.fadeStartMs) / GAMEPLAY.momentumFadeMs
        return Math.max(0, Math.min(1, 1 - t))
    }
    move()
    {
        if (this.motion)
            this.moveY()
        if (this.passThrough && this.getAlpha() <= 0)
            this.faded = true
    }
    // One physics cycle of the vertical motion; dy for a tethered grapnel
    moveY()
    {
        const motion = this.motion
        const gravity = GRAVITY * momentumMotionScale(2)
        if (motion.gravity)
            this.speedY += gravity
        const top = this.y + this.topOffset + this.speedY
        const bottom = this.y + this.bottomOffset + this.speedY
        if ((this.speedY < 0 && top < this.getMotionBound('yMin')) ||
            (this.speedY > 0 && bottom > this.getMotionBound('yMax')))
        {
            this.speedY *= -1
            if (motion.gravity)
                this.speedY += this.speedY > 0 ? gravity : -gravity
        }
        this.y += this.speedY
        this.dy = this.speedY
    }
    // The grapnel cannot hook a used object
    getLines()
    {
        return this.passThrough ? [] : super.getLines()
    }
    drawExtrusion()
    {
        if (!this.passThrough)
            super.drawExtrusion()
    }
    drawGlow()
    {
        if (!this.passThrough)
        {
            super.drawGlow()
            return
        }
        const alpha = this.getAlpha()
        if (alpha <= 0)
            return
        const points = this.getPoints()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        ctx.closePath()
        strokeNeonPath(this.getGlowStroke(), alpha)
    }
    // The convex shape moved inward by inset (each edge shifted along its
    // normal, neighbours intersected), in world units; memoised per position
    getInnerPoints(insetRatio)
    {
        const cache = this.innerCache
        if (cache && cache.x === this.x && cache.y === this.y)
            return cache.points
        const points = this.getPoints()
        const count = points.length
        const inset = Math.min(this.rightPointX - this.leftPointX, this.bottomOffset - this.topOffset) * insetRatio
        let area = 0
        for (let i = 0; i < count; ++i)
        {
            const a = points[i]
            const b = points[(i + 1) % count]
            area += a.x * b.y - b.x * a.y
        }
        const winding = area > 0 ? 1 : -1
        // Inward edge lines: point + direction
        const edges = []
        for (let i = 0; i < count; ++i)
        {
            const a = points[i]
            const b = points[(i + 1) % count]
            const length = Math.hypot(b.x - a.x, b.y - a.y) || 1
            const dx = (b.x - a.x) / length
            const dy = (b.y - a.y) / length
            // Inward normal of a clockwise-on-screen (positive area) polygon
            const nx = -dy * winding
            const ny = dx * winding
            edges.push({x: a.x + nx * inset, y: a.y + ny * inset, dx: dx, dy: dy})
        }
        const res = []
        for (let i = 0; i < count; ++i)
        {
            const p = edges[(i + count - 1) % count]
            const q = edges[i]
            const denominator = p.dx * q.dy - p.dy * q.dx
            if (Math.abs(denominator) < 1e-9)
            {
                res.push({x: q.x, y: q.y})
                continue
            }
            const t = ((q.x - p.x) * q.dy - (q.y - p.y) * q.dx) / denominator
            res.push({x: p.x + p.dx * t, y: p.y + p.dy * t})
        }
        this.innerCache = {x: this.x, y: this.y, points: res}
        return res
    }
    // Blues get the bad blue cube's inner shell (Rect.drawInnerRectangleCopy):
    // an opaque inset copy with a thin outline
    drawInnerShell(alpha)
    {
        const points = this.getInnerPoints(STYLE.badVersionEffects.obstacles.innerCopyInsetRatio)
        ctx.save()
        ctx.globalAlpha = alpha
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        ctx.closePath()
        ctx.fillStyle = this.fill
        ctx.fill()
        ctx.strokeStyle = this.stroke
        ctx.lineWidth = STYLE.strokes.neonOutline.innerWidth / scale[version]
        ctx.stroke()
        ctx.restore()
    }
    hasInnerShell()
    {
        return false
    }
    draw()
    {
        const alpha = this.getAlpha()
        if (alpha <= 0)
            return
        this.drawBadVersionPolygon(this.badVersionFill, this.stroke,
            {baseFillStyle: this.fill, alpha: alpha})
        if (this.hasInnerShell())
            this.drawInnerShell(alpha)
    }
}
