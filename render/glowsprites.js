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

// Gradient dither (TASK-714). Chromium dithers every gradient fill drawn into
// an 8-bit canvas with Skia's 8x8 ordered matrix: a static 2-device-px grid
// over the soft background (stretched to 4-8 px by the fast backdrop). A
// float16 canvas is never dithered, and image draws are not dithered. So no
// gradient of the background is filled into an 8-bit canvas each frame: its
// gradient tiles, sprites, palette wash and vignette are painted once into a
// float16 canvas and copied into 8-bit images (paint8), which the frame draws.
// The crystal tile and the palette wash (the last full-frame light) get a
// fixed non-periodic noise of +-0.5 grey level per channel before that copy,
// so its rounding dithers them (fine noise instead of a grid or 1-level
// bands); the others are rounded (the vignette as a small image drawn
// enlarged). In the fast backdrop, which is enlarged into the frame, the wash
// and the vignette are dithered with a stronger blue noise (BLUE_RMS). Where
// the browser has no float16 canvas every image is painted directly, as before.
//   ?gradientdither=0  keeps the browser dither, for A/B measurements
const GRADIENT_DITHER = (function()
{
    const NOISE_SIZE = 256
    const probe = () =>
    {
        try
        {
            const test = document.createElement('canvas').getContext('2d', {colorType: 'float16'})
            const attributes = test && test.getContextAttributes && test.getContextAttributes()
            return Boolean(attributes && attributes.colorType === 'float16' &&
                test.createImageData(1, 1, {pixelFormat: 'rgba-float16'}).data instanceof Float16Array)
        }
        catch (error)
        {
            return false
        }
    }
    return {
        enabled: new URLSearchParams(location.search).get('gradientdither') !== '0' && probe(),
        // Seeded noise, each channel on its own (and float16 NOISE_SIZE
        // square tiles of it, opaque): 'white' uniform in [-0.5, 0.5) grey levels; 'blue' that
        // noise minus the mean of its 4 neighbours, at BLUE_RMS: anticorrelated
        // neighbours, so the fast backdrop's bilinear 2x upscale leaves fine
        // noise that still dithers the frame's rounding, not 2 px clumps
        noise: {},
        // float16 canvas every bake paints into
        scratch: null,
        // NOISE_SIZE square x 3 channels of kind's noise (grey levels)
        noiseValues(kind)
        {
            const key = kind + 'Values'
            if (this.noise[key])
                return this.noise[key]
            const BLUE_RMS = 1.4 / Math.sqrt(3)
            // mulberry32: the same noise on every run and device
            let seed = 714
            const white = new Float32Array(NOISE_SIZE * NOISE_SIZE * 3)
            for (let i = 0; i < white.length; ++i)
            {
                seed = (seed + 0x6D2B79F5) >>> 0
                let t = seed
                t = Math.imul(t ^ (t >>> 15), t | 1)
                t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
                white[i] = ((t ^ (t >>> 14)) >>> 0) / 4294967296 - 0.5
            }
            if (kind !== 'blue')
                return this.noise[key] = white
            const mask = NOISE_SIZE - 1
            const at = (x, y, c) => white[((y & mask) * NOISE_SIZE + (x & mask)) * 3 + c]
            // white has RMS sqrt(1/12); minus its neighbour mean, 1.25 times its variance
            const gain = BLUE_RMS / Math.sqrt(1.25 / 12)
            const blue = new Float32Array(white.length)
            for (let y = 0; y < NOISE_SIZE; ++y)
                for (let x = 0; x < NOISE_SIZE; ++x)
                    for (let c = 0; c < 3; ++c)
                        blue[(y * NOISE_SIZE + x) * 3 + c] = gain * (at(x, y, c) -
                            (at(x - 1, y, c) + at(x + 1, y, c) + at(x, y - 1, c) + at(x, y + 1, c)) / 4)
            return this.noise[key] = blue
        },
        noiseTile(kind)
        {
            if (this.noise[kind])
                return this.noise[kind]
            const values = this.noiseValues(kind)
            const canvas = document.createElement('canvas')
            canvas.width = canvas.height = NOISE_SIZE
            const context = canvas.getContext('2d', {colorType: 'float16'})
            const image = context.createImageData(NOISE_SIZE, NOISE_SIZE, {pixelFormat: 'rgba-float16'})
            const data = image.data
            for (let i = 0, j = 0; i < data.length; i += 4, j += 3)
            {
                data[i] = values[j] / 255
                data[i + 1] = values[j + 1] / 255
                data[i + 2] = values[j + 2] / 255
                data[i + 3] = 1
            }
            context.putImageData(image, 0, 0)
            return this.noise[kind] = canvas
        },
        // Calls paint(context) for canvas (8-bit) and returns its result.
        // Enabled: paint draws into a float16 canvas of the same size, which
        // is then copied into canvas, rounding each premultiplied channel.
        // dither ('white' or 'blue') adds that noise first: in the float16
        // canvas (an opaque paint), or with alpha set, per pixel in script on
        // the premultiplied colour only (alpha is rounded).
        paint8(canvas, paint, dither, alpha)
        {
            const target = canvas.getContext('2d')
            if (!this.enabled)
                return paint(target)
            if (!this.scratch)
                this.scratch = document.createElement('canvas').getContext('2d', {colorType: 'float16'})
            const scratch = this.scratch
            // a new size also clears it and resets its state
            scratch.canvas.width = canvas.width
            scratch.canvas.height = canvas.height
            const result = paint(scratch)
            if (dither && alpha)
                this.ditherAlpha(scratch, target, this.noiseValues(dither))
            else
            {
                if (dither)
                {
                    scratch.setTransform(1, 0, 0, 1, 0, 0)
                    scratch.globalAlpha = 1
                    scratch.shadowBlur = 0
                    scratch.globalCompositeOperation = 'lighter'
                    scratch.fillStyle = scratch.createPattern(this.noiseTile(dither), 'repeat')
                    scratch.fillRect(0, 0, canvas.width, canvas.height)
                }
                target.save()
                target.setTransform(1, 0, 0, 1, 0, 0)
                target.globalCompositeOperation = 'copy'
                target.drawImage(scratch.canvas, 0, 0)
                target.restore()
            }
            // the scratch keeps no memory past the bake
            scratch.canvas.width = scratch.canvas.height = 1
            return result
        },
        // scratch (float16) into target: premultiplied colour p to
        // round(p + noise), alpha a8 = round(a); ImageData is unpremultiplied,
        // and its stored premultiplied value round(c8 * a8 / 255) is exactly
        // the dithered one
        ditherAlpha(scratch, target, noise)
        {
            const w = scratch.canvas.width, h = scratch.canvas.height
            const source = scratch.getImageData(0, 0, w, h, {pixelFormat: 'rgba-float16'}).data
            const image = target.createImageData(w, h)
            const out = image.data
            const mask = NOISE_SIZE - 1
            for (let y = 0; y < h; ++y)
            {
                const row = (y & mask) * NOISE_SIZE
                for (let x = 0; x < w; ++x)
                {
                    const i = (y * w + x) * 4
                    const a = source[i + 3]
                    const a8 = Math.min(255, Math.round(a * 255))
                    if (a8 <= 0)
                        continue
                    const n = (row + (x & mask)) * 3
                    const k = a * 255, back = 255 / a8
                    // the clamped array rounds the stored value and floors it at 0
                    out[i] = Math.min(a8, Math.round(source[i] * k + noise[n])) * back
                    out[i + 1] = Math.min(a8, Math.round(source[i + 1] * k + noise[n + 1])) * back
                    out[i + 2] = Math.min(a8, Math.round(source[i + 2] * k + noise[n + 2])) * back
                    out[i + 3] = a8
                }
            }
            target.putImageData(image, 0, 0)
        }
    }
})()

