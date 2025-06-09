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







function dot_product(x1, y1, x2, y2) {
    return x1 * x2 + y1 * y2
}

class CollisionElement extends Element
{
    collision(who, line)
    {
        /*let points = this.getPoints()
        for (let i = 0; i < points.length; ++i)
        {
            if (points[i].x == line.x1 && points[i].y == line.y1)
            {
                this.points[(i + 1) % this.points.length].curvature =
                {
                    x: who.x + who.mass * who.speedX,
                    y: who.y + who.mass * who.speedY
                }
            }
        }*/
        
        
        if (line.type == 'vertical')
        {
            console.log('vertical')
            who.speedX *= -1
        }
        else if (line.type == 'line')
        {
            let lineAngle = line.k

            let xn = -who.speedX
            let yn = -who.speedY

            let x = xn * Math.cos(lineAngle) + yn * Math.sin(lineAngle)
            let y = yn * Math.cos(lineAngle) - xn * Math.sin(lineAngle)

            x = -x

            xn = x * Math.cos(lineAngle) - y * Math.sin(lineAngle)
            yn = y * Math.cos(lineAngle) + x * Math.sin(lineAngle)

            
            who.speedX = xn
            who.speedY = yn

            let line_direction_x = line.x2 - line.x1
            let line_direction_y = line.y2 - line.y1
            let ap_x = who.x - line.x1 
            let ap_y = who.y - line.y1
            let distance = dot_product(ap_x, ap_y, line_direction_x, line_direction_y)
            distance /= dot_product(line_direction_x, line_direction_y, line_direction_x, line_direction_y)

            let normal_x = ap_x - distance * line_direction_x
            let normal_y = ap_y - distance * line_direction_y
            let normal_length = Math.sqrt(normal_x * normal_x + normal_y * normal_y) 
            who.x += normal_x / normal_length * (who.radius - normal_length)

            who.y += normal_y / normal_length * (who.radius - normal_length)

            // console.log('directionX', GRAVITY * Math.cos(lineAngle) * Math.sin(lineAngle))
            // console.log('directionY', GRAVITY * Math.pow(Math.cos(lineAngle), 2))
            // who.speedX += Math.cos(lineAngle) * Math.sin(lineAngle)
            // who.speedY -= Math.pow(Math.cos(lineAngle), 2)
        }
        else
            console.log('collision with trampoline error')
    }
}
