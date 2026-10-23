// Transfer direction arrows (TASK-659, distance-based since TASK-671), from the
// imported level's optional svgFormat.transfers[].guide cubic (world units,
// docs/level-svg-format.md). The same shape as the SVG annotation arrows
// (tools/convert_extended_mountain_svg.py draw_arrow): the guide restricted to
// t = 0..t*, where its arc length reaches min(gapFraction * G, L) (G: minimum
// edge-to-edge gap between the transfer's complete fragment polygons, L: the
// guide's arc length), and a triangular head along dB/dt at t*. Stroke and head
// sizes are screen (CSS) pixels, so they shrink in world units as the camera
// zooms in. Purely visual: no physics object, input or save field. A level
// without guides draws nothing.
const ROUTE_ARROWS =
{
    gapFraction: 0.5,
    arcSamples: 1024,
    color: '#8bdde8',
    opacity: 0.4,
    strokePx: 1.5,
    headPx: 6,
    // level -> [{id, gap, length, target, t, curve, tangent, box}]; the guides never change after loading
    cache: new WeakMap(),
    // Levels whose arrows were computed (a cache hit does not count)
    builds: 0,
    // Transfer ids drawn in the last frame (after culling)
    drawn: []
}

function routeArrowLerp(a, b, t)
{
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

function routeArrowPoint(p, t)
{
    const u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t
    return [a * p[0][0] + b * p[1][0] + c * p[2][0] + d * p[3][0], a * p[0][1] + b * p[1][1] + c * p[2][1] + d * p[3][1]]
}

// The de Casteljau sub-cubic of p for [0, t]
function routeArrowHead(p, t)
{
    const a = routeArrowLerp(p[0], p[1], t), b = routeArrowLerp(p[1], p[2], t), c = routeArrowLerp(p[2], p[3], t)
    const ab = routeArrowLerp(a, b, t), bc = routeArrowLerp(b, c, t)
    return [p[0], a, ab, routeArrowLerp(ab, bc, t)]
}

// Unit dB/dt at t; the chord, then +x, when the derivative vanishes
function routeArrowTangent(p, t)
{
    const u = 1 - t
    const dx = 3 * u * u * (p[1][0] - p[0][0]) + 6 * u * t * (p[2][0] - p[1][0]) + 3 * t * t * (p[3][0] - p[2][0])
    const dy = 3 * u * u * (p[1][1] - p[0][1]) + 6 * u * t * (p[2][1] - p[1][1]) + 3 * t * t * (p[3][1] - p[2][1])
    for (const [x, y] of [[dx, dy], [p[3][0] - p[0][0], p[3][1] - p[0][1]], [1, 0]])
    {
        const n = Math.hypot(x, y)
        if (n > 1e-9)
            return [x / n, y / n]
    }
}

// Parameter where the arc length of p reaches s, from a table of chord lengths
function routeArrowParameter(p, s)
{
    const n = ROUTE_ARROWS.arcSamples, table = [0]
    let prev = p[0]
    for (let i = 1; i <= n; i++)
    {
        const q = routeArrowPoint(p, i / n)
        table.push(table[i - 1] + Math.hypot(q[0] - prev[0], q[1] - prev[1]))
        prev = q
    }
    const length = table[n]
    const target = Math.min(s, length)
    if (target <= 0 || length <= 0)
        return {length, target: Math.max(target, 0), t: 0}
    if (target >= length)
        return {length, target, t: 1}
    let lo = 0, hi = n
    while (hi - lo > 1)
    {
        const mid = (lo + hi) >> 1
        if (table[mid] < target)
            lo = mid
        else
            hi = mid
    }
    const span = table[hi] - table[lo]
    return {length, target, t: (lo + (span > 0 ? (target - table[lo]) / span : 0)) / n}
}

function routeArrowSegmentDistance(p, a, b)
{
    const dx = b[0] - a[0], dy = b[1] - a[1], n = dx * dx + dy * dy
    const t = n === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return Math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t)
}

function routeArrowInside(p, poly)
{
    let inside = false
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++)
    {
        const [x1, y1] = poly[j], [x2, y2] = poly[i]
        if ((y1 > p[1]) !== (y2 > p[1]) && p[0] < x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1))
            inside = !inside
    }
    return inside
}

