// Grapple Over purple no-grapple zones (TASK-672/673), 'Ion lattice' look
// (TASK-782): drawn first in the world layer, so the route arrows, the rope,
// every surface and the player stay on top and readable. A zone is
// pass-through: no solid bevel, no drag motes. Inside each zone polygon: a
// faint base fill, a hexagon lattice, a brighter glow band along the inside of
// the edges and a diagonal pulse band in which the lattice is drawn again,
// brighter. Outside it: a bright edge, a fainter second line just outside and
// L brackets at the corners, in screen pixels. The lattice is one seamless hex
// tile canvas, built and warm-drawn at run start (warmGlowSprites), never per
// frame, and drawn as a CanvasPattern anchored to world coordinates whose
// transform maps tile pixels to world units, so a camera zoom rescales it
// without a rebuild and a camera move does not make it swim. The pulse runs on
// simulated time (world.elapsedSteps), so a pause freezes it and a seeded run
// draws identical frames. Culled by each zone's own polygon box. Purely
// visual: no geometry, role or physics field is written. A level without
// zones draws nothing.
const NO_GRAPPLE_ZONES =
{
    // Zone ids drawn in the last frame (after culling)
    drawn: [],
    // Lattice tile canvas, its repeating pattern and one lattice period in
    // world units ({x, y}); built once by build()
    tile: null,
    pattern: null,
    period: null,
    // Pattern transform, reused every frame
    matrix: null,
    // Tile pixels per world unit: the device density of the Grapple Over
    // camera when the tile is built (a denser tile would alias, as a pattern
    // has no mipmaps); a later zoom or resize resamples it
    tilePxPerWorld: 0,

    // One period of the pointy-top hex lattice: centres on a rectangular grid
    // of sqrt(3) R by 3 R plus the same grid shifted by half of both. Null
    // without the lattice tokens (a style.js from before them): no lattice,
    // and a boot that warms it still completes
    build()
    {
        if (this.pattern)
            return this.pattern
        const colors = STYLE.colors.noGrapple
        if (!colors || !(colors.hexRadius > 0))
            return null
        const r = colors.hexRadius
        const period = {x: Math.sqrt(3) * r, y: 3 * r}
        this.tilePxPerWorld = Math.min(1, Math.max(0.1, canvas.width / width * scale.grapple_over))
        const w = Math.max(2, Math.round(period.x * this.tilePxPerWorld))
        const h = Math.max(2, Math.round(period.y * this.tilePxPerWorld))
        const tile = document.createElement('canvas')
        tile.width = w
        tile.height = h
        const c = tile.getContext('2d')
        // World units inside the tile; x and y differ by the rounding only
        c.scale(w / period.x, h / period.y)
        c.strokeStyle = colors.lattice
        c.lineWidth = colors.latticeLineWorld
        c.lineJoin = 'miter'
        const hr = r - colors.hexInset
        c.beginPath()
        for (let j = -1; j <= 1; ++j)
            for (let i = -1; i <= 1; ++i)
                for (const half of [0, 0.5])
                {
                    const cx = (i + half) * period.x, cy = (j + half) * period.y
                    for (let k = 0; k < 6; ++k)
                    {
                        const a = Math.PI / 3 * k + Math.PI / 6
                        const x = cx + Math.cos(a) * hr, y = cy + Math.sin(a) * hr
                        if (k)
                            c.lineTo(x, y)
                        else
                            c.moveTo(x, y)
                    }
                    c.closePath()
                }
        c.stroke()
        this.tile = tile
        this.period = period
        this.matrix = new DOMMatrix()
        this.pattern = c.createPattern(tile, 'repeat')
        return this.pattern
    },

    // Run start: build the tile and fill a little of the scratch context with
    // the pattern, so its first upload happens here and not mid-play
    warm(context)
    {
        const pattern = this.build()
        if (!pattern)
            return
        context.save()
        context.setTransform(1, 0, 0, 1, 0, 0)
        context.globalAlpha = 1
        context.fillStyle = pattern
        context.fillRect(0, 0, 1, 1)
        context.restore()
    }
}

