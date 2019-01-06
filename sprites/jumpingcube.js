class JumpingCube extends Rect
{
    constructor(object)
    {
        super(object)
    }
    move()
    {
        this.speedY += GRAVITY
        
        this.x += this.speedX
        this.y += this.speedY
        
        this.collisionWithElements()
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
                                if (this.y < Math.min(lines[j].y1, lines[j].y2))
                                {
                                    this.speedY = -abs(this.speedY)
                                }
                                else
                                    this.speedY = abs(this.speedY)
                                //this.speedY *= -1
                                return
                            }
                        }
                    }
                }
            }
        }
    }
}