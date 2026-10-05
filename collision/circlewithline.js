// Touching within float roundoff still counts (well below a 1e-6 gap).
const circleSegmentTolerance = 1e-9
// Squared distance from (x0, y0) to the closest point of the segment line.
function segmentDistanceSquared(line, x0, y0)
{
    const dx = line.x2 - line.x1
    const dy = line.y2 - line.y1
    const length2 = dx * dx + dy * dy
    let t = length2 > 0 ? ((x0 - line.x1) * dx + (y0 - line.y1) * dy) / length2 : 0
    if (t < 0)
        t = 0
    else if (t > 1)
        t = 1
    const ex = line.x1 + t * dx - x0
    const ey = line.y1 + t * dy - y0
    return ex * ex + ey * ey
}
function collisionCircleWithLine(line, x0, y0, r)
{
    if (twoCirclesIntersect(x0, y0, r, line.circle))
    {
        if (line.type == 'vertical')
            return collisionCircleWithVertical(x0, y0, r, line)
        return segmentDistanceSquared(line, x0, y0) <= r * r + circleSegmentTolerance
    }
    return false
}
    
function collisionCircleWithVertical(coord0, coordUnknow0, r, vertical)
{
    return segmentDistanceSquared(vertical, coord0, coordUnknow0) <= r * r + circleSegmentTolerance
}
// Even-odd test: is (x, y) strictly inside the polygon points?
function pointInPolygon(points, x, y)
{
    let inside = false
    for (let i = 0, j = points.length - 1; i < points.length; j = i++)
    {
        const a = points[i]
        const b = points[j]
        if ((a.y > y) != (b.y > y) &&
            x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x)
            inside = !inside
    }
    return inside
}
// Edge of lines closest to (x0, y0).
function nearestLine(lines, x0, y0)
{
    let best = null
    let bestDistance = Infinity
    for (let i = 0; i < lines.length; ++i)
    {
        const distance = segmentDistanceSquared(lines[i], x0, y0)
        if (distance < bestDistance)
        {
            bestDistance = distance
            best = lines[i]
        }
    }
    return best
}