class Screen
{
    constructor(yAxisMotion, screenY)
    {
        this.borderX        = 0.35 * width
        
        this.topBorderY     = height * 0.6
        this.bottomBorderY  = height * 0.4
        this.centerBorderY  = height * 0.5
        
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
            let screenNinjaY = ninja.y + screen.y
            
            let screenMoveRatio = 1.5
            const eps = 10
            if (screenNinjaY > this.bottomBorderY && ninja.speedY > 0)
            {
                if (isLess(this.y, this.min))
                {
                    this.y = this.min
                    this.speedY = 0
                    return false
                }
                this.speedY = -screenMoveRatio * abs(ninja.speedY)
                
                return true
            }
            if (screenNinjaY < this.topBorderY && ninja.speedY < 0)
            {
                 if (isMore(this.y, this.max))
                {
                    this.y = this.max
                    this.speedY = 0
                    return false
                }
                this.speedY = screenMoveRatio * abs(ninja.speedY)
                return true
            }
        
            if (ninja.speedY > 0 && !(isEqually(this.y, this.max)))
            {
                if (isLess(this.y, this.min))
                {
                    this.y = this.min
                    this.speedY = 0
                    return false
                }
                this.speedY = -ninja.speedY
                return true
            }
            if (ninja.speedY < 0 && !(isEqually(this.y, this.min)))
            {
                if (isMore(this.y, this.max))
                {
                    this.y = this.max
                    this.speedY = 0
                    return false
                }
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
            
            ctx.beginPath()
            
            ctx.moveTo(0, this.centerBorderY)
            ctx.lineTo(this.borderX, this.centerBorderY)
            
            ctx.strokeStyle = 'red'
            ctx.stroke()
            
            ctx.closePath()
        }
    }
}


