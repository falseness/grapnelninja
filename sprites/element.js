class Element
{
    constructor(object)
    {
        this.speedX = 0
        this.speedY = 0
        
        this.x      = object.x
        this.y      = object.y

        this.fill   = object.fill
        this.stroke = object.stroke
        
        this.track  = new Empty()
        
        this.scored = false
    }
    isToRightThanEdgeOfScreen()
    {
        return this.getLeftPointX() > width
    }
    move()
    {
        
    }
    getX()
    {
        return this.x
    }
    getY()
    {
        return this.y
    }
    moveY()
    {
        
    }
    getLines()
    {
        let points = this.getPoints()
        let res = []
        for (let i = 1; i < points.length; ++i)
        {
            res.push(lineFormula(points[i - 1].x, points[i - 1].y, points[i].x, points[i].y))
        }
        
        res.push(lineFormula(points[points.length - 1].x, points[points.length - 1].y, points[0].x, points[0].y))
        
        return res
    }
    collision()
    {
        reStart()
    }
    isEmpty()
    {
        return false
    }
    isPairElement()
    {
        return false
    }
    draw()
    {
        const strokeWidth = STYLE.strokes.neonWidth

        ctx.save()
        ctx.beginPath()

        let points = this.getPoints()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
        {
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        }
        
        ctx.fillStyle   = this.fill
        ctx.fill()

        ctx.strokeStyle = this.stroke
        ctx.lineWidth = strokeWidth
        ctx.shadowColor = this.stroke
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
    drawBadVersionPolygon(fillStyle, strokeStyle, options)
    {
        options = options || {}
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const points = this.getPoints()
        const lineWidth = options.lineWidth || obstacleStyle.thinStrokeWidth
        const glowWidth = options.glowWidth || obstacleStyle.outerGlowWidth

        ctx.save()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
        {
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        }

        if (options.baseFillStyle)
        {
            ctx.fillStyle = options.baseFillStyle
            ctx.fill()
        }

        ctx.fillStyle = fillStyle
        ctx.fill()

        ctx.strokeStyle = strokeStyle
        ctx.lineWidth = glowWidth
        ctx.globalAlpha = options.glowAlpha || obstacleStyle.highlightAlpha
        ctx.shadowColor = strokeStyle
        ctx.shadowBlur = glowWidth
        ctx.stroke()

        ctx.globalAlpha = 1
        ctx.lineWidth = lineWidth
        ctx.shadowBlur = 0
        ctx.stroke()

        if (options.innerStrokeStyle)
        {
            ctx.globalAlpha = obstacleStyle.innerHighlightAlpha
            ctx.lineWidth = lineWidth
            ctx.strokeStyle = options.innerStrokeStyle
            ctx.stroke()
        }

        ctx.closePath()
        ctx.restore()
    }
}

class FrameGrapnelMarker
{
    constructor(object)
    {
        this.points = object.points
        this.stroke = object.stroke
        this.strokeWidth = object.strokeWidth
        this.scored = false
        this.track = new Empty()
    }
    move()
    {

    }
    isPairElement()
    {
        return false
    }
    getLeftPointX()
    {
        return Math.min(...this.points.map(point => point.x))
    }
    getRightPointX()
    {
        return Math.max(...this.points.map(point => point.x))
    }
    getCircumscribedCircle()
    {
        return {x: this.getRightPointX(), y: this.points[0].y, radius: 0}
    }
    getLines()
    {
        return []
    }
    draw()
    {
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(this.points[0].x + screen.x, this.points[0].y + screen.y)

        for (let i = 1; i < this.points.length; ++i)
        {
            if (i == 2 || i == 4)
                ctx.moveTo(this.points[1].x + screen.x, this.points[1].y + screen.y)

            ctx.lineTo(this.points[i].x + screen.x, this.points[i].y + screen.y)
        }

        ctx.strokeStyle = this.stroke
        ctx.lineWidth = this.strokeWidth
        ctx.stroke()
        ctx.closePath()
        ctx.restore()
    }
}
