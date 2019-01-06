class Ninja
{
    constructor(object)
    {
        this.x      = object.x
        this.y      = object.y
        
        this.speedX = 0
        this.speedY = 0
        this.radius = object.radius
        
        this.fill   = object.fill
        this.stroke = object.stroke
    }
    collision()
    {
        for (let k = 0; k < floors.length; ++k)
        {
            for (let i = 0; i < floors[k].elements.length; ++i)
            {
                if (twoCirclesIntersect(this.x, this.y, this.radius, floors[k].elements[i].getCircumscribedCircle()))
                {
                    let lines = floors[k].elements[i].getLines()
                    for (let j = 0; j < lines.length; ++j)
                    {
                        if (this.collisionNinjaWithLine(lines[j]))
                            floors[k].elements[i].collision(this, lines[j])
                    }
                }
            }
        }
    }
    collisionNinjaWithLine(line)
    {
        return collisionCircleWithLine(line, this.x, this.y, this.radius)
    }
    move()
    {
        const maxSpeed = 0.02 * height
        if (this.speedY > maxSpeed)
            this.speedY = maxSpeed
        if (this.speedY < -maxSpeed)
            this.speedY = -maxSpeed
        this.x += this.speedX
        this.y += this.speedY
    }
    draw()
    {
        ctx.beginPath()
    
        ctx.arc(this.x + screen.x, this.y + screen.y, this.radius, 0, Math.PI * 2, false)
        
        ctx.fillStyle = this.fill
        ctx.fill()
        
        ctx.strokeStyle = this.stroke
        ctx.stroke()
        
        ctx.closePath()
    }
}