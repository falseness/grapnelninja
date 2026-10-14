// Pooled obstacle boxes and sweep box: collisionWithElements runs for every
// cube on every physics step, and never re-enters itself
const cubeObstacles = []
const cubeSweep = {left: 0, right: 0, top: 0, bottom: 0}

class JumpingCube extends Rect
{
    constructor(object)
    {
        super(object)
        // Opaque stripes at 60% of the blue outline, computed once per cube.
        if (this.stroke == STYLE.colors.cube.blueStroke)
            this.hatchColour = '#' + this.stroke.slice(1).match(/../g)
                .map(channel => Math.round(parseInt(channel, 16) * .6).toString(16).padStart(2, '0')).join('')
        this.mass = this.height * this.width * blueSpriteDensity
        
        this.track = new CubeTrackLine(this.width, this.height, this.stroke, STYLE.timing.cubeTrailPoints)
        this.track.addPos(this.x + this.circle.x, this.y + this.circle.y, true)
        
        let cycles = random() * cyclesPerTick
        for (let i = 0; i < cycles; ++i)
        {
            this.move()
        }
    }
    drawDangerHatch(x, y)
    {
        super.drawDangerHatch(x, y, this.hatchColour)
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
        const obstacles = cubeObstacles
        let count = 0
        let maxPad = 0
        for (let k = 0; k < floors.length; ++k)
        {
            const elements = floors[k].elements
            for (let i = 0; i < elements.length; ++i)
            {
                const element = elements[i]
                if (element === this)
                    continue
                if (count == obstacles.length)
                    obstacles.push({left: 0, right: 0, top: 0, bottom: 0, pad: 0})
                const bounds = elementBounds(element, obstacles[count++])
                // Triangles move independently; pad by one step of their motion so the
                // cube bounces off the triangle itself without penetrating it next step.
                bounds.pad = element instanceof Triangle ? Math.abs(element.speedY) : 0
                bounds.top -= bounds.pad
                bounds.bottom += bounds.pad
                maxPad = Math.max(maxPad, bounds.pad)
            }
        }
        // Broad phase: an obstacle can only stop the cube within one step of either
        // axis (a padded stop moves at most maxPad + epsilon), so the rest are skipped.
        const reach = Math.abs(this.speedX) + Math.abs(this.speedY) + 2 * maxPad
            + 2 * GAMEPLAY.cubeContactEpsilon + defaultEqualityTolerance
        const sweep = cubeSweep
        sweep.left = this.x - reach
        sweep.right = this.x + this.width + reach
        sweep.top = this.y - reach
        sweep.bottom = this.y + this.height + reach
        // The overlapping boxes move to the front, in order
        let candidateCount = 0
        for (let i = 0; i < count; ++i)
        {
            const bounds = obstacles[i]
            if (!boundsOverlap(sweep, bounds))
                continue
            obstacles[i] = obstacles[candidateCount]
            obstacles[candidateCount++] = bounds
        }

        for (let a = 0; a < 2; ++a)
        {
            const axis = a == 0 ? 'x' : 'y'
            const vertical = axis == 'y'
            const speed = vertical ? 'speedY' : 'speedX'
            const size = vertical ? this.height : this.width
            const crossStart = vertical ? this.x : this.y
            const crossEnd = crossStart + (vertical ? this.width : this.height)
            let distance = this[speed]
            let away = 0
            let minAwaySpeed = 0
            for (let c = 0; c < candidateCount; ++c)
            {
                const bounds = obstacles[c]
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

// Scratch buffers of CubeTrackLine.writeSweptHull (8 corners, hull of at most 8)
const CUBE_HULL = {
    xs: new Float64Array(8), ys: new Float64Array(8),
    order: new Int8Array(8), chain: new Int8Array(8), out: new Float64Array(16)
}

function hullCross(xs, ys, o, p, q)
{
    return (xs[p] - xs[o]) * (ys[q] - ys[o]) - (ys[p] - ys[o]) * (xs[q] - xs[o])
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
    // Convex hull of the two squares centred on a and b, written as x, y
    // pairs into CUBE_HULL.out; returns the vertex count. Andrew's monotone
    // chain over the same 8 corners in the same order as before (stable
    // sort, collinear points dropped), so every hull has the same winding,
    // but on reused typed arrays: no allocation per trail segment.
    writeSweptHull(a, b)
    {
        const w = this.width / 2
        const h = this.height / 2
        const {xs, ys, order, chain, out} = CUBE_HULL
        let n = 0
        for (let k = 0; k < 2; ++k)
        {
            const p = k ? b : a
            xs[n] = p.x - w; ys[n] = p.y - h; ++n
            xs[n] = p.x + w; ys[n] = p.y - h; ++n
            xs[n] = p.x + w; ys[n] = p.y + h; ++n
            xs[n] = p.x - w; ys[n] = p.y + h; ++n
        }
        // Stable insertion sort by x, then y
        for (let i = 0; i < 8; ++i)
            order[i] = i
        for (let i = 1; i < 8; ++i)
        {
            const v = order[i]
            let j = i - 1
            while (j >= 0 && (xs[order[j]] - xs[v] || ys[order[j]] - ys[v]) > 0)
            {
                order[j + 1] = order[j]
                --j
            }
            order[j + 1] = v
        }
        let count = 0
        for (let pass = 0; pass < 2; ++pass)
        {
            let length = 0
            for (let i = 0; i < 8; ++i)
            {
                const p = order[pass ? 7 - i : i]
                while (length >= 2 && hullCross(xs, ys, chain[length - 2], chain[length - 1], p) <= 0)
                    --length
                chain[length++] = p
            }
            // The chain's last point starts the other half
            for (let i = 0; i < length - 1; ++i)
            {
                out[count * 2] = xs[chain[i]]
                out[count * 2 + 1] = ys[chain[i]]
                ++count
            }
        }
        return count
    }
    draw()
    {
        if (trackEnabled && QUALITY.playerTrail && this.pos.length > 0)
        {
            // Segment i joins pos[i] and pos[i + 1]; a single point is one
            // square
            const pos = this.pos
            const segments = pos.length > 1 ? pos.length - 1 : 1
            const out = CUBE_HULL.out

            ctx.beginPath()
            for (let i = 0; i < segments; ++i)
            {
                const count = this.writeSweptHull(pos[i], pos[Math.min(i + 1, pos.length - 1)])
                ctx.moveTo(out[0] + screen.x, out[1] + screen.y)
                for (let j = 1; j < count; ++j)
                    ctx.lineTo(out[j * 2] + screen.x, out[j * 2 + 1] + screen.y)
                ctx.closePath()
            }
            ctx.globalAlpha = STYLE.alpha.track
            ctx.fillStyle   = this.stroke
            ctx.fill('nonzero')
            ctx.globalAlpha = STYLE.alpha.full
        }
    }
}
