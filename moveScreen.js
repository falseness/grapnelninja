class Screen
{
    constructor(yAxisMotion, screenY)
    {
        this.borderX        = screenWidthPercent(GAMEPLAY.cameraBorderWidthPercent)
        
        this.topBorderY     = screenHeightPercent(GAMEPLAY.cameraTopHeightPercent)
        this.bottomBorderY  = screenHeightPercent(GAMEPLAY.cameraBottomHeightPercent)
        this.centerBorderY  = screenHeightPercent(GAMEPLAY.cameraCenterHeightPercent)
        
        this.speedX         = 0
        this.speedY         = 0
        
        this.yAxisMotion = yAxisMotion
        
        this.x = 0
        this.y = (yAxisMotion)?screenY:0
        
        this.deletionBorder = -width
        
        this.drawEnable = false
        
        this.maxX = 1048576//4294967296 скорее всего в этом нет необходимости, не буду добавлять
    }
    getDeletionBorder()
    {
        return this.deletionBorder
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
            
            const screenMoveRatio = GAMEPLAY.cameraMoveRatio
            const eps = screenHeightPercent(GAMEPLAY.coordinateToleranceHeightPercent)
            if (screenNinjaY > this.bottomBorderY && ninja.speedY > 0)
            {
                if (isLess(this.y, this.min, eps))
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
                 if (isMore(this.y, this.max, eps))
                {
                    this.y = this.max
                    this.speedY = 0
                    return false
                }
                this.speedY = screenMoveRatio * abs(ninja.speedY)
                return true
            }
        
            if (ninja.speedY > 0 && !(isEqually(this.y, this.max, eps)))
            {
                if (isLess(this.y, this.min, eps))
                {
                    this.y = this.min
                    this.speedY = 0
                    return false
                }
                this.speedY = -ninja.speedY
                return true
            }
            if (ninja.speedY < 0 && !(isEqually(this.y, this.min, eps)))
            {
                if (isMore(this.y, this.max, eps))
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
            
            ctx.strokeStyle = STYLE.colors.ui.debug
            ctx.stroke()
            
            ctx.closePath()
            
            ctx.beginPath()
            
            ctx.moveTo(0, this.centerBorderY)
            ctx.lineTo(this.borderX, this.centerBorderY)
            
            ctx.strokeStyle = STYLE.colors.ui.debugAccent
            ctx.stroke()
            
            ctx.closePath()
        }
    }
}


