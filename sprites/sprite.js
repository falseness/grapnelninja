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
    }
    move()
    {
        let points = this.object.attrs.points
        for (let i = 0; i < points.length; i += 2)
        {
            points[i] += this.speedX
            points[i + 1] += this.speedY
        }
        this.object.attrs.points = points
    }
}

