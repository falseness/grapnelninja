class Screen
{
    constructor(yAxisMotion, screenY)
    {
        this.updateWidthLayout()
        
        this.topBorderY     = screenHeightPercent(GAMEPLAY.cameraTopHeightPercent)
        this.bottomBorderY  = screenHeightPercent(GAMEPLAY.cameraBottomHeightPercent)
        this.centerBorderY  = screenHeightPercent(GAMEPLAY.cameraCenterHeightPercent)
        
        this.speedX         = 0
        this.speedY         = 0
        
        this.yAxisMotion = yAxisMotion
        
        this.x = 0
        this.y = (yAxisMotion)?screenY:0
        
        this.leftWall = version === 'grapple_over' ? null : new LeftWall(this)
        this.drawEnable = false
        
        this.maxX = 1048576//4294967296 скорее всего в этом нет необходимости, не буду добавлять
    }
    // Width-derived borders; called again after a live viewport resize.
    updateWidthLayout()
    {
        this.borderX        = screenWidthPercent(GAMEPLAY.cameraBorderWidthPercent) / scale[version]
        this.deletionBorder = -width
    }
    // Called once per fixed physics tick, after the player has moved.
    trackGrappleOver(snap = false)
    {
        const bounds = floors[0].level.bounds
        const viewWidth = width / scale[version]
        const viewHeight = height / scale[version]
        const dt = physicsStepMs / 1000
        const alpha = -Math.expm1(-dt / 0.18)
        const clamp = (v, low, high) => Math.max(low, Math.min(high, v))
        // Ease the player toward the exact view center: no dead zone and no
        // speed look-ahead.
        const track = (offset, position, size, low, high) => {
            if (high - low <= size) return (size - low - high) / 2
            const center = size / 2 - position
            let next = snap ? center : offset + (center - offset) * alpha
            // Bound the lag by the player's full visible extent, even in a
            // fast fall. Ordinary tracking remains exponentially eased.
            next = clamp(next, ninja.radius - position, size - ninja.radius - position)
            return clamp(next, size - high, -low)
        }
        this.x = track(this.x, ninja.x, viewWidth, bounds.left, bounds.right)
        const lead = bounds.topLead
        const top = lead ? Math.max(lead.limit, Math.min(bounds.top,
            bounds.top - lead.rate * (lead.from - ninja.y))) : bounds.top
        this.y = track(this.y, ninja.y, viewHeight, top, bounds.bottom)
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


