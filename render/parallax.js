// Grapple Over parallax silhouettes (GRAPPLE_OVER_PARALLAX): far ridges and a
// mid industrial skyline, one motif per section. Each motif is one tile built
// once through the glow sprite builder (render/glowsprites.js: the only
// shadowBlur, at build time), all bands together and kept in
// GRAPPLE_OVER_PARALLAX_TILES; a frame only copies tiles. Tiles repeat on both axes, so any climb height is covered.
//
// A tile is kept as the rows its paint reaches (TASK-788): the transparent
// rows above the outline's glow are not stored. Below a ridge tile's lowest
// glow only the body's vertical fade is left and every column is the same,
// so a strip of it (parallaxFillStrip, and one strip of the rest of the
// width) is stored and drawn side by side across the tile; not with the
// browser's own gradient dither (no GRADIENT_DITHER), which differs per
// column. Every part is drawn whole and maps its px as the whole tile did:
// Chromium blends a drawImage of a source rect, or a stretched column, at
// globalAlpha < 1 with +-1 level rounding. Same pixels in about half the
// memory.

// Draws the layers into renderer.ctx over renderer.fillBounds() for this
// frame's palette ({from, to, t}: the same band blend as the wash). Returns
// what each layer used (camera translation and offset in logical units).
function drawGrappleOverParallax(renderer, palette)
{
    const context = renderer.ctx
    const bounds = renderer.fillBounds()
    const m = context.getTransform()
    const pixelScale = glowSpriteScale(Math.max(0.25, Math.min(2, renderer.canvas.width / LOGICAL_VIEWPORT.width || 1)))
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
            // A band fading in or out at under a quarter of an 8-bit step
            // changes no pixel: skip its tile copies
            if (layer.alpha * weight * 255 < 0.25)
                continue
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

// Every band's tiles for one pixel scale, outside the glow sprite LRU so none
// is dropped and rebuilt mid-climb. fills are the fill strips' canvases,
// kept and resized by a rebuild, so a rebuild creates only the canvases the
// whole tiles did (fillCount: how many this scale's tiles took).
// pending: [layer, band] of the tiles not built yet at this scale (TASK-889):
// a live frame builds only the tiles it draws, later frames one each
// (nearest band to band first: the last band drawn). stats counts builds by
// when they happened: initial (drawn in the frame of a scale change), ahead
// (from the queue, before any frame drew them), late (queued but needed by a
// frame before the queue reached them: must stay 0) and sync (outside a live
// frame: everything at once, as before); cheap: [layer, band] of initial
// tiles painted cheap (8-bit), rebuilt exact first (stats.exact). log: by tile key, the drawFrameId it
// was built in (and why) and first drawn in (tools/test_parallax_band_builds.py).
const GRAPPLE_OVER_PARALLAX_TILES = {cache: new Map(), scale: null, warm: null, fills: [], fillCount: 0,
    pending: [], cheap: [], scaleFrame: -1, band: 0, stats: {initial: 0, ahead: 0, late: 0, sync: 0, exact: 0},
    log: {built: new Map(), drawn: new Map()}}

// Fill strip widths tried, in tile px: the widest strip sets the most copies
// a tile row draws
const PARALLAX_FILL_STRIP = [256, 512]

// The strip width (in PARALLAX_FILL_STRIP, at most width) whose strip and
// rest of width hold the fewest px; of equals, the widest
function parallaxFillStrip(width)
{
    let best = width
    for (let strip = Math.min(width, PARALLAX_FILL_STRIP[0]); strip <= Math.min(width, PARALLAX_FILL_STRIP[1]); ++strip)
        if (strip + width % strip <= best + width % best)
            best = strip
    return best
}

function getGrappleOverParallaxTile(layer, band, pixelScale)
{
    const store = GRAPPLE_OVER_PARALLAX_TILES
    buildGrappleOverParallaxTiles(pixelScale, layer, band)
    store.band = band
    const key = 'parallax|' + layer.name + '|' + band + '|' + pixelScale
    if (!store.log.drawn.has(key))
        store.log.drawn.set(key, drawFrameId)
    return store.cache.get(key)
}

function parallaxTilesPending()
{
    return GRAPPLE_OVER_PARALLAX_TILES.pending.length > 0 || GRAPPLE_OVER_PARALLAX_TILES.cheap.length > 0
}

// Builds the pending tile of layer and band (why: a stats name). The tiles a
// live frame needs at a scale change ('initial': the boot frame) are painted
// cheap when GRADIENT_DITHER is on and kept in store.cheap until
// rebuildCheapParallaxTile paints them exact (the first queued job).
function buildPendingParallaxTileAt(layer, band, why)
{
    const store = GRAPPLE_OVER_PARALLAX_TILES
    const i = store.pending.findIndex(([l, b]) => l === layer && b === band)
    if (i < 0)
        return
    store.pending.splice(i, 1)
    const pixelScale = store.scale
    const key = 'parallax|' + layer.name + '|' + band + '|' + pixelScale
    // Cheap only under the boot poster (BACKGROUND_BAKE_QUEUE.hidden): never a visible swap
    const cheap = why === 'initial' && GRADIENT_DITHER.enabled && BACKGROUND_BAKE_QUEUE.hidden
    const tile = buildGrappleOverParallaxTile(layer, band, pixelScale,
        () =>
        {
            const n = store.fillCount++
            return store.fills[n] || (store.fills[n] = document.createElement('canvas'))
        }, cheap)
    store.cache.set(key, tile)
    if (cheap)
        store.cheap.push([layer, band])
    else
        warmParallaxTile(tile)
    ++store.stats[why]
    store.log.built.set(key, {frame: drawFrameId, why, cheap})
}

// Its upload happens here, not in the frame that first draws it (a cheap
// tile is drawn in the frame that builds it)
function warmParallaxTile(tile)
{
    const warm = GRAPPLE_OVER_PARALLAX_TILES.warm
    for (const part of tile.parts)
        for (const image of [part.canvas, part.rest])
            if (image)
                warm.drawImage(image, 0, 0, 1, 1)
}

// Paints the oldest cheap tile exact into the same fill canvases; returns
// true if one was
function rebuildCheapParallaxTile()
{
    const store = GRAPPLE_OVER_PARALLAX_TILES
    if (!store.cheap.length)
        return false
    const [layer, band] = store.cheap.shift()
    const key = 'parallax|' + layer.name + '|' + band + '|' + store.scale
    const fills = store.cache.get(key).parts.slice(1).flatMap(part => [part.canvas, part.rest]).filter(Boolean)
    const tile = buildGrappleOverParallaxTile(layer, band, store.scale, () => fills.shift(), false)
    store.cache.set(key, tile)
    warmParallaxTile(tile)
    ++store.stats.exact
    store.log.built.get(key).exactFrame = drawFrameId
    return true
}

// One pending tile, of the band nearest the last one drawn (BACKGROUND_BAKE_QUEUE);
// returns true if one was built
function buildPendingParallaxTile()
{
    const store = GRAPPLE_OVER_PARALLAX_TILES
    if (rebuildCheapParallaxTile())
        return true
    if (!store.pending.length)
        return false
    let next = store.pending[0]
    for (const entry of store.pending)
        if (Math.abs(entry[1] - store.band) < Math.abs(next[1] - store.band))
            next = entry
    buildGrappleOverParallaxTiles(store.scale, next[0], next[1], 'ahead')
    return true
}

// {width, height (tile px), parts: [{canvas, y, rows, rest}]}: each part is
// tile rows y .. y + rows, painted at the tile's transform; rows above the
// first are transparent. The first part's canvas is built by buildGlowSprite.
// A fill part (rest set) is its strip repeated across the tile, then rest,
// the strip of the width left (null when none is): canvases from fill(),
// resized.
function buildGrappleOverParallaxTile(layer, band, pixelScale, fill, cheap)
{
    const {width, height, top, bottom} = parallaxTileRows(layer, band, pixelScale)
    // cheap: painted straight into the 8-bit canvases (no float16 bake, the
    // browser's own gradient dither), same rows and parts
    const smooth = !cheap
    const paint = (canvas, x, y) => paintGlowSprite(canvas, 0, pixelScale, pixelScale, x / pixelScale, y / pixelScale, 1,
        paintGrappleOverParallaxTile, [layer, band], smooth)
    const parts = [{y: top, rows: bottom - top, canvas: buildGlowSprite(width, bottom - top, 0, pixelScale, pixelScale,
        0, top / pixelScale, 1, paintGrappleOverParallaxTile, [layer, band], smooth)}]
    if (bottom < height)
    {
        // The rest is painted at its own px of the tile: where the tile's
        // width is not a whole px, its last column holds two copies' edges
        const strip = parallaxFillStrip(width), [canvas, rest] = [fill(), width % strip ? fill() : null]
        for (const [part, from] of [[canvas, 0], [rest, width - width % strip]])
            if (part)
            {
                part.width = Math.min(strip, width - from)
                part.height = height - bottom
                paint(part, from, bottom)
            }
        parts.push({y: bottom, rows: height - bottom, canvas, rest})
    }
    return {width, height, parts, cheap: Boolean(cheap)}
}

// Tile px: the tile's size, the first painted row (top) and the first of the
// rows that are the same in every column (bottom; height when none are)
function parallaxTileRows(layer, band, pixelScale)
{
    const width = Math.round(layer.tileWidth * pixelScale), height = Math.round(layer.tileHeight * pixelScale)
    const reach = parallaxTileReach(layer, band)
    // Glow reach in tile px: the 4 sigma of the widest shadowBlur (device px,
    // not scaled) plus the stroke. The top is on the 8 px grid, so a browser
    // gradient dither (an 8 x 8 matrix from the canvas origin) keeps its phase.
    const glow = 2 * PARALLAX_TILE_BLUR + PARALLAX_TILE_LINE * pixelScale + 2
    const top = Math.max(0, Math.floor((reach.top * pixelScale - glow) / 8) * 8)
    const bottom = reach.uniformBelow === null || !GRADIENT_DITHER.enabled ? height :
        Math.max(top + 1, Math.min(height, Math.ceil(reach.uniformBelow * pixelScale + glow)))
    return {width, height, top, bottom}
}

// shadowBlur (canvas px) and lineWidth (tile units) of the widest glowing line
const PARALLAX_TILE_BLUR = 12, PARALLAX_TILE_LINE = 1.5

// Tile units: top = the highest painted y but for glow, uniformBelow = the
// y below which only the body's vertical fade is painted (null for the
// skyline: its lit windows reach below the lowest roofs, so a fill part would
// hold few rows)
function parallaxTileReach(layer, band)
{
    const {outline} = parallaxTileOutline(layer, band)
    let top = Infinity, lowest = -Infinity
    for (const [, y] of outline)
    {
        top = Math.min(top, y)
        lowest = Math.max(lowest, y)
    }
    if (layer.name == 'ridges')
        return {top, uniformBelow: lowest}
    // Crane and antenna masts reach up to 0.12 of the tile, plus an antenna's
    // 3 unit ball; lit windows stay below the outline's lowest roof
    const motif = layer.motifs[band]
    if (motif == 'cranes' || motif == 'antennas')
        top = Math.min(top, layer.tileHeight * 0.12 - 3)
    return {top, uniformBelow: null}
}

// The seeded generator and the motif's outline, in tile units: the same on
// every run and device, for the paint and for its reach
function parallaxTileOutline(layer, band)
{
    const motif = layer.motifs[band]
    const W = layer.tileWidth, H = layer.tileHeight
    let seed = (layer.seed + band * 101) >>> 0
    // mulberry32
    const random = () =>
    {
        seed = (seed + 0x6D2B79F5) >>> 0
        let t = seed
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
    const outline = layer.name == 'ridges' ? ridgeOutline(motif, W, H, random) : skylineOutline(motif, W, H, random)
    return {outline, random}
}

// Starts the tiles of every layer and band over when the pixel scale is
// first known or changes (resize, DPR), like the palette strips: each new
// tile is drawn once into a 1x1 canvas so its upload happens when it is
// built, not in the frame a band change first shows it (1-2 Mpx per band at
// 1706x932 DPR 1.5). Outside a live frame (GLYPH_GLOW_QUEUE.defer) all are
// built here, as before; a live frame builds only the tile of layer and band
// (the one it draws) if pending and leaves the rest pending (later frames
// build them: buildPendingParallaxTile, why 'ahead').
function buildGrappleOverParallaxTiles(pixelScale, layer, band, why)
{
    const store = GRAPPLE_OVER_PARALLAX_TILES
    if (store.scale !== pixelScale)
    {
        store.scale = pixelScale
        store.scaleFrame = drawFrameId
        store.cache.clear()
        store.fillCount = 0
        store.cheap = []
        const warm = store.warm || (store.warm = document.createElement('canvas').getContext('2d'))
        warm.canvas.width = warm.canvas.height = 1
        store.pending = []
        for (const layer of GRAPPLE_OVER_PARALLAX.layers)
            layer.motifs.forEach((motif, band) => store.pending.push([layer, band]))
    }
    if (GLYPH_GLOW_QUEUE.defer)
    {
        // No queued job runs in the frame of a scale change
        if (store.scaleFrame === drawFrameId)
            BACKGROUND_BAKE_QUEUE.queuedFrame = drawFrameId
        if (layer)
            buildPendingParallaxTileAt(layer, band, why || (store.scaleFrame === drawFrameId ? 'initial' : 'late'))
        return
    }
    while (rebuildCheapParallaxTile())
        ;
    while (store.pending.length)
        buildPendingParallaxTileAt(store.pending[0][0], store.pending[0][1], 'sync')
}

// Repeats tile (w x h logical) across bounds from (x, y). Edges are snapped to
// device pixels on both axes, so neighbours neither overlap nor leave a gap.
// Each copy draws the tile's parts at their rows of it.
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
        // Part rows placed in device px, as the whole tile's rows were: a
        // tile drawn 1:1 has its parts 1:1 too (an unfiltered copy)
        const topPx = toY(y + row * h), unit = (toY(y + (row + 1) * h) - topPx) / tile.height
        const parts = tile.parts.map(part =>
            [part, fromY(topPx + part.y * unit), fromY(topPx + (part.y + part.rows) * unit)])
        let column = firstColumn
        let left = fromX(toX(x + column * w))
        while (left < right)
        {
            const nextLeft = fromX(toX(x + (column + 1) * w))
            const leftPx = toX(x + column * w), across = (toX(x + (column + 1) * w) - leftPx) / tile.width
            for (const [part, partTop, partBottom] of parts)
                if (part.rest === undefined)
                    context.drawImage(part.canvas, left, partTop, nextLeft - left, partBottom - partTop)
                else
                {
                    // The fill strips side by side, each copy at its px of the
                    // tile: x in device px (a logical x can miss a whole px by
                    // float rounding, and a copy off the px grid is filtered)
                    context.setTransform(1, 0, 0, m.d, 0, m.f)
                    for (let from = 0; from < tile.width;)
                    {
                        const image = from + part.canvas.width <= tile.width ? part.canvas : part.rest
                        context.drawImage(image, leftPx + from * across, partTop, image.width * across, partBottom - partTop)
                        from += image.width
                    }
                    context.setTransform(m)
                }
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
    const fill = ctx.createLinearGradient(0, H * 0.2, 0, H)
    fill.addColorStop(0, palette.top)
    fill.addColorStop(0.55, palette.top + 'bb')
    fill.addColorStop(1, palette.top + '00')

    const {outline, random} = parallaxTileOutline(layer, band)

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
    ctx.shadowBlur = PARALLAX_TILE_BLUR
    ctx.lineWidth = PARALLAX_TILE_LINE
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
