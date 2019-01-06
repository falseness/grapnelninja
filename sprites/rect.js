class Rect extends Element
{
    constructor(object)
    {
        super(object)
        
        this.width = object.width
        this.height = object.height
        
        
        this.fill   = this.fill     || '#f0f0f0'
        this.stroke = this.stroke   || 'black'
        
        this.circle =
        {
            x: this.width  / 2,
            y: this.height / 2
        }
        this.circle.radius = Math.sqrt(Math.pow(this.circle.x - this.x, 2) + Math.pow(this.circle.y - this.y, 2))
    }
    getCircumscribedCircle()
    {
        return {x: this.circle.x + this.x, y: this.circle.y + this.y, radius: this.circle.radius}
    }
    getPoints()
    {   
        let x = this.getX()
        let y = this.getY()
        
        let xPlusMarginX = x + this.width
        let yPlusMarginY = y + this.height
        
        let points = 
        [
            {x: x           , y: y              },
            {x: xPlusMarginX, y: y              },
            {x: xPlusMarginX, y: yPlusMarginY   },
            {x: x           , y: yPlusMarginY   }
        ]
        
        return points
    }
    moveX(speed)
    {
        super.moveX(speed)
    }
    getRightPointX()
    {
        return this.getX() + this.width
    }
    getLeftPointX()
    {
        return this.getX()
    }
    isPairElement()
    {
        return true
    }
    draw()
    {
        ctx.fillStyle   = this.fill
        ctx.strokeStyle = this.stroke
        
        ctx.strokeRect(this.x + screen.x, this.y + screen.y, this.width, this.height) 
        ctx.fillRect(this.x + screen.x, this.y + screen.y, this.width, this.height)
    }
}