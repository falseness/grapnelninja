class JumpingCube extends Rect
{
    constructor(object)
    {
        super(object)
        this.mass = this.height * this.width * blueSpriteDensity
        
        this.track = new TrackLine(this.width, this.stroke, STYLE.timing.cubeTrailPoints)
        this.track.addPos(this.x + this.circle.x, this.y, true)
        
        let cycles = random() * cyclesPerTick
        for (let i = 0; i < cycles; ++i)
        {
            this.move()
        }
    }
    getBottomPointY()
    {
        return this.y + this.height
    }
    move()
    {
        this.speedY += GRAVITY
        this.collisionWithElements()

        if (this.speedY > 0)
            this.track.addPos(this.x + this.circle.x, this.y)
        else
            this.track.addPos(this.x + this.circle.x, this.getBottomPointY())

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
            if (collided)
            {
                this[speed] *= -1
                if (vertical)
                    this.speedY += this.speedY > 0 ? GRAVITY : -GRAVITY
            }
        }
    }
}
