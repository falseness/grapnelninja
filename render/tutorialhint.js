// First-run control hint over the play field (tutorial concept B): an
// outlined neon-tube main word, 'TO GRAPPLE' and the green score line on a
// soft dark vignette. Grapple Over shows 'CLIMB TO THE TOP' instead of the
// score line, over a legend of small drawings of its green (bounce) and
// yellow (drag) obstacles and its purple no-grapple zones; the drawings are
// sprite pixels only, not world objects. The glow is baked once into an
// offscreen sprite in device pixels; draw() only blits it, so a frame does no
// blur work.
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
    // Grapple Over legend icon/label boxes in sprite pixels (last build)
    legendBoxes: [],

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
        return [I18N.language, version, isTouchFirstDevice() ? 'touch' : 'mouse',
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
        this.legendBoxes = []
        c.setTransform(1, 0, 0, 1, 0, 0)
        c.clearRect(0, 0, sprite.width, sprite.height)

        const W = sprite.width, H = sprite.height, u = H / 100
        const cx = W / 2, cy = H / 2
        const font = STYLE.ui.fontFamily
        const colors = STYLE.colors.tutorial
        const hold = I18N.t(isTouchFirstDevice() ? 'tutorial.hold.touch' : 'tutorial.hold.desktop')
        const grapple = I18N.t('tutorial.grapple')
        const climb = version === 'grapple_over'
        const objective = climb ? I18N.t('tutorial.climb') : I18N.t('tutorial.right') + '  →'

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

        const s3 = fit(objective, 3.6 * u, W * 0.6, 'normal', 0.25)
        setFont(s3, 'normal', 0.25)
        neonText(objective, cy + 13 * u, s3, colors.score, colors.scoreCore, 0.6)

        this.lines = [hold, grapple, objective]
        if (climb)
            this.lines.push(...this.buildLegend(c, cx, cy + 20.5 * u, u, W, font))
        this.spriteKey = key
        ++this.buildCount
    },

    // One row centred at (cx, y): a green block '= BOUNCE', a wide yellow
    // strip '= LOSE SPEED', then a purple patch '= NO GRAPPLE', in the game's
    // colours. Returns the three label strings
    buildLegend(c, cx, y, u, W, font)
    {
        const items = [{label: I18N.t('tutorial.legend.bounce'), w: 3.2, h: 3.2, draw: this.drawBounce},
                       {label: I18N.t('tutorial.legend.drag'), w: 6.4, h: 2, draw: this.drawDrag},
                       {label: I18N.t('tutorial.legend.noGrapple'), w: 4.4, h: 2.8, draw: this.drawNoGrapple}]
        const gap = 1.2, spacing = 4
        let size = 2.6 * u
        const measure = () =>
        {
            c.font = 'normal ' + size + 'px ' + font
            c.letterSpacing = size * 0.12 + 'px'
            const k = size / (2.6 * u)
            let total = 0
            for (const item of items)
            {
                item.text = '= ' + item.label
                item.tw = c.measureText(item.text).width
                total += item.w * u * k + gap * u * k + item.tw
            }
            return total + (items.length - 1) * spacing * u * k
        }
        const total = measure()
        if (total > W * 0.8)
        {
            size *= W * 0.8 / total
            measure()
        }
        const k = size / (2.6 * u)
        let x = cx - measure() / 2
        c.textAlign = 'left'
        for (const item of items)
        {
            const w = item.w * u * k, h = item.h * u * k
            item.draw(c, x, y - h / 2, w, h, u * k)
            x += w + gap * u * k
            c.shadowColor = 'rgba(0, 0, 0, 0.8)'
            c.shadowBlur = size * 0.3
            c.fillStyle = STYLE.colors.tutorial.legendText
            c.fillText(item.text, x, y)
            c.shadowBlur = 0
            this.legendBoxes.push({label: item.label, icon: {x: x - w - gap * u * k, y: y - h / 2, w, h},
                                   text: {x, width: item.tw}})
            x += item.tw + spacing * u * k
        }
        c.textAlign = 'center'
        c.letterSpacing = '0px'
        return items.map(item => item.label)
    },

    // Bounce block: dark green body, bright green neon edge and lip
    drawBounce(c, x, y, w, h, s)
    {
        const detail = GRAPPLE_OVER_ROLE_DETAIL.bounce
        const body = c.createLinearGradient(x, y, x, y + h)
        body.addColorStop(0, detail.baseLight)
        body.addColorStop(1, detail.baseDark)
        c.fillStyle = body
        c.fillRect(x, y, w, h)
        c.shadowColor = STYLE.colors.cube.greenStroke
        c.shadowBlur = s * 1.2
        c.strokeStyle = STYLE.colors.cube.greenStroke
        c.lineWidth = s * 0.3
        c.strokeRect(x, y, w, h)
        c.shadowBlur = 0
        c.fillStyle = detail.lip
        c.fillRect(x, y, w, s * 0.4)
    },

    // Drag zone: translucent amber strip with its edge and drifting motes
    drawDrag(c, x, y, w, h, s)
    {
        const drag = STYLE.colors.drag
        c.fillStyle = drag.fill
        c.fillRect(x, y, w, h)
        c.shadowColor = drag.stroke
        c.shadowBlur = s * 1.2
        c.strokeStyle = drag.stroke
        c.lineWidth = s * 0.25
        c.strokeRect(x, y, w, h)
        c.shadowBlur = 0
        c.fillStyle = GRAPPLE_OVER_ROLE_DETAIL.drag.particle
        for (const [fx, fy] of [[0.15, 0.6], [0.35, 0.3], [0.55, 0.7], [0.75, 0.35], [0.9, 0.62]])
        {
            c.beginPath()
            c.arc(x + w * fx, y + h * fy, s * 0.22, 0, Math.PI * 2)
            c.fill()
        }
    },

    // No-grapple zone: the world's translucent violet wash and thin edge
    drawNoGrapple(c, x, y, w, h, s)
    {
        const colors = STYLE.colors.noGrapple
        c.fillStyle = colors.fill
        c.fillRect(x, y, w, h)
        c.strokeStyle = colors.stroke
        c.lineWidth = s * 0.25
        c.strokeRect(x, y, w, h)
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
