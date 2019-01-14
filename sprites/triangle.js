class Triangle extends Element
{
    constructor(object)
    {
        super(object)
    
        this.speedY =   0.005 * height / cyclesPerTick
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