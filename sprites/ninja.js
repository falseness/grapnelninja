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
        this.bounce = null
        // A line hit lies on the element within radius of the centre.
        const reach = circleBounds(this.x, this.y, this.radius, defaultEqualityTolerance)
        for (let k = 0; k < floors.length; ++k)
        {
            for (let i = 0; i < floors[k].elements.length; ++i)
            {
                const element = floors[k].elements[i]
                if (!element)
                    continue
                if (!boundsOverlap(reach, pointsBounds(element.getPoints())))
                    continue

                if (twoCirclesIntersect(this.x, this.y, this.radius, element.getCircumscribedCircle()))
                {
                    let lines = element.getLines()
                    let hit = false
                    let contact = null
                    for (let j = 0; j < lines.length; ++j)
                    {
                        if (this.collisionNinjaWithLine(lines[j]))
                        {
                            contact = this.hitLine(element, lines[j], contact)
                            collision = lines[j]
                            hit = true
                        }
                    }
                    // A ball that already sank in still hits the nearest edge.
                    if (!hit && pointInPolygon(element.getPoints(), this.x, this.y))
                    {
                        collision = nearestLine(lines, this.x, this.y)
                        contact = this.hitLine(element, collision, contact)
                    }
                    if (contact && (!this.bounce || this.deeperContact(contact, this.bounce)))
                        this.bounce = contact
                }
            }
        }
        if (this.bounce)
            this.applyBounce(this.bounce)
        return collision
    }
    // Deadly hits act at once; a bouncy element keeps its nearest hit edge,
    // and the cycle bounces once off the element with the deepest one.
    // Edges the ball moves into rank first, so a shared seam edge never wins.
    hitLine(element, line, best)
    {
        const bouncy = element instanceof Trampoline ||
            (element instanceof Side && element.isBadVersionCeilingBoundary(line))
        if (!bouncy)
        {
            element.collision(this, line)
            return best
        }
        const contact = this.contactWith(line, element.getPoints())
        if (best && (best.approaching > contact.approaching ||
            (best.approaching == contact.approaching && best.distance <= contact.distance)))
            return best
        contact.element = element
        contact.line = line
        return contact
    }
    // Closest point of line, the normal towards the outside and the penetration.
    contactWith(line, points)
    {
        const dx = line.x2 - line.x1
        const dy = line.y2 - line.y1
        const length2 = dx * dx + dy * dy
        let t = length2 > 0 ? ((this.x - line.x1) * dx + (this.y - line.y1) * dy) / length2 : 0
        t = Math.max(0, Math.min(1, t))
        const px = line.x1 + t * dx
        const py = line.y1 + t * dy
        const distance = Math.hypot(this.x - px, this.y - py)
        // A sunk centre is pushed out through the edge, not further in.
        const side = pointInPolygon(points, this.x, this.y) ? -1 : 1
        let nx, ny
        if (distance > 0)
        {
            nx = side * (this.x - px) / distance
            ny = side * (this.y - py) / distance
        }
        else
        {
            const length = Math.sqrt(length2)
            nx = dy / length
            ny = -dx / length
            if (pointInPolygon(points, px + nx, py + ny))
            {
                nx = -nx
                ny = -ny
            }
        }
        return {x: px, y: py, nx: nx, ny: ny, distance: distance, depth: this.radius - side * distance,
                approaching: this.speedX * nx + this.speedY * ny < 0}
    }
    deeperContact(a, b)
    {
        if (a.approaching != b.approaching)
            return a.approaching
        return a.depth > b.depth
    }
    applyBounce(contact)
    {
        if (contact.approaching)
        {
            bounceSpeed(this, contact.line)
            if (visualEffects && visualEffects.particles)
                visualEffects.particles.emitTrampolineSplash(this, contact.element)
        }
        const out = this.radius + GAMEPLAY.cubeContactEpsilon
        this.x = contact.x + contact.nx * out
        this.y = contact.y + contact.ny * out
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
        // A cycle longer than the radius could jump over a thin edge:
        // move in equal sub-steps, colliding after each one.
        const steps = Math.max(1, Math.ceil(Math.hypot(this.speedX, this.speedY) / this.radius))
        for (let i = 1; i <= steps; ++i)
        {
            this.x += this.speedX / steps
            this.y += this.speedY / steps
            
            if (i == steps)
                this.track.addPos(this.x, this.y)
            
            this.collision()
            // A deadly hit restarted the game with a new ninja.
            if (ninja !== this)
                return
        }
        
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
        ctx.globalAlpha = STYLE.playerVisuals.innerHighlightAlpha
        ctx.fill()
        ctx.closePath()
        ctx.globalAlpha = STYLE.alpha.full

        this.drawRotationMarker()

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
    drawRotationMarker()
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
