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
        this.invulnerableMs = 0

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
                const element = floors[k].elements[i]
                if (!element)
                    continue

                if (twoCirclesIntersect(this.x, this.y, this.radius, element.getCircumscribedCircle()))
                {
                    let lines = element.getLines()
                    for (let j = 0; j < lines.length; ++j)
                    {
                        if (this.collisionNinjaWithLine(lines[j]))
                        {
                            element.collision(this, lines[j])
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
        const maxSpeed = screenHeightPercent(GAMEPLAY.ninjaMaxSpeedHeightPercent)
        if (this.speedY > maxSpeed)
            this.speedY = maxSpeed
        if (this.speedY < -maxSpeed)
            this.speedY = -maxSpeed
        this.x += this.speedX
        this.y += this.speedY
        
        this.track.addPos(this.x, this.y)
        
        this.collision()
        
        if (this.x + screen.x < screen.getDeletionBorder())
            onLethalDeath()
    }
    isInvulnerable()
    {
        return this.invulnerableMs > 0
    }
    // Driven by physics steps, so pauses and the continue offer do not consume it.
    tickInvulnerability(ms)
    {
        if (this.invulnerableMs > 0)
            this.invulnerableMs = Math.max(0, this.invulnerableMs - ms)
    }
    getBlinkAlpha()
    {
        if (this.isInvulnerable() && Math.floor(Math.round(this.invulnerableMs) / RESPAWN_BLINK_MS) % 2 == 0)
            return RESPAWN_BLINK_ALPHA
        return STYLE.alpha.full
    }
    draw()
    {
        this.updateVisualRotation()
        const blinkAlpha = this.getBlinkAlpha()

        const centerX = this.x + screen.x
        const centerY = this.y + screen.y

        ctx.save()
        ctx.translate(centerX, centerY)
        ctx.rotate(this.visualRotation)
        ctx.globalAlpha = blinkAlpha

        const visualRadius = this.getVisualRadius()

        ctx.beginPath()

        ctx.arc(0, 0, visualRadius, 0, Math.PI * 2, false)

        ctx.fillStyle = this.fill
        ctx.fill()

        ctx.strokeStyle = this.stroke
        ctx.lineWidth = STYLE.strokes.neonWidth
        ctx.shadowColor = this.stroke
        ctx.shadowBlur = visualRadius * STYLE.playerVisuals.bodyShadowBlurRatio
        ctx.stroke()

        ctx.closePath()
        ctx.shadowBlur = 0

        ctx.beginPath()
        ctx.arc(0, 0, visualRadius * STYLE.playerVisuals.innerHighlightRadiusRatio, 0, Math.PI * 2, false)
        ctx.fillStyle = STYLE.colors.player.highlight
        ctx.globalAlpha = STYLE.playerVisuals.innerHighlightAlpha * blinkAlpha
        ctx.fill()
        ctx.closePath()
        ctx.globalAlpha = blinkAlpha

        this.drawRotationMarker(blinkAlpha)

        ctx.restore()
    }
    getVisualRadius()
    {
        return Math.max(this.radius, STYLE.playerVisuals.minScreenRadius / scale[version])
    }
    updateVisualRotation()
    {
        const config = STYLE.playerVisuals
        const speed = Math.sqrt(this.speedX * this.speedX + this.speedY * this.speedY)

        if (speed < config.rotationMinSpeed)
            return

        this.visualRotation += speed * config.rotationSpeed
    }
    drawRotationMarker(blinkAlpha)
    {
        const config = STYLE.playerVisuals
        const visualRadius = this.getVisualRadius()
        const markerWidth = Math.max(1, visualRadius * config.rotationMarkerWidthRatio)
        const markerLength = visualRadius * config.rotationMarkerLengthRatio
        const markerOffset = visualRadius * config.rotationMarkerOffsetRatio

        ctx.beginPath()
        ctx.moveTo(-markerLength * 0.5, -markerOffset)
        ctx.lineTo(markerLength * 0.5, markerOffset)
        ctx.strokeStyle = STYLE.colors.player.core
        ctx.lineWidth = markerWidth
        ctx.lineCap = 'round'
        ctx.globalAlpha = config.rotationMarkerAlpha * blinkAlpha
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
