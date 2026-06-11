class Ninja
{
    constructor(object)
    {
        this.x      = object.x
        this.y      = object.y
        
        this.speedX = object.speedX || 0
        this.speedY = object.speedY || 0
        this.radius = object.radius
        this.mass   = Math.PI * Math.pow(this.radius, 2) * blueSpriteDensity
        
        this.fill   = object.fill
        this.stroke = object.stroke
        this.visualRotation = 0

        this.track = new TrackLine(this.radius * 1.5, STYLE.colors.player.trail, STYLE.timing.trailPoints)
        this.track.addPos(this.x, this.y, true)
    }
    collision()
    {
        let collision = false
        for (let k = 0; k < floors.length; ++k)
        {
            for (let i = 0; i < floors[k].elements.length; ++i)
            {
                if (twoCirclesIntersect(this.x, this.y, this.radius, floors[k].elements[i].getCircumscribedCircle()))
                {
                    let lines = floors[k].elements[i].getLines()
                    for (let j = 0; j < lines.length; ++j)
                    {
                        if (this.collisionNinjaWithLine(lines[j]))
                        {
                            floors[k].elements[i].collision(this, lines[j])
                            collision = lines[j]
                        }
                    }
                }
            }
        }
        return collision
    }
    collisionNinjaWithLine(line)
    {
        return collisionCircleWithLine(line, this.x, this.y, this.radius)
    }
    move()
    {
        const maxSpeed = 0.02 * height
        if (this.speedY > maxSpeed)
            this.speedY = maxSpeed
        if (this.speedY < -maxSpeed)
            this.speedY = -maxSpeed
        this.x += this.speedX
        this.y += this.speedY
        
        this.track.addPos(this.x, this.y)
        
        this.collision()
        
        if (this.x + screen.x < screen.getDeletionBorder())
            reStart()
    }
    draw()
    {
        this.updateVisualRotation()

        const centerX = this.x + screen.x
        const centerY = this.y + screen.y

        ctx.save()
        ctx.translate(centerX, centerY)
        ctx.rotate(this.visualRotation)

        ctx.beginPath()

        ctx.arc(0, 0, this.radius, 0, Math.PI * 2, false)

        ctx.fillStyle = this.fill
        ctx.fill()

        ctx.strokeStyle = this.stroke
        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.shadowColor = this.stroke
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth
        ctx.stroke()

        ctx.closePath()
        ctx.shadowBlur = 0

        ctx.beginPath()
        ctx.arc(0, 0, this.radius * 0.45, 0, Math.PI * 2, false)
        ctx.fillStyle = STYLE.colors.player.core
        ctx.globalAlpha = 0.8
        ctx.fill()
        ctx.closePath()

        this.drawRotationMarker()

        ctx.restore()
    }
    updateVisualRotation()
    {
        const config = STYLE.playerVisuals
        const speed = Math.sqrt(this.speedX * this.speedX + this.speedY * this.speedY)

        if (speed < config.rotationMinSpeed)
            return

        this.visualRotation += speed * config.rotationSpeed
    }
    drawRotationMarker()
    {
        const config = STYLE.playerVisuals
        const markerWidth = Math.max(1, this.radius * config.rotationMarkerWidthRatio)
        const markerLength = this.radius * config.rotationMarkerLengthRatio
        const markerOffset = this.radius * config.rotationMarkerOffsetRatio

        ctx.beginPath()
        ctx.moveTo(-markerLength * 0.5, -markerOffset)
        ctx.lineTo(markerLength * 0.5, markerOffset)
        ctx.strokeStyle = STYLE.colors.player.core
        ctx.lineWidth = markerWidth
        ctx.lineCap = 'round'
        ctx.globalAlpha = config.rotationMarkerAlpha
        ctx.shadowColor = STYLE.colors.player.core
        ctx.shadowBlur = STYLE.strokes.neonGlowWidth * 0.5
        ctx.stroke()
        ctx.closePath()
        ctx.globalAlpha = STYLE.alpha.full
    }
}
class TrackLine
{
    constructor(width, stroke, pointsLimit)
    {
        this.pos        = []
        this.lineWidth  = width
        this.stroke     = stroke
        this.pointsLimit= pointsLimit
    }
    delete()
    {
        if (trackEnabled && QUALITY.playerTrail)
        {
            if (this.pos.length > this.pointsLimit)
            {
                this.pos.splice(0, this.pos.length - this.pointsLimit)
            }
        }
    }
    addPos(x, y, mustAdd)
    {
        if ((trackEnabled && QUALITY.playerTrail && firstCycleInThisTick) || mustAdd)
        {
            this.pos.push({x, y})
            this.delete()
        }
    }
    draw()
    {
        if (trackEnabled && QUALITY.playerTrail)
        {
            ctx.beginPath()

            ctx.lineCap = 'butt'
            ctx.moveTo(this.pos[0].x + screen.x, this.pos[0].y + screen.y)

            for (let i = 1; i < this.pos.length; ++i)
            {
                ctx.lineTo(this.pos[i].x + screen.x, this.pos[i].y + screen.y)
            }
            ctx.lineWidth = this.lineWidth

            ctx.globalAlpha = STYLE.alpha.track
            ctx.strokeStyle = this.stroke
            //ctx.fillStyle   = ninja.fill

            //ctx.fill()
            ctx.stroke()

            ctx.globalAlpha = STYLE.alpha.full

            ctx.lineWidth = STYLE.strokes.defaultWidth

            ctx.closePath() 
        }
    }
}
