// Momentum green object: a one-time trampoline. The first ninja contact
// bounces like any trampoline (Ninja.applyBounce -> bounceSpeed) and adds to
// the green streak, then it fades out (sprites/momentumonetime.js).
class MomentumGreen extends MomentumOneTime
{
    constructor(object)
    {
        super(object, STYLE.colors.cube.greenStroke, STYLE.colors.cube.greenFill,
            STYLE.badVersionEffects.obstacles.greenFill)
    }
    static box(x, y, w, h)
    {
        return new MomentumGreen(MomentumOneTime.boxObject(x, y, w, h))
    }
    // MomentumOneTime.shapeObject spec (rect, triangle, polygon; motion)
    static shape(spec)
    {
        return new MomentumGreen(MomentumOneTime.shapeObject(spec))
    }
    // Jade rock (render/crystalpieces.js) under the piece's own neon outline.
    // The opaque jade replaces the base fills (hidden under it anyway), so
    // a fading green is the jade and outline at the fade alpha alone; its
    // twinkling glints go on top
    draw()
    {
        const alpha = this.getAlpha()
        if (alpha <= 0)
            return
        if (bloomPassActive || !CRYSTAL_PIECES.enabled)
        {
            super.draw()
            return
        }
        const sprite = CRYSTAL_PIECES.drawGreen(this, alpha)
        const points = this.getPoints()
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        ctx.closePath()
        strokeNeonPath(this.stroke, alpha)
        ctx.restore()
        CRYSTAL_PIECES.drawGlints(this, sprite, alpha)
    }
    onNinjaBounce()
    {
        if (this.use())
            momentumState.onGreenTouch()
    }
}
