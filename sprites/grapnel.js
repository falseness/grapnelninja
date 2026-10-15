const grapnelSpeed = screenHeightPercent(GAMEPLAY.grapnelThrowHeightPercent) / cyclesPerTick
const grappleSpeed = screenHeightPercent(GAMEPLAY.grapplePullHeightPercent) / Math.pow(cyclesPerTick, 2)

// Scratch box for the broad phase, refilled for every element
const grapnelElementBounds = {left: 0, right: 0, top: 0, bottom: 0}

class Grapnel
{
    constructor(object)
    {
        this.throwed = false
        
        this.grappled = false
        this.pos = []
        this.traveled = 0
        this.shotStep = null
        
        this.stroke = object.stroke
    }
    move()
    {
        if (this.throwed)
        {
            if (version === 'grapple_over' && !this.grappled)
            {
                const tip = this.pos[0]
                const speed = Math.hypot(this.speedX, this.speedY)
                const remaining = Math.max(0, MODE_DEFINITIONS.grapple_over.acquisitionRadius - this.traveled)
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
    endShot()
    {
        this.throwed = this.grappled = false
        this.pos = []
        this.shotStep = null
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
    acquireShot()
    {
        if (!this.throwed || !this.shotStep) return
        const start = this.shotStep, tip = this.pos[0]
        const radius = MODE_DEFINITIONS.grapple_over.acquisitionRadius
        let nearest = null
        const groups = screen.leftWall ? [...floors, {elements: [screen.leftWall]}] : floors
        for (const group of groups)
            for (const element of group.elements)
                for (const line of element.getLines())
                {
                    const hit = this.shotIntersection(start, tip, line)
                    if (!hit) continue
                    // Stable geometry order breaks equal-distance ties, with
                    // nonattachable surfaces taking precedence at a shared edge.
                    if (!nearest || hit.t < nearest.hit.t ||
                        (hit.t === nearest.hit.t && element.grapplable === false))
                        nearest = {hit, element}
                }
        this.shotStep = null
        if (nearest)
        {
            this.traveled -= start.length * (1 - nearest.hit.t)
            if (nearest.element.grapplable === false ||
                Math.hypot(nearest.hit.x - ninja.x, nearest.hit.y - ninja.y) > radius + 1e-9)
                this.endShot()
            else
            {
                // Keep the actual surface contact; corner snapping could move
                // an otherwise valid contact outside the acquisition radius.
                this.pos = [[nearest.hit.x, nearest.hit.y, nearest.element]]
                this.grappled = true
            }
        }
        else if (this.traveled >= radius || start.length === 0)
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
            if (version === 'grapple_over')
            {
                // Resolve the first surface along the shot before considering
                // attachment: a nongrapplable boundary occludes terrain behind it.
                let nearest = null
                for (const group of collisionGroups)
                    for (const element of group.elements)
                        for (const line of element.getLines())
                        {
                            const hit = linesCollision(grapnelLine, line)
                            if (!hit) continue
                            const distance = Math.hypot(hit.x - grapnelLine.x1, hit.y - grapnelLine.y1)
                            if (!nearest || distance < nearest.distance)
                                nearest = {hit, element, distance}
                        }
                if (nearest?.element.grapplable === false)
                {
                    this.throwed = this.grappled = false
                    this.pos = []
                    return
                }
                if (!this.grappled && nearest)
                {
                    this.grapple(nearest.hit, nearest.element, q)
                    return
                }
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
    tracePath()
    {
        ctx.beginPath()
        ctx.moveTo(this.pos[0][0] + screen.x, this.pos[0][1] + screen.y)
        for (let i = 1; i < this.pos.length; ++i)
        {
            ctx.lineTo(this.pos[i][0] + screen.x, this.pos[i][1] + screen.y)
        }
        ctx.lineTo(ninja.x + screen.x, ninja.y + screen.y)
    }
    // Flat rope and anchor outline with no exterior halo.
    strokeRope(width)
    {
        ctx.strokeStyle = STYLE.colors.grapnel.rope
        ctx.globalAlpha = STYLE.alpha.full
        ctx.lineWidth = width
        ctx.stroke()
    }
    draw()
    {
        if (this.throwed)
        {
            ctx.save()
            ctx.lineCap = 'round'
            ctx.lineJoin = 'round'

            this.tracePath()
            this.strokeRope(this.getWidth())
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
        const hookX = this.pos[0][0] + screen.x
        const hookY = this.pos[0][1] + screen.y
        ctx.beginPath()
        if (this.grappled)
        {
            ctx.arc(hookX, hookY, width * look.anchorRadiusRatio, 0, 2 * Math.PI)
            ctx.fillStyle = colors.anchorFill
            ctx.fill()
            this.strokeRope(width * look.anchorWidthRatio)
        }
        else
        {
            ctx.arc(hookX, hookY, width * look.tipCoreRadiusRatio, 0, 2 * Math.PI)
            ctx.fillStyle = colors.core
            ctx.globalAlpha = STYLE.alpha.full
            ctx.fill()
        }

        ctx.restore()
    }
}