// G: minimum edge-to-edge distance between two unions of complete filled
// polygons (0 when they touch, cross or one contains the other)
function routeArrowGap(polysA, polysB)
{
    const side = (o, u, v) => (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    let best = Infinity
    for (const a of polysA)
        for (const b of polysB)
        {
            if (routeArrowInside(a[0], b) || routeArrowInside(b[0], a))
                return 0
            for (let i = 0; i < a.length; i++)
            {
                const p = a[i], q = a[(i + 1) % a.length]
                for (let j = 0; j < b.length; j++)
                {
                    const u = b[j], v = b[(j + 1) % b.length]
                    if (side(u, v, p) * side(u, v, q) < 0 && side(p, q, u) * side(p, q, v) < 0)
                        return 0
                    best = Math.min(best, routeArrowSegmentDistance(p, u, v), routeArrowSegmentDistance(q, u, v),
                        routeArrowSegmentDistance(u, p, q), routeArrowSegmentDistance(v, p, q))
                }
            }
        }
    return best
}

// One arrow per guided transfer, computed once per level: its gap, the
// sub-cubic for [0, t*], the unit tangent at t* and the box of the sub-curve's
// control points (the curve stays inside their hull)
function routeArrowsFor(level)
{
    let arrows = ROUTE_ARROWS.cache.get(level)
    if (arrows)
        return arrows
    ROUTE_ARROWS.builds++
    const elements = new Map((level.elements ?? []).map(e => [e.id, e]))
    const fragments = new Map((level.svgFormat?.fragments ?? []).map(f => [f.id, f]))
    const polygons = id => (fragments.get(id)?.elements ?? []).map(eid => elements.get(eid)).filter(e => e)
        .map(e => e.points.map(p => [e.x + p.x, e.y + p.y]))
    arrows = []
    for (const transfer of level.svgFormat?.transfers ?? [])
    {
        const p = transfer.guide
        if (!p)
            continue
        const gap = routeArrowGap(polygons(transfer.from), polygons(transfer.to))
        const {length, target, t} = routeArrowParameter(p, ROUTE_ARROWS.gapFraction * gap)
        const curve = routeArrowHead(p, t)
        const box = {left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity}
        for (const [x, y] of curve)
            addPointToBox(box, {x, y})
        arrows.push({id: transfer.id, gap, length, target, t, curve, tangent: routeArrowTangent(p, t), box})
    }
    ROUTE_ARROWS.cache.set(level, arrows)
    return arrows
}

// World layer, under the grapnel, the player and the terrain
function drawRouteArrows(world)
{
    ROUTE_ARROWS.drawn = []
    if (version !== 'grapple_over' || !world || !world.level)
        return
    const arrows = routeArrowsFor(world.level)
    if (!arrows.length)
        return

    // World units per screen pixel, as drawAcquisitionCircle
    const px = width / getCanvasCssRect().width / scale[version]
    const head = ROUTE_ARROWS.headPx * px
    // Culled by the curve's own box padded by the head, not by its source panel
    const rect = getCullRect()
    const view = {left: rect.left - head, top: rect.top - head, right: rect.right + head, bottom: rect.bottom + head}
    const sx = screen.x, sy = screen.y

    ctx.save()
    ctx.globalAlpha = ROUTE_ARROWS.opacity
    ctx.globalCompositeOperation = 'source-over'
    ctx.shadowBlur = 0
    ctx.shadowOffsetX = ctx.shadowOffsetY = 0
    ctx.setLineDash([])
    ctx.strokeStyle = ctx.fillStyle = ROUTE_ARROWS.color
    ctx.lineWidth = ROUTE_ARROWS.strokePx * px
    for (const arrow of arrows)
    {
        if (!isBoxInCullRect(arrow.box, view))
            continue
        ROUTE_ARROWS.drawn.push(arrow.id)
        const [p0, p1, p2, tip] = arrow.curve
        const [ux, uy] = arrow.tangent
        ctx.beginPath()
        ctx.moveTo(p0[0] + sx, p0[1] + sy)
        ctx.bezierCurveTo(p1[0] + sx, p1[1] + sy, p2[0] + sx, p2[1] + sy, tip[0] + sx, tip[1] + sy)
        ctx.stroke()
        const bx = tip[0] - ux * head, by = tip[1] - uy * head, w = head / 2
        ctx.beginPath()
        ctx.moveTo(tip[0] + sx, tip[1] + sy)
        ctx.lineTo(bx - uy * w + sx, by + ux * w + sy)
        ctx.lineTo(bx + uy * w + sx, by - ux * w + sy)
        ctx.closePath()
        ctx.fill()
    }
    ctx.restore()
}
