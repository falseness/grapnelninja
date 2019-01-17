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