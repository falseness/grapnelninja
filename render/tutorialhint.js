// First-run control hint over the play field (tutorial concept B): an
// outlined neon-tube main word, 'TO GRAPPLE' and the green score line on a
// soft dark vignette. The glow is baked once into an offscreen sprite in
// device pixels; draw() only blits it, so a frame does no blur work.
const TUTORIAL_HINT = {
    visible: false,
    // Fade (0..1) and seconds of active game time since the first press
    alpha: 1,
    time: 0,
    fadeSeconds: 2.5,
    // The first press of this page load started the fade
    pressed: false,
    // The fade has finished: the hint stays hidden for this page load
    done: false,
    sprite: null,
    spriteKey: '',
    // Strings baked into the current sprite, and how many sprites were built
    lines: null,
    buildCount: 0,
    // Momentum legend row boxes [x, y, w, h] in canvas backing px (at t 0)
    legendBoxes: null,

    // Every run start until the first press shows the hint at full strength
    runStarted()
    {
        if (this.pressed)
            return
        this.visible = true
        this.alpha = 1
        this.time = 0
    },

    // The first grapnel throw starts the fade; the throw itself is unaffected
    press(mode)
    {
        if (this.pressed || !this.visible)
            return
        this.pressed = true
        PLATFORM.startup('tutorial_dismissed', mode)
    },

    // Active game time only: the game loop calls this for simulated steps,
    // so pauses, ads, the death screen and hidden or rotated views freeze it
    advance(ms)
    {
        if (!this.pressed || this.done)
            return
        this.time = Math.min(this.fadeSeconds, this.time + ms / 1000)
        this.alpha = Math.pow(1 - this.time / this.fadeSeconds, 1.6)
        // A float sum of whole physics steps can land just under the fade length
        if (this.time >= this.fadeSeconds - 1e-9)
        {
            this.time = this.fadeSeconds
            this.alpha = 0
            this.visible = false
            this.done = true
        }
    },

    cacheKey(canvas)
    {
        const cssWidth = parseFloat(canvas.style.width) || canvas.width
        const dpr = Math.round(canvas.width / cssWidth * 1000) / 1000
        return [I18N.language, isTouchFirstDevice() ? 'touch' : 'mouse',
                canvas.width + 'x' + canvas.height, dpr, version].join('|')
    },

    invalidate()
    {
        this.spriteKey = ''
    },

    // Builds the sprite for the canvas's current size, language, input and
    // mode; worldScale is backing px per world unit of the game transform
    build(canvas, key, worldScale)
    {
        if (!this.sprite)
            this.sprite = document.createElement('canvas')
        const sprite = this.sprite
        sprite.width = canvas.width
        sprite.height = canvas.height
        const c = sprite.getContext('2d')
        c.setTransform(1, 0, 0, 1, 0, 0)
        c.clearRect(0, 0, sprite.width, sprite.height)

        const W = sprite.width, H = sprite.height, u = H / 100
        const cx = W / 2, cy = H / 2
        const font = STYLE.ui.fontFamily
        const colors = STYLE.colors.tutorial
        const hold = I18N.t(isTouchFirstDevice() ? 'tutorial.hold.touch' : 'tutorial.hold.desktop')
        const grapple = I18N.t('tutorial.grapple')
        const right = I18N.t('tutorial.right') + '  →'

        const vignette = c.createRadialGradient(cx, cy, 0, cx, cy, Math.max(W, H) * 0.45)
        vignette.addColorStop(0, colors.vignette)
        vignette.addColorStop(1, colors.vignetteEdge)
        c.fillStyle = vignette
        c.fillRect(0, 0, W, H)

        c.textAlign = 'center'
        c.textBaseline = 'middle'
        c.lineJoin = 'round'
        // Shrinks size so text (with its letter spacing) fits maxWidth
        const fit = (text, size, maxWidth, weight, spacingRatio) =>
        {
            c.font = weight + ' ' + size + 'px ' + font
            const width = c.measureText(text).width + text.length * size * spacingRatio
            return width > maxWidth ? size * maxWidth / width : size
        }
        const setFont = (size, weight, spacingRatio) =>
        {
            c.font = weight + ' ' + size + 'px ' + font
            c.letterSpacing = size * spacingRatio + 'px'
        }
        const neonText = (text, y, size, color, core, glow, x = cx) =>
        {
            for (const [blur, alpha] of [[0.9, 0.35], [0.35, 0.7], [0.12, 1]])
            {
                c.shadowColor = color
                c.shadowBlur = size * blur * glow
                c.globalAlpha = alpha
                c.fillStyle = color
                c.fillText(text, x, y)
            }
            c.shadowBlur = 0
            c.globalAlpha = 1
            c.fillStyle = core
            c.fillText(text, x, y)
        }

        // Main word: three stroke passes of an outlined neon tube
        const s1 = fit(hold, 13 * u, W * 0.5, 'bold', 0.12)
        setFont(s1, 'bold', 0.12)
        for (const [width, blur, alpha, color] of [[0.09, 0.6, 0.5, colors.glow],
                                                   [0.06, 0.2, 0.9, colors.glow],
                                                   [0.022, 0, 1, colors.core]])
        {
            c.lineWidth = s1 * width
            c.shadowColor = colors.glow
            c.shadowBlur = s1 * blur
            c.globalAlpha = alpha
            c.strokeStyle = color
            c.strokeText(hold, cx, cy - 3 * u)
        }
        c.shadowBlur = 0

        const s2 = fit(grapple, 4.6 * u, W * 0.8, 'normal', 0.18)
        setFont(s2, 'normal', 0.18)
        neonText(grapple, cy + 7 * u, s2, colors.glow, colors.grappleCore, 0.7)

        const s3 = fit(right, 3.6 * u, W * 0.6, 'normal', 0.25)
        setFont(s3, 'normal', 0.25)
        neonText(right, cy + 13 * u, s3, colors.score, colors.scoreCore, 0.6)

        this.spriteKey = key
        this.lines = [hold, grapple, right]
        this.legendBoxes = null
        if (version == 'momentum')
        {
            const rows = this.drawMomentumLegend(c, cy + 21 * u, 6.4 * u, 4 * u, W * 0.7, worldScale || 1, neonText)
            this.lines.push(...rows)
        }
        ++this.buildCount
    },

    // Two rows under the score line: 'green ×5 = +heart' and
    // 'blue = −heart', a table centred on the view (icon, count, '=' and
    // result columns line up). The icons are a real MomentumGreen /
    // MomentumBlue box and scoreText.drawHeart, drawn with the global ctx
    // pointed at the sprite in the game's world scale. Returns the row strings.
    drawMomentumLegend(c, y, rowStep, size, maxWidth, worldScale, neonText)
    {
        const colors = STYLE.colors.tutorial
        const spacing = 0.12
        const rows = [{piece: MomentumGreen, count: '\u00d75', sign: '+'},
                      {piece: MomentumBlue, count: '', sign: '\u2212'}]
        const measure = text =>
        {
            c.font = 'bold ' + size + 'px ' + STYLE.ui.fontFamily
            c.letterSpacing = size * spacing + 'px'
            return text ? c.measureText(text).width : 0
        }
        // Column widths in units of size, shrunk to fit maxWidth
        const layout = () =>
        {
            const gap = size * 0.45
            const icon = {w: size * 1.9, h: size * 0.8}
            const count = Math.max(...rows.map(row => measure(row.count)))
            const equals = measure('=')
            const sign = Math.max(...rows.map(row => measure(row.sign)))
            const heart = size * 1.05
            const width = icon.w + gap + count + gap + equals + gap + sign + size * 0.15 + heart
            return {gap, icon, count, equals, sign, heart, width}
        }
        let L = layout()
        if (L.width > maxWidth)
        {
            size *= maxWidth / L.width
            L = layout()
        }
        const left = c.canvas.width / 2 - L.width / 2
        const columns = {
            icon: left,
            count: left + L.icon.w + L.gap,
            equals: left + L.icon.w + L.gap + L.count + L.gap,
            sign: left + L.icon.w + L.gap + L.count + L.gap + L.equals + L.gap
        }
        columns.heart = columns.sign + L.sign + size * 0.15

        const mainCtx = ctx
        const strings = []
        this.legendBoxes = []
        c.textAlign = 'left'
        try
        {
            ctx = c
            rows.forEach((row, i) =>
            {
                const rowY = y + i * rowStep
                // Game pieces in world units: (screen.x, screen.y) is added back
                c.setTransform(worldScale, 0, 0, worldScale, 0, 0)
                const piece = row.piece.box(columns.icon / worldScale - screen.x,
                    (rowY - L.icon.h / 2) / worldScale - screen.y, L.icon.w / worldScale, L.icon.h / worldScale)
                piece.draw()
                scoreText.drawHeart(columns.heart / worldScale, (rowY - L.heart / 2) / worldScale, L.heart / worldScale)
                c.setTransform(1, 0, 0, 1, 0, 0)

                measure('')
                if (row.count)
                    neonText(row.count, rowY, size, colors.glow, colors.core, 0.6, columns.count)
                neonText('=', rowY, size, colors.glow, colors.core, 0.6, columns.equals)
                neonText(row.sign, rowY, size, STYLE.momentum.heartStroke, colors.core, 0.6,
                    columns.sign + (L.sign - measure(row.sign)) / 2)
                strings.push([row.count, '=', row.sign].filter(Boolean).join(' '))
                const top = rowY - Math.max(L.heart, size) / 2
                this.legendBoxes.push([left, top, L.width, Math.max(L.heart, size)])
            })
        }
        finally
        {
            ctx = mainCtx
            c.setTransform(1, 0, 0, 1, 0, 0)
            c.textAlign = 'center'
            c.letterSpacing = '0px'
        }
        return strings
    },

    // Blits the sprite over the whole canvas, drifting up 1.2% of the view
    // height per second of t
    draw(context, alpha, t)
    {
        const canvas = context.canvas
        const key = this.cacheKey(canvas)
        if (key !== this.spriteKey)
            this.build(canvas, key, context.getTransform().a)

        context.save()
        context.setTransform(1, 0, 0, 1, 0, 0)
        context.globalAlpha = alpha
        context.drawImage(this.sprite, 0, -0.012 * canvas.height * t)
        context.restore()
    }
}
