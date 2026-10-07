class Element
{
    constructor(object)
    {
        this.speedX = 0
        this.speedY = 0
        // Displacement applied by the last move(); tethered grapnel points follow it.
        this.dx = 0
        this.dy = 0
        
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
        onLethalDeath()
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
    // Elements without a 3D look (triangles, sides, ground) keep this no-op.
    drawExtrusion()
    {

    }
    // Back face plus the side faces of the edges that face the light direction,
    // drawn before any front face so neighbours never cover each other's fronts.
    drawPolygonExtrusion()
    {
        const extrusion = STYLE.extrusion
        const points = this.getPoints()
        const count = points.length

        let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity, area = 0
        for (let i = 0; i < count; ++i)
        {
            const a = points[i]
            const b = points[(i + 1) % count]
            left = Math.min(left, a.x)
            right = Math.max(right, a.x)
            top = Math.min(top, a.y)
            bottom = Math.max(bottom, a.y)
            area += a.x * b.y - b.x * a.y
        }
        const depth = Math.min(extrusion.depth / scale[version], Math.min(right - left, bottom - top) * extrusion.maxDepthRatio)
        if (!(depth > 0) || area == 0)
            return

        const length = Math.hypot(extrusion.directionX, extrusion.directionY)
        const offsetX = depth * extrusion.directionX / length
        const offsetY = depth * extrusion.directionY / length
        const winding = Math.sign(area)
        const sx = screen.x
        const sy = screen.y

        ctx.save()
        ctx.beginPath()
        // Back face
        ctx.moveTo(points[count - 1].x + offsetX + sx, points[count - 1].y + offsetY + sy)
        for (let i = 0; i < count; ++i)
            ctx.lineTo(points[i].x + offsetX + sx, points[i].y + offsetY + sy)
        ctx.closePath()
        // Side faces of the lit edges (outward normal towards the offset)
        for (let i = 0; i < count; ++i)
        {
            const a = points[i]
            const b = points[(i + 1) % count]
            if (winding * ((b.y - a.y) * offsetX - (b.x - a.x) * offsetY) <= 0)
                continue
            // Same winding as the faces, so the nonzero fill is their union
            ctx.moveTo(a.x + sx, a.y + sy)
            ctx.lineTo(a.x + offsetX + sx, a.y + offsetY + sy)
            ctx.lineTo(b.x + offsetX + sx, b.y + offsetY + sy)
            ctx.lineTo(b.x + sx, b.y + sy)
            ctx.closePath()
        }
        ctx.fillStyle = extrusion.baseFill
        ctx.fill('nonzero')
        ctx.globalAlpha = extrusion.sideAlpha
        ctx.fillStyle = this.stroke
        ctx.fill('nonzero')

        // Visible edges: back edges and connectors of the lit edges
        ctx.beginPath()
        for (let i = 0; i < count; ++i)
        {
            const a = points[i]
            const b = points[(i + 1) % count]
            if (winding * ((b.y - a.y) * offsetX - (b.x - a.x) * offsetY) <= 0)
                continue
            ctx.moveTo(a.x + sx, a.y + sy)
            ctx.lineTo(a.x + offsetX + sx, a.y + offsetY + sy)
            ctx.lineTo(b.x + offsetX + sx, b.y + offsetY + sy)
            ctx.lineTo(b.x + sx, b.y + sy)
        }
        ctx.globalAlpha = extrusion.edgeAlpha
        ctx.strokeStyle = this.stroke
        ctx.lineWidth = extrusion.edgeWidth
        ctx.lineJoin = 'round'
        ctx.stroke()
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
