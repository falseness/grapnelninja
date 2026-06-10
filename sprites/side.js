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
    }
}