// The polygon offset outward by d (world units) along each corner's miter,
// for a polygon of either winding
function offsetNoGrapplePolygon(points, d, out)
{
    const n = points.length
    let area = 0
    for (let i = 0; i < n; ++i)
    {
        const a = points[i], b = points[(i + 1) % n]
        area += a.x * b.y - b.x * a.y
    }
    // Outward normal of edge a->b is (dy, -dx) for a clockwise (y down) polygon
    const sign = area > 0 ? 1 : -1
    out.length = n
    for (let i = 0; i < n; ++i)
    {
        const p = points[(i + n - 1) % n], v = points[i], q = points[(i + 1) % n]
        let ax = v.x - p.x, ay = v.y - p.y, bx = q.x - v.x, by = q.y - v.y
        const la = Math.hypot(ax, ay) || 1, lb = Math.hypot(bx, by) || 1
        ax /= la; ay /= la; bx /= lb; by /= lb
        const n1x = ay * sign, n1y = -ax * sign, n2x = by * sign, n2y = -bx * sign
        let mx = n1x + n2x, my = n1y + n2y
        const ml = Math.hypot(mx, my) || 1
        mx /= ml; my /= ml
        // Miter length, clamped for very sharp corners
        const k = d / Math.max(0.25, mx * n1x + my * n1y)
        const o = out[i] || (out[i] = {x: 0, y: 0})
        o.x = v.x + mx * k
        o.y = v.y + my * k
    }
    return out
}

function traceNoGrapplePolygon(points, sx, sy)
{
    ctx.beginPath()
    ctx.moveTo(points[0].x + sx, points[0].y + sy)
    for (let i = 1; i < points.length; ++i)
        ctx.lineTo(points[i].x + sx, points[i].y + sy)
    ctx.closePath()
}

const noGrappleOuterPoints = []
const noGrappleBracketPoints = []

