// First-run control hint over the play field (tutorial concept B): an
// outlined neon-tube main word, 'TO GRAPPLE' and the green score line on a
// soft dark vignette. The glow is baked once into an offscreen sprite in
// device pixels; draw() only blits it, so a frame does no blur work.
const TUTORIAL_HINT = {
    visible: false,
    // Set by the tutorial lifecycle: fade (0..1) and seconds since the drift began
    alpha: 1,
    time: 0,
    sprite: null,
    spriteKey: '',
    // Strings baked into the current sprite, and how many sprites were built
    lines: null,
    buildCount: 0,

    cacheKey(canvas)
    {
        const cssWidth = parseFloat(canvas.style.width) || canvas.width
        const dpr = Math.round(canvas.width / cssWidth * 1000) / 1000
        return [I18N.language, isTouchFirstDevice() ? 'touch' : 'mouse',
                canvas.width + 'x' + canvas.height, dpr].join('|')
    },

    invalidate()
    {
        this.spriteKey = ''
    },

    // Builds the sprite for the canvas's current size, language and input
    build(canvas, key)
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
        const neonText = (text, y, size, color, core, glow) =>
        {
            for (const [blur, alpha] of [[0.9, 0.35], [0.35, 0.7], [0.12, 1]])
            {
                c.shadowColor = color
                c.shadowBlur = size * blur * glow
                c.globalAlpha = alpha
                c.fillStyle = color
                c.fillText(text, cx, y)
            }
            c.shadowBlur = 0
            c.globalAlpha = 1
            c.fillStyle = core
            c.fillText(text, cx, y)
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
        ++this.buildCount
    },

    // Blits the sprite over the whole canvas, drifting up 1.2% of the view
    // height per second of t
    draw(context, alpha, t)
    {
        const canvas = context.canvas
        const key = this.cacheKey(canvas)
        if (key !== this.spriteKey)
            this.build(canvas, key)

        context.save()
        context.setTransform(1, 0, 0, 1, 0, 0)
        context.globalAlpha = alpha
        context.drawImage(this.sprite, 0, -0.012 * canvas.height * t)
        context.restore()
    }
}
