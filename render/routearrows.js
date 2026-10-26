// Transfer direction arrows (TASK-659, distance-based since TASK-671), from the
// imported level's optional svgFormat.transfers[].guide cubic (world units,
// docs/level-svg-format.md). The guide is restricted to t = 0..t*, where its
// arc length reaches min(gapFraction * G, L) (G: minimum edge-to-edge gap
// between the transfer's complete fragment polygons, L: the guide's arc
// length), as the SVG annotation arrows (tools/convert_extended_mountain_svg.py
// draw_arrow). Since TASK-712 that sub-curve is drawn as a static run of open
// chevrons: one every chevronGapPx of arc length, the last exactly at t* along
// dB/dt there, the others along the local tangent; size, stroke width and alpha
// grow from the first chevron to the last. Every size is in screen (CSS)
// pixels, so it shrinks in world units as the camera zooms in. No time
// dependence. Purely visual: no physics object, input or save field. A level
// without guides draws nothing.
const ROUTE_ARROWS =
{
    gapFraction: 0.5,
    arcSamples: 1024,
    color: '#8bdde8',
    // Screen px of arc length between chevrons; the last one sits at the tip
    chevronGapPx: 16,
    // First -> last chevron, linear in the run fraction (0 at the first, 1 at the tip)
    halfSizePx: [4, 7],
    strokePx: [1.6, 2.6],
    alpha: [0.25, 0.95],
    glowPx: 6,
    // level -> [{id, gap, length, target, t, curve, tangent, box, arc, chevrons}]; the guides never
    // change after loading. chevrons is {px, list} for the last world-per-screen-pixel factor.
    cache: new WeakMap(),
    // Levels whose arrows were computed (a cache hit does not count)
    builds: 0,
    // Chevron layouts computed (once per arrow and camera zoom)
    layouts: 0,
    // Transfer ids drawn in the last frame (after culling), and their chevron counts
    drawn: [],
    drawnChevrons: []
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

// Cumulative chord lengths of p at arcSamples + 1 even parameters
function routeArrowTable(p)
{
    const n = ROUTE_ARROWS.arcSamples, table = [0]
    let prev = p[0]
    for (let i = 1; i <= n; i++)
    {
        const q = routeArrowPoint(p, i / n)
        table.push(table[i - 1] + Math.hypot(q[0] - prev[0], q[1] - prev[1]))
        prev = q
    }
    return table
}

// Parameter where the table's arc length reaches target (0 < target < length)
function routeArrowInvert(table, target)
{
    const n = table.length - 1
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
    return (lo + (span > 0 ? (target - table[lo]) / span : 0)) / n
}

// Parameter where the arc length of p reaches s, from a table of chord lengths
function routeArrowParameter(p, s)
{
    const table = routeArrowTable(p)
    const length = table[table.length - 1]
    const target = Math.min(s, length)
    if (target <= 0 || length <= 0)
        return {length, target: Math.max(target, 0), t: 0}
    if (target >= length)
        return {length, target, t: 1}
    return {length, target, t: routeArrowInvert(table, target)}
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
// sub-cubic for [0, t*], the unit tangent at t*, the box of the sub-curve's
// control points (the curve stays inside their hull) and the sub-curve's
// chord table for placing chevrons
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
        arrows.push({id: transfer.id, gap, length, target, t, curve, tangent: routeArrowTangent(p, t), box,
            arc: routeArrowTable(curve), chevrons: null})
    }
    ROUTE_ARROWS.cache.set(level, arrows)
    return arrows
}

// Chevrons of an arrow for px world units per screen pixel: spaced chevronGapPx
// back from the tip, which keeps the tip tangent. Kept with the arrow until the
// zoom changes.
function routeArrowChevrons(arrow, px)
{
    if (arrow.chevrons && arrow.chevrons.px === px)
        return arrow.chevrons.list
    ROUTE_ARROWS.layouts++
    const R = ROUTE_ARROWS, gap = R.chevronGapPx * px, arc = arrow.arc[arrow.arc.length - 1]
    const count = Math.floor(arrow.target / gap + 1e-6) + 1
    const lerp = ([a, b], f) => a + (b - a) * f
    const list = []
    for (let i = 0; i < count; i++)
    {
        const last = i === count - 1, f = count > 1 ? i / (count - 1) : 1
        // Arc position measured on the sub-curve, whose own length matches target
        const s = arc - (count - 1 - i) * gap
        const t = last ? 1 : s <= 0 ? 0 : routeArrowInvert(arrow.arc, s)
        const [x, y] = last ? arrow.curve[3] : routeArrowPoint(arrow.curve, t)
        const [ux, uy] = last ? arrow.tangent : routeArrowTangent(arrow.curve, t)
        list.push({x, y, ux, uy, half: lerp(R.halfSizePx, f) * px, width: lerp(R.strokePx, f) * px, alpha: lerp(R.alpha, f)})
    }
    arrow.chevrons = {px, list}
    return list
}

// World layer, under the grapnel, the player and the terrain
function drawRouteArrows(world)
{
    ROUTE_ARROWS.drawn = []
    ROUTE_ARROWS.drawnChevrons = []
    if (version !== 'grapple_over' || !world || !world.level)
        return
    const arrows = routeArrowsFor(world.level)
    if (!arrows.length)
        return

    // World units per screen pixel, as drawAcquisitionCircle
    const css = getCanvasCssRect().width
    const px = width / css / scale[version]
    // Culled by the curve's own box padded by the largest chevron and its glow, not by its source panel
    const pad = (ROUTE_ARROWS.halfSizePx[1] * 2 + ROUTE_ARROWS.glowPx) * px
    const rect = getCullRect()
    const view = {left: rect.left - pad, top: rect.top - pad, right: rect.right + pad, bottom: rect.bottom + pad}
    const sx = screen.x, sy = screen.y

    ctx.save()
    ctx.globalCompositeOperation = 'source-over'
    // shadowBlur is in device pixels, unaffected by the transform
    ctx.shadowColor = ROUTE_ARROWS.color
    ctx.shadowBlur = ROUTE_ARROWS.glowPx * canvas.width / css
    ctx.shadowOffsetX = ctx.shadowOffsetY = 0
    ctx.setLineDash([])
    ctx.lineCap = ctx.lineJoin = 'round'
    ctx.strokeStyle = ROUTE_ARROWS.color
    for (const arrow of arrows)
    {
        if (!isBoxInCullRect(arrow.box, view))
            continue
        const chevrons = routeArrowChevrons(arrow, px)
        ROUTE_ARROWS.drawn.push(arrow.id)
        ROUTE_ARROWS.drawnChevrons.push(chevrons.length)
        for (const {x, y, ux, uy, half, width, alpha} of chevrons)
        {
            const bx = x - ux * half + sx, by = y - uy * half + sy
            ctx.globalAlpha = alpha
            ctx.lineWidth = width
            ctx.beginPath()
            ctx.moveTo(bx - uy * half, by + ux * half)
            ctx.lineTo(x + sx, y + sy)
            ctx.lineTo(bx + uy * half, by - ux * half)
            ctx.stroke()
        }
    }
    ctx.restore()
}
