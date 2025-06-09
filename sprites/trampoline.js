class Trampoline extends CollisionElement
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

class TrampolineTest extends Trampoline {
    constructor(object)
    {
        super(object)
    
        this.speedY =   0.005 * height / cyclesPerTick
        //tmp
        // this.speedY *= 0.0
        if (random() < 50)
            this.speedY *= -1
        
        this.restrictionY = 
        {
            min: 100,
            max: 1000
        }
        // this.track = (trackEnabled)?(new MultipointTrackLine(this.side, this.fill, 75)):(new Empty())
        // this.track.addPos(this.getPoints(), true)
    }
    changeSpeed()
    {
        if (this.y < this.restrictionY.min || this.y > this.restrictionY.max)
            this.speedY *= -1
    }
    move()
    {
        this.changeSpeed()
        this.y += this.speedY
        
        // this.track.addPos(this.getPoints())
    }

}