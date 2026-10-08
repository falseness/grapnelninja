class Rect extends Element
{
    constructor(object)
    {
        super(object)
        
        // Semantic factory tag: palette edits must not change the rect type.
        this.isDangerRect = object.isDangerRect === true
        this.width = object.width
        this.height = object.height
        
        
        this.fill   = this.fill     || (this.isDangerRect ? STYLE.colors.cube.dangerFill : STYLE.colors.cube.grayFill)
        this.stroke = this.stroke   || (this.isDangerRect ? STYLE.colors.cube.dangerStroke : STYLE.colors.cube.grayStroke)
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
        // One object per element, refilled: every caller reads it at once
        const circle = this.circumscribedCircle || (this.circumscribedCircle = {x: 0, y: 0, radius: 0})
        circle.x = this.circle.x + this.x
        circle.y = this.circle.y + this.y
        circle.radius = this.circle.radius
        return circle
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
    writeBounds(out)
    {
        const x = this.getX()
        const y = this.getY()
        const xPlusMarginX = x + this.width
        const yPlusMarginY = y + this.height

        startBounds(out, x, y)
        addBoundsPoint(out, xPlusMarginX, y)
        addBoundsPoint(out, xPlusMarginX, yPlusMarginY)
        addBoundsPoint(out, x, yPlusMarginY)
        return out
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
    drawExtrusion()
    {
        this.drawPolygonExtrusion()
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
        ctx.fillRect(x, y, this.width, this.height)
        ctx.beginPath()
        ctx.rect(x, y, this.width, this.height)
        strokeNeonPath(this.stroke)
        const innerFill = !this.isDangerRect && this.stroke == STYLE.colors.cube.blueStroke ? STYLE.colors.cube.blueFill : this.stroke
        this.drawInnerRectangleCopy(x, y, STYLE.badVersionEffects.obstacles.innerCopyInsetRatio, innerFill, this.stroke)
        ctx.restore()
    }
    drawBadVersionRect(x, y)
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const isGreenSafe = !this.isDangerRect && (this.stroke == STYLE.colors.cube.greenStroke || this.stroke == STYLE.colors.hazard.harmlessStroke)
        const fill = isGreenSafe ? obstacleStyle.greenFill : (this.isDangerRect ? obstacleStyle.dangerFill : obstacleStyle.cubeFill)
        const isBlueCube = !this.isDangerRect && this.stroke == STYLE.colors.cube.blueStroke
        const copyFill = isBlueCube
            ? STYLE.colors.cube.blueFill
            : isGreenSafe
            ? obstacleStyle.greenHighlightFill
            : (this.isDangerRect ? obstacleStyle.dangerHighlightFill : obstacleStyle.cubeHighlightFill)

        ctx.save()
        ctx.fillStyle = fill
        ctx.fillRect(x, y, this.width, this.height)

        ctx.beginPath()
        ctx.rect(x, y, this.width, this.height)
        strokeNeonPath(this.stroke)

        this.drawInnerRectangleCopy(x, y, obstacleStyle.innerCopyInsetRatio, copyFill, this.stroke)

        ctx.restore()
    }
    drawInnerRectangleCopy(x, y, insetRatio, fillStyle, strokeStyle)
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const isBlueCubeShell = !this.isDangerRect && strokeStyle == STYLE.colors.cube.blueStroke
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
        ctx.lineWidth = STYLE.strokes.neonOutline.innerWidth / scale[version]
        ctx.strokeRect(x + inset, y + inset, width, height)
        ctx.restore()
    }
}
