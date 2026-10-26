// Grapple Over long-fall reaction (concept big-fall-message-v2): the phrase
// of LONG_FALL.event in bold italic warm white with a lavender glow and a
// dark shadow, tilted and placed off-centre in screen space, fading out over
// 6000 ms of active game time. Each event draws its anchor and tilt once
// from a reaction-only random source; a re-layout (resize) keeps both and
// only refits the size and the safe-area position. The text and its glow
// are baked into a sprite per layout; a frame only blits it rotated.
const FALL_MESSAGE = {
    durationMs: 6000,
    // Normalized canvas anchors, all off centre
    anchors: Object.freeze([[0.25, 0.30], [0.75, 0.30], [0.25, 0.50], [0.75, 0.50], [0.25, 0.70], [0.75, 0.70]]),
    maxAngle: 15,
    marginCss: 16,
    // Text size from the canvas CSS height, never below minSizeCss
    sizeRatio: 0.095,
    minSizeCss: 12,
    shrink: 0.92,
    font: '"Arial Black", "Arial Bold", Arial, sans-serif',
    // Synthetic italic: x shifts by -slant * y, so every font slants the same
    slant: 0.2,
    colors: {text: '#fff6e6', glow: 'rgba(196, 168, 255, 0.9)', shadow: 'rgba(8, 4, 24, 0.85)'},
    // The LONG_FALL event being shown (kept after expiry so it is not shown twice)
    event: null,
    anchorIndex: 0,
    angle: 0,
    elapsedMs: 0,
    expired: true,
    layout: null,
    layoutKey: '',
    sprite: null,
    layoutCount: 0,
    random: null,

    nextRandom()
    {
        return this.random ? this.random() : crypto.getRandomValues(new Uint32Array(1))[0] / 4294967296
    },
    // Test hook: a function returning [0, 1], or null for the default source
    setRandom(source)
    {
        this.random = source || null
    },

    // Picks up a new event (it replaces the current message); a world without
    // one (restart, reload, mode switch) shows nothing. True for a new message.
    sync()
    {
        const event = typeof version != 'undefined' && version === 'grapple_over' ? LONG_FALL.event : null
        if (event === this.event)
            return false
        this.event = event
        this.layout = null
        this.layoutKey = ''
        if (!event)
        {
            this.expired = true
            return false
        }
        const n = this.anchors.length
        this.anchorIndex = Math.min(n - 1, Math.max(0, Math.floor(this.nextRandom() * n) || 0))
        const r = Math.min(1, Math.max(0, this.nextRandom() || 0))
        this.angle = -this.maxAngle + 2 * this.maxAngle * r
        this.elapsedMs = 0
        this.expired = false
        return true
    },

    // Active game time only (the game loop's simulated steps): pauses, ads,
    // hidden or rotated views freeze the fade
    advance(ms)
    {
        if (this.sync() || this.expired)
            return
        this.elapsedMs += ms
        if (this.elapsedMs >= this.durationMs - 1e-9)
        {
            this.elapsedMs = this.durationMs
            this.expired = true
        }
    },

    opacity(elapsedMs = this.elapsedMs)
    {
        const t = Math.max(0, 1 - elapsedMs / this.durationMs)
        return t * t
    },

    // Completion: the message and its event are gone
    clear()
    {
        LONG_FALL.clearEvent()
        this.event = null
        this.expired = true
        this.layout = null
        this.layoutKey = ''
    },

    visible()
    {
        return !this.expired && this.event !== null && this.event === LONG_FALL.event &&
            !menu.gamePaused && !floors[0].climbStats?.completed
    },

    // Boxes (CSS px of the canvas) of the HUD and controls this frame would
    // draw, from LAYOUT_PROBE over a scratch draw in the game transform.
    // Text grows by two glyphs (live values) and every box by a pad.
    reservedRects(target)
    {
        const scratch = this.scratch || (this.scratch = document.createElement('canvas').getContext('2d'))
        const mainCtx = ctx, boxes = LAYOUT_PROBE.boxes
        scratch.setTransform(target.width / width, 0, 0, target.height / height, 0, 0)
        scratch.scale(scale[version], scale[version])
        LAYOUT_PROBE.boxes = []
        ctx = scratch
        let found
        try
        {
            const gameState = visualEffects.getGameState()
            visualEffects.ui.draw(gameState)
            visualEffects.ui.drawFpsCounter(gameState)
            found = LAYOUT_PROBE.boxes
        }
        finally
        {
            ctx = mainCtx
            LAYOUT_PROBE.boxes = boxes
        }
        return found.map(b =>
        {
            const pad = b.kind === 'text' ? Math.max(8, b.fontPx * 0.6) : 8
            const grow = b.kind === 'text' ? 2 * b.fontPx : 0
            return {kind: b.kind, name: b.name, x: b.x - pad, y: b.y - pad,
                    width: b.width + grow + 2 * pad, height: b.height + 2 * pad}
        })
    },

    // Unrotated ink box of text at size (CSS px, around the drawing origin)
    // from the canvas's own glyph metrics, slanted, plus the glow and shadow
    measure(c, text, size)
    {
        c.font = '900 ' + size + 'px ' + this.font
        c.letterSpacing = size * 0.02 + 'px'
        c.textAlign = 'center'
        c.textBaseline = 'alphabetic'
        const m = c.measureText(text)
        const glow = size * 0.3
        return {left: -m.actualBoundingBoxLeft - this.slant * m.actualBoundingBoxDescent - glow,
                right: m.actualBoundingBoxRight + this.slant * m.actualBoundingBoxAscent + glow,
                top: -m.actualBoundingBoxAscent - glow, bottom: m.actualBoundingBoxDescent + glow + size * 0.08}
    },

    // Fits text with the anchor and angle on target (a canvas): the preferred
    // anchor, then the others, at each size before a smaller one. A rotated
    // box past a margin moves inward (safe-area correction); an anchor fails
    // only if that box meets a HUD/control reservation or cannot fit.
    layoutFor(text, anchorIndex, angle, target = canvas, reserved = null)
    {
        const css = getCanvasCssRect()
        const W = css.width, H = css.height, margin = this.marginCss, k = target.width / W
        reserved = reserved || this.reservedRects(target)
        const c = this.measureCtx || (this.measureCtx = document.createElement('canvas').getContext('2d'))
        const rad = angle * Math.PI / 180, cos = Math.cos(rad), sin = Math.sin(rad)
        const order = [anchorIndex, ...this.anchors.map((a, i) => i).filter(i => i !== anchorIndex)]
        const hits = (b, r) => b.left < r.x + r.width && r.x < b.right && b.top < r.y + r.height && r.y < b.bottom
        let size = Math.max(this.minSizeCss, H * this.sizeRatio), attempts = 0
        for (;;)
        {
            const box = this.measure(c, text, size)
            // Whole device px, so the baked sprite is exactly this box
            box.right = box.left + Math.ceil((box.right - box.left) * k) / k
            box.bottom = box.top + Math.ceil((box.bottom - box.top) * k) / k
            const corners = [[box.left, box.top], [box.right, box.top], [box.right, box.bottom], [box.left, box.bottom]]
                .map(([x, y]) => [x * cos - y * sin, x * sin + y * cos])
            const xs = corners.map(p => p[0]), ys = corners.map(p => p[1])
            const ext = {left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys)}
            const fits = ext.right - ext.left <= W - 2 * margin && ext.bottom - ext.top <= H - 2 * margin
            const smallest = size <= this.minSizeCss
            for (const i of order)
            {
                ++attempts
                const [ax, ay] = this.anchors[i]
                let x = ax * W, y = ay * H
                x = Math.min(Math.max(x, margin - ext.left), W - margin - ext.right)
                y = Math.min(Math.max(y, margin - ext.top), H - margin - ext.bottom)
                const bounds = {left: x + ext.left, right: x + ext.right, top: y + ext.top, bottom: y + ext.bottom}
                const clear = !reserved.some(r => hits(bounds, r))
                if ((fits && clear) || (smallest && i === order[order.length - 1]))
                    return {text, size, angle, preferredAnchor: anchorIndex, anchorIndex: i,
                            anchor: [ax * W, ay * H], x, y, box, corners: corners.map(([cx, cy]) => [x + cx, y + cy]),
                            bounds, viewport: {width: W, height: H, margin}, reserved, attempts,
                            fitted: fits && clear, shifted: x !== ax * W || y !== ay * H}
            }
            size = Math.max(this.minSizeCss, size * this.shrink)
        }
    },

    // The sprite holds the unrotated box in device px: two lavender glow
    // passes, then the warm-white face over a dark drop shadow
    bake(layout, k)
    {
        const sprite = this.sprite || (this.sprite = document.createElement('canvas'))
        const box = layout.box
        sprite.width = Math.round((box.right - box.left) * k)
        sprite.height = Math.round((box.bottom - box.top) * k)
        const c = sprite.getContext('2d')
        c.setTransform(1, 0, 0, 1, 0, 0)
        c.clearRect(0, 0, sprite.width, sprite.height)
        c.setTransform(k, 0, 0, k, -box.left * k, -box.top * k)
        c.transform(1, 0, -this.slant, 1, 0, 0)
        const size = layout.size
        this.measure(c, layout.text, size)
        c.fillStyle = this.colors.text
        c.shadowColor = this.colors.glow
        for (const blur of [0.22, 0.08])
        {
            c.shadowBlur = size * blur * k
            c.fillText(layout.text, 0, 0)
        }
        c.shadowColor = this.colors.shadow
        c.shadowBlur = size * 0.06 * k
        c.shadowOffsetX = size * 0.03 * k
        c.shadowOffsetY = size * 0.05 * k
        c.fillText(layout.text, 0, 0)
    },

    // One frame on context (a canvas the size of the game canvas), in screen space
    draw(context)
    {
        this.sync()
        if (!this.visible())
            return
        const target = context.canvas, css = getCanvasCssRect()
        const key = [target.width, target.height, css.width, css.height, this.event.message].join('|')
        if (key !== this.layoutKey)
        {
            this.layout = this.layoutFor(this.event.message, this.anchorIndex, this.angle, target)
            this.layoutKey = key
            this.bake(this.layout, target.width / css.width)
            ++this.layoutCount
        }
        const layout = this.layout, kx = target.width / css.width, ky = target.height / css.height
        context.save()
        context.setTransform(kx, 0, 0, ky, 0, 0)
        context.globalAlpha = this.opacity()
        context.translate(layout.x, layout.y)
        context.rotate(layout.angle * Math.PI / 180)
        context.drawImage(this.sprite, layout.box.left, layout.box.top,
            layout.box.right - layout.box.left, layout.box.bottom - layout.box.top)
        context.restore()
    }
}
