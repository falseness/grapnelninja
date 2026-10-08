// Scratch box for the broad phase, refilled for every element
const ninjaElementBounds = {left: 0, right: 0, top: 0, bottom: 0}

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
                // The circumscribed circle is the cheap reject (no point arrays),
                // so it runs before the bounds of the points.
                if (!twoCirclesIntersect(this.x, this.y, this.radius, element.getCircumscribedCircle()))
                    continue

                if (boundsOverlap(reach, elementBounds(element, ninjaElementBounds)))
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
            // A deadly hit restarted the game with a new ninja or froze
            // the run (continue offer, game over interstitial).
            if (ninja !== this || isRunFrozen())
                return
        }
        
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
        const sprite = Ninja.getGlowSprite(this.getRingOuterRadius(), this.fill, this.stroke, ctx.getTransform())

        ctx.save()
        ctx.translate(centerX, centerY)
        ctx.globalAlpha = blinkAlpha
        if (sprite.halo)
            ctx.drawImage(sprite.halo, -sprite.haloHalf, -sprite.haloHalf, sprite.haloHalf * 2, sprite.haloHalf * 2)
        // Ring, dark centre and inner rim are one pre-rendered image: no shadowBlur per frame
        ctx.drawImage(sprite.canvas, -sprite.half, -sprite.half, sprite.half * 2, sprite.half * 2)

        ctx.rotate(this.visualRotation)
        this.drawRotationMarker(blinkAlpha)

        ctx.restore()
    }
    // radius is the crisp ring outer edge; the soft halo has its own sprite margin.
    // One sprite is kept and rebuilt when the radius, colours or pixel density change
    // (version switch, resize)
    static getGlowSprite(radius, fill, stroke, transform)
    {
        const config = STYLE.playerVisuals
        const density = Math.hypot(transform.a, transform.b) || 1
        const pixelScale = Math.max(0.25, Math.min(config.maxSpritePixelScale, Math.ceil(density * 4) / 4))
        const key = [radius, fill, stroke, pixelScale, STYLE.features.innerGlow, STYLE.player.outerGlow].join('|')
        const cached = Ninja.glowSprite

        if (cached && cached.key === key)
            return cached

        const ringWidth = radius * config.ringWidthRatio
        const ringRadius = radius - ringWidth * 0.5
        const half = radius * config.spriteRadiusRatio
        const spriteCanvas = document.createElement('canvas')
        spriteCanvas.width = spriteCanvas.height = Math.max(1, Math.ceil(half * 2 * pixelScale))
        const spriteCtx = spriteCanvas.getContext('2d')
        const fit = spriteCanvas.width / (half * 2)
        spriteCtx.setTransform(fit, 0, 0, fit, half * fit, half * fit)

        const ring = () =>
        {
            spriteCtx.beginPath()
            spriteCtx.arc(0, 0, ringRadius, 0, Math.PI * 2, false)
        }

        // Dark navy centre, a little lighter towards the ring
        const centre = spriteCtx.createRadialGradient(0, 0, 0, 0, 0, radius)
        centre.addColorStop(0, STYLE.colors.player.centre)
        centre.addColorStop(1, fill)
        spriteCtx.beginPath()
        spriteCtx.arc(0, 0, radius, 0, Math.PI * 2, false)
        spriteCtx.fillStyle = centre
        spriteCtx.fill()

        if (STYLE.features.innerGlow)
        {
            // Halo: the ring blurred (shadowBlur works in canvas pixels), clipped to
            // the ball and faint, so the centre stays dark
            spriteCtx.save()
            spriteCtx.clip()
            spriteCtx.globalAlpha = config.haloAlpha
            spriteCtx.strokeStyle = STYLE.colors.player.halo
            spriteCtx.lineWidth = ringWidth
            spriteCtx.shadowColor = STYLE.colors.player.halo
            spriteCtx.shadowBlur = radius * config.haloBlurRatio * fit
            ring()
            spriteCtx.stroke()
            spriteCtx.restore()
        }

        // Thick cyan ring with a thin pale hot core line along its middle
        ring()
        spriteCtx.strokeStyle = stroke
        spriteCtx.lineWidth = ringWidth
        spriteCtx.stroke()
        ring()
        spriteCtx.strokeStyle = STYLE.colors.player.highlight
        spriteCtx.lineWidth = ringWidth * config.ringCoreWidthRatio
        spriteCtx.stroke()

        // Thin hot rim at the original outer edge keeps the small ring crisp
        // against its restored halo without changing its drawn radius.
        const rimWidth = ringWidth * config.rimWidthRatio
        spriteCtx.beginPath()
        spriteCtx.arc(0, 0, radius - rimWidth * 0.5, 0, Math.PI * 2, false)
        spriteCtx.globalAlpha = config.rimAlpha
        spriteCtx.strokeStyle = STYLE.colors.player.highlight
        spriteCtx.lineWidth = rimWidth
        spriteCtx.stroke()
        spriteCtx.globalAlpha = STYLE.alpha.full

        // Separate cache keeps the ring's original pixel grid and antialiasing.
        const haloHalf = radius * config.outerHaloRadiusRatio
        let haloCanvas = null
        if (STYLE.player.outerGlow)
        {
            haloCanvas = document.createElement('canvas')
            haloCanvas.width = haloCanvas.height = Math.ceil(haloHalf * 2 * pixelScale)
            const haloCtx = haloCanvas.getContext('2d')
            const fit = haloCanvas.width / (haloHalf * 2)
            haloCtx.setTransform(fit, 0, 0, fit, haloHalf * fit, haloHalf * fit)
            const halo = haloCtx.createRadialGradient(0, 0, radius * 0.7, 0, 0, haloHalf)
            halo.addColorStop(0, STYLE.colors.player.halo)
            halo.addColorStop(1, 'rgba(34, 200, 255, 0)')
            haloCtx.globalAlpha = config.outerHaloAlpha
            haloCtx.fillStyle = halo
            haloCtx.fillRect(-haloHalf, -haloHalf, haloHalf * 2, haloHalf * 2)
        }
        Ninja.glowSprite = {key, canvas: spriteCanvas, half, halo: haloCanvas, haloHalf}
        return Ninja.glowSprite
    }
    getVisualRadius()
    {
        return Math.max(this.radius, STYLE.playerVisuals.minScreenRadius / scale[version])
    }
    // Where the pre-overhaul ball ended (e430f92): its neon stroke was centred on the visual radius
    getRingOuterRadius()
    {
        return this.getVisualRadius() + STYLE.strokes.neonWidth * 0.5 / scale[version]
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
