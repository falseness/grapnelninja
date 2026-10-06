class JumpingCube extends Rect
{
    constructor(object)
    {
        super(object)
        this.mass = this.height * this.width * blueSpriteDensity
        
        this.track = new CubeTrackLine(this.width, this.height, this.stroke, STYLE.timing.cubeTrailPoints)
        this.track.addPos(this.x + this.circle.x, this.y + this.circle.y, true)
        
        let cycles = random() * cyclesPerTick
        for (let i = 0; i < cycles; ++i)
        {
            this.move()
        }
    }
    move()
    {
        this.speedY += GRAVITY
        this.collisionWithElements()

        this.track.addPos(this.x + this.circle.x, this.y + this.circle.y)
    }
    // Off-screen cubes and the warm-up moves in the constructor stay silent
    isOnScreen()
    {
        if (!floors || !floors.some(floor => floor.elements.includes(this)))
            return false
        const viewWidth = width / scale[version]
        const viewHeight = height / scale[version]
        const x = this.x + screen.x
        const y = this.y + screen.y
        return x + this.width > 0 && x < viewWidth && y + this.height > 0 && y < viewHeight
    }
    collisionWithElements()
    {
        // Sweep each axis before moving, so even thin obstacles cannot be skipped.
        // Conservative polygon bounds also cover containment and collinear edges.
        const obstacles = []
        let maxPad = 0
        for (const floor of floors)
        {
            for (const element of floor.elements)
            {
                if (element === this)
                    continue
                const bounds = pointsBounds(element.getPoints())
                // Triangles move independently; pad by one step of their motion so the
                // cube bounces off the triangle itself without penetrating it next step.
                bounds.pad = element instanceof Triangle ? Math.abs(element.speedY) : 0
                bounds.top -= bounds.pad
                bounds.bottom += bounds.pad
                maxPad = Math.max(maxPad, bounds.pad)
                obstacles.push(bounds)
            }
        }
        // Broad phase: an obstacle can only stop the cube within one step of either
        // axis (a padded stop moves at most maxPad + epsilon), so the rest are skipped.
        const reach = Math.abs(this.speedX) + Math.abs(this.speedY) + 2 * maxPad
            + 2 * GAMEPLAY.cubeContactEpsilon + defaultEqualityTolerance
        const sweep = {left: this.x - reach, right: this.x + this.width + reach,
                       top: this.y - reach, bottom: this.y + this.height + reach}
        const candidates = obstacles.filter(bounds => boundsOverlap(sweep, bounds))

        for (const axis of ['x', 'y'])
        {
            const vertical = axis == 'y'
            const speed = vertical ? 'speedY' : 'speedX'
            const size = vertical ? this.height : this.width
            const crossStart = vertical ? this.x : this.y
            const crossEnd = crossStart + (vertical ? this.width : this.height)
            let distance = this[speed]
            let away = 0
            let minAwaySpeed = 0
            for (const bounds of candidates)
            {
                const crossMin = vertical ? bounds.left : bounds.top
                const crossMax = vertical ? bounds.right : bounds.bottom
                if (crossEnd <= crossMin || crossStart >= crossMax)
                    continue
                const near = vertical ? bounds.top : bounds.left
                const far = vertical ? bounds.bottom : bounds.right
                const end = this[axis] + size
                // A moving triangle closes the gap by itself, so a cube inside its
                // padding is in contact too and gets pushed out to the padded edge.
                const pad = vertical ? bounds.pad : 0
                if ((distance > 0 || pad > 0) && end <= near + pad && end + distance >= near)
                {
                    const stop = near - end - GAMEPLAY.cubeContactEpsilon
                    distance = pad > 0 ? stop : Math.max(0, stop)
                    away = -1
                    minAwaySpeed = Math.max(minAwaySpeed, pad)
                }
                else if ((distance < 0 || pad > 0) && this[axis] >= far - pad && this[axis] + distance <= far)
                {
                    const stop = far - this[axis] + GAMEPLAY.cubeContactEpsilon
                    distance = pad > 0 ? stop : Math.min(0, stop)
                    away = 1
                    minAwaySpeed = Math.max(minAwaySpeed, pad)
                }
            }
            this[axis] += distance
            this[vertical ? 'dy' : 'dx'] = distance
            if (away != 0 && Math.sign(this[speed]) != away)
            {
                this[speed] *= -1
                if (vertical)
                    this.speedY += this.speedY > 0 ? GRAVITY : -GRAVITY
            }
            // Leave at least as fast as the triangle approaches, or it catches up.
            if (away * this[speed] < minAwaySpeed)
                this[speed] = away * minAwaySpeed
        }
    }
}

// Trail of cube centres drawn as the union of the squares swept between them,
// so it matches the cube silhouette for motion in any direction.
class CubeTrackLine extends TrackLine
{
    constructor(width, height, stroke, pointsLimit)
    {
        super(width, stroke, pointsLimit)
        this.width  = width
        this.height = height
    }
    getSweptHull(a, b)
    {
        const w = this.width / 2
        const h = this.height / 2
        const corners = []
        for (const p of [a, b])
            for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]])
                corners.push({x: p.x + sx * w, y: p.y + sy * h})
        corners.sort((p, q) => p.x - q.x || p.y - q.y)
        // Monotone chain: every hull comes out with the same winding.
        const cross = (o, p, q) => (p.x - o.x) * (q.y - o.y) - (p.y - o.y) * (q.x - o.x)
        const half = points =>
        {
            const chain = []
            for (const p of points)
            {
                while (chain.length >= 2 && cross(chain[chain.length - 2], chain[chain.length - 1], p) <= 0)
                    chain.pop()
                chain.push(p)
            }
            chain.pop()
            return chain
        }
        return half(corners).concat(half(corners.slice().reverse()))
    }
    draw()
    {
        if (trackEnabled && QUALITY.playerTrail && this.pos.length > 0)
        {
            const pairs = []
            for (let i = 0; i < this.pos.length; ++i)
                pairs.push([this.pos[i], this.pos[Math.min(i + 1, this.pos.length - 1)]])
            if (this.pos.length > 1)
                pairs.pop()

            ctx.beginPath()
            for (const [a, b] of pairs)
            {
                const hull = this.getSweptHull(a, b)
                ctx.moveTo(hull[0].x + screen.x, hull[0].y + screen.y)
                for (let i = 1; i < hull.length; ++i)
                    ctx.lineTo(hull[i].x + screen.x, hull[i].y + screen.y)
                ctx.closePath()
            }
            ctx.globalAlpha = STYLE.alpha.track
            ctx.fillStyle   = this.stroke
            ctx.fill('nonzero')
            ctx.globalAlpha = STYLE.alpha.full
        }
    }
}
