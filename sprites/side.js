class Ground extends Trampoline
{
    constructor(object)
    {
        super(object)
    }
    draw()
    {
        super.draw()
        
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
    draw()
    {
        super.draw()
        
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
    drawNeonBoundary()
    {
        const boundaryY = this.y > height / 2 ? this.y : this.y + this.height

        ctx.save()
        ctx.beginPath()

        ctx.lineWidth = STYLE.strokes.neonGlowWidth
        ctx.strokeStyle = STYLE.colors.ground.stroke
        ctx.shadowColor = STYLE.colors.ground.line
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.moveTo(this.x + screen.x, boundaryY + screen.y)
        ctx.lineTo(this.x + this.width + screen.x, boundaryY + screen.y)
        ctx.stroke()

        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.strokeStyle = STYLE.colors.ground.line
        ctx.shadowBlur = 0
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
}
