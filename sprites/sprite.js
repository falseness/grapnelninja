let sprites = []

class Sprite
{
    constructor(object)
    {
        this.object = object
        this.x = object.attrs.x
        this.y = object.attrs.y
        this.width = object.attrs.width
        this.height = object.attrs.height
        this.speedX = 0
        this.speedY = 0
        if (object.className == "Line")
            this.points = object.attrs.points.slice(0, object.attrs.points.length)
    }
    move()
    {
        for (let i = 0; i < this.points.length; i += 2)
        {
            this.points[i] += this.speedX
            this.points[i + 1] += this.speedY
        }
        /*let points = this.object.attrs.points
        for (let i = 0; i < points.length; i += 2)
        {
            points[i] += this.speedX
            points[i + 1] += this.speedY
        }
        this.object.attrs.points = points*/
    }
    moveObject()
    {
        
    }
    collision()
    {
        reStart()
    }
}


