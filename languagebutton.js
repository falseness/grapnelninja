// Language toggle in the top-left corner of the menu: a globe and the
// current language's name in that language. A click switches to the next
// language at once, re-lays out the screens and saves the choice. Drawn and
// hit-tested in logical canvas units.
const LANGUAGE_BUTTON =
{
    sizeRatio: 0.072,
    marginRatio: 0.012,

    rect()
    {
        const margin = this.marginRatio * height
        const size = Math.max(this.sizeRatio * height, minTouchSize())
        ctx.save()
        ctx.font = getArcadeFont(this.fontSize(size))
        const textWidth = ctx.measureText(I18N.t('language.name')).width
        ctx.restore()
        return {x: margin, y: margin, width: size * 1.1 + textWidth + size * 0.3, height: size}
    },
    fontSize(size)
    {
        return size * 0.5
    },
    // coords: logical canvas coordinates; true when the click was taken
    click(coords)
    {
        if (!menu.visible || menu.gamePaused)
            return false
        const r = this.rect()
        if (r.x < coords.x && coords.x < r.x + r.width &&
            r.y < coords.y && coords.y < r.y + r.height)
        {
            setLanguage(I18N.next())
            return true
        }
        return false
    },
    draw()
    {
        const r = this.rect()
        const color = STYLE.colors.ui.hudGlow

        ctx.save()
        ctx.strokeStyle = color
        ctx.fillStyle = color
        ctx.lineWidth = STYLE.ui.buttonLineWidth
        strokeNeonRect(r.x, r.y, r.width, r.height, color, STYLE.ui.neonUnit.small)
        ctx.shadowColor = color
        ctx.shadowBlur = STYLE.ui.buttonShadowBlur
        LAYOUT_PROBE.rect('button', 'language', r.x, r.y, r.width, r.height)

        // Globe: outline, meridian and two parallels
        const cx = r.x + r.height * 0.55
        const cy = r.y + r.height / 2
        const radius = r.height * 0.3
        ctx.lineWidth = Math.max(STYLE.ui.buttonLineWidth, 0.05 * r.height)
        ctx.beginPath()
        ctx.arc(cx, cy, radius, 0, Math.PI * 2)
        ctx.moveTo(cx + radius * 0.45, cy)
        ctx.ellipse(cx, cy, radius * 0.45, radius, 0, 0, Math.PI * 2)
        ctx.moveTo(cx - radius, cy)
        ctx.lineTo(cx + radius, cy)
        for (const dy of [-0.5, 0.5])
        {
            const half = radius * Math.sqrt(1 - dy * dy)
            ctx.moveTo(cx - half, cy + dy * radius)
            ctx.lineTo(cx + half, cy + dy * radius)
        }
        ctx.stroke()

        ctx.shadowBlur = STYLE.ui.textShadowBlur
        ctx.font = getArcadeFont(this.fontSize(r.height))
        ctx.textAlign = 'start'
        ctx.textBaseline = 'middle'
        ctx.fillText(I18N.t('language.name'), r.x + r.height * 1.1, cy)
        LAYOUT_PROBE.text(I18N.t('language.name'), r.x + r.height * 1.1, cy)
        ctx.restore()
    },
    // Bloom pass: the frame as one plain line
    drawGlow()
    {
        const r = this.rect()
        ctx.beginPath()
        ctx.rect(r.x, r.y, r.width, r.height)
        strokeNeonPath(STYLE.colors.ui.hudGlow, 1, STYLE.ui.neonUnit.small)
    }
}