// HUD labels recur every frame. Retain their metrics as well as their pixels;
// measureText otherwise repeats font shaping even when the glow sprite exists.
// Game labels use the default kerning, spacing and font variant settings.
const GLOW_TEXT_METRICS = new Map()
if (document.fonts)
    document.fonts.addEventListener('loadingdone', () => GLOW_TEXT_METRICS.clear())

function measureGlowText(text, font = ctx.font, align = ctx.textAlign, baseline = ctx.textBaseline)
{
    const key = text + '|' + font + '|' + align + '|' + baseline + '|' + ctx.direction
    let metrics = GLOW_TEXT_METRICS.get(key)
    if (!metrics)
    {
        metrics = ctx.measureText(text)
        if (GLOW_TEXT_METRICS.size >= 128)
            GLOW_TEXT_METRICS.clear()
        GLOW_TEXT_METRICS.set(key, metrics)
    }
    return metrics
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

// Least recently used sprites are dropped past store.limit
function getGlowSprite(key, build, store = GLOW_SPRITES)
{
    const cache = store.cache
    let sprite = cache.get(key)
    if (sprite)
    {
        cache.delete(key)
        cache.set(key, sprite)
        return sprite
    }

    sprite = build()
    cache.set(key, sprite)
    if (cache.size > store.limit)
        cache.delete(cache.keys().next().value)
    return sprite
}

// Calls drawShape(...args) with the global ctx pointing at a new canvas whose
// transform maps the logical point (originX, originY) to (pad, pad). The
// caller's globalAlpha is baked in (each layer at alpha, as drawn directly).
// A smooth sprite (soft gradient fills) is painted by GRADIENT_DITHER.
function buildGlowSprite(widthPx, heightPx, pad, scaleX, scaleY, originX, originY, alpha, drawShape, args, smooth)
{
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, widthPx)
    canvas.height = Math.max(1, heightPx)
    paintGlowSprite(canvas, pad, scaleX, scaleY, originX, originY, alpha, drawShape, args, smooth)
    return canvas
}

