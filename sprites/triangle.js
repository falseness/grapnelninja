class Triangle extends Element
{
    constructor(object)
    {
        super(object)
    
        this.speedY =   screenHeightPercent(GAMEPLAY.triangleSpeedHeightPercent) / cyclesPerTick
        if (random() < GAMEPLAY.triangleUpwardChancePercent)
            this.speedY *= -1
        
        this.side   =   object.radius * Math.sqrt(3)
        this.height =   this.side * Math.sin(Math.PI / 3)
        this.radius = object.radius
        
        this.restrictionY = 
        {
            min: object.yMin,
            max: object.yMax
        }
        this.track = (trackEnabled)?(new MultipointTrackLine(this.side, this.stroke, STYLE.timing.triangleTrailPoints)):(new Empty())
        this.track.addPos(this.getPoints(), true)
    }
    getCircumscribedCircle()
    {
        // One object per element, refilled: every caller reads it at once
        const circle = this.circumscribedCircle || (this.circumscribedCircle = {x: 0, y: 0, radius: 0})
        circle.x = this.x
        circle.y = this.y
        circle.radius = this.radius
        return circle
    }
    move()
    {
        this.changeSpeed()
        this.y += this.speedY
        this.dy = this.speedY
        
        this.track.addPos(this.getPoints())
        
            
    }
    getRightPointX()
    {
        return this.getX() + this.side / 2
    }
    getLeftPointX()
    {
        return this.getX() - this.side / 2
    }
    getTopPointY()
    {
        return this.getY() - this.height * (1 / 3)
    }
    getBottomPointY()
    {
        return this.getY() + this.height * (2 / 3)
    }
    getPoints()
    {
        let x = this.getX()
        let y = this.getY()
        
        let points = 
        [
            {x: x - this.side / 2   , y: y - this.height * (1 / 3)},
            {x: x + this.side / 2   , y: y - this.height * (1 / 3)},
            {x: x                   , y: y + this.height * (2 / 3)}
        ]
        return points
    }
    writeBounds(out)
    {
        const x = this.getX()
        const y = this.getY()

        startBounds(out, x - this.side / 2, y - this.height * (1 / 3))
        addBoundsPoint(out, x + this.side / 2, y - this.height * (1 / 3))
        addBoundsPoint(out, x, y + this.height * (2 / 3))
        return out
    }
    changeSpeed()
    {
        if (this.getTopPointY() < this.restrictionY.min || this.getBottomPointY() > this.restrictionY.max)
            this.speedY *= -1
    }
    // Done by draw(), and by Floor.draw for culled triangles, so the trail colour
    // does not depend on whether the triangle was on screen.
    syncTrackStyle()
    {
        if (version != 'bad')
            this.track.stroke = STYLE.colors.hazard.classicTriangleStroke
    }
    getGlowStroke()
    {
        return version != 'bad' ? STYLE.colors.hazard.classicTriangleStroke : this.stroke
    }
    draw()
    {
        this.syncTrackStyle()
        if (version != 'bad')
        {
            this.drawClassicGameplayTriangle()
            return
        }

        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const isHarmless = this instanceof HarmlessTriangle
        this.drawBadVersionPolygon(
            isHarmless ? STYLE.colors.hazard.harmlessFill : obstacleStyle.hazardFill,
            this.stroke
        )

        this.drawBadVersionInnerTreatment()
    }
    drawClassicGameplayTriangle()
    {
        const fill = STYLE.colors.hazard.classicTriangleFill
        const stroke = STYLE.colors.hazard.classicTriangleStroke
        const points = this.getPoints()

        ctx.save()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
        {
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        }

        ctx.closePath()

        ctx.fillStyle = fill
        ctx.fill()

        strokeNeonPath(stroke)

        ctx.restore()
    }
    drawBadVersionInnerTreatment()
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const points = this.getPoints()
        const centerX = this.x + screen.x
        const centerY = this.y + screen.y
        const innerScale = obstacleStyle.hazardInnerScale

        ctx.save()
        ctx.beginPath()
        for (let i = 0; i < points.length; ++i)
        {
            const x = centerX + (points[i].x - this.x) * innerScale
            const y = centerY + (points[i].y - this.y) * innerScale

            if (i == 0)
                ctx.moveTo(x, y)
            else
                ctx.lineTo(x, y)
        }
        ctx.closePath()
        ctx.strokeStyle = this.stroke
        ctx.lineWidth = STYLE.strokes.neonOutline.innerWidth / scale[version]
        ctx.globalAlpha = obstacleStyle.hazardInnerStrokeAlpha
        ctx.stroke()
        ctx.restore()
    }
}

class HarmlessTriangle extends Triangle{
    collision() {

    }
}

class MultipointTrackLine extends TrackLine
{
    constructor(width, stroke, pointsLimit)
    {
        super(width, stroke, pointsLimit)
    }
    addPos(point, mustAdd)
    {
        if ((trackEnabled && QUALITY.playerTrail && firstCycleInThisTick) || mustAdd)
        {
            this.pos.push(point)
            this.delete()
        }
    }
    draw()
    {
        if (!trackEnabled || !QUALITY.playerTrail || this.pos.length < 2)
            return

        // Faint historical outlines preserve motion without filling the swept
        // bounding envelope, which looked like rectangular lighting patches.
        const config = STYLE.trails.hazard
        ctx.save()
        ctx.strokeStyle = this.stroke
        ctx.lineJoin = 'round'
        ctx.lineWidth = config.envelopeLineWidth
        for (let i = 0; i < this.pos.length - 1; i += config.sampleStep)
        {
            const age = (i + 1) / this.pos.length
            ctx.globalAlpha = config.maxAlpha * age * age
            const points = this.pos[i]
            ctx.beginPath()
            ctx.moveTo(points[0].x + screen.x, points[0].y + screen.y)
            for (let j = 1; j < points.length; ++j)
                ctx.lineTo(points[j].x + screen.x, points[j].y + screen.y)
            ctx.closePath()
            ctx.stroke()
        }
        ctx.restore()
    }
}
