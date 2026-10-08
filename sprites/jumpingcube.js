// Pooled obstacle boxes and sweep box: collisionWithElements runs for every
// cube on every physics step, and never re-enters itself
const cubeObstacles = []
const cubeSweep = {left: 0, right: 0, top: 0, bottom: 0}

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
    draw()
    {
        if (!trackEnabled || !QUALITY.playerTrail || this.pos.length < 2)
            return

        // One fading stroke avoids both flat-ended rectangles and alpha
        // accumulation where adjacent segments overlap on slow-moving cubes.
        const first = this.pos[0], last = this.pos[this.pos.length - 1]
        if (Math.hypot(last.x - first.x, last.y - first.y) < 1)
            return

        ctx.save()
        const fade = ctx.createLinearGradient(first.x + screen.x, first.y + screen.y,
            last.x + screen.x, last.y + screen.y)
        fade.addColorStop(0, colorWithAlpha(this.stroke, 0))
        fade.addColorStop(1, colorWithAlpha(this.stroke, STYLE.trails.hazard.maxAlpha))
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        ctx.strokeStyle = fade
        ctx.lineWidth = this.lineWidth * 0.5
        ctx.beginPath()
        ctx.moveTo(first.x + screen.x, first.y + screen.y)
        for (let i = 1; i < this.pos.length; ++i)
            ctx.lineTo(this.pos[i].x + screen.x, this.pos[i].y + screen.y)
        ctx.stroke()
        ctx.restore()
    }
}
