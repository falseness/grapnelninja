// Bounds and coordinates use the caller's local or shared world origin. Inverse-transform the backing
// viewport so even enormous mostly-offscreen objects enumerate visible lines only.
// Path2D deliberately leaves the caller's current path (triangle border) intact.
function drawDangerHatchLines(context, variant, colour = variant == 'bold' ? '#99501c' : '#b56020', left, top, right, bottom)
{
    if (variant == 'off') return
    const inverse = context.getTransform().inverse()
    const corners = [[0, 0], [context.canvas.width, 0], [0, context.canvas.height],
        [context.canvas.width, context.canvas.height]].map(([x, y]) => inverse.transformPoint({x, y}))
    left = Math.max(left, Math.min(...corners.map(p => p.x)))
    right = Math.min(right, Math.max(...corners.map(p => p.x)))
    top = Math.max(top, Math.min(...corners.map(p => p.y)))
    bottom = Math.min(bottom, Math.max(...corners.map(p => p.y)))
    if (!(left < right && top < bottom)) return
    const lineWidth = variant == 'bold' ? 9 : variant == 'thin' ? 2 : 3
    // Include stroke coverage at the clip edges and complete chevron joins.
    const pad = lineWidth * 2
    left -= pad; right += pad; top -= pad; bottom += pad
    const path = new Path2D()
    if (variant == 'chevron') {
        for (let y = Math.floor(top / 32) * 32; y <= bottom; y += 32)
            for (let x = Math.ceil((left - 16) / 32) * 32; x <= right; x += 32) {
                path.moveTo(x, y); path.lineTo(x + 16, y + 16); path.lineTo(x, y + 32)
            }
    } else {
        for (let d = Math.ceil((left - bottom) / 32) * 32; d <= right - top; d += 32) {
            path.moveTo(top + d, top); path.lineTo(bottom + d, bottom)
        }
        if (variant == 'cross')
            for (let d = Math.ceil((left + top) / 32) * 32; d <= right + bottom; d += 32) {
                path.moveTo(d - top, top); path.lineTo(d - bottom, bottom)
            }
    }
    context.save()
    context.strokeStyle = colour
    context.lineWidth = lineWidth
    context.lineCap = 'butt'
    context.lineJoin = 'miter'
    context.miterLimit = 10
    context.setLineDash([])
    context.stroke(path)
    context.restore()
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
    // The same array until the rect moves or resizes: callers only read it
    // (trails keep earlier arrays, so a change builds a new one)
    getPoints()
    {   
        let x = this.getX()
        let y = this.getY()
        const cache = this.pointsCache
        if (cache && cache.x === x && cache.y === y && cache.width === this.width && cache.height === this.height)
            return cache.points
        
        let xPlusMarginX = x + this.width
        let yPlusMarginY = y + this.height
        
        let points = 
        [
            {x: x           , y: y              },
            {x: xPlusMarginX, y: y              },
            {x: xPlusMarginX, y: yPlusMarginY   },
            {x: x           , y: yPlusMarginY   }
        ]
        this.pointsCache = {x, y, width: this.width, height: this.height, points}
        
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
    drawDangerHatch(x, y, colour)
    {
        if ((!this.isDangerRect && !colour) || STYLE.dangerHatch.variant == 'off') return
        // Leave the neon outline and inner bevel clear. Translation anchors the
        // pattern to the obstacle, including fractional camera movement.
        const inset = Math.max(2, Math.min(this.width, this.height) * .20)
        if (this.width <= inset * 2 || this.height <= inset * 2) return
        ctx.save()
        ctx.translate(x, y)
        const clip = new Path2D()
        clip.rect(inset, inset, this.width - inset * 2, this.height - inset * 2)
        ctx.clip(clip)
        drawDangerHatchLines(ctx, STYLE.dangerHatch.variant, colour,
            inset, inset, this.width - inset, this.height - inset)
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
