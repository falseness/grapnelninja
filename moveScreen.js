class Screen
{
    constructor()
    {
        //constants
        this.borderX        = 0.35 * width
        
        this.topBorderY     = 0.3 * height
        this.bottomBorderY  = height * 0.7
        
        this.speedX         = 0
        this.speedY         = 0
        
        this.x = 0
        this.y = screenY
        
        this.drawEnable = false
    }
    isMoving()
    {
        return this.speed
    }
    move()
    {
        this.x += this.speedX
        this.y += this.speedY
        
        /*for (let i = sides.length; i < elements.length; ++i)
        {
            elements[i].x += this.speedX
            elements[i].y += this.speedY
            
            elements[i].moveY() // оптимизация
           // elements[i].moveY(this.speedY) 
        }
        for (let i = 0; i < sides.length; ++i)
            elements[i].y += this.speedY
         
        ninja.x += this.speedX
        ninja.y += this.speedY
        
        
        for (let i = 0; i < grapnel.pos.length; ++i)
        {
            grapnel.pos[i][0] += this.speedX
            grapnel.pos[i][1] += this.speedY
        }*/
        
    }
    shouldStartMove()
    {
        return this.shouldStartMoveX() | this.shouldStartMoveY()
    }
    shouldStartMoveX()
    {
        if (ninja.x > this.borderX - screen.x && ninja.speedX > 0)
        {
            this.speedX = -ninja.speedX
            return true
        }
        this.speedX = 0
        return false
    }
    shouldStartMoveY()
    {
        if (ninja.y > this.bottomBorderY - screen.y && ninja.speedY > 0)
        {
            this.speedY = -ninja.speedY
            return true
        }
        if (ninja.y < this.topBorderY - screen.y && ninja.speedY < 0)
        {
            this.speedY = -ninja.speedY
            return true
        }
        this.speedY = 0
        return false
    }
    draw()
    {
        if (this.drawEnable)
        {
            ctx.beginPath()

            ctx.moveTo(this.borderX, this.topBorderY)
            ctx.lineTo(this.borderX, this.bottomBorderY)

            ctx.moveTo(0, this.topBorderY)
            ctx.lineTo(this.borderX, this.topBorderY)

            ctx.moveTo(0, this.bottomBorderY)
            ctx.lineTo(this.borderX, this.bottomBorderY)

            ctx.strokeStyle = 'green'
            ctx.stroke()
            ctx.closePath()
        }
    }
}

let screen = new Screen()


