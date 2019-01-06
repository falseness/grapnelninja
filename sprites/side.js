class Side extends Trampoline
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
        
        ctx.moveTo(this.x + screen.x, this.y + screen.y + 1)
        ctx.lineTo(this.x + screen.x, this.y + this.points[1].y + screen.y)
        
        ctx.lineWidth = 3
        ctx.strokeStyle = this.fill
        ctx.stroke()
        
        ctx.lineWidth = 1
        
        ctx.closePath()
    }
}