function collisionCircleWithLine(x1, y1, x2, y2, x0, y0, r)
{
    if (x1 == x2)
    {
        if (y1 > y2)
        {
            let t = y2
            y2 = y1
            y1 = t
        }
        return collisionCalculation(r, x1, x0, y0, y1, y2)
    }
    let k = (y1 - y2) / (x1 - x2)
    let b = y1 - k * x1
    /*
    ax^2 + bx + c = 0
    */
    let a = k * k + 1
    let c = x0 * x0 + b * b - 2 * y0 * b + y0 * y0 - r * r
    b = 2 * k * b - 2 * x0 - 2 * y0 * k
    let D = b * b - 4 * a * c
    if (D >= 0)
    {
        D = Math.sqrt(D)
        let root1 = (-b - D) / (2 * a)
        let root2 = (-b + D) / (2 * a)
        // x2 > x1
        if (root1 < x2 && x1 < root1 || 
            root2 < x2 && x1 < root2 ||
            root1 < x1 && x2 < root1 ||
            root2 < x1 && x2 < root2)
            return true
    }
    return false
}
    
function collisionCalculation(r, coord, coord0, coordUnknow0, lineBegin, lineEnd)
{
    let c = Math.pow(r, 2) - Math.pow((coord - coord0), 2) - Math.pow(coordUnknow0, 2)
    let D = Math.pow(2 * coordUnknow0, 2) + 4 * c
    if (D >= 0)
    {
        D = Math.sqrt(D)
        let root1 = (2 * coordUnknow0 - D) / 2
        let root2 = (2 * coordUnknow0 + D) / 2
        {
            if (lineBegin <= root1 && root1 <= lineEnd
               || lineBegin <= root2 && root2 <= lineEnd)
                return true
        }
    }
    return false
}