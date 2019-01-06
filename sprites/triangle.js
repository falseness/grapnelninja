class Triangle extends Element
{
    constructor(object)
    {
        super(object)
    
        this.speedY =   0.005 * height
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
    }
    getCircumscribedCircle()
    {
        return {x: this.x, y: this.y, radius: this.radius}
    }
    move()
    {
        this.changeSpeed()
        this.y += this.speedY
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
/*const radius = height * 0.15 / Math.sqrt(3)
const triangleRestriction = 
{
    top: area[0].y + area[0].height + 0.01 * height,
    bottom: area[1].y - 0.01 * height
}

function generateTriangle(x)
{    
    
    let model = 
    {
        x: x + radius * Math.sqrt(3)                                                    ,
        y: random(triangleRestriction.top + radius * 1.5 / 3, triangleRestriction.bottom - radius),
        radius: radius
    }
    
    elements.push(new Triangle(createTriangleByModel(model)))
    if (random() < 50)
    {
        elements[elements.length - 1].speedY *= -1
    }
    
    
    let generatedElementsNumber = 1
    return generatedElementsNumber
}*/