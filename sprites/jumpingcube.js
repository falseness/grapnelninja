class JumpingCube extends Rect
{
    constructor(object)
    {
        super(object)
        this.mass = this.height * this.width * blueSpriteDensity
        
        this.track = new TrackLine(this.width, this.fill, 50)
        this.track.addPos(this.x + this.circle.x, this.y, true)
        
        let cycles = random() * cyclesPerTick
        for (let i = 0; i < cycles; ++i)
        {
            this.move()
        }
        
    }
    getBottomPointY()
    {
        return this.y + this.height
    }
    move()
    {
        this.speedY += GRAVITY
        
        this.x += this.speedX
        this.y += this.speedY
        
        if (this.speedY > 0)
            this.track.addPos(this.x + this.circle.x, this.y)
        else
            this.track.addPos(this.x + this.circle.x, this.getBottomPointY())
        
        this.collisionWithElements()
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
    collisionWithElements()
    {
        let cubeLines = this.getLines()
        let circle = this.getCircumscribedCircle()
        
        
        for (let k = 0; k < floors.length; ++k)
        {
            for (let i = 0; i < floors[k].elements.length; ++i)
            {
                if (circlesIntersect(circle, floors[k].elements[i].getCircumscribedCircle()))
                {
                    let lines = floors[k].elements[i].getLines()
                    for (let j = 0; j < lines.length; ++j)
                    {
                        for (let q = 0; q < cubeLines.length; ++q)
                        {                   
                            if (linesCollision(lines[j], cubeLines[q]))
                            {
                                //тупо:
                                this.speedY *= -1
                                if (this.speedY > 0)
                                    this.speedY += GRAVITY
                                else
                                    this.speedY -= GRAVITY

                                return
                            }
                        }
                    }
                }
            }
        }
    }
}