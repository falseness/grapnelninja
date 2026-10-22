// Short transfer direction arrows (TASK-659), from the imported level's
// optional svgFormat.transfers[].guide cubic (world units, docs/level-svg-format.md).
// The same shape as the SVG annotation arrows (tools/convert_extended_mountain_svg.py
// draw_arrow): the guide restricted to t = 0..ROUTE_ARROWS.t, and a triangular head
// along dB/dt at that t. Stroke and head sizes are screen (CSS) pixels, so they
// shrink in world units as the camera zooms in. Purely visual: no physics object,
// input or save field. A level without guides draws nothing.
const ROUTE_ARROWS =
{
    t: 0.25,
    color: '#8bdde8',
    opacity: 0.4,
    strokePx: 1.5,
    headPx: 6,
    // level -> [{id, curve, tangent, box}]; the guides never change after loading
    cache: new WeakMap(),
    // Transfer ids drawn in the last frame (after culling)
    drawn: []
}

function routeArrowLerp(a, b, t)
{
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

// One arrow per guided transfer: the de Casteljau sub-cubic for [0, t], the
// unit tangent at its end and the box of its control points (the curve stays
// inside their hull)
function routeArrowsFor(level)
{
    let arrows = ROUTE_ARROWS.cache.get(level)
    if (arrows)
        return arrows
    const t = ROUTE_ARROWS.t
    arrows = []
    for (const transfer of level.svgFormat?.transfers ?? [])
    {
        const p = transfer.guide
        if (!p)
            continue
        const a = routeArrowLerp(p[0], p[1], t), b = routeArrowLerp(p[1], p[2], t), c = routeArrowLerp(p[2], p[3], t)
        const ab = routeArrowLerp(a, b, t), bc = routeArrowLerp(b, c, t)
        const curve = [p[0], a, ab, routeArrowLerp(ab, bc, t)]
        const u = 1 - t
        const dx = 3 * u * u * (p[1][0] - p[0][0]) + 6 * u * t * (p[2][0] - p[1][0]) + 3 * t * t * (p[3][0] - p[2][0])
        const dy = 3 * u * u * (p[1][1] - p[0][1]) + 6 * u * t * (p[2][1] - p[1][1]) + 3 * t * t * (p[3][1] - p[2][1])
        const n = Math.hypot(dx, dy) || 1
        const box = {left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity}
        for (const [x, y] of curve)
            addPointToBox(box, {x, y})
        arrows.push({id: transfer.id, curve, tangent: [dx / n, dy / n], box})
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
