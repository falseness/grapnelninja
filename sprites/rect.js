// One repeating tile per variant/context, shared by every orange obstacle.
const dangerHatchPatterns = new WeakMap()
function dangerHatchPattern(context, variant)
{
    let cache = dangerHatchPatterns.get(context)
    if (!cache) { cache = Object.create(null); dangerHatchPatterns.set(context, cache) }
    if (cache[variant]) return cache[variant]
    const tile = document.createElement('canvas')
    tile.width = tile.height = 32
    const c = tile.getContext('2d')
    c.strokeStyle = variant == 'bold' ? '#99501c' : '#b56020'
    c.lineWidth = variant == 'bold' ? 9 : variant == 'thin' ? 2 : 3
    c.beginPath()
    for (let i = -32; i <= 64; i += 32) {
        if (variant == 'chevron') {
            c.moveTo(i, 0); c.lineTo(i + 16, 16); c.lineTo(i, 32)
        } else {
            c.moveTo(i - 32, -32); c.lineTo(i + 64, 64)
            if (variant == 'cross') { c.moveTo(i + 64, -32); c.lineTo(i - 32, 64) }
        }
    }
    c.stroke()
    return cache[variant] = context.createPattern(tile, 'repeat')
}

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
        this.drawDangerHatch(x, y)
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
        this.drawDangerHatch(x, y)

        ctx.restore()
    }
    drawDangerHatch(x, y)
    {
        if (!this.isDangerRect || STYLE.dangerHatch.variant == 'off') return
        const pattern = dangerHatchPattern(ctx, STYLE.dangerHatch.variant)
        // Leave the neon outline and inner bevel clear. Translation anchors the
        // pattern to the obstacle, including fractional camera movement.
        const inset = Math.max(2, Math.min(this.width, this.height) * .20)
        if (this.width <= inset * 2 || this.height <= inset * 2) return
        ctx.save()
        ctx.translate(x, y)
        ctx.beginPath()
        ctx.rect(inset, inset, this.width - inset * 2, this.height - inset * 2)
        ctx.clip()
        ctx.fillStyle = pattern
        ctx.fillRect(inset, inset, this.width - inset * 2, this.height - inset * 2)
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
