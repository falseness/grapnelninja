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
        this.x += this.speedX
        this.y += this.speedY
        this.object.setX(this.x)
        this.object.setY(this.y)
    }
}
class Ninja extends Sprite
{
    constructor(object)
    {
        super(object)
        this.radius = object.attrs.radius
        this.grappleCoords = null
    }
    collision()
    {
        for (let i = 0; i < sprites.length; ++i)
        {
           if (this.collisionNinjaWithLine(sprites[i].x, sprites[i].y, 
                                           sprites[i].x + sprites[i].width, sprites[i].y) ||
                this.collisionNinjaWithLine(sprites[i].x, sprites[i].y + sprites[i].height,
                                          sprites[i].x + sprites[i].width, sprites[i].y + sprites[i].height) ||
                this.collisionNinjaWithLine(sprites[i].x, sprites[i].y,
                                          sprites[i].x, sprites[i].y + sprites[i].height) ||
                this.collisionNinjaWithLine(sprites[i].x + sprites[i].width, sprites[i].y,
                                          sprites[i].x + sprites[i].width, sprites[i].y + sprites[i].height))
               console.log('collision')
        }
    }
    collisionNinjaWithLine(x1, y1, x2, y2)
    {
        return collisionCircleWithLine(x1, y1, x2, y2, this.x, this.y, this.radius)
    }
    grapple()
    {
        
    }
}
class Grapnel extends Sprite
{
    constructor(object)
    {
        super(object)
        
    }
}