// buildGlowSprite's painting, into a canvas already sized
function paintGlowSprite(canvas, pad, scaleX, scaleY, originX, originY, alpha, drawShape, args, smooth)
{
    const build = spriteCtx =>
    {
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
    }
    if (smooth)
        GRADIENT_DITHER.paint8(canvas, build, false)
    else
        build(canvas.getContext('2d'))
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
    const metrics = measureGlowText(text, font, align, baseline)
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

// HUD values that change (time, height, FPS, score) would build a sprite per
// string. They are drawn from glyph sprites instead: one per character and
// subpixel phase, in a cache of their own so a ticking counter never evicts
// other glow sprites. Neighbouring glyph glows add up by source-over rather
// than in one shadow, a near-identical result.
// A glyph sprite is a cell of a shared atlas page, so a new glyph creates no
// canvas: it is painted on one scratch canvas of exactly its own size (the
// raster of a sprite canvas) and copied 1:1 into the page. A full page starts
// the next one; past maxPages the oldest page and its cells are dropped.
const GLYPH_SPRITES =
{
    limit: 512,
    // Glyph origins snap across to 1/phases of a canvas px
    phases: 4,
    cache: new Map(),
    metrics: new Map(),
    pageSize: 1024,
    maxPages: 4,
    // Transparent px around every cell
    gap: 2,
    pages: [],
    scratch: null
}
if (document.fonts)
    document.fonts.addEventListener('loadingdone', () => GLYPH_SPRITES.metrics.clear())

// Advance and ink bounds of one character drawn left-aligned
function measureGlyph(ch, font, baseline)
{
    const key = ch + '|' + font + '|' + baseline
    let glyph = GLYPH_SPRITES.metrics.get(key)
    if (!glyph)
    {
        ctx.save()
        ctx.font = font
        ctx.textAlign = 'left'
        ctx.textBaseline = baseline
        const m = ctx.measureText(ch)
        ctx.restore()
        glyph = {ch, advance: m.width, left: m.actualBoundingBoxLeft, right: m.actualBoundingBoxRight,
            ascent: m.actualBoundingBoxAscent, descent: m.actualBoundingBoxDescent}
        glyph.ink = glyph.left + glyph.right > 0 && glyph.ascent + glyph.descent > 0
        if (GLYPH_SPRITES.metrics.size >= 1024)
            GLYPH_SPRITES.metrics.clear()
        GLYPH_SPRITES.metrics.set(key, glyph)
    }
    return glyph
}

// A width x height atlas cell {image, x, y, width, height} holding what
// paint(canvas) draws on a canvas of that size
function buildGlyphCell(width, height, paint)
{
    const store = GLYPH_SPRITES, gap = store.gap
    let page = store.pages[store.pages.length - 1]
    if (page && page.x + width + gap > store.pageSize)
    {
        page.x = gap
        page.y += page.row + gap
        page.row = 0
    }
    if (!page || page.y + height + gap > store.pageSize)
    {
        if (store.pages.length >= store.maxPages)
        {
            const oldest = store.pages.shift()
            for (const [key, cell] of store.cache)
                if (cell.image === oldest.canvas)
                    store.cache.delete(key)
        }
        const canvas = document.createElement('canvas')
        canvas.width = canvas.height = store.pageSize
        page = {canvas, context: canvas.getContext('2d'), x: gap, y: gap, row: 0}
        store.pages.push(page)
    }
    const scratch = store.scratch || (store.scratch = document.createElement('canvas'))
    scratch.width = width
    scratch.height = height
    paint(scratch)
    page.context.drawImage(scratch, page.x, page.y)
    const cell = {image: page.canvas, x: page.x, y: page.y, width, height}
    page.x += width + gap
    page.row = Math.max(page.row, height)
    return cell
}

// drawGlowText for a changing string: the same box (the string's left and top
// snap to whole canvas px as its sprite did), glyphs at their measured
// advances; textAlign left/start, center and right/end (left to right)
function drawGlowGlyphs(text, x, y, shadowColor, blur, stroke)
{
    const font = ctx.font, align = ctx.textAlign, baseline = ctx.textBaseline
    const fill = ctx.fillStyle, strokeStyle = ctx.strokeStyle, lineWidth = ctx.lineWidth
    const glyphs = Array.from(text, ch => measureGlyph(ch, font, baseline))
    if (!glyphs.length)
        return
    let width = 0, ascent = -Infinity
    for (const glyph of glyphs)
    {
        width += glyph.advance
        ascent = Math.max(ascent, glyph.ascent)
    }
    const start = align == 'center' ? x - width / 2 : align == 'right' || align == 'end' ? x - width : x

    const m = ctx.getTransform()
    const sx = glowSpriteScale(m.a), sy = glowSpriteScale(m.d)
    const pad = glowSpritePad(blur, stroke ? lineWidth : 0, sx)
    const store = GLYPH_SPRITES, q = store.phases
    // Canvas px of the string's sprite origin; inside it glyphs sit at the
    // sprite scale. The baseline keeps its exact phase (text rasterization
    // snaps it to a whole px), one or two per HUD row.
    const left = Math.round(m.a * (start - glyphs[0].left) + m.e)
    const baselineY = Math.round(m.d * (y - ascent) + m.f) + ascent * sy
    // Rounded: float noise from the row's height would key new sprites
    const iy = Math.floor(baselineY), phaseY = Math.round((baselineY - iy) * 1e6) / 1e6
    const alpha = ctx.globalAlpha
    const style = '|' + font + '|left|' + baseline + '|' + fill + '|' + (stroke ? strokeStyle + '|' + lineWidth : '') +
        '|' + shadowColor + '|' + blur + '|' + alpha + '|' + sx + '|' + sy + '|'

    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.globalAlpha = 1
    let originX = left + glyphs[0].left * sx
    for (const glyph of glyphs)
    {
        if (glyph.ink)
        {
            const snapped = Math.round(originX * q) / q
            const ix = Math.floor(snapped), phaseX = snapped - ix
            // Canvas px from the sprite's top left to the glyph origin, less the phase
            const offsetX = pad + Math.ceil(glyph.left * sx), offsetY = pad + Math.ceil(glyph.ascent * sy)
            const cell = getGlowSprite('glyph|' + glyph.ch + style + phaseX + '|' + phaseY, () =>
                buildGlyphCell(Math.min(store.pageSize - store.gap * 2, Math.ceil((glyph.left + glyph.right) * sx) + 1 + pad * 2),
                    Math.min(store.pageSize - store.gap * 2, Math.ceil((glyph.ascent + glyph.descent) * sy) + 1 + pad * 2),
                    canvas => paintGlowSprite(canvas, 0, sx, sy, -(offsetX + phaseX) / sx, -(offsetY + phaseY) / sy, alpha, () =>
                {
                    ctx.font = font
                    ctx.textAlign = 'left'
                    ctx.textBaseline = baseline
                    ctx.fillStyle = fill
                    ctx.strokeStyle = strokeStyle
                    ctx.lineWidth = lineWidth
                    ctx.shadowColor = shadowColor
                    ctx.shadowBlur = blur
                    if (stroke)
                        ctx.strokeText(glyph.ch, 0, 0)
                    ctx.fillText(glyph.ch, 0, 0)
                })), store)
            ctx.drawImage(cell.image, cell.x, cell.y, cell.width, cell.height,
                ix - offsetX, iy - offsetY, cell.width, cell.height)
        }
        originX += glyph.advance * sx
    }
    ctx.restore()
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
