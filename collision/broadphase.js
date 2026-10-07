// Broad phase: axis-aligned bounds checked before the exact line/circle tests.
// Boxes are padded by the tolerances of the exact tests, so a pair is only
// rejected when the exact test could not accept it either.
function pointsBounds(points, pad)
{
    pad = pad || 0
    let left = points[0].x, right = left, top = points[0].y, bottom = top
    for (let i = 1; i < points.length; ++i)
    {
        const x = points[i].x, y = points[i].y
        if (x < left)   left = x
        if (x > right)  right = x
        if (y < top)    top = y
        if (y > bottom) bottom = y
    }
    return {left: left - pad, right: right + pad, top: top - pad, bottom: bottom + pad}
}
// Grows the box to hold (x, y); the same comparisons pointsBounds makes.
function addBoundsPoint(out, x, y)
{
    if (x < out.left)   out.left = x
    if (x > out.right)  out.right = x
    if (y < out.top)    out.top = y
    if (y > out.bottom) out.bottom = y
}
function startBounds(out, x, y)
{
    out.left = x
    out.right = x
    out.top = y
    out.bottom = y
    return out
}
// pointsBounds(element.getPoints()) written into out, without the point
// arrays: elements override writeBounds with their own corner formulas.
function elementBounds(element, out)
{
    return element.writeBounds(out)
}
function segmentBounds(x1, y1, x2, y2, pad)
{
    pad = pad || 0
    return {
        left: Math.min(x1, x2) - pad, right: Math.max(x1, x2) + pad,
        top: Math.min(y1, y2) - pad, bottom: Math.max(y1, y2) + pad
    }
}
function circleBounds(x, y, r, pad)
{
    const reach = r + (pad || 0)
    return {left: x - reach, right: x + reach, top: y - reach, bottom: y + reach}
}
// Touching boxes overlap.
function boundsOverlap(a, b)
{
    return a.left <= b.right && b.left <= a.right && a.top <= b.bottom && b.top <= a.bottom
}