function drawNoGrappleZones(world)
{
    NO_GRAPPLE_ZONES.drawn.length = 0
    if (version !== 'grapple_over' || !world || !world.noGrappleZones || !world.noGrappleZones.length)
        return
    const colors = STYLE.colors.noGrapple
    const rect = getCullRect()
    const sx = screen.x, sy = screen.y
    // World units per screen pixel, as drawAcquisitionCircle
    const px = width / getCanvasCssRect().width / scale[version]
    const pattern = NO_GRAPPLE_ZONES.pattern || NO_GRAPPLE_ZONES.build()
    if (!pattern)
        return
    const period = NO_GRAPPLE_ZONES.period, tile = NO_GRAPPLE_ZONES.tile
    // Tile pixel -> world unit, anchored at world (0, 0)
    const m = NO_GRAPPLE_ZONES.matrix
    m.a = period.x / tile.width
    m.d = period.y / tile.height
    m.b = m.c = 0
    m.e = sx
    m.f = sy
    pattern.setTransform(m)
    // Pulse: centre of the band at u = phase (mod the period), u = p . dir
    const dir = colors.pulseDirection
    const dl = Math.hypot(dir[0], dir[1])
    const dx = dir[0] / dl, dy = dir[1] / dl
    const clockMs = (world.elapsedSteps || 0) * physicsStepMs / cyclesPerTick
    const phase = (clockMs / 1000 * colors.pulseSpeed) % colors.pulsePeriodWorld
    ctx.save()
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
    ctx.shadowBlur = 0
    ctx.shadowOffsetX = ctx.shadowOffsetY = 0
    ctx.setLineDash([])
    for (const zone of world.noGrappleZones)
    {
        const box = getElementCullBox(zone)
        if (!isCullBoxVisible(box, rect))
            continue
        NO_GRAPPLE_ZONES.drawn.push(zone.id)
        const points = zone.getPoints()
        const left = box.left + sx, top = box.top + sy, w = box.right - box.left, h = box.bottom - box.top

        ctx.save()
        traceNoGrapplePolygon(points, sx, sy)
        ctx.clip()
        // Base fill and lattice
        ctx.fillStyle = colors.fill
        ctx.fillRect(left, top, w, h)
        ctx.fillStyle = pattern
        ctx.globalAlpha = colors.latticeAlpha
        ctx.fillRect(left, top, w, h)
        // Inner glow: clipped strokes, wider ones fainter (alphas stack toward the edge)
        ctx.strokeStyle = colors.glow
        ctx.lineJoin = 'miter'
        ctx.globalAlpha = colors.glowAlpha / colors.glowSteps
        traceNoGrapplePolygon(points, sx, sy)
        for (let i = colors.glowSteps; i >= 1; --i)
        {
            ctx.lineWidth = 2 * colors.glowWorld * i / colors.glowSteps
            ctx.stroke()
        }
        // Pulse bands crossing this zone's box: three nested bands, the lattice at pulseAlpha in the middle
        const u0 = Math.min(box.left * dx, box.right * dx) + Math.min(box.top * dy, box.bottom * dy)
        const u1 = Math.max(box.left * dx, box.right * dx) + Math.max(box.top * dy, box.bottom * dy)
        const half = colors.pulseWorld / 2, P = colors.pulsePeriodWorld
        const cx = (box.left + box.right) / 2, cy = (box.top + box.bottom) / 2
        const t0 = cx * -dy + cy * dx, reach = Math.hypot(w, h) / 2 + 1
        ctx.fillStyle = pattern
        ctx.globalAlpha = colors.pulseAlpha / 3
        for (let c = phase + Math.floor((u0 - half - phase) / P) * P; c - half < u1; c += P)
        {
            if (c + half <= u0)
                continue
            for (let b = 1; b <= 3; ++b)
            {
                const hb = half * b / 3
                ctx.beginPath()
                ctx.moveTo(dx * (c - hb) - dy * (t0 - reach) + sx, dy * (c - hb) + dx * (t0 - reach) + sy)
                ctx.lineTo(dx * (c + hb) - dy * (t0 - reach) + sx, dy * (c + hb) + dx * (t0 - reach) + sy)
                ctx.lineTo(dx * (c + hb) - dy * (t0 + reach) + sx, dy * (c + hb) + dx * (t0 + reach) + sy)
                ctx.lineTo(dx * (c - hb) - dy * (t0 + reach) + sx, dy * (c - hb) + dx * (t0 + reach) + sy)
                ctx.closePath()
                ctx.fill()
            }
        }
        ctx.restore()

        // Edge, the fainter line just outside it and the corner brackets, in screen px
        ctx.lineJoin = 'miter'
        ctx.globalAlpha = 1
        ctx.strokeStyle = colors.stroke
        ctx.lineWidth = colors.edgePx * px
        traceNoGrapplePolygon(points, sx, sy)
        ctx.stroke()
        ctx.strokeStyle = colors.outerStroke
        ctx.lineWidth = colors.outerPx * px
        traceNoGrapplePolygon(offsetNoGrapplePolygon(points, colors.outerGapPx * px, noGrappleOuterPoints), sx, sy)
        ctx.stroke()
        const corners = offsetNoGrapplePolygon(points, colors.bracketGapPx * px, noGrappleBracketPoints)
        const n = corners.length, arm = colors.bracketLengthPx * px
        ctx.strokeStyle = colors.bracket
        ctx.lineWidth = colors.bracketPx * px
        ctx.beginPath()
        for (let i = 0; i < n; ++i)
        {
            const p = corners[(i + n - 1) % n], v = corners[i], q = corners[(i + 1) % n]
            const lp = Math.hypot(p.x - v.x, p.y - v.y) || 1, lq = Math.hypot(q.x - v.x, q.y - v.y) || 1
            const ap = Math.min(arm, lp / 2) / lp, aq = Math.min(arm, lq / 2) / lq
            ctx.moveTo(v.x + (p.x - v.x) * ap + sx, v.y + (p.y - v.y) * ap + sy)
            ctx.lineTo(v.x + sx, v.y + sy)
            ctx.lineTo(v.x + (q.x - v.x) * aq + sx, v.y + (q.y - v.y) * aq + sy)
        }
        ctx.stroke()
    }
    ctx.restore()
}
