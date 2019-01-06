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
        
        this.line = new NinjaLine(this.radius)
        this.line.addPos(this.x, this.y)
    }
    collision()
    {
        let collision = false
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
                        {
                            floors[k].elements[i].collision(this, lines[j])
                            collision = lines[j]
                        }
                    }
                }
            }
        }
        return collision
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
        
        this.line.addPos(this.x, this.y)
        
        this.collision()
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
class NinjaLine
{
    constructor(r)
    {
        this.pos        = []
        this.radius     = r
        this.lineWidth  = 15
    }
    delete()
    {
        const maxPos = 100
        if (this.pos.length > maxPos)
        {
            this.pos.splice(0, this.pos.length - maxPos)
        }
    }
    addPos(x, y)
    {
        this.pos.push({x, y})
        this.delete()
    }
    draw()
    {
        ctx.beginPath()

        ctx.lineCap = 'round'
        ctx.moveTo(this.pos[0].x + screen.x, this.pos[0].y + screen.y)
        
        for (let i = 1; i < this.pos.length; ++i)
        {
            ctx.lineTo(this.pos[i].x + screen.x, this.pos[i].y + screen.y)
        }
        ctx.lineWidth = this.lineWidth
        
        ctx.globalAlpha = 0.5
        ctx.strokeStyle = ninja.fill//ninja.stroke
        //ctx.fillStyle   = ninja.fill
        
        //ctx.fill()
        ctx.stroke()
        
        ctx.globalAlpha = 1
        
        ctx.lineWidth = 1
        ctx.lineCap = 'butt'
        
        ctx.closePath()   
    }
}