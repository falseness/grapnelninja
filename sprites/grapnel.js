const grapnelSpeed = screenHeightPercent(GAMEPLAY.grapnelThrowHeightPercent) / cyclesPerTick
const grappleSpeed = screenHeightPercent(GAMEPLAY.grapplePullHeightPercent) / Math.pow(cyclesPerTick, 2)

// Scratch box for the broad phase, refilled for every element
const grapnelElementBounds = {left: 0, right: 0, top: 0, bottom: 0}
// The Grapple Over helix stops twisting under prefers-reduced-motion: reduce.
const grapnelReducedMotionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null

class Grapnel
{
    constructor(object)
    {
        this.throwed = false
        
        this.grappled = false
        this.pos = []
        this.traveled = 0
        this.shotStep = null
        // Unit aim of the owning press; a held miss parks along it at the range edge.
        this.aim = null
        // Where a blocking surface cuts the held line this tick, if anywhere.
        this.clip = null
        
        this.stroke = object.stroke
    }
    move()
    {
        if (this.throwed)
        {
            if (version === 'grapple_over' && !this.grappled)
            {
                const tip = this.pos[0]
                const radius = grappleOverAcquisitionRadius()
                if (this.isParked())
                {
                    // acquireShot() tests the whole held line; the tip only follows the aim.
                    tip[0] = ninja.x + this.aim.x * radius
                    tip[1] = ninja.y + this.aim.y * radius
                    this.shotStep = null
                    return
                }
                const speed = Math.hypot(this.speedX, this.speedY)
                const remaining = Math.max(0, radius - this.traveled)
                const length = Math.min(speed, remaining)
                this.shotStep = {x: tip[0], y: tip[1], length}
                if (speed > 0)
                {
                    tip[0] += this.speedX / speed * length
                    tip[1] += this.speedY / speed * length
                }
                this.traveled += length
                return
            }
            for (let i = 0; i < this.pos.length; ++i)
            {
                if (this.pos[i][2].isEmpty())
                {
                    this.pos[i][0] += this.speedX
                    this.pos[i][1] += this.speedY
                }
            }
            
            // Follow each element's actual displacement from its last move().
            for (let i = 0; i < this.pos.length; ++i)
            {
                this.pos[i][0] += this.pos[i][2].dx
                this.pos[i][1] += this.pos[i][2].dy
            }
        }
    }
    calcSpeed(direction)
    {
        let dx = direction.x - ninja.x
        let dy = direction.y - ninja.y
        let distance = Math.sqrt(Math.pow(dx, 2) + Math.pow(dy, 2))
        
        if (version === 'grapple_over' && distance === 0)
            return {sin: 0, cos: 0}
        let sin = dy / distance
        let cos = dx / distance

        return {sin: sin, cos: cos}
        
    }
    // A shot that used its full range stays out while its owning press is held.
    isParked()
    {
        return this.throwed && !this.grappled && this.aim !== null &&
            this.traveled >= grappleOverAcquisitionRadius() &&
            pressHeld && gameplayPressOwned && !stalePress
    }
    setAim(direction)
    {
        const dx = direction.x - ninja.x, dy = direction.y - ninja.y
        const length = Math.hypot(dx, dy)
        if (length > 0)
            this.aim = {x: dx / length, y: dy / length}
    }
    endShot()
    {
        this.throwed = this.grappled = false
        this.pos = []
        this.shotStep = null
        this.aim = null
        this.clip = null
        stalePress = true
    }
    // Inclusive segment intersection: the last clipped endpoint is in range.
    // Collinear edges use their first overlap along the moving tip's path.
    shotIntersection(start, end, line)
    {
        const rx = end[0] - start.x, ry = end[1] - start.y
        const sx = line.x2 - line.x1, sy = line.y2 - line.y1
        const qx = line.x1 - start.x, qy = line.y1 - start.y
        const cross = rx * sy - ry * sx
        const eps = 1e-10
        let t
        if (Math.abs(cross) > eps)
        {
            t = (qx * sy - qy * sx) / cross
            const u = (qx * ry - qy * rx) / cross
            if (t < -eps || t > 1 + eps || u < -eps || u > 1 + eps) return null
        }
        else
        {
            const length2 = rx * rx + ry * ry
            if (!length2 || Math.abs(qx * ry - qy * rx) > eps) return null
            const a = (qx * rx + qy * ry) / length2
            const b = a + (sx * rx + sy * ry) / length2
            if (Math.max(a, b) < 0 || Math.min(a, b) > 1) return null
            t = Math.max(0, Math.min(a, b))
        }
        t = Math.max(0, Math.min(1, t))
        return {x: start.x + t * rx, y: start.y + t * ry, t}
    }
    // Hazards and nonattachable surfaces stop the line without hooking it.
    blocksShot(element)
    {
        return element.grapplable === false || element.surfaceRole === 'hazard'
    }
    // Nearest crossing of start->end with any surface at its current position.
    nearestCrossing(start, end)
    {
        const reach = segmentBounds(start.x, start.y, end[0], end[1], defaultEqualityTolerance)
        let nearest = null
        const groups = screen.leftWall ? [...floors, {elements: [screen.leftWall]}] : floors
        for (const group of groups)
            for (const element of group.elements)
            {
                if (!boundsOverlap(reach, elementBounds(element, grapnelElementBounds))) continue
                for (const line of element.getLines())
                {
                    const hit = this.shotIntersection(start, end, line)
                    if (!hit) continue
                    // Stable geometry order breaks equal-distance ties, with
                    // nonattachable surfaces taking precedence at a shared edge.
                    if (!nearest || hit.t < nearest.hit.t ||
                        (hit.t === nearest.hit.t && this.blocksShot(element)))
                        nearest = {hit, element}
                }
            }
        return nearest
    }
    attachAt(hit, element)
    {
        // Keep the actual surface contact; corner snapping could move
        // an otherwise valid contact outside the acquisition radius.
        this.pos = [[hit.x, hit.y, element]]
        this.grappled = true
        this.clip = null
    }
    acquireShot()
    {
        if (!this.throwed) return
        const step = this.shotStep, tip = this.pos[0]
        const radius = grappleOverAcquisitionRadius()
        this.shotStep = null
        this.clip = null
        if (!step && !this.isParked()) return
        // The whole held line, from the ninja to the tip before this step
        // (or the parked tip), limited to the acquisition radius.
        const ninjaPoint = {x: ninja.x, y: ninja.y}
        const lineEnd = step ? [step.x, step.y] : tip
        const reach = Math.hypot(lineEnd[0] - ninja.x, lineEnd[1] - ninja.y)
        const end = reach > radius ? [ninja.x + (lineEnd[0] - ninja.x) * radius / reach,
                                      ninja.y + (lineEnd[1] - ninja.y) * radius / reach] : lineEnd
        const held = reach > 0 ? this.nearestCrossing(ninjaPoint, end) : null
        if (held && !this.blocksShot(held.element))
        {
            this.attachAt(held.hit, held.element)
            return
        }
        if (held) this.clip = {x: held.hit.x, y: held.hit.y}
        if (step && !held)
        {
            // The tip's own swept step, beyond the already deployed line.
            const nearest = this.nearestCrossing(step, tip)
            if (nearest && this.blocksShot(nearest.element))
                this.clip = {x: nearest.hit.x, y: nearest.hit.y}
            else if (nearest && Math.hypot(nearest.hit.x - ninja.x, nearest.hit.y - ninja.y) <= radius + 1e-9)
            {
                this.traveled -= step.length * (1 - nearest.hit.t)
                this.attachAt(nearest.hit, nearest.element)
                return
            }
        }
        if (this.traveled >= radius && this.isParked())
        {
            tip[0] = ninja.x + this.aim.x * radius
            tip[1] = ninja.y + this.aim.y * radius
        }
        else if (this.traveled >= radius || (step && step.length === 0))
            this.endShot()
    }
    collision()
    {
        if (version === 'grapple_over' && !this.grappled)
        {
            this.acquireShot()
            return
        }
        for (let q = 1; q <= this.pos.length; ++q)
        {
            let grapnelLine
            if (q == this.pos.length)
                grapnelLine = lineFormula(ninja.x, ninja.y, this.pos[this.pos.length - 1][0], this.pos[this.pos.length - 1][1])
            else
                grapnelLine = lineFormula(this.pos[q - 1][0], this.pos[q - 1][1], this.pos[q][0], this.pos[q][1])
            
            // A hit lies on both segments, so inside both boxes.
            const reach = segmentBounds(grapnelLine.x1, grapnelLine.y1, grapnelLine.x2, grapnelLine.y2,
                                        defaultEqualityTolerance)
            const collisionGroups = screen.leftWall ? [...floors, {elements: [screen.leftWall]}] : floors
            // Initial acquisition (and its range/occlusion checks) returns above.
            // Attached segments only add wrapping contacts, even beyond range.
            if (version === 'grapple_over')
            {
                // Process one contact at a time from the anchor toward the player.
                // Inserting a corner changes the segment: recheck that new geometry
                // instead of inserting more hits from the obsolete straight rope.
                let nearest = null
                const origin = this.pos[q - 1]
                for (const group of collisionGroups)
                    for (const element of group.elements)
                    {
                        if (element.grapplable === false ||
                            !boundsOverlap(reach, elementBounds(element, grapnelElementBounds))) continue
                        for (const line of element.getLines())
                        {
                            const hit = linesCollision(grapnelLine, line)
                            if (!hit) continue
                            const corner = this.correctToCornerOfElement(hit.x, hit.y, element.getPoints(),
                                screenHeightPercent(GAMEPLAY.cornerToleranceHeightPercent))
                            if (this.pos.some(p => p[2] === element &&
                                Math.hypot(p[0] - corner.x, p[1] - corner.y) < 1e-7)) continue
                            const distance = Math.hypot(hit.x - origin[0], hit.y - origin[1])
                            if (!nearest || distance < nearest.distance)
                                nearest = {corner, element, distance}
                        }
                    }
                if (nearest)
                {
                    const previous = this.pos.slice()
                    this.grapple(nearest.corner, nearest.element, q)
                    if (this.pos.length !== previous.length || this.pos.some((p, i) => p !== previous[i]))
                        q = 0
                }
                continue
            }
            for (let k = 0; k < collisionGroups.length; ++k)
            {
                for (let i = 0; i < collisionGroups[k].elements.length; ++i)
                {
                    if (!boundsOverlap(reach, elementBounds(collisionGroups[k].elements[i], grapnelElementBounds)))
                        continue
                    if (circlesIntersect(grapnelLine.circle, collisionGroups[k].elements[i].getCircumscribedCircle()))
                    {
                        let lines = collisionGroups[k].elements[i].getLines()
                        for (let j = 0; j < lines.length; ++j)
                        {
                            this.grapple(linesCollision(grapnelLine, lines[j]), collisionGroups[k].elements[i], q)
                        }
                    }
                }
            }
        }
    }
    correctToCornerOfElement(x, y, points, eps)
    {
        if (version === 'grapple_over')
        {
            // Elements expose vertices as {x, y}, not a flat coordinate array.
            for (const point of points)
                if (isPointsEqually([x, y], [point.x, point.y], eps))
                    return {x: point.x, y: point.y}
            return {x, y}
        }
        for (let i = 0; i < points.length; i += 2)
        {
            if (isPointsEqually([x, y], [points[i], points[i + 1]], eps))
                return {x: points[i], y: points[i + 1]}
        }
        return {x: x, y: y}
    }
    pointsIsOnOneLine(point1, point2, point3)
    {
        let line = lineFormula(point1[0], point1[1], point2[0], point2[1])
        return pointIsOnStraight({x: point3[0], y: point3[1]}, line)
    }
    grapple(coords, element, index)
    {
        if (coords && element.grapplable !== false)
        {
            const correctCornerEps = screenHeightPercent(GAMEPLAY.cornerToleranceHeightPercent)
            const firstPointEps = screenHeightPercent(GAMEPLAY.firstPointToleranceHeightPercent)
            coords = this.correctToCornerOfElement(coords.x, coords.y, element.getPoints(), correctCornerEps)
            
            // A snapped corner may be reported by both adjoining edges. Do not
            // grow the rope with duplicate contacts while iterating its segments.
            if (version === 'grapple_over' && this.pos.some(point =>
                point[2] === element && Math.hypot(point[0] - coords.x, point[1] - coords.y) < 1e-7))
                return
            this.grappled = true
            if  (
                    index == 1                                                          && 
                    this.pos[0][2].isEmpty()                                            && 
                    isPointsEqually(this.pos[0], [coords.x, coords.y], firstPointEps)
                )
            {
                this.pos[0] = [coords.x, coords.y, element]
            }
            else if (this.pos.length == index)
            {
                if      (
                            index - 2 >= 0                  &&
                            this.pointsIsOnOneLine
                                (
                                    this.pos[index - 2], 
                                    this.pos[index - 1],
                                    [coords.x, coords.y]
                                )
                        )
                    this.pos.pop()
                    
                this.pos.push([coords.x, coords.y, element])
            }
            else 
            { 
                if      (
                            this.pointsIsOnOneLine
                                (
                                    this.pos[index - 1] , 
                                    this.pos[index]     ,
                                    [coords.x, coords.y]
                                )
                        )
                    return

                this.pos.splice(index, 0, [coords.x, coords.y, element])
            }
        }
    }
    isGrappled()
    {
        return this.grappled
    }
    setGrappled(boolean)
    {
        this.grappled = boolean
    }
    getWidth()
    {
        // Bad mode draws the world scaled down: keep the rope readable on screen.
        return Math.max(Math.round(screenHeightPercent(STYLE.strokes.grapnelWidthHeightPercent)),
                        STYLE.grapnelVisuals.minScreenWidth / scale[version])
    }
    // The visible end of the line: a blocking surface clips it.
    visibleTip()
    {
        return this.clip ? [this.clip.x, this.clip.y] : this.pos[0]
    }
    tracePath()
    {
        ctx.beginPath()
        const tip = this.visibleTip()
        ctx.moveTo(tip[0] + screen.x, tip[1] + screen.y)
        for (let i = 1; i < this.pos.length; ++i)
        {
            ctx.lineTo(this.pos[i][0] + screen.x, this.pos[i][1] + screen.y)
        }
        ctx.lineTo(ninja.x + screen.x, ninja.y + screen.y)
    }
    // Flat rope and anchor outline with no exterior halo.
    strokeRope(width, color = STYLE.colors.grapnel.rope)
    {
        ctx.strokeStyle = color
        ctx.globalAlpha = STYLE.alpha.full
        ctx.lineWidth = width
        ctx.stroke()
    }
    // Twist phase: one turn per second of game time, frozen for reduced motion.
    helixPhase()
    {
        if (grapnelReducedMotionQuery && grapnelReducedMotionQuery.matches)
            return 0
        return 2 * Math.PI * STYLE.grapnelHelix.turnsPerSecond * performance.now() / 1000
    }
    // Both strands and the crossing nodes along the visible rope polyline (tip ->
    // wrap points -> ninja), in canvas units before the camera scale. The phase is
    // measured by arc length from the tip, so it runs on across wrap points, where
    // the offset turns about the corner from one segment's normal to the next.
    helixStrands(phase = this.helixPhase())
    {
        const look = STYLE.grapnelHelix
        const unit = 1 / scale[version]
        const tip = this.visibleTip()
        const points = [[tip[0], tip[1]]]
        for (let i = 1; i < this.pos.length; ++i)
            points.push([this.pos[i][0], this.pos[i][1]])
        points.push([ninja.x, ninja.y])

        let total = 0
        for (let i = 1; i < points.length; ++i)
            total += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        const amplitude = look.amplitude * unit, waveRadius = look.waveRadius * unit
        const damping = look.endDamping * unit, step = look.sampleStep * unit
        const offsetAt = distance => amplitude * Math.sin(distance / waveRadius + phase) *
            Math.max(0, Math.min(1, distance / damping, (total - distance) / damping))

        const strands = [[], []], nodes = []
        const push = (x, y, nx, ny, offset) =>
        {
            strands[0].push([x + nx * offset, y + ny * offset])
            strands[1].push([x - nx * offset, y - ny * offset])
        }
        // First crossing (sin = 0) at or after the tip
        let crossing = (Math.ceil(phase / Math.PI) * Math.PI - phase) * waveRadius
        let start = 0, normal = null
        for (let i = 1; i < points.length; ++i)
        {
            const [x0, y0] = points[i - 1], [x1, y1] = points[i]
            const length = Math.hypot(x1 - x0, y1 - y0)
            if (length === 0)
                continue
            const ux = (x1 - x0) / length, uy = (y1 - y0) / length
            if (normal)
            {
                // Turn the offset about the wrap point by the shorter way
                const offset = offsetAt(start)
                const from = Math.atan2(normal[1], normal[0])
                let turn = Math.atan2(ux, -uy) - from
                turn -= 2 * Math.PI * Math.round(turn / (2 * Math.PI))
                const count = Math.ceil(Math.abs(turn) / (Math.PI / 32))
                for (let k = 1; k < count; ++k)
                {
                    const angle = from + turn * k / count
                    push(x0, y0, Math.cos(angle), Math.sin(angle), offset)
                }
            }
            normal = [-uy, ux]
            const samples = Math.max(1, Math.ceil(length / step))
            for (let k = 0; k <= samples; ++k)
            {
                const along = length * k / samples
                push(x0 + ux * along, y0 + uy * along, normal[0], normal[1], offsetAt(start + along))
            }
            for (; crossing <= start + length; crossing += Math.PI * waveRadius)
                if (crossing > damping * 2 / 3 && crossing < total - damping * 2 / 3)
                    nodes.push([x0 + ux * (crossing - start), y0 + uy * (crossing - start)])
            start += length
        }
        return {strands, nodes, total}
    }
    // Grapple Over rope: glow under both strands, the strands, then crossing nodes.
    drawHelix()
    {
        const look = STYLE.grapnelHelix
        const unit = 1 / scale[version]
        const {strands, nodes} = this.helixStrands()
        // The strands end under the player: keep their glow off the player's ring.
        let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
        for (const strand of strands)
            for (const [x, y] of strand)
            {
                left = Math.min(left, x); right = Math.max(right, x)
                top = Math.min(top, y); bottom = Math.max(bottom, y)
            }
        const margin = (look.glowWidth + look.nodeRadius) * unit
        ctx.beginPath()
        ctx.rect(left - margin + screen.x, top - margin + screen.y,
                 right - left + 2 * margin, bottom - top + 2 * margin)
        ctx.arc(ninja.x + screen.x, ninja.y + screen.y,
                ninja.getRingOuterRadius() + look.playerClearance * unit, 0, 2 * Math.PI)
        ctx.clip('evenodd')
        const trace = strand =>
        {
            ctx.beginPath()
            ctx.moveTo(strand[0][0] + screen.x, strand[0][1] + screen.y)
            for (let i = 1; i < strand.length; ++i)
                ctx.lineTo(strand[i][0] + screen.x, strand[i][1] + screen.y)
        }
        ctx.globalAlpha = STYLE.alpha.full
        ctx.strokeStyle = look.glowColor
        ctx.lineWidth = look.glowWidth * unit
        for (const strand of strands)
        {
            trace(strand)
            ctx.stroke()
        }
        // Lavender under white, as in the approved mock
        for (let i = strands.length - 1; i >= 0; --i)
        {
            trace(strands[i])
            ctx.strokeStyle = look.strandColors[i]
            ctx.lineWidth = look.strandWidths[i] * unit
            ctx.stroke()
        }
        const radius = look.nodeRadius * unit
        for (const [x, y] of nodes)
        {
            const cx = x + screen.x, cy = y + screen.y
            const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
            glow.addColorStop(0, look.nodeCore)
            glow.addColorStop(0.45, look.nodeMid)
            glow.addColorStop(1, look.nodeEdge)
            ctx.fillStyle = glow
            ctx.beginPath()
            ctx.arc(cx, cy, radius, 0, 2 * Math.PI)
            ctx.fill()
        }
    }
    draw()
    {
        if (this.throwed)
        {
            ctx.save()
            ctx.lineCap = 'round'
            ctx.lineJoin = 'round'

            if (version === 'grapple_over')
                this.drawHelix()
            else
            {
                this.tracePath()
                this.strokeRope(this.getWidth())
            }
            ctx.restore()
        }
    }
    // Drawn after the floors so the anchor ring sits on top of the element it hooks;
    // a bright tip while the grapnel is still flying.
    drawHook()
    {
        if (!this.throwed)
            return

        const look = STYLE.grapnelVisuals
        const colors = STYLE.colors.grapnel
        const width = this.getWidth()

        ctx.save()
        const tip = this.visibleTip()
        const hookX = tip[0] + screen.x
        const hookY = tip[1] + screen.y
        ctx.beginPath()
        if (this.grappled)
        {
            ctx.arc(hookX, hookY, width * look.anchorRadiusRatio, 0, 2 * Math.PI)
            ctx.fillStyle = colors.anchorFill
            ctx.fill()
            this.strokeRope(width * look.anchorWidthRatio,
                version === 'grapple_over' ? STYLE.grapnelHelix.hookStroke : colors.rope)
        }
        else
        {
            ctx.arc(hookX, hookY, width * look.tipCoreRadiusRatio, 0, 2 * Math.PI)
            ctx.fillStyle = version === 'grapple_over' ? STYLE.grapnelHelix.tipCore : colors.core
            ctx.globalAlpha = STYLE.alpha.full
            ctx.fill()
        }

        ctx.restore()
    }
}
