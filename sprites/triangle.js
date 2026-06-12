class Triangle extends Element
{
    constructor(object)
    {
        super(object)
    
        this.speedY =   0.005 * height / cyclesPerTick
        if (random() < 50)
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
        return {x: this.x, y: this.y, radius: this.radius}
    }
    move()
    {
        this.changeSpeed()
        this.y += this.speedY
        
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
    changeSpeed()
    {
        if (this.getTopPointY() < this.restrictionY.min || this.getBottomPointY() > this.restrictionY.max)
            this.speedY *= -1
    }
    draw()
    {
        if (version != 'bad')
        {
            this.track.stroke = STYLE.colors.hazard.classicTriangleStroke
            this.drawClassicGameplayTriangle()
            return
        }

        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const isHarmless = this instanceof HarmlessTriangle
        this.drawBadVersionPolygon(
            isHarmless ? STYLE.colors.hazard.harmlessFill : obstacleStyle.hazardFill,
            this.stroke,
            {
                lineWidth: obstacleStyle.thinStrokeWidth,
                glowWidth: obstacleStyle.outerGlowWidth,
                innerStrokeStyle: this.stroke
            }
        )

        this.drawBadVersionInnerTreatment()
    }
    drawClassicGameplayTriangle()
    {
        const fill = STYLE.colors.hazard.classicTriangleFill
        const stroke = STYLE.colors.hazard.classicTriangleStroke
        const strokeWidth = STYLE.strokes.neonWidth
        const points = this.getPoints()

        ctx.save()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
        {
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        }

        ctx.fillStyle = fill
        ctx.fill()

        ctx.strokeStyle = stroke
        ctx.lineWidth = strokeWidth
        ctx.shadowColor = stroke
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
    drawBadVersionInnerTreatment()
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const points = this.getPoints()
        const centerX = this.x + screen.x
        const centerY = this.y + screen.y
        const scale = obstacleStyle.hazardInnerScale

        ctx.save()
        ctx.beginPath()
        for (let i = 0; i < points.length; ++i)
        {
            const x = centerX + (points[i].x - this.x) * scale
            const y = centerY + (points[i].y - this.y) * scale

            if (i == 0)
                ctx.moveTo(x, y)
            else
                ctx.lineTo(x, y)
        }
        ctx.closePath()
        ctx.strokeStyle = this.stroke
        ctx.lineWidth = obstacleStyle.thinStrokeWidth
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
        if (trackEnabled && QUALITY.playerTrail)
        {
            if (version == 'bad')
            {
                this.drawBadVersionTrail()
                return
            }

            ctx.beginPath()

            //Работает только в частном случае
            let min0, min1, max0, max1, max2

            let extremum =
            [
                {min: this.pos[0][0].y, max: this.pos[0][0].y},
                {min: this.pos[0][1].y, max: this.pos[0][1].y},
                {min: this.pos[0][2].y, max: this.pos[0][2].y}
            ]
            for (let i = 0; i < this.pos.length; ++i)
            {
                for (let j = 0; j < this.pos[i].length; ++j)
                {
                    if (this.pos[i][j].y < extremum[j].min)
                        extremum[j].min = this.pos[i][j].y
                    if (this.pos[i][j].y > extremum[j].max)
                        extremum[j].max = this.pos[i][j].y
                }
            }
            ctx.moveTo(this.pos[0][0].x + screen.x, extremum[0].min + screen.y)
            ctx.lineTo(this.pos[0][0].x + screen.x, extremum[0].max + screen.y)
            ctx.lineTo(this.pos[0][2].x + screen.x, extremum[2].max + screen.y)
            ctx.lineTo(this.pos[0][1].x + screen.x, extremum[1].max + screen.y)
            ctx.lineTo(this.pos[0][1].x + screen.x, extremum[1].min + screen.y)
            ctx.lineTo(this.pos[0][0].x + screen.x, extremum[0].min + screen.y)

            ctx.globalAlpha = STYLE.alpha.multipointTrack
            ctx.fillStyle = this.stroke
            ctx.fill()
            ctx.globalAlpha = STYLE.alpha.full

            ctx.closePath()  
        }
    }
    drawBadVersionTrail()
    {
        if (this.pos.length < 2)
            return

        const config = STYLE.trails.hazard
        const extremum = this.getPointExtremes()

        ctx.save()
        ctx.beginPath()
        ctx.moveTo(this.pos[0][0].x + screen.x, extremum[0].min + screen.y)
        ctx.lineTo(this.pos[0][0].x + screen.x, extremum[0].max + screen.y)
        ctx.lineTo(this.pos[0][2].x + screen.x, extremum[2].max + screen.y)
        ctx.lineTo(this.pos[0][1].x + screen.x, extremum[1].max + screen.y)
        ctx.lineTo(this.pos[0][1].x + screen.x, extremum[1].min + screen.y)
        ctx.closePath()

        ctx.shadowColor = this.stroke
        ctx.globalCompositeOperation = STYLE.visualStability.stableBrightness
            ? STYLE.visualStability.effectCompositeOperation
            : 'lighter'

        ctx.fillStyle = this.stroke
        ctx.shadowBlur = config.glowBlur
        ctx.globalAlpha = config.envelopeGlowAlpha
        ctx.fill()

        ctx.shadowBlur = 0
        ctx.globalAlpha = config.envelopeAlpha
        ctx.fill()

        ctx.strokeStyle = this.stroke
        ctx.lineJoin = 'round'
        ctx.lineWidth = config.envelopeGlowWidth
        ctx.shadowBlur = config.glowBlur
        ctx.globalAlpha = config.envelopeGlowAlpha
        ctx.stroke()

        ctx.shadowBlur = 0
        ctx.lineWidth = config.envelopeLineWidth
        ctx.globalAlpha = config.outlineAlpha
        ctx.stroke()
        ctx.restore()
    }
    getPointExtremes()
    {
        const extremum =
        [
            {min: this.pos[0][0].y, max: this.pos[0][0].y},
            {min: this.pos[0][1].y, max: this.pos[0][1].y},
            {min: this.pos[0][2].y, max: this.pos[0][2].y}
        ]

        for (let i = 0; i < this.pos.length; ++i)
        {
            for (let j = 0; j < this.pos[i].length; ++j)
            {
                if (this.pos[i][j].y < extremum[j].min)
                    extremum[j].min = this.pos[i][j].y
                if (this.pos[i][j].y > extremum[j].max)
                    extremum[j].max = this.pos[i][j].y
            }
        }

        return extremum
    }
}
