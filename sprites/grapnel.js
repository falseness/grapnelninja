const grapnelSpeed = 0.018891687657430732 * height * 2
const grappleSpeed = 0.00025188916876574307 * height

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
            
            for (let i = 0; i < this.pos.length; ++i)
            {
                this.pos[i][1] += this.pos[i][2].speedY
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
            
            for (let k = 0; k < floors.length; ++k)
            {
                for (let i = 0; i < floors[k].elements.length; ++i)
                {
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
        if (coords.x && coords.y)
        {
            const correctCornerEps = 6
            const firstPointEps = 50
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
    draw()
    {
        if (this.throwed)
        {
            ctx.beginPath()
            
            ctx.moveTo(this.pos[0][0] + screen.x, this.pos[0][1] + screen.y)
            
            for (let i = 1; i < this.pos.length; ++i)
            {
                ctx.lineTo(this.pos[i][0] + screen.x, this.pos[i][1] + screen.y)
            }
            ctx.lineTo(ninja.x + screen.x, ninja.y + screen.y)
            ctx.strokeStyle = this.stroke
            
            const strokeWidth = Math.round(0.006 * height)
            ctx.lineWidth = strokeWidth
            ctx.stroke()
            ctx.lineWidth = 1
            
            ctx.closePath()
        }
    }     
}