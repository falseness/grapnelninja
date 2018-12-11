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
            let points = sprites[i].points
            for (let j = 0; j < points.length; j += 2)
            {
                if (this.collisionNinjaWithLine(points[j], points[j + 1], points[j + 2], points[j + 3]))
                    sprites[i].collision(this, lineFormula(points[j], points[j + 1], points[j + 2], points[j + 3]))
            }
            if (this.collisionNinjaWithLine(points[points.length - 2], points[points.length - 1], points[0], points[1]))
                sprites[i].collision(this, lineFormula(points[points.length - 2], points[points.length - 1], points[0], points[1]))
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
        /*this.object.setX(Math.floor(this.x))
        this.object.setY(Math.floor(this.y))*/
    }
}