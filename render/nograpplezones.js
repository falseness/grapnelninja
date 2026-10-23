// Grapple Over purple no-grapple zones (TASK-672/673): translucent purple
// regions drawn first in the world layer, so the route arrows, the rope, every
// surface and the player stay on top and readable. A zone is pass-through: no
// solid bevel, no drag motes, only a flat fill and a thin edge in screen
// pixels. Culled by each zone's own polygon box. Purely visual: no geometry,
// role or physics field is written. A level without zones draws nothing.
const NO_GRAPPLE_ZONES =
{
    // Zone ids drawn in the last frame (after culling)
    drawn: []
}

function drawNoGrappleZones(world)
{
    NO_GRAPPLE_ZONES.drawn.length = 0
    if (version !== 'grapple_over' || !world || !world.noGrappleZones || !world.noGrappleZones.length)
        return
    const colors = STYLE.colors.noGrapple
    const rect = getCullRect()
    const sx = screen.x, sy = screen.y
    ctx.save()
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
    ctx.shadowBlur = 0
    ctx.shadowOffsetX = ctx.shadowOffsetY = 0
    ctx.setLineDash([])
    ctx.lineJoin = 'round'
    ctx.fillStyle = colors.fill
    ctx.strokeStyle = colors.stroke
    // World units per screen pixel, as drawAcquisitionCircle
    ctx.lineWidth = colors.edgePx * width / getCanvasCssRect().width / scale[version]
    for (const zone of world.noGrappleZones)
    {
        if (!isCullBoxVisible(getElementCullBox(zone), rect))
            continue
        NO_GRAPPLE_ZONES.drawn.push(zone.id)
        const points = zone.getPoints()
        ctx.beginPath()
        ctx.moveTo(points[0].x + sx, points[0].y + sy)
        for (let i = 1; i < points.length; ++i)
            ctx.lineTo(points[i].x + sx, points[i].y + sy)
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
    }
    ctx.restore()
}
