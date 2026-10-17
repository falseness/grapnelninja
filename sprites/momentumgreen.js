// Momentum green object: a one-time trampoline. The first ninja contact
// bounces like any trampoline (Ninja.applyBounce -> bounceSpeed) and adds to
// the green streak; from then on it lets the ninja and the grapnel through
// and fades out linearly over GAMEPLAY.momentumFadeMs of render clock
// (performance.now()). Its floor drops it once the fade is over
// (Floor.moveElements reads `faded`).
class MomentumGreen extends Trampoline
{
    constructor(object)
    {
        super(object)
        this.stroke = STYLE.colors.cube.greenStroke
        this.fill = STYLE.colors.cube.greenFill
        this.fadeStartMs = null
        this.passThrough = false
        this.faded = false
    }
    // Axis-aligned w x h box with its top-left corner at (x, y)
    static box(x, y, w, h)
    {
        return new MomentumGreen({x: x, y: y, points: [
            {x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}
        ]})
    }
    onNinjaBounce()
    {
        if (this.passThrough)
            return
        this.passThrough = true
        this.fadeStartMs = performance.now()
        momentumState.onGreenTouch()
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
    // The grapnel cannot hook a used green
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
        this.drawBadVersionPolygon(STYLE.badVersionEffects.obstacles.greenFill, this.stroke,
            {baseFillStyle: this.fill, alpha: alpha})
    }
}
