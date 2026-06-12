class Rect extends Element
{
    constructor(object)
    {
        super(object)
        
        this.width = object.width
        this.height = object.height
        
        
        this.fill   = this.fill     || STYLE.colors.cube.grayFill
        this.stroke = this.stroke   || STYLE.colors.cube.grayStroke
        this.isPairElement = object.isPairElement || function() {return false}
        
        this.circle =
        {
            x: this.width  / 2,
            y: this.height / 2
        }
        this.circle.radius = Math.sqrt(Math.pow(this.circle.x - this.x, 2) + Math.pow(this.circle.y - this.y, 2))
    }
    getCircumscribedCircle()
    {
        return {x: this.circle.x + this.x, y: this.circle.y + this.y, radius: this.circle.radius}
    }
    getPoints()
    {   
        let x = this.getX()
        let y = this.getY()
        
        let xPlusMarginX = x + this.width
        let yPlusMarginY = y + this.height
        
        let points = 
        [
            {x: x           , y: y              },
            {x: xPlusMarginX, y: y              },
            {x: xPlusMarginX, y: yPlusMarginY   },
            {x: x           , y: yPlusMarginY   }
        ]
        
        return points
    }
    moveX(speed)
    {
        super.moveX(speed)
    }
    getRightPointX()
    {
        return this.getX() + this.width
    }
    getLeftPointX()
    {
        return this.getX()
    }
    draw()
    {
        const x = this.x + screen.x
        const y = this.y + screen.y

        if (version == 'bad')
        {
            this.drawBadVersionRect(x, y)
            return
        }

        ctx.save()
        ctx.fillStyle   = this.fill
        ctx.strokeStyle = this.stroke
        
        ctx.fillRect(x, y, this.width, this.height)
        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.shadowColor = this.stroke
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.strokeRect(x, y, this.width, this.height)
        this.drawInnerRectangleCopy(x, y, STYLE.badVersionEffects.obstacles.innerCopyInsetRatio, this.stroke, this.stroke)
        ctx.restore()
    }
    drawBadVersionRect(x, y)
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const isGreenSafe = this.stroke == STYLE.colors.cube.greenStroke || this.stroke == STYLE.colors.hazard.harmlessStroke
        const isGray = this.stroke == STYLE.colors.cube.grayStroke
        const fill = isGreenSafe ? obstacleStyle.greenFill : (isGray ? obstacleStyle.grayFill : obstacleStyle.cubeFill)
        const isBlueCube = this.stroke == STYLE.colors.cube.blueStroke
        const copyFill = isBlueCube
            ? this.stroke
            : isGreenSafe
            ? obstacleStyle.greenHighlightFill
            : (isGray ? obstacleStyle.grayHighlightFill : obstacleStyle.cubeHighlightFill)

        ctx.save()
        ctx.fillStyle = fill
        ctx.fillRect(x, y, this.width, this.height)

        ctx.strokeStyle = this.stroke
        ctx.lineWidth = obstacleStyle.outerGlowWidth
        ctx.globalAlpha = obstacleStyle.highlightAlpha
        ctx.shadowColor = this.stroke
        ctx.shadowBlur = obstacleStyle.outerGlowWidth
        ctx.strokeRect(x, y, this.width, this.height)

        ctx.globalAlpha = 1
        ctx.lineWidth = obstacleStyle.thinStrokeWidth
        ctx.shadowBlur = 0
        ctx.strokeRect(x, y, this.width, this.height)

        this.drawInnerRectangleCopy(x, y, obstacleStyle.innerCopyInsetRatio, copyFill, this.stroke)

        ctx.restore()
    }
    drawInnerRectangleCopy(x, y, insetRatio, fillStyle, strokeStyle)
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const isBlueCubeShell = strokeStyle == STYLE.colors.cube.blueStroke
        const inset = Math.min(this.width, this.height) * insetRatio
        const width = Math.max(0, this.width - inset * 2)
        const height = Math.max(0, this.height - inset * 2)

        if (width <= 0 || height <= 0)
            return

        ctx.save()
        ctx.shadowBlur = 0
        ctx.fillStyle = fillStyle
        ctx.globalAlpha = isBlueCubeShell ? STYLE.alpha.full : obstacleStyle.innerCopyFillAlpha
        ctx.fillRect(x + inset, y + inset, width, height)

        ctx.globalAlpha = isBlueCubeShell ? STYLE.alpha.full : obstacleStyle.innerHighlightAlpha
        ctx.strokeStyle = strokeStyle
        ctx.lineWidth = version == 'bad' ? obstacleStyle.thinStrokeWidth : STYLE.strokes.neonWidth
        ctx.strokeRect(x + inset, y + inset, width, height)
        ctx.restore()
    }
}
