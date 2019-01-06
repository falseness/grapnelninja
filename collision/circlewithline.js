function collisionCircleWithLine(line, x0, y0, r)
{
    if (twoCirclesIntersect(x0, y0, r, line.circle))
    {
        if (line.type == 'vertical')
        {
            //y2 < y1
            return collisionCircleWithVertical(x0, y0, r, line)
        }
        let k = (line.y1 - line.y2) / (line.x1 - line.x2)
        let b = line.y1 - k * line.x1
        /*
        ax^2 + bx + c = 0
        */
        let a = Math.pow(k, 2) + 1
        let c = Math.pow(x0, 2) + Math.pow(b, 2) - (y0 * b * 2) + Math.pow(y0, 2) - Math.pow(r, 2)
        b = (k * b - x0 - y0 * k) * 2
        let D = Math.pow(b, 2) - ((a * c) * 4)
        if (D >= 0)
        {
            D = Math.sqrt(D)
            let a2 = a * 2
            let root1 = (-b - D) / (a2)
            let root2 = (-b + D) / (a2)
            // x2 > x1
            if (pointOnLine(root1, line.x1, line.x2) ||
                pointOnLine(root2, line.x1, line.x2))
                return true
        }
    }
    return false
}
    
function collisionCircleWithVertical(coord0, coordUnknow0, r, vertical)
{
    let c = Math.pow(r, 2) - Math.pow((vertical.x1 - coord0), 2) - Math.pow(coordUnknow0, 2)
    coordUnknow02 = coordUnknow0 * 2
    let D = Math.pow(coordUnknow02, 2) + 4 * c
    if (D >= 0)
    {
        D = Math.sqrt(D)
        let root1 = (coordUnknow02 - D) / 2
        let root2 = (coordUnknow02 + D) / 2
        {
            if (pointOnLine(root1, vertical.y1, vertical.y2)
               || pointOnLine(root2, vertical.y1, vertical.y2))
                return true
        }
    }
    return false
}