





function dot_product(x1, y1, x2, y2) {
    return x1 * x2 + y1 * y2
}

class Triangle extends Element
{
    constructor(object)
    {
        super(object)
    
        this.speedY =   0.005 * height / cyclesPerTick
        //tmp
        this.speedY *= 0.3
        if (random() < 50)
            this.speedY *= -1
        
        this.side   =   object.radius * Math.sqrt(3)
        this.height =   this.side * Math.sin(Math.PI / 3)
        this.radius = object.radius
        
        this.restrictionY = 
        {
            min: object.yMin,
            max: object.yMax
        }
        this.track = (trackEnabled)?(new MultipointTrackLine(this.side, this.fill, 75)):(new Empty())
        this.track.addPos(this.getPoints(), true)
    }
    getCircumscribedCircle()
    {
        return {x: this.x, y: this.y, radius: this.radius}
    }
    move()
    {
        this.changeSpeed()
        this.y += this.speedY
        
        this.track.addPos(this.getPoints())
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
            
            // who.x += who.speedX

            // who.y += who.speedY
            // console.log('directionX', GRAVITY * Math.cos(lineAngle) * Math.sin(lineAngle))
            // console.log('directionY', GRAVITY * Math.pow(Math.cos(lineAngle), 2))
            // who.speedX += Math.cos(lineAngle) * Math.sin(lineAngle)
            // who.speedY -= Math.pow(Math.cos(lineAngle), 2)
        }
        else
            console.log('collision with trampoline error')
    }
    getRightPointX()
    {
        return this.getX() + this.side / 2
    }
    getLeftPointX()
    {
        return this.getX() - this.side / 2
    }
    getTopPointY()
    {
        return this.getY() - this.height * (1 / 3)
    }
    getBottomPointY()
    {
        return this.getY() + this.height * (2 / 3)
    }
    getPoints()
    {
        let x = this.getX()
        let y = this.getY()
        
        let points = 
        [
            {x: x - this.side / 2   , y: y - this.height * (1 / 3)},
            {x: x + this.side / 2   , y: y - this.height * (1 / 3)},
            {x: x                   , y: y + this.height * (2 / 3)}
        ]
        return points
    }
    changeSpeed()
    {
        if (this.getTopPointY() < this.restrictionY.min || this.getBottomPointY() > this.restrictionY.max)
            this.speedY *= -1
    }
}

class HarmlessTriangle extends Triangle{
    collision() {

    }
}

class MultipointTrackLine extends TrackLine
{
    constructor(width, stroke, pointsLimit)
    {
        super(width, stroke, pointsLimit)
    }
    addPos(point, mustAdd)
    {
        if (trackEnabled && firstCycleInThisTick || mustAdd)
        {
            this.pos.push(point)
            this.delete()
        }
    }
    draw()
    {
        if (trackEnabled)
        {
            ctx.beginPath()

            //Работает только в частном случае
            let min0, min1, max0, max1, max2

            let extremum =
            [
                {min: this.pos[0][0].y, max: this.pos[0][0].y},
                {min: this.pos[0][1].y, max: this.pos[0][1].y},
                {min: this.pos[0][2].y, max: this.pos[0][2].y}
            ]
            for (let i = 0; i < this.pos.length; ++i)
            {
                for (let j = 0; j < this.pos[i].length; ++j)
                {
                    if (this.pos[i][j].y < extremum[j].min)
                        extremum[j].min = this.pos[i][j].y
                    if (this.pos[i][j].y > extremum[j].max)
                        extremum[j].max = this.pos[i][j].y
                }
            }
            ctx.moveTo(this.pos[0][0].x + screen.x, extremum[0].min + screen.y)
            ctx.lineTo(this.pos[0][0].x + screen.x, extremum[0].max + screen.y)
            ctx.lineTo(this.pos[0][2].x + screen.x, extremum[2].max + screen.y)
            ctx.lineTo(this.pos[0][1].x + screen.x, extremum[1].max + screen.y)
            ctx.lineTo(this.pos[0][1].x + screen.x, extremum[1].min + screen.y)
            ctx.lineTo(this.pos[0][0].x + screen.x, extremum[0].min + screen.y)

            ctx.globalAlpha = 0.5
            ctx.fillStyle = this.stroke
            ctx.fill()
            ctx.globalAlpha = 1

            ctx.closePath()  
        }
    }
}