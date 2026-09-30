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
    collisionWithElements()
    {
        // Sweep each axis before moving, so even thin obstacles cannot be skipped.
        // Conservative polygon bounds also cover containment and collinear edges.
        const obstacles = []
        for (const floor of floors)
        {
            for (const element of floor.elements)
            {
                if (element === this)
                    continue
                const points = element.getPoints()
                const bounds = {
                    left: Math.min(...points.map(point => point.x)),
                    right: Math.max(...points.map(point => point.x)),
                    top: Math.min(...points.map(point => point.y)),
                    bottom: Math.max(...points.map(point => point.y))
                }
                // Triangles move independently; reserve their full vertical travel,
                // including the one-step overshoot of Triangle.changeSpeed().
                if (element instanceof Triangle)
                {
                    bounds.top = Math.min(bounds.top, element.restrictionY.min - Math.abs(element.speedY))
                    bounds.bottom = Math.max(bounds.bottom, element.restrictionY.max + Math.abs(element.speedY))
                }
                obstacles.push(bounds)
            }
        }

        for (const axis of ['x', 'y'])
        {
            const vertical = axis == 'y'
            const speed = vertical ? 'speedY' : 'speedX'
            const size = vertical ? this.height : this.width
            const crossStart = vertical ? this.x : this.y
            const crossEnd = crossStart + (vertical ? this.width : this.height)
            let distance = this[speed]
            let collided = false
            for (const bounds of obstacles)
            {
                const crossMin = vertical ? bounds.left : bounds.top
                const crossMax = vertical ? bounds.right : bounds.bottom
                if (crossEnd <= crossMin || crossStart >= crossMax)
                    continue
                const near = vertical ? bounds.top : bounds.left
                const far = vertical ? bounds.bottom : bounds.right
                const end = this[axis] + size
                if (distance > 0 && end <= near && end + distance >= near)
                {
                    distance = Math.max(0, near - end - GAMEPLAY.cubeContactEpsilon)
                    collided = true
                }
                else if (distance < 0 && this[axis] >= far && this[axis] + distance <= far)
                {
                    distance = Math.min(0, far - this[axis] + GAMEPLAY.cubeContactEpsilon)
                    collided = true
                }
            }
            this[axis] += distance
            this[vertical ? 'dy' : 'dx'] = distance
            if (collided)
            {
                this[speed] *= -1
                if (vertical)
                    this.speedY += this.speedY > 0 ? GRAVITY : -GRAVITY
            }
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
