class Ninja extends Sprite
{
    constructor(object)
    {
        super(object)
        this.radius = object.attrs.radius
        
    }
    collision()
    {
        for (let i = 0; i < sprites.length; ++i)
        {
            let points = sprites[i].object.attrs.points
            for (let i = 0; i < points.length; i += 2)
            {
                if (this.collisionNinjaWithLine(points[i], points[i + 1], points[i + 2], points[i + 3]))
                    console.log('collisiont')
            }
            if (this.collisionNinjaWithLine(points[points.length - 2], points[points.length - 1], points[0], points[1]))
                console.log('collision')
          /* if (this.collisionNinjaWithLine(sprites[i].x, sprites[i].y, 
                                           sprites[i].x + sprites[i].width, sprites[i].y) ||
                this.collisionNinjaWithLine(sprites[i].x, sprites[i].y + sprites[i].height,
                                          sprites[i].x + sprites[i].width, sprites[i].y + sprites[i].height) ||
                this.collisionNinjaWithLine(sprites[i].x, sprites[i].y,
                                          sprites[i].x, sprites[i].y + sprites[i].height) ||
                this.collisionNinjaWithLine(sprites[i].x + sprites[i].width, sprites[i].y,
                                          sprites[i].x + sprites[i].width, sprites[i].y + sprites[i].height))
               console.log('collision')*/
        }
    }
    collisionNinjaWithLine(x1, y1, x2, y2)
    {
        return collisionCircleWithLine(x1, y1, x2, y2, this.x, this.y, this.radius)
    }
    move()
    {
        this.x += this.speedX
        this.y += this.speedY
        this.object.setX(this.x)
        this.object.setY(this.y)
    }
}