// Grapple Over parallax silhouettes (GRAPPLE_OVER_PARALLAX): far ridges and a
// mid industrial skyline, one motif per section. Each motif is one tile built
// once through the glow sprite builder (render/glowsprites.js: the only
// shadowBlur, at build time) and kept in the glow sprite cache; a frame only
// copies tiles. Tiles repeat on both axes, so any climb height is covered.

// Draws the layers into renderer.ctx over renderer.fillBounds() for this
// frame's palette ({from, to, t}: the same band blend as the wash). Returns
// what each layer used (camera translation and offset in logical units).
function drawGrappleOverParallax(renderer, palette)
{
    const context = renderer.ctx
    const bounds = renderer.fillBounds()
    const m = context.getTransform()
    const pixelScale = glowSpriteScale(Math.max(0.25, Math.min(1, renderer.canvas.width / LOGICAL_VIEWPORT.width || 1)))
    const cameraX = screen.x * scale[version]
    const cameraY = screen.y * scale[version]
    const weights = palette.t > 0 ? [[palette.from, 1 - palette.t], [palette.to, palette.t]] : [[palette.from, 1]]
    const used = []

    context.save()
    context.shadowBlur = 0
    context.globalCompositeOperation = 'source-over'
    for (const layer of GRAPPLE_OVER_PARALLAX.layers)
    {
        const x = cameraX * layer.factor
        const y = cameraY * layer.factor
        for (const [band, weight] of weights)
        {
            const tile = getGrappleOverParallaxTile(layer, band, pixelScale)
            context.globalAlpha = layer.alpha * weight
            drawParallaxTiles(context, bounds, m, tile, x, y, layer.tileWidth, layer.tileHeight)
        }
        used.push({name: layer.name, factor: layer.factor, cameraX, cameraY, x, y,
            motifs: weights.map(([band, weight]) => [layer.motifs[band], weight])})
    }
    context.restore()
    return used
}

function getGrappleOverParallaxTile(layer, band, pixelScale)
{
    return getGlowSprite('parallax|' + layer.name + '|' + band + '|' + pixelScale, () =>
        buildGlowSprite(Math.round(layer.tileWidth * pixelScale), Math.round(layer.tileHeight * pixelScale),
            0, pixelScale, pixelScale, 0, 0, 1, paintGrappleOverParallaxTile, [layer, band]))
}

// Repeats tile (w x h logical) across bounds from (x, y). Edges are snapped to
// device pixels on both axes, so neighbours neither overlap nor leave a gap.
function drawParallaxTiles(context, bounds, m, tile, x, y, w, h)
{
    const toX = v => Math.round(m.a * v + m.e), fromX = p => (p - m.e) / m.a
    const toY = v => Math.round(m.d * v + m.f), fromY = p => (p - m.f) / m.d
    const right = bounds.x + bounds.width
    const bottom = bounds.y + bounds.height
    const firstColumn = Math.floor((bounds.x - x) / w)
    let row = Math.floor((bounds.y - y) / h)
    let top = fromY(toY(y + row * h))

    while (top < bottom)
    {
        const nextTop = fromY(toY(y + (row + 1) * h))
        let column = firstColumn
        let left = fromX(toX(x + column * w))
        while (left < right)
        {
            const nextLeft = fromX(toX(x + (column + 1) * w))
            context.drawImage(tile, left, top, nextLeft - left, nextTop - top)
            left = nextLeft
            ++column
        }
        top = nextTop
        ++row
    }
}

