class Floor
{
    constructor(topBorder, bottomBorder, elementsIntervalX, creations, primaryElementsQuantity)
    {
        this.bottom             = bottomBorder
        this.top                = topBorder
        
        this.creations          = creations
        this.elementsIntervalX  = elementsIntervalX
        this.primaryElementsQuantity = primaryElementsQuantity || 8
        
        this.elements           = []
    }
    generatePrimaryElements()
    {
        const firstPrimaryElementX      = 0.2 * width
        const primaryElementsQuantity   = this.primaryElementsQuantity
        
        let nextElementX                = firstPrimaryElementX
        
        for (let i = 0; i < primaryElementsQuantity; ++i)
        {
            this.generateElements(nextElementX)
            try
            {
            nextElementX = this.elements[this.elements.length - 1].getRightPointX()
            }
            catch(e)
            {
                console.log('err')
            }
        }
    }
    generateElements(x)
    {
        let num = random()
        
        let sumChances = 0
        for (let i = 0; i < this.creations.length; ++i)
        {
            if (num <= this.creations[i].chance + sumChances)
            {
                this.elements.push(...elementsFactory.create(
                    {min: x + this.elementsIntervalX.min, max: x + this.elementsIntervalX.max}, 
                    {min: this.top, max: this.bottom}   , this.creations[i].type))
                
                return
            }
            sumChances += this.creations[i].chance
        }
        console.log('generation element on floor error')
    }
    deleteElements()
    {
        let newElements = 0
        for (let i = 0; i < this.elements.length - newElements; ++i)
        {
            if (!this.elements[i].scored && 
                this.elements[i].getRightPointX() + screen.x < 0)
            {
                this.elements[i].scored = true
                if (this.elements[i].isPairElement() && this.elements[i + 1])
                    this.elements[++i].scored = true
                
                changeScoreText()
            }
            else if (this.elements[i].getRightPointX() + screen.x < screen.getDeletionBorder())
            {
                let nextElementX = this.elements[i].getRightPointX()
                if (this.elements[i].isPairElement())
                {
                    if (this.elements[i + 1])
                        nextElementX = Math.max(nextElementX, this.elements[i + 1].getRightPointX())
                    this.elements.splice(i, 2)
                    ++newElements
                }
                else
                    this.elements.splice(i, 1)
                
                const previousElement = this.elements[this.elements.length - 1]
                this.generateElements(previousElement ? previousElement.getRightPointX() : nextElementX)
                
                ++newElements
                --i
            }
        }
    }
    moveElements()
    {
        for (let i = 0; i < this.elements.length; ++i)
        {
            this.elements[i].move()
        }
    }
    draw()
    {
        for (let i = 0; i < this.elements.length; ++i)
        {
            this.elements[i].draw()
        }
    }
    drawTracks()
    {
        if (trackEnabled)
        {
            for (let i = 0; i < this.elements.length; ++i)
            {
                this.elements[i].track.draw()
            }
        }
    }
}
class SideFloor extends Floor
{
    constructor(bottomBorder, topBorder, creations)
    {
        super(bottomBorder, topBorder, {min: 0, max: 0}, creations)
        
        this.leftPointX = screen.getDeletionBorder()
    }
    generatePrimaryElements()
    {
        const firstPrimaryElementX      = this.leftPointX
        const primaryElementsQuantity   = 6
        
        let nextElementX                = firstPrimaryElementX
        
        for (let i = 0; i < primaryElementsQuantity; ++i)
        {
            this.generateElements(nextElementX)
            let t = this.elements[this.elements.length - 1]
            nextElementX = t.getRightPointX()
        }
    }
    deleteElements()
    {
        if (this.elements[0].getRightPointX() + screen.x < this.leftPointX)
        {
            this.elements.splice(0, 1)
            this.generateElements(this.elements[this.elements.length - 1].getRightPointX())
        }
    }
    moveElements()
    {

    }
    draw()
    {
        if (!this.elements.length)
            return

        if (version == 'bad' && this.elements[0].isInHudClearZone && this.elements[0].isInHudClearZone())
        {
            this.drawHudZoneCeilingBoundary()
            return
        }

        this.drawContinuousSurface()
    }
    getContinuousSurfaceBounds()
    {
        let left = this.elements[0].getLeftPointX()
        let right = this.elements[0].getRightPointX()
        let top = Infinity
        let bottom = -Infinity
        let boundaryY = 0

        for (let i = 0; i < this.elements.length; ++i)
        {
            const element = this.elements[i]
            left = Math.min(left, element.getLeftPointX())
            right = Math.max(right, element.getRightPointX())

            const points = element.getPoints()
            for (let j = 0; j < points.length; ++j)
            {
                top = Math.min(top, points[j].y)
                bottom = Math.max(bottom, points[j].y)
            }
        }

        if (top > height / 2)
            boundaryY = top
        else
            boundaryY = bottom

        return {left, right, top, bottom, boundaryY}
    }
    drawContinuousSurface()
    {
        if (version != 'bad')
        {
            this.drawClassicContinuousSurface()
            return
        }

        const bounds = this.getContinuousSurfaceBounds()
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const x = bounds.left + screen.x
        const y = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top
        const boundaryY = bounds.boundaryY + screen.y
        const capHeight = Math.max(2, height * 0.012)
        const isLowerSurface = bounds.boundaryY == bounds.top
        const capY = isLowerSurface ? boundaryY : boundaryY - capHeight

        ctx.save()
        ctx.fillStyle = obstacleStyle.groundFill
        ctx.fillRect(x, y, surfaceWidth, surfaceHeight)

        ctx.fillStyle = obstacleStyle.groundCapFill
        ctx.fillRect(x, capY, surfaceWidth, capHeight)

        ctx.strokeStyle = obstacleStyle.groundStroke
        ctx.lineWidth = obstacleStyle.thinStrokeWidth
        ctx.globalAlpha = obstacleStyle.groundFillAlpha
        ctx.shadowColor = obstacleStyle.groundLine
        ctx.shadowBlur = obstacleStyle.outerGlowWidth
        ctx.strokeRect(x, y, surfaceWidth, surfaceHeight)
        ctx.restore()

        this.drawContinuousNeonBoundary(bounds)
    }
    drawClassicContinuousSurface()
    {
        const bounds = this.getContinuousSurfaceBounds()
        const x = bounds.left + screen.x
        const y = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top

        ctx.save()
        ctx.fillStyle = STYLE.colors.ground.fill
        ctx.fillRect(x, y, surfaceWidth, surfaceHeight)

        ctx.strokeStyle = STYLE.colors.ground.stroke
        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.shadowColor = STYLE.colors.ground.line
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.strokeRect(x, y, surfaceWidth, surfaceHeight)
        ctx.restore()

        this.drawClassicSurfaceShell(bounds)
        this.drawClassicContinuousBoundary(bounds)
    }
    drawClassicSurfaceShell(bounds)
    {
        const x = bounds.left + screen.x
        const y = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top
        const inset = Math.max(STYLE.strokes.neonGlowWidth, surfaceHeight * STYLE.badVersionEffects.obstacles.innerCopyInsetRatio)
        const shellWidth = Math.max(0, surfaceWidth - inset * 2)
        const shellHeight = Math.max(0, surfaceHeight - inset * 2)

        if (shellWidth <= 0 || shellHeight <= 0)
            return

        ctx.save()
        ctx.strokeStyle = STYLE.colors.ground.line
        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.globalAlpha = 0.58
        ctx.shadowColor = STYLE.colors.ground.line
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.strokeRect(x + inset, y + inset, shellWidth, shellHeight)

        ctx.globalAlpha = 0.2
        ctx.fillStyle = STYLE.colors.ground.line
        ctx.fillRect(x + inset, y + inset, shellWidth, Math.max(1, STYLE.strokes.neonWidth))
        ctx.fillRect(x + inset, y + inset + shellHeight - Math.max(1, STYLE.strokes.neonWidth), shellWidth, Math.max(1, STYLE.strokes.neonWidth))
        ctx.restore()
    }
    drawClassicContinuousBoundary(bounds)
    {
        const y = bounds.boundaryY + screen.y

        ctx.save()
        ctx.beginPath()

        ctx.lineWidth = STYLE.strokes.neonGlowWidth
        ctx.strokeStyle = STYLE.colors.ground.stroke
        ctx.shadowColor = STYLE.colors.ground.line
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.moveTo(bounds.left + screen.x, y)
        ctx.lineTo(bounds.right + screen.x, y)
        ctx.stroke()

        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.strokeStyle = STYLE.colors.ground.line
        ctx.shadowBlur = 0
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
    drawContinuousNeonBoundary(bounds)
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const y = bounds.boundaryY + screen.y

        ctx.save()
        ctx.beginPath()

        ctx.lineWidth = STYLE.strokes.neonGlowWidth
        ctx.strokeStyle = obstacleStyle.groundStroke
        ctx.shadowColor = obstacleStyle.groundLine
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.moveTo(bounds.left + screen.x, y)
        ctx.lineTo(bounds.right + screen.x, y)
        ctx.stroke()

        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.strokeStyle = obstacleStyle.groundLine
        ctx.shadowBlur = 0
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
    drawHudZoneCeilingBoundary()
    {
        const bounds = this.getContinuousSurfaceBounds()
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const x = bounds.left + screen.x
        const y = bounds.boundaryY + screen.y
        const surfaceY = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top
        const capHeight = Math.max(2, height * 0.012)

        ctx.save()
        ctx.fillStyle = obstacleStyle.groundFill
        ctx.fillRect(x, surfaceY, surfaceWidth, surfaceHeight)

        ctx.fillStyle = obstacleStyle.groundCapFill
        ctx.fillRect(x, y - capHeight, surfaceWidth, capHeight)

        ctx.beginPath()

        ctx.globalAlpha = 0.72
        ctx.lineWidth = STYLE.strokes.neonGlowWidth
        ctx.strokeStyle = obstacleStyle.groundStroke
        ctx.shadowColor = obstacleStyle.groundLine
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.moveTo(bounds.left + screen.x, y)
        ctx.lineTo(bounds.right + screen.x, y)
        ctx.stroke()

        ctx.globalAlpha = 1
        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.strokeStyle = obstacleStyle.groundLine
        ctx.shadowBlur = 0
        ctx.stroke()

        ctx.closePath()
        ctx.restore()
    }
}
