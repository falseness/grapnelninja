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
        
        this.stroke = object.stroke
    }
    move()
    {
        if (this.throwed)
        {
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
        
        let sin = dy / distance
        let cos = dx / distance

        return {sin: sin, cos: cos}
        
    }
    collision()
    { 
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
            for (let k = 0; k < floors.length; ++k)
            {
                for (let i = 0; i < floors[k].elements.length; ++i)
                {
                    if (!boundsOverlap(reach, elementBounds(floors[k].elements[i], grapnelElementBounds)))
                        continue
                    if (circlesIntersect(grapnelLine.circle, floors[k].elements[i].getCircumscribedCircle()))
                    {
                        let lines = floors[k].elements[i].getLines()
                        for (let j = 0; j < lines.length; ++j)
                        {
                            this.grapple(linesCollision(grapnelLine, lines[j]), floors[k].elements[i], q)
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
        if (coords)
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
    // Glow without shadowBlur: a wide faint stroke, the cyan rope and a pale core.
    strokeGlow(width)
    {
        const look = STYLE.grapnelVisuals
        const colors = STYLE.colors.grapnel

        ctx.strokeStyle = colors.halo
        ctx.globalAlpha = look.haloAlpha
        ctx.lineWidth = width * look.haloWidthRatio
        ctx.stroke()

        ctx.strokeStyle = colors.rope
        ctx.globalAlpha = STYLE.alpha.full
        ctx.lineWidth = width
        ctx.stroke()

        ctx.strokeStyle = colors.core
        ctx.lineWidth = width * look.coreWidthRatio
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
            this.strokeGlow(this.getWidth())
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
            this.strokeGlow(width * look.anchorWidthRatio)
        }
        else
        {
            ctx.arc(hookX, hookY, width * look.tipRadiusRatio, 0, 2 * Math.PI)
            ctx.fillStyle = colors.halo
            ctx.globalAlpha = look.haloAlpha
            ctx.fill()
            ctx.beginPath()
            ctx.arc(hookX, hookY, width * look.tipCoreRadiusRatio, 0, 2 * Math.PI)
            ctx.fillStyle = colors.core
            ctx.globalAlpha = STYLE.alpha.full
            ctx.fill()
        }

        ctx.restore()
    }
}
