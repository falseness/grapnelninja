// Momentum one-time objects (greens and blues): the first ninja contact
// uses them up (use()); from then on they let the ninja and the grapnel
// through (a grapnel hooked on them is released, Grapnel.releaseElement) and fade out linearly over GAMEPLAY.momentumFadeMs of render clock
// (performance.now()). Their floor drops them once the fade is over
// (Floor.moveElements reads `faded`). Trampoline geometry, own colours.
class MomentumOneTime extends Trampoline
{
    constructor(object, stroke, fill, badVersionFill)
    {
        super(object)
        this.stroke = stroke
        this.fill = fill
        this.badVersionFill = badVersionFill
        this.fadeStartMs = null
        this.passThrough = false
        this.faded = false
    }
    // Axis-aligned w x h box points with the top-left corner at (x, y)
    static boxObject(x, y, w, h)
    {
        return {x: x, y: y, points: [
            {x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}
        ]}
    }
    // Starts the fade; false if it was used already
    use()
    {
        if (this.passThrough)
            return false
        this.passThrough = true
        this.fadeStartMs = performance.now()
        // A used object no longer holds the grapnel
        if (grapnel)
            grapnel.releaseElement(this)
        return true
    }
    getAlpha(now)
    {
        if (this.fadeStartMs === null)
            return 1
        const t = ((now === undefined ? performance.now() : now) - this.fadeStartMs) / GAMEPLAY.momentumFadeMs
        return Math.max(0, Math.min(1, 1 - t))
    }
    move()
    {
        if (this.passThrough && this.getAlpha() <= 0)
            this.faded = true
    }
    // The grapnel cannot hook a used object
    getLines()
    {
        return this.passThrough ? [] : super.getLines()
    }
    drawExtrusion()
    {
        if (!this.passThrough)
            super.drawExtrusion()
    }
    drawGlow()
    {
        if (!this.passThrough)
        {
            super.drawGlow()
            return
        }
        const alpha = this.getAlpha()
        if (alpha <= 0)
            return
        const points = this.getPoints()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        ctx.closePath()
        strokeNeonPath(this.getGlowStroke(), alpha)
    }
    draw()
    {
        const alpha = this.getAlpha()
        if (alpha <= 0)
            return
        this.drawBadVersionPolygon(this.badVersionFill, this.stroke,
            {baseFillStyle: this.fill, alpha: alpha})
    }
}
