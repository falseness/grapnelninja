class Screen
{
    constructor(yAxisMotion, screenY)
    {
        this.borderX        = 0.35 * width
        
        this.topBorderY     = 0.5 * height
        this.bottomBorderY  = height * 0.5
        
        this.speedX         = 0
        this.speedY         = 0
        
        this.yAxisMotion = yAxisMotion
        
        this.x = 0
        this.y = (yAxisMotion)?screenY:0
        
        
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
        if (this.yAxisMotion)
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
        }
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


