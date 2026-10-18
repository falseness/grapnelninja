// Momentum one-time objects (greens and blues): the first ninja contact
// uses them up (use()); from then on they let the ninja and the grapnel
// through (a grapnel hooked on them is released, Grapnel.releaseElement) and fade out linearly over GAMEPLAY.momentumFadeMs of render clock
// (performance.now()). Their floor drops them once the fade is over
// (Floor.moveElements reads `faded`). Trampoline geometry (any convex
// polygon: boxes, rotated rectangles, triangles), own colours.
// object.motion {speedY, yMin, yMax, gravity} adds the bad-mode vertical
// motion: speedY reverses whenever the shape would leave [yMin, yMax]
// (Triangle.changeSpeed), with gravity it falls and bounces like a
// JumpingCube.
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
        this.shards = null
        this.measureShape()
        this.motion = null
        if (object.motion)
        {
            const motion = object.motion
            this.motion = {yMin: motion.yMin, yMax: motion.yMax, gravity: !!motion.gravity}
            this.speedY = (motion.speedY || 0) * momentumMotionScale(1)
        }
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
    // Starts the fade; false if it was used already
    use()
    {
        if (this.passThrough)
            return false
        this.passThrough = true
        this.fadeStartMs = performance.now()
        if (this.hasShards())
            this.shards = this.makeShards()
        // A used object no longer holds the grapnel
        if (grapnel)
            grapnel.releaseElement(this)
        return true
    }
    getAlpha(now)
    {
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
        if ((this.speedY < 0 && top < motion.yMin) || (this.speedY > 0 && bottom > motion.yMax))
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
        if (this.shards && version == 'momentum' && MOMENTUM_FX.enabled)
        {
            this.drawShards(alpha)
            return
        }
        const points = this.getPoints()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        ctx.closePath()
        strokeNeonPath(this.getGlowStroke(), alpha)
    }
    // Blues break into shards when used (visual only)
    hasShards()
    {
        return false
    }
    // Shard layout from the shape alone (seeded by a hash of its points and
    // position, no Math.random), in local units: start on the outline,
    // outward unit direction, travel, size, start angle, spin
    makeShards()
    {
        const fxStyle = STYLE.momentumFx
        const points = this.points
        const count = points.length
        let seed = 2166136261
        const mix = v => { seed = Math.imul(seed ^ (Math.round(v * 16) | 0), 16777619) >>> 0 }
        mix(this.x)
        mix(this.y)
        for (const point of points)
        {
            mix(point.x)
            mix(point.y)
        }
        const random = () =>
        {
            seed = (seed + 0x6D2B79F5) >>> 0
            let t = Math.imul(seed ^ (seed >>> 15), seed | 1)
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296
        }
        const lerp = (range, k) => range[0] + (range[1] - range[0]) * k
        let perimeter = 0
        for (let i = 0; i < count; ++i)
        {
            const a = points[i], b = points[(i + 1) % count]
            perimeter += Math.hypot(b.x - a.x, b.y - a.y)
        }
        const circle = this.circle
        const extent = Math.min(this.rightPointX - this.leftPointX, this.bottomOffset - this.topOffset)
        const shards = []
        for (let n = 0; n < fxStyle.shardCount; ++n)
        {
            // Evenly round the outline, jittered within its slot
            let along = (n + 0.2 + 0.6 * random()) / fxStyle.shardCount * perimeter
            let i = 0
            let a = points[0], b = points[1 % count]
            let length = Math.hypot(b.x - a.x, b.y - a.y)
            while (along > length && i < count - 1)
            {
                along -= length
                ++i
                a = points[i]
                b = points[(i + 1) % count]
                length = Math.hypot(b.x - a.x, b.y - a.y)
            }
            const k = length > 0 ? Math.min(1, along / length) : 0
            const x = a.x + (b.x - a.x) * k, y = a.y + (b.y - a.y) * k
            const angle = Math.atan2(y - circle.y, x - circle.x) + (random() - 0.5) * 0.6
            shards.push({x: x, y: y, dx: Math.cos(angle), dy: Math.sin(angle),
                         travel: circle.radius * lerp(fxStyle.shardTravel, random()),
                         size: extent * lerp(fxStyle.shardSize, random()),
                         angle: random() * Math.PI * 2,
                         spin: (random() * 2 - 1) * fxStyle.shardSpin * Math.PI * 2})
        }
        return shards
    }
    // The shards at fade progress 1 - alpha: neon triangles (fill + stroke
    // in the blue's colours; bloom pass: the stroke alone)
    drawShards(alpha)
    {
        const fxStyle = STYLE.momentumFx
        const t = 1 - alpha
        const ease = 1 - (1 - t) * (1 - t)
        const fall = fxStyle.shardFall * this.circle.radius * t * t
        const ox = this.x + screen.x, oy = this.y + screen.y
        ctx.save()
        ctx.lineJoin = 'round'
        ctx.lineWidth = (bloomPassActive ? STYLE.bloom.lineWidth : STYLE.strokes.neonOutline.innerWidth) / scale[version]
        ctx.strokeStyle = this.getGlowStroke()
        ctx.fillStyle = this.stroke
        for (const shard of this.shards)
        {
            const cx = ox + shard.x + shard.dx * shard.travel * ease
            const cy = oy + shard.y + shard.dy * shard.travel * ease + fall
            const angle = shard.angle + shard.spin * t
            const r = shard.size / Math.sqrt(3)
            ctx.beginPath()
            for (let v = 0; v < 3; ++v)
            {
                const a = angle + v * Math.PI * 2 / 3
                // A slightly stretched triangle reads as a splinter
                const s = v == 0 ? 1.5 : 1
                const px = cx + Math.cos(a) * r * s, py = cy + Math.sin(a) * r * s
                if (v == 0)
                    ctx.moveTo(px, py)
                else
                    ctx.lineTo(px, py)
            }
            ctx.closePath()
            if (!bloomPassActive)
            {
                ctx.globalAlpha = alpha * fxStyle.shardFillAlpha
                ctx.fill()
            }
            ctx.globalAlpha = alpha
            ctx.stroke()
        }
        ctx.restore()
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
        // A used blue (MOMENTUM_FX): shards instead of the fading outline
        const shards = !!this.shards && version == 'momentum' && MOMENTUM_FX.enabled
        this.drawBadVersionPolygon(this.badVersionFill, this.stroke,
            {baseFillStyle: this.fill, alpha: alpha, noOutline: shards})
        if (this.hasInnerShell())
            this.drawInnerShell(alpha)
        if (shards)
            this.drawShards(alpha)
    }
}
