function circlesDoNotIntersect(x1, y1, x2, y2, r1, r2)
{
    return  Math.pow(x1 - x2, 2) +
            Math.pow(y1 - y2, 2) > Math.pow(r1 + r2, 2)
}
function twoCirclesIntersect(x, y, r, circle)
{
    return  Math.pow(x - circle.x, 2) +
            Math.pow(y - circle.y, 2) <= Math.pow(r + circle.radius, 2)
}
function circlesIntersect(circle1, circle2)
{
    return  Math.pow(circle2.x - circle1.x, 2) +
            Math.pow(circle2.y - circle1.y, 2) <= Math.pow(circle2.radius + circle1.radius, 2)
}
function circlesCircumscribedAroundTwoVerticalsIntersect(y1, y2, r1, r2)
{
    return  Math.abs(y1 - y2) <= (r1 + r2)
}