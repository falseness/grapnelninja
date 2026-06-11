class Rect extends Element
{
    constructor(object)
    {
        super(object)
        
        this.width = object.width
        this.height = object.height
        
        
        this.fill   = this.fill     || STYLE.colors.cube.platformFill
        this.stroke = this.stroke   || STYLE.colors.cube.stroke
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
        if (version == 'bad')
        {
            this.drawBadVersionRect()
            return
        }

        ctx.save()
        ctx.fillStyle   = this.fill
        ctx.strokeStyle = this.stroke
        
        ctx.fillRect(this.x + screen.x, this.y + screen.y, this.width, this.height)
        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.shadowColor = this.stroke
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.strokeRect(this.x + screen.x, this.y + screen.y, this.width, this.height)
        ctx.restore()
    }
    drawBadVersionRect()
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const x = this.x + screen.x
        const y = this.y + screen.y
        const accentInset = Math.min(this.width, this.height) * obstacleStyle.accentInsetRatio

        ctx.save()
        ctx.fillStyle = obstacleStyle.cubeFill
        ctx.fillRect(x, y, this.width, this.height)

        ctx.fillStyle = obstacleStyle.cubeHighlightFill
        ctx.fillRect(x + accentInset, y + accentInset, Math.max(0, this.width - accentInset * 2), Math.max(0, this.height * 0.32))

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

        ctx.globalAlpha = obstacleStyle.innerHighlightAlpha
        ctx.strokeStyle = STYLE.colors.cube.accentStroke
        ctx.strokeRect(x + accentInset, y + accentInset, Math.max(0, this.width - accentInset * 2), Math.max(0, this.height - accentInset * 2))

        ctx.restore()
    }
}
