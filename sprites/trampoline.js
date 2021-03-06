class Trampoline extends Element
{
    constructor(object)
    {
        super(object)

        this.isPairElement = object.isPairElement || function() {return false}
        
        this.stroke = this.stroke   || 'black'
        this.fill   = this.fill     || '#7bd17b'
        
        this.circle = 
        {
            x: 0,
            y: 0
        }
        
        this.points         = object.points.slice()
        this.rightPointX    = object.points[0].x
        this.leftPointX     = object.points[0].x
        
        for (let i = 0; i < object.points.length; i += 2)
        {
            if (object.points[i].x > this.rightPointX)
                this.rightPointX = object.points[i].x
            if (object.points[i].x < this.leftPointX)
                this.leftPointX = object.points[i].x
            
            this.circle.x += object.points[i].x
            this.circle.y += object.points[i].y
        }
        
        this.circle.x /= (object.points.length)
        this.circle.y /= (object.points.length)
        
        let r = 0
        for (let i = 0; i < object.points.length; ++i)
        {
            let t = Math.pow(object.points[i].x - this.circle.x, 2) +
                    Math.pow(object.points[i].y - this.circle.y, 2)
            if (t > r)
                r = t
        }
        this.circle.radius = Math.sqrt(r)
    }
    getCircumscribedCircle()
    {
        return {x: this.x + this.circle.x, y: this.y + this.circle.y, radius: this.circle.radius}
    }
    getRightPointX()
    {
        return this.x + this.rightPointX
    }
    getLeftPointX()
    {
        return this.x + this.leftPointX
    }
    getPoints()
    {
        let res = []
        for (let i = 0; i < this.points.length; ++i)
            res.push({x: this.points[i].x + this.x, y: this.points[i].y + this.y, curvature: this.points[i].curvature})
        return res
    }
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
            who.speedX += GRAVITY * Math.cos(lineAngle) * Math.sin(lineAngle)
            who.speedY -= GRAVITY * Math.pow(Math.cos(lineAngle), 2)
        }
        else
            console.log('collision with trampoline error')
    }
    draw()
    {
        ctx.beginPath()
        
        let points = this.getPoints()
        
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
        {
            if (points[i].curvature)
                ctx.quadraticCurveTo(points[i].curvature.x + screen.x, points[i].curvature.y + screen.y, 
                                     points[i].x + screen.x, points[i].y + screen.y)
            else
                ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        }
        
        ctx.fillStyle   = this.fill
        ctx.fill()
        
        ctx.strokeStyle = this.stroke
        ctx.stroke()
        
        ctx.closePath()
    }
}
