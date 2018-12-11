function pointOnLine(x, x1, x2)
{
    return ((x < x1 && x2 < x) || (x < x2 && x1 < x))
}
function collisionVerticalWithLine(vertical, line)
{
    let y = line.k  * vertical.x + line.b
    if (pointOnLine(y, vertical.y1, vertical.y2) && pointOnLine(vertical.x, line.x1, line.x2))
        return {x: vertical.x, y: y}
    return false
}
function collisionVerticalWithVertical(vertical1, vertical2)
{
    if (vertical1.x == vertical2.x)
    {
        if (pointOnLine(vertical1.y1, vertical2.y1, vertical2.y2))
            return {x: vertical1.x, y: vertical1.y}
        if (pointOnLine(vertical1.y2, vertical2.y1, vertical2.y2))
            return {x: vertical1.x, y: vertical1.y2}
        if (pointOnLine(vertical2.y1, vertical1.y1, vertical1.y2))
            return {x: vertical1.x, y: vertical2.y1}
        if (pointOnLine(vertical2.y2, vertical1.y1, vertical1.y2))
            return {x: vertical1.x, y: vertical2.y2}
    }
    return false
}
function collisionLineWithLine(line1, line2)
{
    
    if (line1.k != line2.k)
    {
        let x = (line2.b - line1.b) / (line1.k - line2.k)
        let y = line1.k * x + line1.b
        if (pointOnLine(x, line1.x1, line1.x2) && pointOnLine(x, line2.x1, line2.x2))
        {
            //&& pointOnLine(y, line1.y1, line2.y2) && pointOnLine(x, line2.y1, line2.y2))
            return {x: x, y: y}
        }
    }
    return false
}
function lineFormula(x1, y1, x2, y2)
{
    if (x1 == x2)
    {
        return {type: 'vertical', x: x1, y1: y1, y2: y2}
    }
    else
    {
        let k = ((y1 - y2) / (x1 - x2))
        return {type: 'line', x1: x1, x2: x2, y1: y1, y2: y2, k: k, b: (y1 - k * x1)}
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
    else
        return collisionVerticalWithVertical(line1, line2)
}