// Paints one motif with the global ctx (the sprite canvas) in tile units.
// Everything wraps horizontally (shapes are drawn again one tile left and
// right, the ridge line is periodic) and the fill fades out before the tile
// bottom, so copies meet without a seam on either axis.
function paintGrappleOverParallaxTile(layer, band)
{
    const palette = GRAPPLE_OVER_THEME.palettes[band]
    const motif = layer.motifs[band]
    const W = layer.tileWidth, H = layer.tileHeight
    let seed = (layer.seed + band * 101) >>> 0
    // mulberry32: the same tiles on every run and device
    const random = () =>
    {
        seed = (seed + 0x6D2B79F5) >>> 0
        let t = seed
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    const fill = ctx.createLinearGradient(0, H * 0.2, 0, H)
    fill.addColorStop(0, palette.top)
    fill.addColorStop(0.55, palette.top + 'bb')
    fill.addColorStop(1, palette.top + '00')

    const outline = layer.name == 'ridges' ? ridgeOutline(motif, W, H, random) : skylineOutline(motif, W, H, random)

    // Body, then a thin glowing rim along the outline (shadowBlur here only:
    // this runs once per tile, inside buildGlowSprite)
    ctx.fillStyle = fill
    for (const dx of [-W, 0, W])
    {
        ctx.beginPath()
        ctx.moveTo(outline[0][0] + dx, H)
        for (const [px, py] of outline)
            ctx.lineTo(px + dx, py)
        ctx.lineTo(outline[outline.length - 1][0] + dx, H)
        ctx.closePath()
        ctx.fill()
    }
    ctx.strokeStyle = palette.glow
    ctx.shadowColor = palette.glow
    ctx.shadowBlur = 12
    ctx.lineWidth = 1.5
    ctx.lineJoin = 'round'
    ctx.globalAlpha = 0.55
    for (const dx of [-W, 0, W])
    {
        ctx.beginPath()
        outline.forEach(([px, py], i) => i ? ctx.lineTo(px + dx, py) : ctx.moveTo(px + dx, py))
        ctx.stroke()
    }
    if (layer.name == 'skyline')
        paintSkylineDetails(motif, W, H, random, palette)
}

// Periodic ridge line over [0, W]: sums of whole-period waves, shaped per motif
function ridgeOutline(motif, W, H, random)
{
    const waves = [1, 2, 3, 5, 8].map((k, i) => ({k, a: 1 / (i + 1), phase: random() * Math.PI * 2}))
    const spikes = Array.from({length: 7}, () => ({x: random() * W, h: 0.2 + random() * 0.25, w: 20 + random() * 30}))
    const crest = H * 0.42, amplitude = H * 0.14
    const points = []
    for (let x = 0; x <= W; x += 8)
    {
        let v = 0
        for (const w of waves)
        {
            const s = Math.sin(2 * Math.PI * w.k * x / W + w.phase)
            v += w.a * (motif == 'jagged' ? 1 - 2 * Math.abs(s) : s)
        }
        v /= 2
        if (motif == 'mesa')
            v = Math.max(-0.35, Math.min(0.35, v)) * 1.6
        if (motif == 'spires')
            for (const s of spikes)
            {
                const d = Math.min(Math.abs(x - s.x), W - Math.abs(x - s.x))
                v += Math.max(0, 1 - d / s.w) * s.h * 4
            }
        points.push([x, crest - v * amplitude])
    }
    points[points.length - 1][1] = points[0][1]
    return points
}

// Building skyline as a step outline over [0, W] (a height map on a 6-unit
// grid, wrapped), with motif-specific roof shapes
function skylineOutline(motif, W, H, random)
{
    const step = 6, n = Math.round(W / step)
    const heights = new Array(n).fill(H * 0.12)
    const raise = (x, width, h) =>
    {
        for (let i = Math.floor(x / step); i < Math.ceil((x + width) / step); ++i)
        {
            const j = ((i % n) + n) % n
            heights[j] = Math.max(heights[j], h)
        }
    }
    let x = 0
    while (x < W)
    {
        const width = 40 + random() * 90
        raise(x, width, H * (0.15 + random() * (motif == 'towers' ? 0.45 : 0.25)))
        if (motif == 'chimneys' && random() < 0.5)
            raise(x + width * 0.3, 12, H * (0.45 + random() * 0.2))
        if (motif == 'domes')
        {
            const r = width / 2, h0 = H * (0.2 + random() * 0.15)
            for (let dx = 0; dx < width; dx += step)
                raise(x + dx, step, h0 + Math.sqrt(Math.max(0, r * r - (dx - r) ** 2)) * 0.8)
        }
        if (motif == 'pylons' && random() < 0.4)
            for (let dx = 0; dx < 36; dx += step)
                raise(x + dx, step, H * 0.25 + (18 - Math.abs(dx - 18)) * 9)
        x += width + random() * 20
    }
    const points = []
    for (let i = 0; i < n; ++i)
    {
        const y = H * 0.75 - heights[i]
        points.push([i * step, y], [(i + 1) * step, y])
    }
    return points
}

// Lit windows and line details (crane jibs, antennas) over the skyline
function paintSkylineDetails(motif, W, H, random, palette)
{
    ctx.shadowBlur = 0
    ctx.fillStyle = palette.bottom
    ctx.globalAlpha = 0.35
    for (let i = 0; i < 140; ++i)
    {
        const x = random() * W, y = H * (0.45 + random() * 0.25)
        for (const dx of [-W, 0, W])
            ctx.fillRect(x + dx, y, 4, 3)
    }
    if (motif != 'cranes' && motif != 'antennas')
        return
    ctx.strokeStyle = palette.glow
    ctx.shadowColor = palette.glow
    ctx.shadowBlur = 8
    ctx.lineWidth = 1.5
    ctx.globalAlpha = 0.5
    for (let i = 0; i < 6; ++i)
    {
        const x = random() * W, top = H * (0.12 + random() * 0.15)
        for (const dx of [-W, 0, W])
        {
            ctx.beginPath()
            ctx.moveTo(x + dx, H * 0.6)
            ctx.lineTo(x + dx, top)
            if (motif == 'cranes')
            {
                ctx.moveTo(x + dx - 40, top + 8)
                ctx.lineTo(x + dx + 140, top + 8)
                ctx.moveTo(x + dx + 120, top + 8)
                ctx.lineTo(x + dx + 120, top + 70)
            }
            else
                ctx.arc(x + dx, top, 3, 0, Math.PI * 2)
            ctx.stroke()
        }
    }
}
