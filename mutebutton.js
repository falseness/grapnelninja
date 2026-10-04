// Speaker toggle for the 'user' mute source. Shown in the top-right corner of
// the menu and, during a run and on the pause screen, right below the HUD menu
// button. Drawn and hit-tested in logical (unscaled) canvas units; the hit
// area is never smaller than minCssPx CSS pixels.
const MUTE_BUTTON =
{
    muted: false,
    minCssPx: 44,
    sizeRatio: 0.072,
    marginRatio: 0.012,

    // Boot: apply the saved setting without a save or a click sound
    restore(muted)
    {
        this.muted = !!muted
        AUDIO.setMute('user', this.muted)
    },
    toggle()
    {
        AUDIO.play('click')
        this.muted = !this.muted
        AUDIO.setMute('user', this.muted)
        PROGRESS.setMuted(this.muted)
        PROGRESS.save()
    },
    // Logical units per CSS pixel turn the CSS floor into a logical size
    minSize()
    {
        const cssHeight = canvas.getBoundingClientRect().height
        return cssHeight > 0 ? this.minCssPx * height / cssHeight : 0
    },
    rect(where)
    {
        const margin = this.marginRatio * height
        if (where != 'menu' && menu.button)
        {
            const s = scale[version]
            const b = menu.button.background
            const size = Math.max(b.width * s, this.minSize())
            return {
                x: Math.min((b.x + b.width / 2) * s - size / 2, width - margin - size),
                y: (b.y + b.height) * s + margin,
                width: size,
                height: size
            }
        }
        const size = Math.max(this.sizeRatio * height, this.minSize())
        return {x: width - margin - size, y: margin, width: size, height: size}
    },
    // The screen the player sees now: 'menu', 'pause' or 'hud'
    current()
    {
        if (menu.visible)
            return 'menu'
        return menu.gamePaused ? 'pause' : 'hud'
    },
    // coords: logical canvas coordinates; true when the click was taken
    click(coords)
    {
        const where = this.current()
        if (where != 'menu' && !menu.button)
            return false
        const r = this.rect(where)
        if (r.x < coords.x && coords.x < r.x + r.width &&
            r.y < coords.y && coords.y < r.y + r.height)
        {
            this.toggle()
            this.redraw(where)
            return true
        }
        return false
    },
    // Menu and pause screens are not redrawn every frame
    redraw(where)
    {
        if (where == 'menu')
            menu.draw()
        else if (where == 'pause')
        {
            draw()
            menu.drawPauseScreen()
        }
    },
    draw(where)
    {
        const r = this.rect(where)
        const color = STYLE.colors.ui.hudGlow

        ctx.save()
        ctx.strokeStyle = color
        ctx.fillStyle = color
        ctx.lineWidth = STYLE.ui.buttonLineWidth
        ctx.shadowColor = color
        ctx.shadowBlur = STYLE.ui.buttonShadowBlur
        ctx.strokeRect(r.x, r.y, r.width, r.height)

        // Speaker body
        const px = f => r.x + f * r.width
        const py = f => r.y + f * r.height
        ctx.beginPath()
        ctx.moveTo(px(0.2), py(0.4))
        ctx.lineTo(px(0.35), py(0.4))
        ctx.lineTo(px(0.55), py(0.22))
        ctx.lineTo(px(0.55), py(0.78))
        ctx.lineTo(px(0.35), py(0.6))
        ctx.lineTo(px(0.2), py(0.6))
        ctx.closePath()
        ctx.fill()

        ctx.lineWidth = Math.max(STYLE.ui.buttonLineWidth, 0.06 * r.height)
        ctx.lineCap = 'round'
        ctx.beginPath()
        if (this.muted)
        {
            ctx.moveTo(px(0.65), py(0.38))
            ctx.lineTo(px(0.85), py(0.62))
            ctx.moveTo(px(0.85), py(0.38))
            ctx.lineTo(px(0.65), py(0.62))
        }
        else
        {
            for (const radius of [0.13, 0.25])
            {
                ctx.moveTo(px(0.55) + radius * r.width * Math.cos(-Math.PI / 4),
                           py(0.5) + radius * r.height * Math.sin(-Math.PI / 4))
                ctx.arc(px(0.55), py(0.5), radius * r.width, -Math.PI / 4, Math.PI / 4)
            }
        }
        ctx.stroke()
        ctx.restore()
    }
}
