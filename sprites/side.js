class Ground extends Trampoline
{
    constructor(object)
    {
        super(object)
    }
    draw()
    {
        this.drawGroundBody()
        
        //Чтобы не было "швов"
        ctx.beginPath()
        
        ctx.lineWidth = STYLE.strokes.seamWidth
        ctx.moveTo(this.x + screen.x, this.y + screen.y + 1)
        ctx.lineTo(this.x + screen.x, this.y + this.points[1].y + screen.y - 1)
        
        
        ctx.strokeStyle = this.fill
        ctx.stroke()
        
        ctx.lineWidth = STYLE.strokes.defaultWidth
        
        ctx.closePath()

        this.drawNeonBoundary()
    }
    drawGroundBody()
    {
        if (version != 'bad')
        {
            super.draw()
            return
        }

        const obstacleStyle = STYLE.badVersionEffects.obstacles
        this.drawBadVersionPolygon(
            obstacleStyle.groundFill,
            STYLE.colors.ground.stroke,
            {
                lineWidth: obstacleStyle.thinStrokeWidth,
                glowWidth: obstacleStyle.outerGlowWidth,
                glowAlpha: obstacleStyle.groundFillAlpha,
                innerStrokeStyle: STYLE.colors.ground.line
            }
        )

        const points = this.getPoints()
        const topY = Math.min(points[0].y, points[1].y, points[2].y, points[3].y) + screen.y
        ctx.save()
        ctx.fillStyle = obstacleStyle.groundCapFill
        ctx.fillRect(this.x + screen.x, topY, this.points[2].x, Math.max(2, height * 0.012))
        ctx.restore()
    }
    drawNeonBoundary()
    {
        const boundaryY = this.y > height / 2 ? this.y : this.y + this.points[1].y

        ctx.save()
        ctx.beginPath()

        ctx.lineWidth = STYLE.strokes.neonGlowWidth
        ctx.strokeStyle = STYLE.colors.ground.stroke
        ctx.shadowColor = STYLE.colors.ground.line
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.moveTo(this.x + screen.x, boundaryY + screen.y)
        ctx.lineTo(this.x + this.points[2].x + screen.x, boundaryY + screen.y)
        ctx.stroke()

        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.strokeStyle = STYLE.colors.ground.line
        ctx.shadowBlur = 0
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
}
class Side extends Rect
{
    constructor(object)
    {
        super(object)
    }
    collision(who, line)
    {
        if (this.isBadVersionCeilingBoundary(line))
        {
            Trampoline.prototype.collision.call(this, who, line)
            return
        }

        super.collision(who, line)
    }
    isBadVersionCeilingBoundary(line)
    {
        if (version != 'bad' || line.type != 'line' || this.y >= height / 2)
            return false

        const ceilingBoundaryY = this.y + this.height
        return line.y1 == ceilingBoundaryY && line.y2 == ceilingBoundaryY
    }
    isInHudClearZone()
    {
        const boundaryY = this.y > height / 2 ? this.y : this.y + this.height
        const screenBoundaryY = boundaryY + screen.y
        const hudClearTop = height / scale[version] * STYLE.ui.hudClearTopRatio

        return screenBoundaryY < hudClearTop
    }
    draw()
    {
        if (this.isInHudClearZone())
            return

        this.drawSideBody()
        
        //Чтобы не было "швов"
        ctx.beginPath()
        
        ctx.lineWidth = STYLE.strokes.seamWidth
        ctx.moveTo(this.x + screen.x, this.y + screen.y + 1)
        ctx.lineTo(this.x + screen.x, this.y + this.height + screen.y - 1)
        
        
        ctx.strokeStyle = this.fill
        ctx.stroke()
        
        ctx.lineWidth = STYLE.strokes.defaultWidth
        
        ctx.closePath()

        this.drawNeonBoundary()
    }
    drawSideBody()
    {
        if (version != 'bad')
        {
            super.draw()
            return
        }

        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const x = this.x + screen.x
        const y = this.y + screen.y
        const boundaryY = this.y > height / 2 ? this.y : this.y + this.height
        const capY = boundaryY + screen.y

        ctx.save()
        ctx.fillStyle = obstacleStyle.groundFill
        ctx.fillRect(x, y, this.width, this.height)

        ctx.fillStyle = obstacleStyle.groundCapFill
        ctx.fillRect(x, capY - Math.max(2, height * 0.01), this.width, Math.max(2, height * 0.012))

        ctx.strokeStyle = STYLE.colors.ground.stroke
        ctx.lineWidth = obstacleStyle.thinStrokeWidth
        ctx.globalAlpha = obstacleStyle.groundFillAlpha
        ctx.shadowColor = STYLE.colors.ground.line
        ctx.shadowBlur = obstacleStyle.outerGlowWidth
        ctx.strokeRect(x, y, this.width, this.height)
        ctx.restore()
    }
    drawNeonBoundary()
    {
        const boundaryY = this.y > height / 2 ? this.y : this.y + this.height
        const screenBoundaryY = boundaryY + screen.y

        if (this.isInHudClearZone())
            return

        ctx.save()
        ctx.beginPath()

        ctx.lineWidth = STYLE.strokes.neonGlowWidth
        ctx.strokeStyle = STYLE.colors.ground.stroke
        ctx.shadowColor = STYLE.colors.ground.line
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.moveTo(this.x + screen.x, screenBoundaryY)
        ctx.lineTo(this.x + this.width + screen.x, screenBoundaryY)
        ctx.stroke()

        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.strokeStyle = STYLE.colors.ground.line
        ctx.shadowBlur = 0
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
}
