
function pointOnLine(x, x1, x2)
{
    return ((x < x1 && x2 < x) || (x < x2 && x1 < x))
}
function collisionVerticalWithLine(vertical, line)
{
    if (circlesIntersect(line.circle, vertical.circle))
    { 
        let y = line.k  * vertical.x1 + line.b
        if (pointOnLine(y, vertical.y1, vertical.y2) && pointOnLine(vertical.x1, line.x1, line.x2))
            return {x: vertical.x1, y: y}
    }
    return false
}
function collisionVerticalWithVertical(vertical1, vertical2)
{   
    if ( 
            vertical1.x1 == vertical2.x1 && 
            circlesCircumscribedAroundTwoVerticalsIntersect
            (
                vertical1.circle.y      , vertical2.circle.y, 
                vertical1.circle.radius , vertical2.circle.radius
            )
       )
    {
        if (pointOnLine(vertical1.y1, vertical2.y1, vertical2.y2))
            return {x: vertical1.x1, y: vertical1.y}
        if (pointOnLine(vertical1.y2, vertical2.y1, vertical2.y2))
            return {x: vertical1.x1, y: vertical1.y2}
        if (pointOnLine(vertical2.y1, vertical1.y1, vertical1.y2))
            return {x: vertical1.x1, y: vertical2.y1}
        if (pointOnLine(vertical2.y2, vertical1.y1, vertical1.y2))
            return {x: vertical1.x1, y: vertical2.y2}
    }
    return false
}
function collisionLineWithLine(line1, line2)
{
    if (circlesIntersect(line1.circle, line2.circle))
    {
        if (line1.k != line2.k)
        {
            let x = (line2.b - line1.b) / (line1.k - line2.k)
            let y = line1.k * x + line1.b
            if (pointOnLine(x, line1.x1, line1.x2) && pointOnLine(x, line2.x1, line2.x2))
            {
                return {x: x, y: y}
            }
        }
    }
    return false
}
function lineFormula(x1, y1, x2, y2)
{
    if (x1 == x2)
    {
        let res     = {type: 'vertical', x1: x1, x2: x1, y1: y1, y2: y2, 
                        circle: {x: x1, y: (y1 + y2) / 2}}
        res.circle.radius  = Math.abs(res.y1 - res.circle.y)
        return res
    }
    else
    {
        let k       = ((y1 - y2) / (x1 - x2))
        let res     = {type: 'line', x1: x1, x2: x2, y1: y1, y2: y2, k: k, b: (y1 - k * x1),
                        circle: {x: (x1 + x2) / 2, y: (y1 + y2) / 2}}
        res.circle.radius  = Math.sqrt(Math.pow(x1 - res.circle.x, 2) + Math.pow(y1 -  res.circle.y, 2))
        return res
    }
}
function linesCollision(line1, line2)
{
    if (line1.type == 'line' && line2.type == 'line')
        return collisionLineWithLine(line1, line2)
    else if (line1.type == 'vertical' && line2.type == 'line')
        return collisionVerticalWithLine(line1, line2)
    else if (line1.type == 'line' && line2.type == 'vertical')
        return collisionVerticalWithLine(line2, line1)
    
    return collisionVerticalWithVertical(line1, line2)
}
function pointIsOnStraight(point, line)
{
    if (line.type == 'vertical')
    {
        return (line.x1 == point.x)
    }
    else if (line.type == 'line')
    {
        const eps = 0.1
        return (isEqually(point.y, line.k * point.x + line.b, eps))
    }
    else
        console.log('Error line type')
}