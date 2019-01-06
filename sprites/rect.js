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
const rectWidth = 0.05 * width
const rectIndent = 0.3 * width

function generateRect(x)
{
    const wayHeight = 0.3 * height
    let rectHeight = random(0, height - area[1].height - area[0].height - wayHeight)
    
    let rectModel = 
    {
        x: x, 
        y: area[0].height, 
        width: rectWidth,
        height: rectHeight
    }
    
    elements.push(new Rect(createRectByModel(rectModel)))
    
    
    
    
    rectModel.y += rectHeight + wayHeight
    rectModel.height = height - rectModel.y - area[1].height

    elements.push(new Rect(createRectByModel(rectModel)))
    
    const generatedElementsNumber = 2
    return generatedElementsNumber
}