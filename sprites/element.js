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
        ctx.stroke()
        
        ctx.closePath()
    }
}