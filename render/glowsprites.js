// Pre-rendered shadowBlur glow. A shape's glow is drawn once into an offscreen
// canvas (the only place shadowBlur is set) and copied with drawImage every
// frame. shadowBlur works in canvas pixels, so a sprite is built at the scale
// of the current transform and drawn in canvas pixels, its origin snapped to a
// whole pixel (<= 0.5 px) so the 9-slice pieces of a rect meet without seams.
const GLOW_SPRITES =
{
    limit: 96,
    cache: new Map()
}

// Canvas px around the bounds: the blur reach plus the shape's own margin
function glowSpritePad(blur, margin, scaleX)
{
    return Math.ceil(blur * 1.5 + margin * scaleX) + 2
}

// Sprite scale: draw() scales the transform by s and 1/s each frame, so its
// scale drifts in the last digits; rounded, it keys the same sprite
function glowSpriteScale(value)
{
    return Math.round(value * 1e4) / 1e4
}

// Least recently used sprites are dropped past GLOW_SPRITES.limit
function getGlowSprite(key, build)
{
    const cache = GLOW_SPRITES.cache
    let sprite = cache.get(key)
    if (sprite)
    {
        cache.delete(key)
        cache.set(key, sprite)
        return sprite
    }

    sprite = build()
    cache.set(key, sprite)
    if (cache.size > GLOW_SPRITES.limit)
        cache.delete(cache.keys().next().value)
    return sprite
}

// Calls drawShape(...args) with the global ctx pointing at a new canvas whose
// transform maps the logical point (originX, originY) to (pad, pad). The
// caller's globalAlpha is baked in (each layer at alpha, as drawn directly).
function buildGlowSprite(widthPx, heightPx, pad, scaleX, scaleY, originX, originY, alpha, drawShape, args)
{
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, widthPx)
    canvas.height = Math.max(1, heightPx)
    const spriteCtx = canvas.getContext('2d')
    spriteCtx.setTransform(scaleX, 0, 0, scaleY, pad - originX * scaleX, pad - originY * scaleY)
    spriteCtx.globalAlpha = alpha

    const mainCtx = ctx
    ctx = spriteCtx
    try
    {
        drawShape.apply(null, args || [])
    }
    finally
    {
        ctx = mainCtx
    }
    return canvas
}

// drawShape draws with the global ctx in the current logical coordinates,
// inside (x, y, w, h) grown by margin, and sets its own state (shadowBlur up to
// blur). key must name everything that changes its pixels except the scale.
function drawGlowSprite(key, x, y, w, h, margin, blur, drawShape)
{
    const m = ctx.getTransform()
    const sx = glowSpriteScale(m.a), sy = glowSpriteScale(m.d)
    const pad = glowSpritePad(blur, margin, sx)
    const widthPx = Math.ceil(w * sx) + pad * 2
    const heightPx = Math.ceil(h * sy) + pad * 2
    const alpha = ctx.globalAlpha
    const sprite = getGlowSprite(key + '|' + alpha + '|' + sx + '|' + sy,
        () => buildGlowSprite(widthPx, heightPx, pad, sx, sy, x, y, alpha, drawShape))

    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.globalAlpha = 1
    ctx.drawImage(sprite, Math.round(m.a * x + m.e) - pad, Math.round(m.d * y + m.f) - pad)
    ctx.restore()
}

// A rect-like shape whose features lie within margin of its edges, drawn by
// drawShape(x, y, w, h). The sprite is built for at most a core-sized rect and
// its middle row and column stretch to the real size (9-slice), so one sprite
// serves every length.
function drawGlowRect(key, x, y, w, h, margin, blur, drawShape)
{
    const m = ctx.getTransform()
    const sx = glowSpriteScale(m.a), sy = glowSpriteScale(m.d)
    const pad = glowSpritePad(blur, margin, sx)
    // Corners hold the outer glow, the margin and the inner glow
    const core = (pad + Math.ceil(margin * sx)) * 2 + 2
    const widthPx = Math.max(1, Math.round(w * m.a))
    const heightPx = Math.max(1, Math.round(h * m.d))
    const coreWidth = Math.min(widthPx, core)
    const coreHeight = Math.min(heightPx, core)
    const alpha = ctx.globalAlpha
    const sprite = getGlowSprite(key + '|' + alpha + '|' + sx + '|' + sy + '|' + coreWidth + '|' + coreHeight,
        () => buildGlowSprite(coreWidth + pad * 2, coreHeight + pad * 2, pad, sx, sy, 0, 0, alpha,
            drawShape, [0, 0, coreWidth / sx, coreHeight / sy]))

    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.globalAlpha = 1
    drawNineSlice(sprite, Math.round(m.a * x + m.e) - pad, Math.round(m.d * y + m.f) - pad,
        widthPx + pad * 2, heightPx + pad * 2)
    ctx.restore()
}

// fillText (after strokeText when stroke is set) with a shadow glow, in the
// ctx's current font, alignment, baseline, colours and line width
function drawGlowText(text, x, y, shadowColor, blur, stroke)
{
    const font = ctx.font, align = ctx.textAlign, baseline = ctx.textBaseline
    const fill = ctx.fillStyle, strokeStyle = ctx.strokeStyle, lineWidth = ctx.lineWidth
    const metrics = ctx.measureText(text)
    const left = x - metrics.actualBoundingBoxLeft
    const top = y - metrics.actualBoundingBoxAscent
    const key = 'text|' + text + '|' + font + '|' + align + '|' + baseline + '|' + fill + '|' +
        (stroke ? strokeStyle + '|' + lineWidth : '') + '|' + shadowColor + '|' + blur

    drawGlowSprite(key, left, top, metrics.actualBoundingBoxLeft + metrics.actualBoundingBoxRight,
        metrics.actualBoundingBoxAscent + metrics.actualBoundingBoxDescent, stroke ? lineWidth : 0, blur, () =>
    {
        ctx.font = font
        ctx.textAlign = align
        ctx.textBaseline = baseline
        ctx.fillStyle = fill
        ctx.strokeStyle = strokeStyle
        ctx.lineWidth = lineWidth
        ctx.shadowColor = shadowColor
        ctx.shadowBlur = blur
        if (stroke)
            ctx.strokeText(text, x, y)
        ctx.fillText(text, x, y)
    })
}

// Splits the sprite after its middle pixel row/column; that pixel stretches
// over the extra size. An axis with no extra size is drawn in one piece.
function drawNineSlice(sprite, dx, dy, dw, dh)
{
    const sw = sprite.width, sh = sprite.height
    const midX = Math.floor(sw / 2), midY = Math.floor(sh / 2)
    const columns = dw > sw ? 3 : 1
    const rows = dh > sh ? 3 : 1

    let sy = 0, y = dy
    for (let row = 0; row < rows; ++row)
    {
        const srcH = rows == 1 ? sh : (row == 0 ? midY : row == 1 ? 1 : sh - midY - 1)
        const dstH = rows == 1 ? sh : (row == 1 ? dh - sh + 1 : srcH)
        let sx = 0, x = dx
        for (let column = 0; column < columns; ++column)
        {
            const srcW = columns == 1 ? sw : (column == 0 ? midX : column == 1 ? 1 : sw - midX - 1)
            const dstW = columns == 1 ? sw : (column == 1 ? dw - sw + 1 : srcW)
            if (srcW > 0 && srcH > 0)
                ctx.drawImage(sprite, sx, sy, srcW, srcH, x, y, dstW, dstH)
            sx += srcW
            x += dstW
        }
        sy += srcH
        y += dstH
    }
}
